"""Bounded, throttled authenticated observations; never an authorization source."""
from collections import OrderedDict
import threading
import time
import re

from .. import db
from .dashboard_policy import identity

_lock=threading.Lock()
_recent=OrderedDict()


def observe(cfg,path,principal,reported_version='',capabilities=''):
    pid=identity(path);who=('machine:'+principal.machine_id) if principal.machine_id else 'human:'+principal.user_id
    key=(cfg.db_name,pid,who);now=time.monotonic()
    with _lock:
        prior=_recent.pop(key,0);_recent[key]=prior
        if now-prior<60:return
        _recent[key]=now
        while len(_recent)>1024:_recent.popitem(last=False)
    # Header assertions are informational; no arbitrary text or credential values.
    ver=reported_version if re.fullmatch(r'[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}(?:[-+][A-Za-z0-9.-]{1,20})?',reported_version or '') else ''
    caps=','.join(sorted(set(x for x in capabilities.split(',') if x in {'protocol1','queued_tools1','checkpoints1','windows1'})))
    try:
        from .auth import Policy
        policy=Policy.load(path)
        configured=['human:'+name for name in policy.users]+['machine:'+name for name in policy.machines]
        with db.connect(cfg) as conn:
            conn.execute("SET LOCAL statement_timeout='1s'")
            conn.execute('DELETE FROM dashboard_presence WHERE policy_id=%s AND NOT(principal_id=ANY(%s))',(pid,configured))
            if len(configured)<=512:
                conn.execute('INSERT INTO dashboard_presence(policy_id,principal_id,version,capabilities) VALUES (%s,%s,%s,%s) ON CONFLICT(policy_id,principal_id) DO UPDATE SET seen_at=now(),version=EXCLUDED.version,capabilities=EXCLUDED.capabilities WHERE dashboard_presence.seen_at<now()-interval \'1 minute\'',(pid,who,ver,caps))
    except Exception:
        # Observability must never turn an accepted foreground read into failure.
        pass
