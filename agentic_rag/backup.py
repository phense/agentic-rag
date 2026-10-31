"""pg_dump backups: local always, cloud when mounted, honest warnings otherwise."""
from __future__ import annotations

import re
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import Config

WARNING_STATE = Path.home() / ".agentic-rag" / "state" / "backup_warning"
_DUMP_RE = re.compile(r"^agentic_rag-(\d{8})-(\d{6})\.dump$")
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / "com.agentic-rag.backup.plist"

# Fallback dirs tried after PATH and cfg.pg_bin_dir. Homebrew keg-only paths on
# macOS; distro package layouts on Linux (glob: the major version is in the path).
_PG_FALLBACK_DIRS = {
    "darwin": ["/opt/homebrew/opt/postgresql@17/bin", "/opt/homebrew/bin",
               "/usr/local/opt/postgresql@17/bin", "/usr/local/bin"],
    "linux": ["/usr/lib/postgresql/*/bin", "/usr/bin", "/usr/local/bin"],
}


def _candidate_dirs(cfg: Config | None) -> list[Path]:
    dirs: list[Path] = []
    if cfg is not None and cfg.pg_bin_dir is not None:
        dirs.append(cfg.pg_bin_dir)
    for pattern in _PG_FALLBACK_DIRS.get(sys.platform, []):
        if "*" in pattern:
            # highest version first (…/17/bin sorts after …/16/bin)
            dirs += sorted(Path("/").glob(pattern.lstrip("/")), reverse=True)
        else:
            dirs.append(Path(pattern))
    return dirs


def _pg_bin(name: str, cfg: Config | None = None) -> str:
    found = shutil.which(name)
    if found:
        return found
    for d in _candidate_dirs(cfg):
        candidate = d / name
        if candidate.exists():
            return str(candidate)
    raise RuntimeError(
        f"{name} not found on PATH or in known PostgreSQL locations — "
        f"set [pg] bin_dir in config.toml or add the bin dir to PATH")


def _run_pg(cmd: list[str]) -> None:
    """Run a pg tool; surface its stderr on failure — an unattended launchd
    run must log the actual cause (auth, disk full), not just an exit code."""
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"{Path(cmd[0]).name} failed: {(e.stderr or '').strip()}"
        ) from e


@dataclass
class BackupResult:
    local_path: Path
    cloud_path: Path | None
    warnings: list[str] = field(default_factory=list)
    deleted: list[Path] = field(default_factory=list)


def _dumps(directory: Path) -> list[Path]:
    return sorted(
        (p for p in directory.glob("*.dump") if _DUMP_RE.match(p.name)),
        key=lambda p: p.name,
        reverse=True,  # newest first
    )


def _week(p: Path) -> str:
    ymd = _DUMP_RE.match(p.name).group(1)
    return datetime.strptime(ymd, "%Y%m%d").strftime("%G-%V")


def rotate(directory: Path, keep_daily: int, keep_weekly: int = 0) -> list[Path]:
    if type(keep_daily) is not int or type(keep_weekly) is not int or not 1<=keep_daily<=366 or not 0<=keep_weekly<=366:
        raise ValueError('finite backup retention required')
    dumps = _dumps(directory)
    keep = set(dumps[:keep_daily])
    if keep_weekly:
        covered = {_week(p) for p in dumps[:keep_daily]}
        by_week: dict[str, Path] = {}
        for p in dumps[keep_daily:]:
            week = _week(p)
            if week in covered:
                continue  # weekly slots buy ADDITIONAL history, not overlap
            by_week.setdefault(week, p)  # newest per week (list is sorted)
        keep |= set(list(by_week.values())[:keep_weekly])
    deleted = [p for p in dumps if p not in keep]
    for p in deleted:
        p.unlink()
    return deleted


def ensure_storage(cfg: Config, directory: Path, *, incoming: int) -> None:
    from .service.engine import ResourcePressure
    if shutil.disk_usage(directory).free<cfg.service_min_free_bytes+incoming:
        raise ResourcePressure('backup_storage_low',507)


def run_backup(cfg: Config) -> BackupResult:
    from . import db
    cfg.backup_local_dir.mkdir(parents=True, exist_ok=True)
    if cfg.service_mode=='server':
        with db.connect(cfg) as conn:
            size=conn.execute('SELECT pg_database_size(current_database()) bytes').fetchone()['bytes']
        ensure_storage(cfg,cfg.backup_local_dir,incoming=size*2)
    name = f"agentic_rag-{datetime.now():%Y%m%d-%H%M%S}.dump"
    local = cfg.backup_local_dir / name
    fd=os.open(local,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    _run_pg([_pg_bin("pg_dump", cfg), "-Fc", "-f", str(local), "-d", db.dsn(cfg)])
    result = BackupResult(local_path=local, cloud_path=None)
    result.deleted += rotate(cfg.backup_local_dir, cfg.backup_keep_local)

    if cfg.backup_cloud_dir is None:
        return result          # cloud copy not configured — local-only, no warning
    cloud_parent = cfg.backup_cloud_dir.parent
    if cloud_parent.exists():  # volume mounted — never mkdir a mount point
        cfg.backup_cloud_dir.mkdir(parents=True, exist_ok=True)
        cloud = cfg.backup_cloud_dir / name
        if cfg.service_mode=='server':ensure_storage(cfg,cfg.backup_cloud_dir,incoming=local.stat().st_size)
        fd=os.open(cloud,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        shutil.copy2(local, cloud)
        result.cloud_path = cloud
        result.deleted += rotate(
            cfg.backup_cloud_dir, cfg.backup_keep_daily, cfg.backup_keep_weekly
        )
        if WARNING_STATE.exists():
            WARNING_STATE.unlink()
    else:
        msg = (f"cloud backup dir unavailable ({cloud_parent} not mounted); "
               f"backed up locally only: {local}")
        result.warnings.append(msg)
        WARNING_STATE.parent.mkdir(parents=True, exist_ok=True)
        WARNING_STATE.write_text(f"{datetime.now().isoformat()} {msg}\n")
    return result


_RESTORE_DEFAULTS = """BEGIN;
SET LOCAL search_path = pg_catalog;
-- CREATE must see PostgreSQL's base defaults, not the target's additive grants.
-- The archive restores its own default ACLs after recreating the relations.
DO $restore_defaults$
DECLARE item record; objects text; scope text;
BEGIN
    FOR item IN
        SELECT d.defaclobjtype, n.nspname, a.grantee, r.rolname
        FROM pg_catalog.pg_default_acl d
        LEFT JOIN pg_catalog.pg_namespace n ON n.oid=d.defaclnamespace
        CROSS JOIN LATERAL pg_catalog.aclexplode(d.defaclacl) a
        LEFT JOIN pg_catalog.pg_roles r ON r.oid=a.grantee
        WHERE d.defaclrole=(SELECT oid FROM pg_catalog.pg_roles WHERE rolname=current_user)
          AND d.defaclobjtype IN ('r','S','f','T','n')
    LOOP
        objects := CASE item.defaclobjtype WHEN 'r' THEN 'TABLES' WHEN 'S' THEN 'SEQUENCES'
            WHEN 'f' THEN 'FUNCTIONS' WHEN 'T' THEN 'TYPES' WHEN 'n' THEN 'SCHEMAS' END;
        scope := CASE WHEN item.nspname IS NULL THEN '' ELSE format(' IN SCHEMA %I',item.nspname) END;
        EXECUTE format('ALTER DEFAULT PRIVILEGES%s REVOKE ALL ON %s FROM %s',
            scope,objects,CASE WHEN item.grantee=0 THEN 'PUBLIC' ELSE quote_ident(item.rolname) END);
    END LOOP;
    EXECUTE format('ALTER DEFAULT PRIVILEGES GRANT ALL ON TABLES TO %I',current_user);
    EXECUTE format('ALTER DEFAULT PRIVILEGES GRANT ALL ON SEQUENCES TO %I',current_user);
    EXECUTE format('ALTER DEFAULT PRIVILEGES GRANT ALL ON FUNCTIONS TO %I',current_user);
    ALTER DEFAULT PRIVILEGES GRANT EXECUTE ON FUNCTIONS TO PUBLIC;
    EXECUTE format('ALTER DEFAULT PRIVILEGES GRANT ALL ON TYPES TO %I',current_user);
    ALTER DEFAULT PRIVILEGES GRANT USAGE ON TYPES TO PUBLIC;
    EXECUTE format('ALTER DEFAULT PRIVILEGES GRANT ALL ON SCHEMAS TO %I',current_user);
END
$restore_defaults$;
"""


def _check_restore_archive(cfg: Config, dump: Path) -> None:
    # pg_restore's script contains an internal COMMIT around large objects.
    # Refuse those archives before connecting to the target, never skip the data.
    large_objects = False
    with subprocess.Popen([_pg_bin('pg_restore', cfg), '--list', str(dump)],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as process:
        for line in process.stdout:
            if re.match(rb'^\d+;\s+\d+\s+\d+\s+(?:BLOBS?|LARGE OBJECT)\b', line):
                large_objects = True
        if process.wait() != 0:
            raise RuntimeError(f'restore archive inspection failed (pg_restore={process.returncode})')
    if large_objects:
        raise RuntimeError('large objects require an empty restore target; in-place restore refused')


def restore(cfg: Config, dump: Path, assume_yes: bool = False) -> None:
    from . import db
    if not assume_yes:
        raise RuntimeError("restore requires explicit confirmation (assume_yes=True)")
    _check_restore_archive(cfg, dump)
    # One transaction includes the temporary default-ACL reset and the restore.
    # Stream COPY data without buffering the archive as SQL in RAM or on disk.
    # COMMIT is sent only after pg_restore produced the complete script.
    with subprocess.Popen([_pg_bin("pg_restore", cfg), "--clean", "--if-exists", "--file=-", str(dump)],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as source:
        target = None
        try:
            target = subprocess.Popen([_pg_bin("psql", cfg), "-X", "--set=ON_ERROR_STOP=on",
                                       "-d", db.dsn(cfg), "--file=-"], stdin=subprocess.PIPE,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            target.stdin.write(_RESTORE_DEFAULTS.encode())
            shutil.copyfileobj(source.stdout, target.stdin)
            source.stdout.close()
            if source.wait() == 0:
                target.stdin.write(b"\nCOMMIT;\n")
            target.stdin.close()
            if target.wait() != 0 or source.returncode != 0:
                raise RuntimeError(f"restore failed (pg_restore={source.returncode}, psql={target.returncode}); "
                                   "verify transaction outcome before retrying")
        except BrokenPipeError as exc:
            raise RuntimeError(f"restore failed (SQL stream closed, psql={target.poll()}); "
                               "verify transaction outcome before retrying") from exc
        finally:
            for process in (target, source):
                if process is not None:
                    if process.poll() is None:
                        process.terminate()
                    process.wait()
            source.stdout.close()
            if target is not None and target.stdin is not None and not target.stdin.closed:
                try:
                    target.stdin.close()
                except BrokenPipeError:
                    pass


_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.agentic-rag.backup</string>
  <key>ProgramArguments</key>
  <array><string>{rag_bin}</string><string>backup</string></array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>3</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardErrorPath</key><string>{log}</string>
  <key>StandardOutPath</key><string>{log}</string>
</dict></plist>
"""


def install_launchd(cfg: Config, rag_bin: Path) -> Path:
    log = Path.home() / ".agentic-rag" / "log" / "backup.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(_PLIST.format(rag_bin=rag_bin, log=log))
    subprocess.run(["launchctl", "unload", str(PLIST_PATH)],
                   capture_output=True)
    subprocess.run(["launchctl", "load", "-w", str(PLIST_PATH)],
                   check=True, capture_output=True, text=True)
    return PLIST_PATH
