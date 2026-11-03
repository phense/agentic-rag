"""RAG-070 AC-001: static image bytes are proven before any engine call or write."""
import io
import struct
import zlib

import pytest

PIL = pytest.importorskip('PIL')
from PIL import Image  # noqa: E402

from agentic_rag import image_media as media  # noqa: E402


def encoded(fmt, size=(64, 32), color='white', **kw):
    out = io.BytesIO()
    Image.new('RGB', size, color).save(out, fmt, **kw)
    return out.getvalue()


@pytest.mark.parametrize('fmt,mime', [('PNG', 'image/png'), ('JPEG', 'image/jpeg'), ('WEBP', 'image/webp')])
def test_supported_static_images_are_sniffed_and_completely_decoded(fmt, mime):
    data = encoded(fmt)
    sniffed = media.sniff(data)
    assert (sniffed.mime, sniffed.width, sniffed.height, sniffed.frames) == (mime, 64, 32, 1)
    info = media.validate(data)
    assert (info.mime, info.width, info.height, info.frames, info.byte_size) == (mime, 64, 32, 1, len(data))
    import hashlib
    assert info.sha256 == hashlib.sha256(data).hexdigest()


def _code(data, **kw):
    with pytest.raises(media.ImageRejected) as caught:
        media.validate(data, **kw)
    return caught.value.code


def test_spoofed_unsupported_and_empty_inputs_are_rejected_without_decoding(monkeypatch):
    calls = []
    monkeypatch.setattr(media, '_decode', lambda *a, **k: calls.append(a))
    gif = io.BytesIO(); Image.new('RGB', (4, 4)).save(gif, 'GIF')
    assert _code(gif.getvalue()) == 'unsupported_image_type'
    assert _code(b'') == 'unsupported_image_type'
    assert _code(b'%PDF-1.7 not an image') == 'unsupported_image_type'
    assert _code(b'<svg xmlns="http://www.w3.org/2000/svg"/>') == 'unsupported_image_type'
    assert _code(b'\x89PNG\r\n\x1a\n' + b'\0' * 4) == 'malformed_image'
    assert calls == []


def test_truncated_and_corrupted_images_fail_complete_decoding():
    for fmt in ('PNG', 'JPEG', 'WEBP'):
        data = encoded(fmt, size=(256, 256), color='red') if fmt != 'PNG' else _noisy_png()
        assert _code(data[:len(data) // 2]) in {'malformed_image'}, fmt
    png = bytearray(_noisy_png())
    png[-40] ^= 0xFF  # IDAT payload corruption with a valid header
    assert _code(bytes(png)) == 'malformed_image'


def _noisy_png():
    import random
    rng = random.Random(7)
    im = Image.frombytes('RGB', (128, 128), bytes(rng.randrange(256) for _ in range(128 * 128 * 3)))
    out = io.BytesIO(); im.save(out, 'PNG'); return out.getvalue()


def test_animated_png_and_webp_are_rejected():
    frames = [Image.new('RGB', (16, 16), c) for c in ('red', 'blue')]
    for fmt in ('PNG', 'WEBP'):
        out = io.BytesIO()
        frames[0].save(out, fmt, save_all=True, append_images=frames[1:], duration=50, loop=0)
        assert _code(out.getvalue()) == 'animated_image', fmt


def _png_header(width, height):
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    chunk = struct.pack('>I', len(ihdr)) + b'IHDR' + ihdr + struct.pack('>I', zlib.crc32(b'IHDR' + ihdr))
    idat = zlib.compress(b'\0' * 64)
    return (b'\x89PNG\r\n\x1a\n' + chunk + struct.pack('>I', len(idat)) + b'IDAT' + idat
            + struct.pack('>I', zlib.crc32(b'IDAT' + idat)) + struct.pack('>I', 0) + b'IEND' + struct.pack('>I', zlib.crc32(b'IEND')))


def test_dimension_pixel_and_byte_bounds_precede_decoding(monkeypatch):
    calls = []
    monkeypatch.setattr(media, '_decode', lambda *a, **k: calls.append(a))
    assert _code(_png_header(8193, 10)) == 'image_dimensions_exceeded'
    assert _code(_png_header(5000, 5000)) == 'image_dimensions_exceeded'  # 25M pixel bomb header
    assert _code(_png_header(0, 10)) == 'malformed_image'
    assert _code(b'\x89PNG\r\n\x1a\n' + b'\0' * (media.MAX_BYTES)) == 'image_too_large'
    assert calls == []


def test_real_decompression_bomb_within_byte_limit_is_rejected():
    # A genuinely encoded 4100x4100 (16.8M pixel) image compresses to a few KiB.
    data = encoded('PNG', size=(4100, 4100))
    assert len(data) < media.MAX_BYTES
    assert _code(data) == 'image_dimensions_exceeded'


def test_decoder_resources_are_bounded_and_failures_are_explicit(monkeypatch):
    data = encoded('PNG')
    assert _code(data, timeout=0.000001) in {'decode_timeout'}
    monkeypatch.setattr(media, 'DECODER_MODULE', 'agentic_rag.no_such_decoder')
    assert _code(data) == 'decoder_unavailable'


def test_regular_file_reader_refuses_links_devices_and_oversize(tmp_path):
    good = tmp_path / 'a.png'
    good.write_bytes(encoded('PNG'))
    assert media.read_file(good) == good.read_bytes()
    link = tmp_path / 'link.png'
    link.symlink_to(good)
    for path in (link, tmp_path, '/dev/zero', tmp_path / 'missing.png'):
        with pytest.raises(media.ImageRejected) as caught:
            media.read_file(path)
        assert caught.value.code == 'image_file_unavailable'
    big = tmp_path / 'big.png'
    big.write_bytes(b'\0' * (media.MAX_BYTES + 1))
    with pytest.raises(media.ImageRejected) as caught:
        media.read_file(big)
    assert caught.value.code == 'image_too_large'


def test_bounded_run_caps_output_time_and_never_uses_a_shell(tmp_path):
    import sys
    loud = media.bounded_run([sys.executable, '-c', 'import sys;sys.stdout.write("x"*100000)'],
                             timeout=10, max_output=1000, workdir=tmp_path)
    assert loud.output_exceeded and len(loud.stdout) <= 1000
    slow = media.bounded_run([sys.executable, '-c', 'import time;time.sleep(30)'], timeout=0.5, max_output=1000,
                             workdir=tmp_path)
    assert slow.timed_out
    echo = media.bounded_run([sys.executable, '-c', 'import sys;print(sys.argv[1])', '$(id)'], timeout=10,
                             max_output=1000, workdir=tmp_path)
    assert echo.returncode == 0 and echo.stdout.strip() == b'$(id)'


def test_rejected_resource_limit_never_runs_the_command_or_escapes_as_a_subprocess_error(tmp_path, monkeypatch):
    import sys

    # Model Darwin's rejected RLIMIT_AS in the real pre-exec child, not Popen.
    def rejected_limits(*args):
        def apply():
            raise ValueError('current limit exceeds maximum limit')
        return apply

    monkeypatch.setattr(media, '_limits', rejected_limits)
    marker = tmp_path / 'must-not-run'
    result = media.bounded_run(
        [sys.executable, '-c', 'import pathlib,sys;pathlib.Path(sys.argv[1]).touch()', str(marker)],
        timeout=2, max_output=1000, workdir=tmp_path, memory=1024**3)
    assert result == media.RunResult(None, b'', b'', False, False)
    assert not marker.exists()
    assert _code(encoded('PNG')) == 'decoder_unavailable'

    from agentic_rag.config import Config
    from agentic_rag.image_engines import EngineError, TesseractEngine
    for language in ('deu', 'eng'):
        (tmp_path / f'{language}.traineddata').write_bytes(b'synthetic language data')
    engine = TesseractEngine.from_config(Config(
        image_ocr_command=sys.executable, image_ocr_tessdata=tmp_path))
    with pytest.raises(EngineError) as caught:
        engine.identity()
    assert caught.value.code == 'ocr_unavailable'
