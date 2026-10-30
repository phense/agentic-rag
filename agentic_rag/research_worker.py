"""Private subprocess entrypoint. No shell, user artifacts or persistent writes."""
import json
from contextlib import nullcontext
import sys
from pathlib import Path

from . import db
from .config import Config
from .research import ResearchBudget, _base, _research


def main():
    payload = json.loads(sys.stdin.read())
    values = payload['config']
    for key in ('backup_cloud_dir', 'backup_local_dir', 'pg_bin_dir'):
        if values[key] is not None:
            values[key] = Path(values[key])
    cfg = Config(**values)
    budget = ResearchBudget(**payload['budget'])
    def emit(packet):
        print(json.dumps(packet,ensure_ascii=False,separators=(',',':')),flush=True)
    try:
        from .service.context import request_scope
        from .service.auth import Principal
        authority=payload.get('service_scope')
        if authority is not None:
            for key in ('read_domains','write_domains','read_projects','write_projects','session_teams'):
                authority[key]=frozenset(authority.get(key,[]))
        with (request_scope(Principal(**authority),cfg,read_only=True) if authority else nullcontext()), db.connect(cfg, role='reader') as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            result = _research(conn,cfg,payload['question'],budget=budget,
                               progress=emit,**payload['options'])
    except Exception:
        result = _base(payload['question'],budget)
        result.update(termination='worker_failure',abstained=True)
        result['warnings'].append('reader failed; diagnostic content withheld')
    emit(result)


if __name__ == '__main__':
    main()
