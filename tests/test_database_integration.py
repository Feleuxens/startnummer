"""Opt-in isolated SQL integration checks; never target a live gallery database."""

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from startnummer.adapters.db.schema import Base
from startnummer.adapters.db.store import Store
from startnummer.core.batch import Batch, Conflict, DescriptionWrite, Destination, Photo, WriteState
from startnummer.core.enums import Sport
from startnummer.core.interfaces import EntryList
from startnummer.core.models import Athlete
from startnummer.core.record import Album


@pytest.fixture
def postgres(monkeypatch):
    url = os.environ.get("STARTNUMMER_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set STARTNUMMER_TEST_DATABASE_URL for isolated Postgres checks")
    admin = create_engine(url)
    schema = "sn_test_" + uuid4().hex
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated_url = (
        make_url(url).update_query_dict({"options": "-csearch_path=" + schema}).render_as_string(hide_password=False)
    )
    engine = create_engine(isolated_url)
    monkeypatch.setenv("STARTNUMMER_DATABASE_URL", isolated_url)
    yield Store(engine)
    engine.dispose()
    with admin.begin() as connection:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


def batch(store):
    owner = uuid4()
    value = Batch(
        album=Album(owner_id=owner, name="SQL test", sport=Sport.ATHLETICS),
        roster=EntryList(athletes=[Athlete(name="Synthetic Runner", bib="12", entered_events=["100m"])]),
        photos=[
            Photo(
                display_name="synthetic.jpg",
                blob_key="test",
                content_hash="sha256:" + "a" * 64,
                size=1,
                mime_type="image/jpeg",
            )
        ],
    )
    with store.transaction(owner) as session:
        store.save(session, value)
    return value


def test_postgres_migration_upgrade_and_downgrade(postgres):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    config = Config("alembic.ini")
    command.upgrade(config, "head")
    assert set(Base.metadata.tables).issubset(inspect(postgres.engine).get_table_names())
    saved = batch(postgres)
    assert postgres.get(saved.album.owner_id, saved.album.id) == saved
    command.downgrade(config, "base")
    assert not set(Base.metadata.tables).intersection(inspect(postgres.engine).get_table_names())


def test_postgres_concurrent_claims_and_fenced_atomic_completion(postgres):
    Base.metadata.create_all(postgres.engine)
    first, second = batch(postgres), batch(postgres)
    for item in (first, second):
        postgres.enqueue(item.album.owner_id, item.album.id)
    with ThreadPoolExecutor(max_workers=2) as executor:
        jobs = list(executor.map(lambda _: postgres.claim(), range(2)))
    assert len({job.id for job in jobs}) == 2
    assert all(job.attempts == 1 for job in jobs)
    original = jobs[0]

    def broken_merge(value):
        value.photos[0].caption = "Must not commit"
        raise RuntimeError("simulated storage failure")

    with pytest.raises(RuntimeError):
        postgres.complete(original, broken_merge)
    assert postgres.get(original.owner_id, original.batch_id).photos[0].caption is None
    assert postgres.jobs(original.owner_id, original.batch_id)[0].state == "running"
    stale = original.model_copy(update={"lease_token": uuid4()})
    with pytest.raises(Conflict):
        postgres.complete(stale, lambda value: None)
    postgres.complete(original, lambda value: setattr(value.photos[0], "caption", "Saved together"))
    assert postgres.jobs(original.owner_id, original.batch_id)[0].state == "done"
    assert postgres.get(original.owner_id, original.batch_id).photos[0].caption == "Saved together"


def test_mariadb_exact_null_safe_writes_and_restore():
    dsn = os.environ.get("STARTNUMMER_TEST_MYSQL_DSN")
    if not dsn:
        pytest.skip("Set STARTNUMMER_TEST_MYSQL_DSN to an isolated SQL test database")
    from startnummer.adapters.chevereto import Chevereto

    # A database dedicated to adapter tests is mandatory; never use 'chevereto'.
    if not make_url(dsn).database.startswith("startnummer_test_"):
        pytest.fail("MariaDB tests require a startnummer_test_* database")
    gallery = Chevereto("http://gallery.test", dsn)
    with gallery.connect() as db, db.cursor() as cursor:
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS chv_images (image_id INT PRIMARY KEY, "
            "image_description TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci)"
        )
        cursor.execute("DELETE FROM chv_images")
        cursor.execute("INSERT INTO chv_images VALUES (1,NULL),(2,'Résumé')")
        db.commit()
    target = Destination(instance="http://gallery.test", image_id=1, page_url="http://gallery.test/image/1")
    change = DescriptionWrite(destination=target, expected=None, replacement="A 'quoted' caption")
    assert gallery.write(change).state is WriteState.APPLIED
    assert gallery.write(change).state is WriteState.UNCHANGED
    assert (
        gallery.write(change.model_copy(update={"expected": "wrong", "replacement": "overwrite"})).state
        is WriteState.CONFLICT
    )
    assert (
        gallery.write(DescriptionWrite(destination=target, expected=change.replacement, replacement=None)).state
        is WriteState.APPLIED
    )
    exact = DescriptionWrite(
        destination=target.model_copy(update={"image_id": 2}), expected="resume", replacement="changed"
    )
    assert gallery.write(exact).state is WriteState.CONFLICT
    assert gallery.write(exact.model_copy(update={"expected": "Résumé"})).state is WriteState.APPLIED
