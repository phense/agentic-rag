"""Owned continuation state; input metadata is never interpreted as a server path."""
from dataclasses import asdict

from pydantic import Field, StrictBool, StrictStr, ValidationError, model_validator

from .. import db
from ..continuity import store
from ..continuity.model import CheckpointSnapshot
from ..continuity.render import render_checkpoint
from ..secrets import strip_secrets_json
from .context import request_scope
from .engine import ServiceError
from .ingest import Contract
from .spool import canonical


class Snapshot(Contract):
    cursor: StrictStr=Field(min_length=1,max_length=4096)
    turn_id: StrictStr | None=None
    source: StrictStr=Field(min_length=1,max_length=80)
    trigger: StrictStr | None=None
    cwd: StrictStr | None=None
    transcript_fingerprint: StrictStr | None=None
    git: dict=Field(default_factory=dict)
    artifacts: list[StrictStr]=Field(default_factory=list,max_length=16)
    warnings: list[StrictStr]=Field(default_factory=list,max_length=16)


class Packet(Contract):
    version: int=Field(ge=1,le=1)
    session_id: StrictStr=Field(min_length=1,max_length=256)
    project: StrictStr=Field(min_length=1,max_length=4096)
    snapshot: Snapshot
    handoff: StrictStr | None=Field(default=None,max_length=8000)
    compacted: StrictBool=False

    @model_validator(mode='after')
    def bounded(self):
        if len(canonical(self.model_dump()).encode())>32768 or '\\u0000' in canonical(self.model_dump()):
            raise ValueError('checkpoint limit or invalid string')
        if self.snapshot.trigger not in {None,'auto','manual'}: raise ValueError('invalid trigger')
        return self


def save(cfg,principal,data):
    try: packet=Packet.model_validate(data)
    except (ValidationError,ValueError,TypeError): raise ServiceError('invalid_checkpoint') from None
    with request_scope(principal,cfg):
        from ..scope import project_id
        project=packet.project if packet.project in {'global','unknown'} else project_id(packet.project)
        if principal.readonly or ('*' not in principal.write_projects and project not in principal.write_projects): raise ServiceError('scope_denied',403)
        clean,_=strip_secrets_json(packet.snapshot.model_dump())
        snapshot=CheckpointSnapshot(session_id=principal.session_id(packet.session_id),project_root=project,**clean)
        from .resources import admission
        with admission(cfg) as budget, db.connect(cfg,role='writer') as conn:
            budget.check(incoming=65536)
            from .session_logs import publish
            publish(conn,principal,snapshot.session_id,project)
            checkpoint=store.upsert_snapshot(conn,snapshot)
            if packet.handoff is not None:
                checkpoint=store.attach_handoff(conn,checkpoint.id,packet.handoff,max_chars=cfg.checkpoint_handoff_max_chars)
            if packet.compacted:
                store.mark_compacted(conn,checkpoint.session_id,checkpoint.cursor)
                checkpoint=store.get(conn,checkpoint.id)
        return {'durable':True,'checkpoint':asdict(checkpoint)}


def latest(cfg,principal,session):
    with request_scope(principal,cfg,read_only=True),db.connect(cfg,role='reader') as conn:
        checkpoint=store.latest_for_session(conn,principal.session_id(session))
        if checkpoint is None: raise ServiceError('not_found',404)
        return {'checkpoint':asdict(checkpoint),'rendered':render_checkpoint(checkpoint,max_chars=cfg.checkpoint_render_max_chars,
            current_cwd=checkpoint.cwd,current_project_root=checkpoint.project_root,stale_days=cfg.stale_days)}
