"""The first release has one initial schema and preserves the complete dev head."""

from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("alembic")
pytest.importorskip("fastapi")
pytest.importorskip("multipart")

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from startnummer.adapters.db.schema import Base
from startnummer.app.manage import migrate
from tests.test_workflow import environment as environment
from tests.test_workflow import import_batch

ROOT = Path(__file__).resolve().parents[1]


def test_single_initial_migration_matches_the_complete_schema(tmp_path):
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    revisions = list(ScriptDirectory.from_config(config).walk_revisions())
    assert len(revisions) == 1 and revisions[0].down_revision is None
    assert revisions[0].revision == "0003"
    engine = create_engine("sqlite:///" + str(tmp_path / "initial.db"))
    try:
        migrate(engine)
        with engine.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0003"
    finally:
        engine.dispose()


def test_complete_development_schema_and_saved_batches_need_no_restamp(environment):
    service, _ = environment
    batch = import_batch(service)
    with service.store.engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('0003')"))
    before = service.store.get(batch.album.owner_id, batch.album.id)
    migrate(service.store.engine)
    assert service.store.get(batch.album.owner_id, batch.album.id) == before
