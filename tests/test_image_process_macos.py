"""Issue100: real Darwin subprocess limits, without production data or models."""
import concurrent.futures
from pathlib import Path
import sys
import tempfile
import time
import unittest

from agentic_rag import image_media


@unittest.skipUnless(sys.platform == 'darwin', 'requires the real Darwin kernel')
class MacImageProcessTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory(prefix='rag100-test-')
        self.addCleanup(self.work.cleanup)

    def run_child(self, code, *, memory=128 * 1024**2, timeout=5, output=4096, cpu=None):
        return image_media.bounded_run(
            [sys.executable, '-c', code], timeout=timeout, max_output=output,
            workdir=self.work.name, memory=memory, cpu_seconds=cpu)

    def test_normal_command_runs_with_the_configured_memory_budget(self):
        # Removing Darwin support recreates decoder_unavailable/ocr_unavailable.
        result = self.run_child('print("bounded-darwin")')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'bounded-darwin\n')

    def test_memory_growth_is_rejected_before_success(self):
        # Skipping memory accounting would let this command publish success.
        result = self.run_child(
            'import time; x=bytearray(96*1024**2); time.sleep(.4); print("unsafe-success")',
            memory=64 * 1024**2)
        self.assertEqual(result.returncode, 6)
        self.assertNotIn(b'unsafe-success', result.stdout)

    def test_short_lived_memory_peak_is_not_accepted(self):
        result = self.run_child('x=bytearray(96*1024**2); print("peak")', memory=64 * 1024**2)
        self.assertEqual(result.returncode, 6)

    def test_timeout_remains_finite(self):
        result = self.run_child('import time; time.sleep(20)', timeout=.4)
        self.assertTrue(result.timed_out)
        self.assertNotEqual(result.returncode, 0)

    def test_cpu_limit_is_applied_before_the_target(self):
        result = self.run_child('while True: pass', timeout=5, cpu=.1)
        self.assertFalse(result.timed_out)
        self.assertNotEqual(result.returncode, 0)

    def test_both_output_streams_are_capped(self):
        for stream in ('stdout', 'stderr'):
            with self.subTest(stream=stream):
                result = self.run_child(f'import sys;sys.{stream}.write("x"*100000)', output=1000)
                self.assertTrue(result.output_exceeded)
                self.assertLessEqual(len(result.stdout), 1000)
                self.assertLessEqual(len(result.stderr), 1000)

    def test_threaded_callers_run_without_a_preexec_callback(self):
        # The production API calls the engine from worker threads.
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(lambda _: self.run_child('print("thread")'), range(6)))
        self.assertTrue(all(r.returncode == 0 and r.stdout == b'thread\n' for r in results))

    def test_descendant_memory_counts_towards_the_same_budget(self):
        code = ('import os,time; p=os.fork(); '
                'x=bytearray(40*1024**2); time.sleep(.4); print("unsafe-group")')
        result = self.run_child(code, memory=64 * 1024**2)
        self.assertEqual(result.returncode, 6)
        self.assertNotIn(b'unsafe-group', result.stdout)

    def test_descendants_are_killed_after_the_leader_exits(self):
        marker = Path(self.work.name) / 'late-side-effect'
        code = ('import os,time,pathlib; p=os.fork(); '
                f'\nif p == 0:\n time.sleep(.5); pathlib.Path({str(marker)!r}).touch()\n')
        result = self.run_child(code)
        self.assertEqual(result.returncode, 0)
        time.sleep(.7)
        self.assertFalse(marker.exists())

    def test_unavailable_accounting_never_launches_the_target(self):
        marker = Path(self.work.name) / 'must-not-run'
        code = ("import sys; from agentic_rag import image_process as p\n"
                "class Broken:\n def __init__(self): raise OSError('unavailable')\n"
                "p._MemoryUsage=Broken\n"
                f"sys.exit(p.main(['supervisor','4096','134217728','5',sys.executable,'-c',"
                f"{('import pathlib; pathlib.Path('+repr(str(marker))+').touch()')!r}]))")
        result = self.run_child(code)
        self.assertEqual(result.returncode, 4)
        self.assertFalse(marker.exists())

    def test_lost_accounting_kills_the_target_instead_of_accepting_it(self):
        marker = Path(self.work.name) / 'late-unobserved'
        target = f'import time,pathlib; time.sleep(.4); pathlib.Path({str(marker)!r}).touch()'
        code = ("import sys; from agentic_rag import image_process as p\n"
                "class Broken:\n calls=0\n def read(self):\n  self.calls+=1\n"
                "  if self.calls>1: raise OSError('unavailable')\n  return 1\n"
                "p._MemoryUsage=Broken\n"
                f"sys.exit(p.main(['supervisor','4096','134217728','5',sys.executable,'-c',{target!r}]))")
        result = self.run_child(code)
        self.assertEqual(result.returncode, 4)
        time.sleep(.6)
        self.assertFalse(marker.exists())


if __name__ == '__main__':
    unittest.main()
