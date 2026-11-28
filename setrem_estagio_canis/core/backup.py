"""Automated backup engine for Laika database and uploaded media.

Supports atomic SQLite snapshots, PostgreSQL dumps via ``pg_dump``, bundling of
uploaded media files into timestamped ``.tar.gz`` archives, local retention
pruning, and optional off-site synchronization to Google Drive via ``rclone``.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import shutil
import signal
import sqlite3
import subprocess
import tarfile
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import FrameType
from urllib.parse import unquote, urlparse

import orjson

from setrem_estagio_canis.core.config import (
    BACKUP_DIR,
    BACKUP_INTERVAL_HOURS,
    BACKUP_RCLONE_CONFIG,
    BACKUP_RCLONE_REMOTE,
    BACKUP_RETENTION_DAYS,
    DATABASE_URL,
    UPLOAD_DIR,
)

logger = logging.getLogger(__name__)

_BACKUP_PREFIX = "laika_backup_"
_BACKUP_SUFFIX = ".tar.gz"
_APP_VERSION = "0.3.0"


class BackupError(RuntimeError):
    """Raised when a critical backup operation fails."""


@dataclass(frozen=True)
class BackupConfig:
    """Configuration container for a Laika backup execution."""

    database_url: str
    upload_dir: Path
    backup_dir: Path
    retention_days: int = 30
    rclone_remote: str = ""
    rclone_config: str = ""

    @classmethod
    def from_env(cls) -> BackupConfig:
        """Build a BackupConfig from environment-backed application settings.

        Returns:
            Populated BackupConfig instance.
        """
        return cls(
            database_url=DATABASE_URL,
            upload_dir=UPLOAD_DIR,
            backup_dir=BACKUP_DIR,
            retention_days=max(1, BACKUP_RETENTION_DAYS),
            rclone_remote=BACKUP_RCLONE_REMOTE,
            rclone_config=BACKUP_RCLONE_CONFIG,
        )


@dataclass(frozen=True)
class BackupResult:
    """Metadata describing the outcome of a single backup execution."""

    archive_path: Path
    size_bytes: int
    db_engine: str
    uploaded_to_remote: bool
    remote_target: str
    pruned_local_count: int
    created_at_utc: str


@dataclass(frozen=True)
class BackupEntry:
    """Summary of an existing local backup archive."""

    filename: str
    size_bytes: int
    created_at_str: str

    @property
    def size_human(self) -> str:
        """Format archive size in human-readable KB or MB."""
        if self.size_bytes >= 1024 * 1024:
            return f"{self.size_bytes / (1024 * 1024):.2f} MB"
        return f"{max(1, round(self.size_bytes / 1024))} KB"


def _sha256_file(path: Path) -> str:
    """Compute the SHA-256 hex digest of a file using buffered streaming.

    Args:
        path: Path to the file to hash.

    Returns:
        Lowercase hexadecimal SHA-256 digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_sqlite_path(database_url: str) -> Path:
    """Extract the filesystem path from a SQLite SQLAlchemy URL.

    Args:
        database_url: SQLAlchemy SQLite connection URL.

    Returns:
        Resolved Path to the SQLite database file.

    Raises:
        BackupError: If the URL refers to an in-memory database or is empty.
    """
    raw = database_url.split(":///", maxsplit=1)
    if len(raw) != 2 or not raw[1] or ":memory:" in raw[1]:
        raise BackupError("Nao e possivel realizar backup de banco SQLite em memoria.")
    return Path(unquote(raw[1])).expanduser().resolve()


def dump_sqlite(database_url: str, dest_path: Path) -> Path:
    """Create a consistent online snapshot of a SQLite database.

    Args:
        database_url: SQLAlchemy SQLite connection URL.
        dest_path: Target path for the snapshot file.

    Returns:
        Path to the created SQLite snapshot file.

    Raises:
        BackupError: If the source file does not exist or sqlite3 backup fails.
    """
    source_path = _resolve_sqlite_path(database_url)
    if not source_path.exists():
        raise BackupError(f"Arquivo SQLite de origem nao encontrado: {source_path}")

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with (
            sqlite3.connect(str(source_path)) as src_conn,
            sqlite3.connect(str(dest_path)) as dst_conn,
        ):
            src_conn.backup(dst_conn)
    except sqlite3.Error as exc:
        logger.error("Falha ao gerar snapshot SQLite: %s", exc)
        raise BackupError("Falha ao realizar snapshot do banco SQLite.") from exc
    return dest_path


def _parse_postgres_params(database_url: str) -> tuple[list[str], dict[str, str]]:
    """Build safe ``pg_dump`` arguments and environment without leaking secrets.

    Args:
        database_url: SQLAlchemy PostgreSQL connection URL.

    Returns:
        Tuple of (pg_dump_args, env_vars) where password is placed exclusively
        in ``PGPASSWORD``.

    Raises:
        BackupError: If the URL is missing a database name or host.
    """
    normalized = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlparse(normalized)
    db_name = parsed.path.lstrip("/")
    if not parsed.hostname or not db_name:
        raise BackupError("DATABASE_URL PostgreSQL invalida para pg_dump.")

    args = [
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--no-acl",
        "--host",
        parsed.hostname,
        "--port",
        str(parsed.port or 5432),
        "--dbname",
        db_name,
    ]
    if parsed.username:
        args.extend(["--username", unquote(parsed.username)])

    env = dict(os.environ)
    if parsed.password:
        env["PGPASSWORD"] = unquote(parsed.password)
    return args, env


def dump_postgres(database_url: str, dest_path: Path) -> Path:
    """Create a custom-format PostgreSQL dump using ``pg_dump``.

    Args:
        database_url: SQLAlchemy PostgreSQL connection URL.
        dest_path: Target path for the ``.dump`` file.

    Returns:
        Path to the created PostgreSQL dump file.

    Raises:
        BackupError: If ``pg_dump`` is unavailable or exits with a non-zero status.
    """
    if shutil.which("pg_dump") is None:
        raise BackupError("Binario pg_dump nao encontrado no ambiente.")

    args, env = _parse_postgres_params(database_url)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [*args, "--file", str(dest_path)]

    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        logger.error("Erro ao invocar pg_dump: %s", exc)
        raise BackupError("Nao foi possivel executar o comando pg_dump.") from exc

    if result.returncode != 0:
        logger.error("pg_dump retornou erro (codigo %d).", result.returncode)
        raise BackupError(f"pg_dump falhou com codigo {result.returncode}.")
    return dest_path


def _collect_upload_files(upload_dir: Path) -> list[Path]:
    """List regular files inside the uploads directory.

    Args:
        upload_dir: Root directory containing uploaded media files.

    Returns:
        Sorted list of regular file paths under ``upload_dir``.
    """
    if not upload_dir.exists():
        return []
    return sorted(p for p in upload_dir.rglob("*") if p.is_file())


def sync_to_rclone(
    archive_path: Path,
    rclone_remote: str,
    retention_days: int,
    rclone_config: str = "",
) -> bool:
    """Upload a backup archive to a configured rclone remote and prune old copies.

    Args:
        archive_path: Local path to the generated ``.tar.gz`` backup archive.
        rclone_remote: Destination rclone remote path (e.g. ``gdrive:laika-backups``).
        retention_days: Maximum age in days to retain backups on the remote.
        rclone_config: Optional explicit path to ``rclone.conf``.

    Returns:
        True if the archive was uploaded successfully, False otherwise.
    """
    remote = rclone_remote.strip()
    if not remote:
        return False

    if shutil.which("rclone") is None:
        logger.error("rclone nao encontrado; backup mantido apenas localmente.")
        return False

    base_cmd = ["rclone"]
    if rclone_config.strip():
        base_cmd.extend(["--config", rclone_config.strip()])

    copy_cmd = [*base_cmd, "copy", str(archive_path), remote]
    try:
        copy_res = subprocess.run(
            copy_cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        logger.error("Erro ao executar rclone copy: %s", exc)
        return False

    if copy_res.returncode != 0:
        logger.error(
            "Falha ao enviar backup via rclone (codigo %d).", copy_res.returncode
        )
        return False

    prune_cmd = [
        *base_cmd,
        "delete",
        remote,
        "--min-age",
        f"{max(1, retention_days)}d",
        "--include",
        f"{_BACKUP_PREFIX}*{_BACKUP_SUFFIX}",
    ]
    try:
        prune_res = subprocess.run(
            prune_cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        if prune_res.returncode != 0:
            logger.error(
                "Aviso: rclone delete falhou ao limpar backups antigos (codigo %d).",
                prune_res.returncode,
            )
    except OSError as exc:
        logger.error("Erro ao executar limpeza remota via rclone: %s", exc)

    return True


def prune_old_backups(backup_dir: Path, retention_days: int) -> int:
    """Remove local backup archives older than ``retention_days``.

    Always preserves the most recent archive to guarantee at least one copy.

    Args:
        backup_dir: Directory storing local ``laika_backup_*.tar.gz`` archives.
        retention_days: Retention window in days.

    Returns:
        Number of expired local backup archives removed.
    """
    if not backup_dir.exists():
        return 0

    archives = sorted(
        backup_dir.glob(f"{_BACKUP_PREFIX}*{_BACKUP_SUFFIX}"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if len(archives) <= 1:
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, retention_days))
    removed = 0
    for candidate in archives[1:]:
        mtime = datetime.fromtimestamp(candidate.stat().st_mtime, tz=timezone.utc)
        if mtime < cutoff:
            try:
                candidate.unlink()
                removed += 1
            except OSError as exc:
                logger.error(
                    "Falha ao remover backup expirado %s: %s", candidate.name, exc
                )
    return removed


def list_local_backups(backup_dir: Path | None = None) -> list[BackupEntry]:
    """List existing local backup archives ordered from newest to oldest.

    Args:
        backup_dir: Optional directory override; defaults to configured ``BACKUP_DIR``.

    Returns:
        List of BackupEntry summaries.
    """
    target_dir = backup_dir or BACKUP_DIR
    if not target_dir.exists():
        return []

    archives = sorted(
        target_dir.glob(f"{_BACKUP_PREFIX}*{_BACKUP_SUFFIX}"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    entries: list[BackupEntry] = []
    for path in archives:
        stat = path.stat()
        dt = datetime.fromtimestamp(stat.st_mtime)
        entries.append(
            BackupEntry(
                filename=path.name,
                size_bytes=stat.st_size,
                created_at_str=dt.strftime("%d/%m/%Y %H:%M"),
            )
        )
    return entries


def resolve_local_backup_path(
    filename: str,
    backup_dir: Path | None = None,
) -> Path | None:
    """Safely resolve a local backup filename preventing path traversal.

    Args:
        filename: Requested archive filename.
        backup_dir: Optional directory override; defaults to ``BACKUP_DIR``.

    Returns:
        Resolved Path if valid and existing, otherwise None.
    """
    if (
        not filename.startswith(_BACKUP_PREFIX)
        or not filename.endswith(_BACKUP_SUFFIX)
        or "/" in filename
        or "\\" in filename
        or ".." in filename
    ):
        return None

    base = (backup_dir or BACKUP_DIR).resolve()
    candidate = (base / filename).resolve()
    if candidate.parent != base or not candidate.is_file():
        return None
    return candidate


def run_backup(config: BackupConfig | None = None) -> BackupResult:
    """Execute a complete backup of the Laika database and uploaded media.

    Args:
        config: Optional BackupConfig; defaults to environment configuration.

    Returns:
        BackupResult describing the created archive and remote sync status.

    Raises:
        BackupError: If database dump or archive creation fails.
    """
    cfg = config or BackupConfig.from_env()
    now_utc = datetime.now(timezone.utc)
    timestamp = now_utc.strftime("%Y%m%d_%H%M%S")
    cfg.backup_dir.mkdir(parents=True, exist_ok=True)
    archive_path = cfg.backup_dir / f"{_BACKUP_PREFIX}{timestamp}{_BACKUP_SUFFIX}"

    is_sqlite = cfg.database_url.startswith("sqlite")
    db_engine = "sqlite" if is_sqlite else "postgresql"
    db_filename = "database.sqlite" if is_sqlite else "database.dump"

    with tempfile.TemporaryDirectory(prefix="laika_bk_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        db_dump_path = tmp_dir / db_filename

        if is_sqlite:
            dump_sqlite(cfg.database_url, db_dump_path)
        else:
            dump_postgres(cfg.database_url, db_dump_path)

        upload_files = _collect_upload_files(cfg.upload_dir)
        manifest = {
            "application": "Laika",
            "version": _APP_VERSION,
            "created_at_utc": now_utc.isoformat(),
            "db_engine": db_engine,
            "db_file": db_filename,
            "db_sha256": _sha256_file(db_dump_path),
            "uploads_count": len(upload_files),
        }
        manifest_path = tmp_dir / "manifest.json"
        manifest_path.write_bytes(orjson.dumps(manifest, option=orjson.OPT_INDENT_2))

        try:
            with tarfile.open(archive_path, mode="w:gz") as tar:
                tar.add(manifest_path, arcname="manifest.json")
                tar.add(db_dump_path, arcname=db_filename)
                for file_path in upload_files:
                    rel = file_path.relative_to(cfg.upload_dir)
                    tar.add(file_path, arcname=str(Path("uploads") / rel))
        except (OSError, tarfile.TarError) as exc:
            logger.error("Falha ao empacotar arquivo de backup: %s", exc)
            raise BackupError("Falha ao criar arquivo compactado de backup.") from exc

    uploaded = sync_to_rclone(
        archive_path=archive_path,
        rclone_remote=cfg.rclone_remote,
        retention_days=cfg.retention_days,
        rclone_config=cfg.rclone_config,
    )
    pruned = prune_old_backups(cfg.backup_dir, cfg.retention_days)

    return BackupResult(
        archive_path=archive_path,
        size_bytes=archive_path.stat().st_size,
        db_engine=db_engine,
        uploaded_to_remote=uploaded,
        remote_target=cfg.rclone_remote,
        pruned_local_count=pruned,
        created_at_utc=now_utc.isoformat(),
    )


def run_daemon(
    interval_hours: int = BACKUP_INTERVAL_HOURS,
    config: BackupConfig | None = None,
) -> None:
    """Run backups continuously on a fixed interval until interrupted.

    Args:
        interval_hours: Hours to wait between consecutive backup runs.
        config: Optional BackupConfig override.
    """
    stop_event = threading.Event()

    def _handle_signal(_signum: int, _frame: FrameType | None) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    wait_seconds = max(60, interval_hours * 3600)
    logger.info(
        "Servico de backup Laika iniciado (intervalo: %d h).",
        max(1, interval_hours),
    )

    while not stop_event.is_set():
        try:
            res = run_backup(config)
            logger.info(
                "Backup concluido: %s (%d bytes, nuvem=%s).",
                res.archive_path.name,
                res.size_bytes,
                res.uploaded_to_remote,
            )
        except BackupError as exc:
            logger.error("Execucao agendada de backup falhou: %s", exc)
        stop_event.wait(wait_seconds)


def main() -> None:
    """CLI entrypoint for one-shot or scheduled Laika backups."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Rotina de backup do banco de dados e arquivos do Laika."
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Executa continuamente no intervalo definido em BACKUP_INTERVAL_HOURS.",
    )
    args = parser.parse_args()

    if args.daemon:
        run_daemon()
    else:
        res = run_backup()
        logger.info(
            "Backup concluido: %s (%d bytes, nuvem=%s).",
            res.archive_path.name,
            res.size_bytes,
            res.uploaded_to_remote,
        )


if __name__ == "__main__":
    main()
