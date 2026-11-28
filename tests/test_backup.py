"""Unit and integration tests for the Laika backup engine and admin routes."""

import hashlib
import os
import sqlite3
import subprocess
import tarfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import orjson
import pytest
from fastapi.testclient import TestClient

os.environ["TESTING"] = "1"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["GOOGLE_CLIENT_ID"] = ""
os.environ["GOOGLE_CLIENT_SECRET"] = ""

from setrem_estagio_canis.core.backup import (
    BackupConfig,
    BackupError,
    BackupResult,
    dump_postgres,
    dump_sqlite,
    list_local_backups,
    prune_old_backups,
    resolve_local_backup_path,
    run_backup,
    sync_to_rclone,
)
from setrem_estagio_canis.database.models import Base
from setrem_estagio_canis.database.repository import seed_initial_data
from setrem_estagio_canis.database.session import SessionLocal, engine
from setrem_estagio_canis.main import app

_TEST_OUTPUT_ROOT = (
    Path(__file__).resolve().parent.parent / "test_outputs" / "backup_tests"
)


def _new_case_dir(prefix: str) -> Path:
    """Create an isolated directory under the gitignored test_outputs folder."""
    case_dir = _TEST_OUTPUT_ROOT / f"{prefix}_{uuid.uuid4().hex[:8]}"
    case_dir.mkdir(parents=True, exist_ok=True)
    return case_dir


def _authenticated_client(email: str, password: str) -> TestClient:
    """Create an authenticated TestClient via local login."""
    client = TestClient(app)
    resp = client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    return client


def test_run_backup_sqlite_bundles_db_uploads_and_manifest() -> None:
    """Run an end-to-end SQLite backup and verify archive integrity and manifest."""
    case_dir = _new_case_dir("sqlite_bundle")
    db_file = case_dir / "source.db"
    upload_dir = case_dir / "uploads"
    backup_dir = case_dir / "backups"
    (upload_dir / "animals").mkdir(parents=True, exist_ok=True)
    (upload_dir / "animals" / "sample.webp").write_bytes(b"RIFFfakewebp")

    with sqlite3.connect(str(db_file)) as conn:
        conn.execute("CREATE TABLE animais (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO animais (name) VALUES ('Pipoca')")
        conn.commit()

    cfg = BackupConfig(
        database_url=f"sqlite:///{db_file}",
        upload_dir=upload_dir,
        backup_dir=backup_dir,
        retention_days=30,
        rclone_remote="",
    )

    result = run_backup(cfg)

    assert result.archive_path.exists()
    assert result.db_engine == "sqlite"
    assert result.uploaded_to_remote is False
    assert result.size_bytes > 0

    with tarfile.open(result.archive_path, mode="r:gz") as tar:
        names = set(tar.getnames())
        assert "manifest.json" in names
        assert "database.sqlite" in names
        assert "uploads/animals/sample.webp" in names

        manifest_file = tar.extractfile("manifest.json")
        db_member = tar.extractfile("database.sqlite")
        assert manifest_file is not None
        assert db_member is not None
        manifest = orjson.loads(manifest_file.read())
        db_bytes = db_member.read()

    assert manifest["application"] == "Laika"
    assert manifest["db_engine"] == "sqlite"
    assert manifest["uploads_count"] == 1
    assert manifest["db_sha256"] == hashlib.sha256(db_bytes).hexdigest()


def test_dump_sqlite_rejects_in_memory_database() -> None:
    """Reject attempts to back up an in-memory SQLite database."""
    case_dir = _new_case_dir("sqlite_mem")
    dest = case_dir / "out.sqlite"

    with pytest.raises(BackupError, match="memoria"):
        dump_sqlite("sqlite:///:memory:", dest)


def test_dump_postgres_uses_pgpassword_env_not_cli() -> None:
    """Invoke pg_dump with password isolated in PGPASSWORD and not in CLI args."""
    case_dir = _new_case_dir("pg_dump")
    dest = case_dir / "database.dump"
    mock_completed = subprocess.CompletedProcess(
        args=["pg_dump"], returncode=0, stdout="", stderr=""
    )

    with (
        patch("shutil.which", return_value="/usr/bin/pg_dump"),
        patch("subprocess.run", return_value=mock_completed) as mock_run,
    ):
        returned = dump_postgres(
            "postgresql+psycopg://laika_user:supersecret@postgres:5432/laika",
            dest,
        )

    assert returned == dest
    cmd = mock_run.call_args.args[0]
    env = mock_run.call_args.kwargs["env"]
    assert "supersecret" not in " ".join(cmd)
    assert env["PGPASSWORD"] == "supersecret"
    assert "--dbname" in cmd
    assert "laika" in cmd
    assert "--host" in cmd
    assert "postgres" in cmd


def test_dump_postgres_raises_when_binary_missing() -> None:
    """Raise BackupError when pg_dump is not installed."""
    case_dir = _new_case_dir("pg_missing")
    dest = case_dir / "database.dump"

    with (
        patch("shutil.which", return_value=None),
        pytest.raises(BackupError, match="pg_dump"),
    ):
        dump_postgres("postgresql+psycopg://u:p@localhost:5432/laika", dest)


def test_sync_to_rclone_uploads_and_prunes_remote() -> None:
    """Verify rclone copy and remote retention delete are invoked when configured."""
    case_dir = _new_case_dir("rclone_ok")
    archive = case_dir / "laika_backup_20261128_000000.tar.gz"
    archive.write_bytes(b"gzdata")
    ok_proc: subprocess.CompletedProcess[str] = subprocess.CompletedProcess(
        args=["rclone"], returncode=0, stdout="", stderr=""
    )

    with (
        patch("shutil.which", return_value="/usr/bin/rclone"),
        patch("subprocess.run", return_value=ok_proc) as mock_run,
    ):
        synced = sync_to_rclone(
            archive_path=archive,
            rclone_remote="gdrive:laika-backups",
            retention_days=15,
            rclone_config="/etc/rclone.conf",
        )

    assert synced is True
    assert mock_run.call_count == 2
    copy_cmd = mock_run.call_args_list[0].args[0]
    prune_cmd = mock_run.call_args_list[1].args[0]
    assert copy_cmd == [
        "rclone",
        "--config",
        "/etc/rclone.conf",
        "copy",
        str(archive),
        "gdrive:laika-backups",
    ]
    assert "delete" in prune_cmd
    assert "15d" in prune_cmd


def test_sync_to_rclone_handles_failure_gracefully() -> None:
    """Return False without crashing when rclone copy returns non-zero."""
    case_dir = _new_case_dir("rclone_fail")
    archive = case_dir / "laika_backup_20261128_000001.tar.gz"
    archive.write_bytes(b"gzdata")
    fail_proc: subprocess.CompletedProcess[str] = subprocess.CompletedProcess(
        args=["rclone"], returncode=1, stdout="", stderr=""
    )

    with (
        patch("shutil.which", return_value="/usr/bin/rclone"),
        patch("subprocess.run", return_value=fail_proc),
    ):
        synced = sync_to_rclone(
            archive_path=archive,
            rclone_remote="gdrive:laika-backups",
            retention_days=30,
        )

    assert synced is False


def test_prune_old_backups_keeps_newest_and_prunes_expired() -> None:
    """Prune expired archives while always preserving the most recent backup."""
    case_dir = _new_case_dir("prune")
    newest = case_dir / "laika_backup_20261128_000000.tar.gz"
    old_one = case_dir / "laika_backup_20260901_000000.tar.gz"
    old_two = case_dir / "laika_backup_20260801_000000.tar.gz"

    for path in (newest, old_one, old_two):
        path.write_bytes(b"backup")

    old_ts = (datetime.now(timezone.utc) - timedelta(days=45)).timestamp()
    os.utime(old_one, (old_ts, old_ts))
    os.utime(old_two, (old_ts - 86400, old_ts - 86400))

    unlinked_names: list[str] = []

    def _fake_unlink(self: Path) -> None:
        unlinked_names.append(self.name)

    with patch.object(Path, "unlink", _fake_unlink):
        removed = prune_old_backups(case_dir, retention_days=30)

    assert removed == 2
    assert set(unlinked_names) == {old_one.name, old_two.name}
    assert newest.name not in unlinked_names


def test_resolve_local_backup_path_blocks_path_traversal() -> None:
    """Allow valid archive filenames and reject traversal or invalid names."""
    case_dir = _new_case_dir("resolve")
    valid = case_dir / "laika_backup_20261128_010000.tar.gz"
    valid.write_bytes(b"ok")

    assert resolve_local_backup_path(valid.name, backup_dir=case_dir) == valid.resolve()
    assert resolve_local_backup_path("../.env", backup_dir=case_dir) is None
    assert (
        resolve_local_backup_path("laika_backup_../x.tar.gz", backup_dir=case_dir)
        is None
    )
    assert resolve_local_backup_path("other.tar.gz", backup_dir=case_dir) is None
    assert len(list_local_backups(backup_dir=case_dir)) == 1


def test_admin_backup_endpoints_enforce_rbac_and_download() -> None:
    """Restrict backup trigger/download routes to admin users and serve archives."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_initial_data(db)

    case_dir = _new_case_dir("routes")
    archive = case_dir / "laika_backup_20261128_020000.tar.gz"
    archive.write_bytes(b"\x1f\x8b\x08fakegzip")

    volunteer = _authenticated_client(
        "lucia.voluntaria@patasepelos.org.br", "voluntario2026"
    )
    admin = _authenticated_client("coordenacao@patasepelos.org.br", "prototipo2026")

    assert volunteer.post("/admin/backups/executar").status_code == 403
    assert volunteer.get(f"/admin/backups/{archive.name}").status_code == 403
    assert "Backups do Sistema" not in volunteer.get("/configuracoes").text

    fake_result = BackupResult(
        archive_path=archive,
        size_bytes=archive.stat().st_size,
        db_engine="sqlite",
        uploaded_to_remote=True,
        remote_target="gdrive:laika-backups",
        pruned_local_count=0,
        created_at_utc="2026-11-28T02:00:00+00:00",
    )

    with (
        patch("setrem_estagio_canis.api.web.run_backup", return_value=fake_result),
        patch(
            "setrem_estagio_canis.api.web.resolve_local_backup_path",
            return_value=archive,
        ),
        patch(
            "setrem_estagio_canis.api.web.list_local_backups",
            return_value=list_local_backups(case_dir),
        ),
    ):
        trigger_resp = admin.post(
            "/admin/backups/executar",
            follow_redirects=False,
        )
        assert trigger_resp.status_code == 303
        assert "enviado+para+a+nuvem" in trigger_resp.headers["location"]

        cfg_resp = admin.get("/configuracoes")
        assert cfg_resp.status_code == 200
        assert "Backups do Sistema" in cfg_resp.text
        assert archive.name in cfg_resp.text

        dl_resp = admin.get(f"/admin/backups/{archive.name}")
        assert dl_resp.status_code == 200
        assert dl_resp.headers["content-type"] == "application/gzip"
        assert dl_resp.content == archive.read_bytes()

    mock_resolve = MagicMock(return_value=None)
    with patch("setrem_estagio_canis.api.web.resolve_local_backup_path", mock_resolve):
        assert (
            admin.get("/admin/backups/laika_backup_missing.tar.gz").status_code == 404
        )
