"""Darwin-only image command supervisor, launched in its own process group.

Darwin reserves hundreds of GiB of virtual address space before user code runs,
so Linux's small RLIMIT_AS is unusable. Keep the kernel CPU/file/core limits and
enforce a sampled physical-memory budget over the owned group instead. This is
not an allocator-level hard cap: allocation can overshoot between 10ms samples.
Unobservable usage fails closed; wait4 rejects short-lived resident-memory peaks.
No preexec callback runs in the threaded service. Linux keeps its existing path.
"""
from __future__ import annotations

import ctypes
import errno
import os
import resource
import subprocess
import sys
import time


# Apple's <sys/resource.h>, RUSAGE_INFO_V4; native uint64_t fields, UUID first.
class _Rusage(ctypes.Structure):
    _fields_ = [('uuid', ctypes.c_uint8 * 16)] + [
        (name, ctypes.c_uint64) for name in (
            'user_time', 'system_time', 'pkg_idle_wkups', 'interrupt_wkups',
            'pageins', 'wired_size', 'resident_size', 'phys_footprint',
            'proc_start_abstime', 'proc_exit_abstime', 'child_user_time',
            'child_system_time', 'child_pkg_idle_wkups', 'child_interrupt_wkups',
            'child_pageins', 'child_elapsed_abstime', 'diskio_bytesread',
            'diskio_byteswritten', 'cpu_time_qos_default', 'cpu_time_qos_maintenance',
            'cpu_time_qos_background', 'cpu_time_qos_utility', 'cpu_time_qos_legacy',
            'cpu_time_qos_user_initiated', 'cpu_time_qos_user_interactive',
            'billed_system_time', 'serviced_system_time', 'logical_writes',
            'lifetime_max_phys_footprint', 'instructions', 'cycles', 'billed_energy',
            'serviced_energy', 'interval_max_phys_footprint', 'runnable_time')]


class _MemoryUsage:
    def __init__(self):
        lib = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
        self.usage = lib.proc_pid_rusage
        self.usage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
        self.usage.restype = ctypes.c_int
        self.members = lib.proc_listpgrppids
        self.members.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
        self.members.restype = ctypes.c_int
        self.peaks = {}
        self.read()  # Prove accounting works before the target can be launched.

    def read(self):
        pids = (ctypes.c_int * 256)()
        count = self.members(os.getpgrp(), pids, ctypes.sizeof(pids))
        # Unlike proc_listpids, this convenience API returns a PID count.
        if count <= 0 or count >= len(pids):
            raise OSError('image process accounting unavailable')
        found_self = False
        for pid in pids[:count]:
            if pid <= 0:
                continue
            usage = _Rusage()
            if self.usage(pid, 4, ctypes.byref(usage)):
                if ctypes.get_errno() == errno.ESRCH and pid != os.getpid():
                    continue  # A helper vanished; retain its last observed peak.
                raise OSError('image process accounting unavailable')
            if usage.proc_start_abstime == 0 or usage.resident_size == 0:
                raise OSError('image process accounting unavailable')
            found_self |= pid == os.getpid()
            key = (pid, usage.proc_start_abstime)
            self.peaks[key] = max(self.peaks.get(key, 0), usage.resident_size,
                                  usage.phys_footprint, usage.lifetime_max_phys_footprint)
        if not found_self:
            raise OSError('image process accounting unavailable')
        # Sum lifetime peaks conservatively, including vanished helpers. PID start
        # time prevents reuse from erasing a previously observed allocation.
        return sum(self.peaks.values())


def main(argv):
    """Exit 4 unavailable, 6 memory budget, otherwise the target's exit status."""
    child = None
    try:
        max_output, memory = int(argv[1]), int(argv[2])
        cpu = max(1, int(float(argv[3])) + 1)
        if max_output <= 0 or memory < 0 or len(argv) < 5:
            return 4
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (max_output + 1, max_output + 1))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
        guard = _MemoryUsage() if memory else None
        if guard and guard.read() > memory:
            return 6
        child = subprocess.Popen(argv[4:], stdin=subprocess.DEVNULL, close_fds=True)
        while True:
            if guard and guard.read() > memory:
                return 6
            pid, status, usage = os.wait4(child.pid, os.WNOHANG)
            if pid:
                child.returncode = os.waitstatus_to_exitcode(status)
                # On Darwin ru_maxrss is bytes. Check after exit as well, before
                # accepting any output from a command shorter than a sample.
                if memory and usage.ru_maxrss > memory:
                    return 6
                return child.returncode if child.returncode >= 0 else 128 - child.returncode
            time.sleep(.01)
    except (OSError, ValueError, AttributeError, OverflowError):
        return 4
    finally:
        if child is not None and child.returncode is None:
            child.kill()
            child.wait()
        # The caller kills this supervisor's entire group even after success.


if __name__ == '__main__':
    sys.exit(main(sys.argv))
