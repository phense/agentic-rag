"""One bounded client-only upload pass; safe for hook launch or a timer."""
from ..config import load_config
from ..hooks.common import log_hook_error
from ..worker import acquire_lock
from .client import RemoteClient
from .local import stage_sources


def main():
    cfg=load_config()
    if cfg.service_mode!='client':return 0
    cfg.service_spool_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    lock=acquire_lock(cfg.service_spool_dir/'uploader.lock')
    if lock is None:return 0
    with lock:
        try:
            with RemoteClient(cfg) as client:
                try:stage_sources(client)
                except Exception:
                    client.spool.note('source_staging_failed')
                    # Already staged input must still drain when the source/capacity
                    # problem prevents producing another window.
                client.flush()
        except Exception as exc:
            log_hook_error('uploader',type(exc).__name__)
    return 0


if __name__=='__main__':raise SystemExit(main())
