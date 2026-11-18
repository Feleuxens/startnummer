"""Configuration diagnostics identify invalid fields without echoing their values."""

import os

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("alembic")

from sqlalchemy import create_engine, text

from startnummer.app.manage import main
from startnummer.app.settings import Settings
from startnummer.core.batch import WorkflowError


@pytest.fixture
def configuration(tmp_path, monkeypatch):
    for key in os.environ:
        if key.startswith("STARTNUMMER_"):
            monkeypatch.delenv(key)
    return ["--env-file", str(tmp_path / "absent.env")]


@pytest.mark.parametrize("invalid_app_settings", [False, True])
def test_migration_needs_only_its_database_url(configuration, tmp_path, monkeypatch, capsys, invalid_app_settings):
    url = "sqlite:///" + str(tmp_path / "migrated.db")
    monkeypatch.setenv("STARTNUMMER_DATABASE_URL", url)
    if invalid_app_settings:
        # App-only values must not prevent schema migration, including first setup.
        monkeypatch.setenv("STARTNUMMER_SESSION_SECRET", "short-secret")
        monkeypatch.setenv("STARTNUMMER_WORKER_SECRET", "w" * 32)
        monkeypatch.setenv("STARTNUMMER_FACE_SESSION_TTL", "not-an-integer")
    main([*configuration, "migrate"])
    assert "Migrations applied" in capsys.readouterr().out
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "3"
    finally:
        engine.dispose()


def test_migration_reports_missing_database_url(configuration, capsys):
    with pytest.raises(SystemExit) as result:
        main([*configuration, "migrate"])
    assert result.value.code == 1
    assert "STARTNUMMER_DATABASE_URL is required" in capsys.readouterr().err


def test_migration_reports_invalid_url_without_credentials(configuration, monkeypatch, capsys):
    password = "synthetic-private-password"
    monkeypatch.setenv("STARTNUMMER_DATABASE_URL", f"postgresql+psycopg://example:{password}@localhost:invalid/app")
    with pytest.raises(SystemExit) as result:
        main([*configuration, "migrate"])
    assert result.value.code == 1
    error = capsys.readouterr().err
    assert "STARTNUMMER_DATABASE_URL" in error and "invalid" in error
    assert password not in error


@pytest.mark.parametrize("name", ["STARTNUMMER_SESSION_SECRET", "STARTNUMMER_WORKER_SECRET"])
def test_short_secret_error_names_only_its_field(configuration, monkeypatch, capsys, name):
    monkeypatch.setenv("STARTNUMMER_SESSION_SECRET", "s" * 32)
    monkeypatch.setenv("STARTNUMMER_WORKER_SECRET", "w" * 32)
    monkeypatch.setenv(name, "synthetic-short-secret")
    with pytest.raises(SystemExit) as result:
        main([*configuration, "status"])
    assert result.value.code == 1
    error = capsys.readouterr().err
    assert name in error and "32 characters" in error
    assert "synthetic-short-secret" not in error


@pytest.mark.parametrize(
    "name",
    [
        "STARTNUMMER_FACE_SESSION_TTL",
        "STARTNUMMER_MAX_FILE_BYTES",
        "STARTNUMMER_MAX_BATCH_BYTES",
    ],
)
def test_integer_error_names_only_its_field(configuration, tmp_path, monkeypatch, name):
    for key, value in {
        "STARTNUMMER_SESSION_SECRET": "s" * 32,
        "STARTNUMMER_WORKER_SECRET": "w" * 32,
        "STARTNUMMER_DATABASE_URL": "sqlite://",
        "STARTNUMMER_BLOB_ROOT": str(tmp_path / "photos"),
        "STARTNUMMER_PASSWORD": "synthetic-login",
        name: "synthetic-invalid-value",
    }.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(WorkflowError) as result:
        Settings.from_env()
    assert name in str(result.value) and "integer" in str(result.value)
    assert "synthetic-invalid-value" not in str(result.value)


@pytest.fixture
def cookie_configuration(configuration, tmp_path, monkeypatch):
    monkeypatch.setenv("STARTNUMMER_DATABASE_URL", "sqlite://")
    monkeypatch.setenv("STARTNUMMER_BLOB_ROOT", str(tmp_path / "photos"))
    monkeypatch.setenv("STARTNUMMER_SESSION_SECRET", "s" * 32)
    monkeypatch.setenv("STARTNUMMER_WORKER_SECRET", "w" * 32)
    return configuration


@pytest.mark.parametrize("value, secure", [(None, True), ("1", True), ("TRUE", True), ("0", False), ("false", False)])
def test_secure_cookie_is_default_and_http_requires_explicit_opt_out(cookie_configuration, monkeypatch, value, secure):
    if value is not None:
        monkeypatch.setenv("STARTNUMMER_COOKIE_SECURE", value)
    assert Settings.from_env().cookie_secure is secure


@pytest.mark.parametrize("value", ["", "flase", "synthetic-private-value"])
def test_invalid_cookie_setting_stops_native_startup(cookie_configuration, monkeypatch, capsys, value):
    monkeypatch.setenv("STARTNUMMER_COOKIE_SECURE", value)
    with pytest.raises(SystemExit) as result:
        main([*cookie_configuration, "start"])
    assert result.value.code == 1
    assert capsys.readouterr().err == "STARTNUMMER_COOKIE_SECURE must be 1, 0, true, or false\n"


def test_setup_code_cli_does_not_require_an_environment_login(configuration, tmp_path, monkeypatch, capsys):
    from startnummer.adapters.db.store import Store
    from startnummer.app.auth import Authentication
    from startnummer.app.manage import migrate

    for name, value in {
        "STARTNUMMER_DATABASE_URL": "sqlite:///" + str(tmp_path / "setup.db"),
        "STARTNUMMER_BLOB_ROOT": str(tmp_path / "photos"),
        "STARTNUMMER_SESSION_SECRET": "s" * 32,
        "STARTNUMMER_WORKER_SECRET": "w" * 32,
    }.items():
        monkeypatch.setenv(name, value)
    settings = Settings.from_env()
    engine = create_engine(settings.database_url)
    try:
        migrate(engine)
        main([*configuration, "setup-code"])
        code = capsys.readouterr().out.strip()
        assert len(code) == 64 and settings.session_secret not in code
        authentication = Authentication(engine, settings)
        user = authentication.setup(code, "first-admin", "synthetic-long-password")
        assert Store(engine).list_batches(user.id) == []
        with pytest.raises(SystemExit):
            main([*configuration, "setup-code"])
        assert "already been completed" in capsys.readouterr().err
    finally:
        engine.dispose()
