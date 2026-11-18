"""Fresh migrations and upgrades support account setup and preserve ownership."""

from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("alembic")
pytest.importorskip("fastapi")
pytest.importorskip("multipart")

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, inspect, select, text
from sqlalchemy.orm import Session

from startnummer.adapters.db.schema import Base, InstanceRow, UserRow
from startnummer.adapters.db.store import Store
from startnummer.adapters.face.sessions import FaceSessions
from startnummer.app.api import create_app
from startnummer.app.manage import migrate
from startnummer.app.settings import Settings
from tests.test_accounts import HEADERS, PASSWORD, imported

ROOT = Path(__file__).resolve().parents[1]


def configuration():
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return config


@pytest.fixture
def migrated(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "initial.db"))

    @event.listens_for(engine, "connect")
    def enforce_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys = ON")

    try:
        migrate(engine)
        yield engine
    finally:
        engine.dispose()


def test_migrations_match_the_complete_schema(migrated):
    revisions = list(ScriptDirectory.from_config(configuration()).walk_revisions())
    assert [(revision.revision, revision.down_revision) for revision in revisions] == [
        ("3", "2"),
        ("2", "1"),
        ("1", None),
    ]
    with migrated.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "3"
    with Session(migrated) as db:
        instance = db.get(InstanceRow, 1)
        assert instance.admin_owner_id is None and not instance.registration_enabled and instance.revision == 0
        assert db.scalar(select(func.count()).select_from(UserRow)) == 0


def test_upgrade_from_first_release_preserves_users_sessions_and_batches(migrated, tmp_path):
    settings = Settings(
        database_url=str(migrated.url),
        blob_root=tmp_path / "photos",
        password="",
        session_secret="s" * 32,
        worker_secret="w" * 32,
        cookie_secure=False,
        owner_id=uuid4(),
    )
    app = create_app(settings, store=Store(migrated), sessions=FaceSessions())
    with TestClient(app, headers=HEADERS) as admin, TestClient(app, headers=HEADERS) as visitor:
        assert admin.get("/api/auth/status").json() == {"setup_required": True, "registration_enabled": False}
        response = admin.post(
            "/api/auth/setup",
            json={"username": "first-admin", "password": PASSWORD, "code": app.state.authentication.setup_code()},
        )
        assert response.status_code == 200 and response.json()["is_admin"]
        batch = imported(admin)
        saved = admin.get(f"/api/batches/{batch['album']['id']}").json()
        body = {"username": "member", "password": PASSWORD}
        assert visitor.post("/api/auth/register", json=body).status_code == 400
        assert (
            admin.put("/api/admin/registration", json={"revision": 0, "registration_enabled": True}).status_code == 200
        )
        assert visitor.post("/api/auth/register", json=body).status_code == 200
        assert visitor.get("/api/session").json()["is_admin"] is False

        config = configuration()
        with migrated.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "1")
            assert "disabled" not in {column["name"] for column in inspect(connection).get_columns("sn_users")}
        migrate(migrated)
        assert admin.get(f"/api/batches/{batch['album']['id']}").json() == saved
        assert admin.get("/api/auth/status").json() == {"setup_required": False, "registration_enabled": True}
        assert visitor.get("/api/session").status_code == 200
        assert all(not user["disabled"] for user in admin.get("/api/admin/accounts").json()["users"])
        with Session(migrated) as db:
            assert db.scalar(select(func.count()).select_from(UserRow)) == 2


def test_initial_revision_can_be_downgraded_and_reapplied(migrated):
    config = configuration()
    with migrated.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "base")
    assert not set(Base.metadata.tables).intersection(inspect(migrated).get_table_names())
    migrate(migrated)
    with migrated.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "3"
