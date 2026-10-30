"""Plugin-only status/cancel tools; legacy MCP surfaces retain their contract."""
import sys
from ..config import load_config
from ..mcp_server import build_server
from ..service.client import RemoteClient


def build(read_only=False):
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
    build('--read-only' in sys.argv).run(transport='stdio')


if __name__=='__main__':main()
