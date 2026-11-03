"""Bounded proof that bytes are one static PNG, JPEG or WebP image (RAG-070 AC-001).

Two stages, both before any engine call or database write:

1. `sniff` parses only container headers in pure Python: actual type from magic
   bytes (never a filename or declared MIME type), dimensions, pixel count and
   animation markers. Oversized or animated inputs never reach a decoder.
2. `_decode` completely decodes the image in an owned child process with
   finite time, address space, CPU and output, so a malformed or hostile file
   cannot exhaust the caller. Pillow is an optional dependency (`images` extra).

`bounded_run` is the only subprocess primitive used by image engines: argument
vector without a shell, a new session that is killed as a group, temporary-file
outputs capped by RLIMIT_FSIZE instead of unbounded pipes.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import resource
import signal
import stat
import struct
import subprocess
import sys
import tempfile
import json

MAX_BYTES = 4 * 1024 * 1024
MAX_PIXELS = 16_000_000
MAX_SIDE = 8192
DECODER_MODULE = 'agentic_rag.image_decode'
DECODE_TIMEOUT = 15.0
DECODE_MEMORY = 1024 * 1024 * 1024
_DECODE_OUTPUT = 64 * 1024
MIME = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp'}


class ImageRejected(ValueError):
    """A stable, content-free reason. Never carries bytes, paths or decoder text."""
    def __init__(self, code):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class MediaInfo:
    mime: str
    format: str
    width: int
    height: int
    frames: int
    sha256: str
    byte_size: int


@dataclass(frozen=True)
class RunResult:
    returncode: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool
    output_exceeded: bool


def _bounds(width, height):
    if width <= 0 or height <= 0:
        raise ImageRejected('malformed_image')
    if width > MAX_SIDE or height > MAX_SIDE or width * height > MAX_PIXELS:
        raise ImageRejected('image_dimensions_exceeded')


def _png(data):
    if len(data) < 33 or data[12:16] != b'IHDR' or struct.unpack('>I', data[8:12])[0] != 13:
        raise ImageRejected('malformed_image')
    width, height = struct.unpack('>II', data[16:24])
    _bounds(width, height)
    offset, frames = 8, 1
    while True:  # chunk scan up to the first image data; bounded by the input size
        if offset + 8 > len(data):
            raise ImageRejected('malformed_image')
        length, kind = struct.unpack('>I', data[offset:offset + 4])[0], data[offset + 4:offset + 8]
        if offset + 12 + length > len(data):
            raise ImageRejected('malformed_image')
        if kind == b'acTL':
            frames = max(2, struct.unpack('>I', data[offset + 8:offset + 12])[0]) if length >= 4 else 2
        if kind in (b'IDAT', b'IEND'):
            break
        offset += 12 + length
    if kind != b'IDAT':
        raise ImageRejected('malformed_image')
    return 'PNG', width, height, frames


_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def _jpeg(data):
    offset = 2
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            raise ImageRejected('malformed_image')
        marker = data[offset + 1]
        if marker == 0xFF:
            offset += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            offset += 2
            continue
        length = struct.unpack('>H', data[offset + 2:offset + 4])[0]
        if length < 2 or offset + 2 + length > len(data):
            raise ImageRejected('malformed_image')
        if marker in _SOF:
            if length < 7:
                raise ImageRejected('malformed_image')
            height, width = struct.unpack('>HH', data[offset + 5:offset + 9])
            _bounds(width, height)
            return 'JPEG', width, height, 1
        if marker in (0xDA, 0xD9):
            break
        offset += 2 + length
    raise ImageRejected('malformed_image')


def _webp(data):
    if len(data) < 20 or struct.unpack('<I', data[4:8])[0] + 8 > len(data) + 1 or data[8:12] != b'WEBP':
        raise ImageRejected('malformed_image')
    offset, size, frames = 12, None, 1
    while offset + 8 <= len(data):
        kind, length = data[offset:offset + 4], struct.unpack('<I', data[offset + 4:offset + 8])[0]
        body = data[offset + 8:offset + 8 + length]
        if len(body) < length:
            raise ImageRejected('malformed_image')
        if kind == b'VP8X':
            if length < 10:
                raise ImageRejected('malformed_image')
            if body[0] & 0x02:
                frames = 2
            size = (int.from_bytes(body[4:7], 'little') + 1, int.from_bytes(body[7:10], 'little') + 1)
        elif kind in (b'ANIM', b'ANMF'):
            frames = 2
        elif kind == b'VP8 ' and size is None:
            if length < 10 or body[3:6] != b'\x9d\x01\x2a':
                raise ImageRejected('malformed_image')
            size = (struct.unpack('<H', body[6:8])[0] & 0x3FFF, struct.unpack('<H', body[8:10])[0] & 0x3FFF)
        elif kind == b'VP8L' and size is None:
            if length < 5 or body[0] != 0x2F:
                raise ImageRejected('malformed_image')
            bits = int.from_bytes(body[1:5], 'little')
            size = ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
        offset += 8 + length + (length & 1)
    if size is None:
        raise ImageRejected('malformed_image')
    _bounds(*size)
    return 'WEBP', size[0], size[1], frames


def sniff(data: bytes) -> MediaInfo:
    if not isinstance(data, (bytes, bytearray)):
        raise ImageRejected('unsupported_image_type')
    if len(data) > MAX_BYTES:
        raise ImageRejected('image_too_large')
    data = bytes(data)
    try:
        if data.startswith(b'\x89PNG\r\n\x1a\n'):
            fmt, width, height, frames = _png(data)
        elif data.startswith(b'\xff\xd8\xff'):
            fmt, width, height, frames = _jpeg(data)
        elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            fmt, width, height, frames = _webp(data)
        else:
            raise ImageRejected('unsupported_image_type')
    except struct.error:
        raise ImageRejected('malformed_image') from None
    if frames != 1:
        raise ImageRejected('animated_image')
    return MediaInfo(MIME[fmt], fmt, width, height, frames, hashlib.sha256(data).hexdigest(), len(data))


def _limits(max_output, memory, cpu_seconds):
    def apply():
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (max_output + 1, max_output + 1))
        if memory:
            resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        if cpu_seconds:
            limit = max(1, int(cpu_seconds) + 1)
            resource.setrlimit(resource.RLIMIT_CPU, (limit, limit + 1))
    return apply


def bounded_run(argv, *, timeout, max_output, workdir, env=None, memory=None, cpu_seconds=None) -> RunResult:
    """Run one argument vector with finite time, memory, CPU and captured output."""
    if not argv or not all(isinstance(a, str) for a in argv):
        raise ValueError('invalid argument vector')
    with tempfile.TemporaryFile(dir=workdir) as out, tempfile.TemporaryFile(dir=workdir) as err:
        try:
            process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err, cwd=workdir,
                                       env=env if env is not None else {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'},
                                       close_fds=True, start_new_session=True,
                                       preexec_fn=_limits(max_output, memory, cpu_seconds or timeout))
        except (OSError, subprocess.SubprocessError):
            # A rejected pre-exec resource limit must fail closed, just like an
            # unavailable executable. Never retry without the resource limits.
            return RunResult(None, b'', b'', False, False)
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)  # also reaps helpers forked by the engine
            except (ProcessLookupError, PermissionError):
                pass
            process.wait()
        sizes = [os.fstat(f.fileno()).st_size for f in (out, err)]
        out.seek(0)
        err.seek(0)
        stdout, stderr = out.read(max_output), err.read(min(max_output, 65536))
        exceeded = sizes[0] > max_output or process.returncode == -signal.SIGXFSZ
        return RunResult(process.returncode, stdout, stderr, timed_out, exceeded)


def _decode(data: bytes, *, timeout=None, memory=None, workdir=None) -> dict:
    with tempfile.TemporaryDirectory(dir=workdir, prefix='rag-image-') as private:
        os.chmod(private, 0o700)
        path = Path(private) / 'input'
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        result = bounded_run([sys.executable, '-I', '-m', DECODER_MODULE, str(path), str(MAX_PIXELS)],
                             timeout=DECODE_TIMEOUT if timeout is None else timeout, max_output=_DECODE_OUTPUT,
                             workdir=private, memory=memory or DECODE_MEMORY,
                             env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})
    if result.timed_out:
        raise ImageRejected('decode_timeout')
    if result.returncode == 0 and not result.output_exceeded:
        try:
            return json.loads(result.stdout)
        except ValueError:
            raise ImageRejected('decode_failed') from None
    codes = {2: 'malformed_image', 3: 'image_dimensions_exceeded', 4: 'decoder_unavailable',
             6: 'decode_resources_exceeded'}
    if result.returncode in codes:
        raise ImageRejected(codes[result.returncode])
    if result.returncode is None or (result.returncode == 1 and b'No module named' in result.stderr):
        raise ImageRejected('decoder_unavailable')
    raise ImageRejected('decode_failed')


def validate(data: bytes, *, timeout=None, memory=None, workdir=None) -> MediaInfo:
    """Header bounds first, then a complete bounded decode that must agree."""
    info = sniff(data)
    decoded = _decode(bytes(data), timeout=timeout, memory=memory, workdir=workdir)
    if (decoded.get('format'), decoded.get('width'), decoded.get('height')) != (info.format, info.width, info.height):
        raise ImageRejected('malformed_image')
    if decoded.get('frames') != 1:
        raise ImageRejected('animated_image')
    return info


def read_file(path) -> bytes:
    """One explicit regular file: no symlink, device, FIFO or directory; bounded read."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, 'O_CLOEXEC', 0))
    except (OSError, TypeError, ValueError):
        raise ImageRejected('image_file_unavailable') from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ImageRejected('image_file_unavailable')
        if info.st_size > MAX_BYTES:
            raise ImageRejected('image_too_large')
        chunks, total = [], 0
        while True:
            chunk = os.read(fd, min(1 << 20, MAX_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_BYTES:
                raise ImageRejected('image_too_large')
        return b''.join(chunks)
    except OSError:
        raise ImageRejected('image_file_unavailable') from None
    finally:
        os.close(fd)
