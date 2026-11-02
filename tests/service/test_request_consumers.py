"""PB3-03/05: configured request consumers keep the default pool reserve.

`run_one` is the only double; the real Executor, asyncio.to_thread, ContextVar
propagation and graceful shutdown run unchanged. A plain settings object is
used so failures here are behavioral (concurrency/validation), not a missing
constructor argument.
"""
import asyncio
from contextvars import ContextVar
import os
import threading
import time
from types import SimpleNamespace

import pytest

from agentic_rag.config import Config

from agentic_rag.service import requests

MARK = ContextVar('consumer_test_mark', default=None)


def settings(consumers=None):
    return Config() if consumers is None else SimpleNamespace(service_request_consumers=consumers)


def observe(monkeypatch, *, hold):
    state = {'active': 0, 'peak': 0, 'calls': 0, 'marks': set(), 'threads': set()}
    lock = threading.Lock()
    def run_one(cfg):
        with lock:
            state['calls'] += 1
            state['active'] += 1
            state['peak'] = max(state['peak'], state['active'])
            state['marks'].add(MARK.get())
            state['threads'].add(threading.get_ident())
        try:
            hold.wait(5)
            return False
        finally:
            with lock:
                state['active'] -= 1
    monkeypatch.setattr(requests, 'run_one', run_one)
    return state


def cpus(monkeypatch, count, *, process=True):
    if process:
        monkeypatch.setattr(os, 'process_cpu_count', lambda: count, raising=False)
    else:
        monkeypatch.delattr(os, 'process_cpu_count', raising=False)
        monkeypatch.setattr(os, 'cpu_count', lambda: count)


async def run_executor(cfg, state, hold, expected):
    MARK.set('request-context')
    async with requests.Executor(cfg):
        for _ in range(200):
            if state['peak'] >= expected:
                break
            await asyncio.sleep(.01)
        await asyncio.sleep(.05)
        peak = state['peak']
        hold.set()
    return peak


def test_default_is_two_consumers_with_context_propagation(monkeypatch):
    hold = threading.Event()
    cpus(monkeypatch, 4)
    state = observe(monkeypatch, hold=hold)
    peak = asyncio.run(run_executor(settings(), state, hold, 2))
    assert peak == 2
    assert state['marks'] == {'request-context'}


@pytest.mark.parametrize('consumers', [1, 3, 4])
def test_configured_consumers_run_concurrently(monkeypatch, consumers):
    hold = threading.Event()
    cpus(monkeypatch, 4)  # reference: min(32, 4+4)=8 default workers, half=4
    state = observe(monkeypatch, hold=hold)
    peak = asyncio.run(run_executor(settings(consumers), state, hold, consumers))
    assert peak == consumers
    assert len(state['threads']) >= consumers


@pytest.mark.parametrize('cpu,consumers,process', [(1, 3, True), (2, 4, True), (2, 4, False), (1, 3, False)])
def test_consumers_above_half_default_pool_fail_before_any_work(monkeypatch, cpu, consumers, process):
    hold = threading.Event()
    cpus(monkeypatch, cpu, process=process)
    state = observe(monkeypatch, hold=hold)
    async def start():
        async with requests.Executor(settings(consumers)):
            await asyncio.sleep(.05)
    with pytest.raises(ValueError, match='request_consumers'):
        asyncio.run(start())
    hold.set()
    assert state['calls'] == 0


@pytest.mark.parametrize('cpu,consumers,process', [(1, 2, True), (2, 3, True), (28, 4, True)])
def test_consumers_within_reserve_start(monkeypatch, cpu, consumers, process):
    hold = threading.Event()
    cpus(monkeypatch, cpu, process=process)
    state = observe(monkeypatch, hold=hold)
    assert asyncio.run(run_executor(settings(consumers), state, hold, consumers)) == consumers


def test_reserve_falls_back_to_cpu_count_without_process_cpu_count(monkeypatch):
    # Python < 3.13 has no os.process_cpu_count; its default pool uses cpu_count.
    # Only the check runs here: removing the attribute on 3.13 would also break
    # CPython's own default executor, which a real older interpreter does not.
    cpus(monkeypatch, 2, process=False)
    assert requests.default_pool_size() == 6
    assert requests.check_consumers(3) == 3
    with pytest.raises(ValueError, match='request_consumers'):
        requests.check_consumers(4)


def test_reserve_uses_process_cpu_count_before_cpu_count(monkeypatch):
    monkeypatch.setattr(os, 'process_cpu_count', lambda: 1, raising=False)
    monkeypatch.setattr(os, 'cpu_count', lambda: 64)
    assert requests.default_pool_size() == 5
    monkeypatch.setattr(os, 'process_cpu_count', lambda: None, raising=False)
    monkeypatch.setattr(os, 'cpu_count', lambda: None)
    assert requests.default_pool_size() == 5
    monkeypatch.setattr(os, 'process_cpu_count', lambda: 64, raising=False)
    assert requests.default_pool_size() == 32


def test_shutdown_waits_for_live_calls_and_starts_no_replacement(monkeypatch):
    # Characterization: exit waits for every running to_thread call (no
    # abandoned live gateway) and no consumer starts new work after stop.
    starts, ends, stopped = [], [], []
    lock = threading.Lock()
    def run_one(cfg):
        with lock:
            starts.append(time.monotonic())
        time.sleep(.3)
        with lock:
            ends.append(time.monotonic())
        return True
    monkeypatch.setattr(requests, 'run_one', run_one)
    cpus(monkeypatch, 4)
    async def scenario():
        async with requests.Executor(Config()):
            while len(starts) < 2:
                await asyncio.sleep(.01)
            stopped.append(time.monotonic())
        return time.monotonic()
    exited = asyncio.run(scenario())
    assert len(starts) == len(ends) == 2
    assert max(starts) < stopped[0] and max(ends) <= exited
