"""A real foreign loopback listener must never be used or terminated."""
from contextlib import contextmanager
import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[2]


def api():
    spec=importlib.util.spec_from_file_location('benchmark_ownership',ROOT/'scripts/benchmark_embeddings.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


@contextmanager
def listener():
    # Inherit a bound socket: no free-port race in this test's child setup.
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        code='import socket,sys,time;s=socket.socket(fileno=int(sys.argv[1]));s.listen();print("ready",flush=True);time.sleep(15)'
        p=subprocess.Popen([sys.executable,'-I','-c',code,str(sock.fileno())],pass_fds=(sock.fileno(),),stdout=subprocess.PIPE,text=True)
        sock.close()
        try:
            assert p.stdout.readline().strip()=='ready'
            yield p,port
        finally:
            p.terminate();p.wait(timeout=5);p.stdout.close()


def test_busy_port_fails_before_reusing_a_foreign_daemon():
    m=api()
    with listener() as (foreign,port):
        with pytest.raises(RuntimeError,match='already in use'):m.require_free_port(port)
        assert foreign.poll() is None


def test_listener_must_belong_to_exact_owned_child():
    m=api()
    with listener() as (owned,port):
        m.assert_owned_listener(owned,port)
        with pytest.raises(RuntimeError,match='ownership'):
            m.assert_owned_listener(SimpleNamespace(pid=os.getpid(),poll=lambda:None),port)
        assert owned.poll() is None
    with pytest.raises(RuntimeError,match='exited'):m.assert_owned_listener(owned,port)
