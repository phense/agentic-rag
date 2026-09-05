"""Project applicability, independent of topics and database authorization."""
from __future__ import annotations

from pathlib import Path
import subprocess
import os


def _location(value: str) -> tuple[Path, Path | None]:
    if not isinstance(value, str) or not value.startswith('/') or '\x00' in value:
        raise ValueError('project must be an absolute directory path')
    path = Path(value).resolve()
    existing = path
    while not existing.exists() and existing.parent != existing:
        existing = existing.parent
    if not existing.is_dir():
        raise ValueError('project must be a directory')
    git_env = {k:v for k,v in os.environ.items() if not k.startswith("GIT_")}
    try:
        result = subprocess.run(['git','--no-optional-locks','-c','core.fsmonitor=false',
            '-C',str(existing),'rev-parse','--show-toplevel','--git-common-dir'],
            capture_output=True,text=True,timeout=1,check=False,env=git_env)
        lines = result.stdout.splitlines()
        if result.returncode != 0 or len(lines) != 2:
            markers = [existing, *existing.parents]
            no_git = ("not a git repository" in result.stderr.lower()
                      and not any((parent/".git").exists() for parent in markers))
            return (path, None) if no_git else (path, path)
        top = Path(lines[0]).resolve()
        common = Path(lines[1])
        common = (common if common.is_absolute() else existing/common).resolve()
        if common.name == '.git':
            primary = common.parent
        else:
            listing = subprocess.run(['git','--no-optional-locks','-C',str(existing),
                'worktree','list','--porcelain'],capture_output=True,text=True,timeout=1,check=True,env=git_env)
            first = listing.stdout.splitlines()[0]
            if not first.startswith('worktree '):
                return path, path
            primary = Path(first.removeprefix('worktree ')).resolve()
        return primary/path.relative_to(top), primary
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        # Unknown Git identity must never broaden selection to parent projects.
        return path, path


def project_id(value: str) -> str:
    anchor, root = _location(value)
    return str(root or anchor)


def path_anchor(value: str) -> str:
    return str(_location(value)[0])


def ancestors(value: str) -> list[str]:
    path = Path(value)
    return [str(path), *(str(p) for p in path.parents)]


def selection(project: str | None = None, scope: str | None = None) -> list[str] | None:
    scope = scope or ('project' if project else 'all')
    if scope not in {'project','global','all'}:
        raise ValueError('scope must be project, global or all')
    if scope != 'project':
        if project is not None:
            raise ValueError('project cannot be combined with global/all scope')
        return ['global'] if scope == 'global' else None
    if not project:
        raise ValueError('project scope requires an absolute project path')
    anchor, root = _location(project)
    # A nested Git repository is its own project, even inside another repo.
    return ['global', str(root)] if root is not None else ['global', *ancestors(str(anchor))]


def pin_paths(project: str | None) -> list[str]:
    return ancestors(path_anchor(project)) if project else []


def write_scope(project=None, scope=None, provenance=None) -> str | None:
    if scope is not None:
        if scope not in {'project','global','unknown'}:
            raise ValueError('write scope must be project, global or unknown')
        if scope in {'global','unknown'}:
            if project is not None:
                raise ValueError('project conflicts with global/unknown scope')
            return scope
        if not project:
            raise ValueError('project scope requires an absolute project path')
    if project is not None:
        return project_id(project)
    legacy = (provenance or {}).get('project')
    if isinstance(legacy,str) and legacy.startswith('/'):
        return project_id(legacy)
    return None


def backfill(conn) -> dict:
    """Idempotent audited mapping, one transaction; unknown never means global."""
    from . import store
    changed = pins_changed = 0
    unknown = []
    try:
        rows = conn.execute("SELECT id,slug,provenance,meta,scope_explicit FROM documents WHERE project_scope='unknown' ORDER BY id").fetchall()
        for row in rows:
            if row['scope_explicit']:
                unknown.append({'slug':row['slug'],'reason':'explicit unknown scope retained'})
                continue
            source = row['provenance'].get('project')
            meta_project = row['meta'].get('project')
            if not isinstance(source,str) or not source.startswith('/'):
                unknown.append({'slug':row['slug'],'reason':'missing or non-absolute provenance.project'})
                continue
            try:
                value = project_id(source)
                if meta_project is not None and (not isinstance(meta_project,str)
                    or not meta_project.startswith('/') or project_id(meta_project)!=value):
                    unknown.append({'slug':row['slug'],'reason':'conflicting project metadata'})
                    continue
                changed += store.set_project_scope(conn,str(row['id']),project=value,
                    expected_scope='unknown',actor='migration',commit=False)
            except ValueError:
                unknown.append({'slug':row['slug'],'reason':'invalid project path'})
        from .pins import refresh_scope_paths
        pins_changed = refresh_scope_paths(conn)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return {'documents_mapped':changed,'pin_paths_mapped':pins_changed,
            'unknown_count':len(unknown),'unknown':unknown}
