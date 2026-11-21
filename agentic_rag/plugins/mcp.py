"""Plugin-only status/cancel tools; legacy MCP surfaces retain their contract."""
import os
import sys
from ..config import load_config
from ..mcp_server import build_server
from ..service.client import RemoteClient


def _env_readonly() -> bool:
    return os.environ.get('RAG_READONLY','').strip()=='1'


def build(read_only=False):
    read_only=bool(read_only) or _env_readonly()
    server=build_server(read_only)
    cfg=load_config()
    if cfg.service_mode=='client':
        @server.tool()
        def memory_request_status(request_id: str) -> dict:
            """Check an accepted/local waiting handle; never resubmit with a new ID."""
            with RemoteClient(cfg) as client:
                return client.request_status(request_id)
        if not read_only:
            @server.tool()
            def memory_request_cancel(request_id: str) -> dict:
                """Cancel owned pending/running work; completed changes stay applied."""
                with RemoteClient(cfg) as client:
                    return client.request_status(request_id,cancel=True)
    return server


def main():
    read_only='--read-only' in sys.argv or _env_readonly()
    if read_only:
        os.environ['RAG_READONLY']='1'
    build(read_only).run(transport='stdio')


if __name__=='__main__':main()
