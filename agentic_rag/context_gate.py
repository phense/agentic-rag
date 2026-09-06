"""Cheap recall eligibility and bounded receipts for actually emitted host context."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import time

RECEIPT_DIR = Path.home() / '.agentic-rag' / 'state' / 'context-receipts'
MAX_RECEIPTS = 128
RECEIPT_TTL = 86400
_WORD = re.compile(r'[\w]+(?:(?:::|[_.:-])[\w]+)*',re.UNICODE)
_HISTORY = re.compile(
    r'\b(?:what did we (?:decide|choose|use)|what (?:was|were) our|'
    r'(?:earlier|previous|last) (?:decision|discussion|session)|'
    r'was hatten wir|wie hatten wir|was haben wir (?:zuletzt|damals)|'
    r'(?:letzte|frühere|vorherige) (?:entscheidung|sitzung|diskussion))\b',re.I)
_PROJECT = re.compile(
    r'\b(?:this|our|current) (?:project|repo|repository|codebase)\b|'
    r'\b(?:dieses|diesem|unser|unserem|unseres|aktuellen?) (?:projekt|repo|repository)\b',re.I)
_QUESTION = re.compile(r'\b(?:how|what|which|where|why|wie|was|welche\w*|wo|warum)\b',re.I)
_STOP = set('''how what which where why do does did we i our this the is are was were
of a an in on for to about earlier previous last session decision discussion decide
choose use had have it its can should please project repo repository codebase current
wie was welche welcher welches wo warum wir ich unser unsere unserem unseres dieses
diesem dieser das der die den dem des ein eine einen und oder im in an zu zum zur
mit hatten haben zuletzt damals früher bitte projekt sitzung entschieden startenwir
x'''.split())


def detect(prompt: str, project: str | None) -> str | None:
    if not isinstance(prompt,str) or not prompt.strip():
        return None
    bounded=prompt[:4000]
    if _HISTORY.search(bounded):
        return 'history'
    request=re.search(r'\b(?:explain|show|remind|erkläre|zeige|erinnere)\b',bounded,re.I)
    if _PROJECT.search(bounded) and (_QUESTION.search(bounded) or request):
        return 'project'
    if project and _QUESTION.search(bounded):
        name=Path(project).name
        if len(name)>=3 and re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)',bounded,re.I):
            return 'project'
    return None


def query(prompt: str) -> str | None:
    """Safe bounded OR terms; SQL handles English/German stemming and applicability."""
    words=[]
    for word in _WORD.findall(prompt[:4000]):
        word=word.casefold()
        if len(word)>1 and word not in _STOP and word not in words:
            words.append(word)
            if len(words)==8:
                break
    return ' OR '.join(words) if words else None


def receipt_key(payload: dict, *, project: str | None, revision: str,
                config: str, text: str, host: str = 'codex') -> str | None:
    session,turn=payload.get('session_id'),payload.get('turn_id')
    if not all(isinstance(v,str) and v.strip() for v in (session,turn)):
        return None
    # A missing host turn ID is never replaced by the repeated prompt text.
    fields=[host,session,project,turn,config,revision,text]
    return hashlib.sha256(json.dumps(fields,ensure_ascii=False).encode()).hexdigest()


def _path(key: str | None) -> Path | None:
    return RECEIPT_DIR/(key+'.receipt') if isinstance(key,str) and re.fullmatch(r'[0-9a-f]{64}',key) else None


def delivered(key: str | None) -> bool:
    path=_path(key)
    try:
        return path is not None and path.is_file() and 0<=time.time()-path.stat().st_mtime<RECEIPT_TTL
    except OSError:
        return False


def record(key: str | None) -> None:
    """Call only after emit succeeds. Failure permits another injection, never data loss."""
    path=_path(key)
    if path is None:
        return
    try:
        RECEIPT_DIR.mkdir(parents=True,exist_ok=True,mode=0o700)
        try:
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            os.close(fd)
        except FileExistsError:
            if path.is_symlink():
                return
            os.utime(path,None)
        files=sorted(RECEIPT_DIR.glob('*.receipt'),key=lambda p:p.stat().st_mtime,reverse=True)
        for old in files[MAX_RECEIPTS:]:
            old.unlink(missing_ok=True)
    except OSError:
        pass
