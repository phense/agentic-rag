"""Owned finite localhost HTTP listener shared by integration/browser tests."""
from contextlib import contextmanager
import socket
import threading
import time
import uvicorn


@contextmanager
def server(app):
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    instance=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False,proxy_headers=False))
    thread=threading.Thread(target=lambda:instance.run(sockets=[sock]),daemon=True);thread.start()
    deadline=time.monotonic()+10
    while not instance.started:
        if not thread.is_alive() or time.monotonic()>deadline:raise RuntimeError('owned_browser_server_start_failed')
        time.sleep(.02)
    try:yield f'http://127.0.0.1:{port}'
    finally:
        instance.should_exit=True;thread.join(timeout=15);sock.close()
        assert not thread.is_alive(),'owned browser server failed to stop'
