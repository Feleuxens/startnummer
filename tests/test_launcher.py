"""Local launcher lifecycle with real subprocesses and synthetic storage."""

import json
import os
import signal
import socket
import subprocess
import sys
import time
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")
pytest.importorskip("multipart")

from sqlalchemy import create_engine

from startnummer.app.manage import migrate, parser, process_identity, read_state, status, stop, supervise
from startnummer.app.settings import Settings
from startnummer.core.batch import WorkflowError


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for(predicate, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for launcher fixture")


def test_supervisor_starts_probes_restarts_only_failed_child_and_stops_own_services(tmp_path):
    port, worker_port = free_port(), free_port()
    while worker_port == port:
        worker_port = free_port()
    directory = tmp_path / "runtime"
    env = {key: value for key, value in os.environ.items() if not key.startswith("STARTNUMMER_")}
    env.update(
        STARTNUMMER_DATABASE_URL="sqlite:///" + str(tmp_path / "launcher.db"),
        STARTNUMMER_BLOB_ROOT=str(tmp_path / "photos"),
        STARTNUMMER_USERNAME="test-launcher",
        STARTNUMMER_PASSWORD="launcher-test-only",
        STARTNUMMER_SESSION_SECRET="s" * 32,
        STARTNUMMER_WORKER_SECRET="w" * 32,
        STARTNUMMER_CHEVERETO_DSN="must-not-reach-the-worker",
        STARTNUMMER_WORKER_URL=f"http://127.0.0.1:{worker_port}",
    )
    migrate(create_engine(env["STARTNUMMER_DATABASE_URL"]))
    settings = Settings(
        database_url=env["STARTNUMMER_DATABASE_URL"],
        blob_root=tmp_path / "photos",
        password="launcher-test-only",
        session_secret="s" * 32,
        worker_secret="w" * 32,
        owner_id=uuid4(),
        worker_url=env["STARTNUMMER_WORKER_URL"],
    )
    with (tmp_path / "launcher.log").open("w") as log:
        child = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "tests.launcher_fixture",
                "--run-dir",
                str(directory),
                "start",
                "--port",
                str(port),
                "--worker-port",
                str(worker_port),
            ],
            env=env,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        try:
            wait_for(lambda: read_state(directory))
            wait_for(lambda: status(directory, settings)["api"] == "ready")
            wait_for(lambda: status(directory, settings)["worker"] == "idle")
            before = read_state(directory)
            os.kill(before["children"]["worker"]["pid"], signal.SIGKILL)
            restarted = wait_for(
                lambda: (state := read_state(directory)) and state["children"]["worker"]["restarts"] == 1 and state
            )
            assert restarted["children"]["api"]["pid"] == before["children"]["api"]["pid"]
            assert restarted["children"]["worker"]["pid"] != before["children"]["worker"]["pid"]
            wait_for(lambda: status(directory, settings)["worker"] == "idle")
            stop(directory)
            child.wait(timeout=10)
            assert child.returncode == 0
            assert read_state(directory) is None
            for item in restarted["children"].values():
                assert process_identity(item["pid"]) != item["identity"]
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=10)


def test_occupied_port_is_reported_without_starting_or_stopping_external_service(tmp_path):
    with socket.socket() as existing:
        existing.bind(("127.0.0.1", 0))
        port = existing.getsockname()[1]
        args = parser().parse_args(
            ["--run-dir", str(tmp_path / "run"), "start", "--port", str(port), "--worker-port", str(free_port())]
        )
        with pytest.raises(WorkflowError, match=f"Port {port} is already in use"):
            supervise(args, None)
        assert existing.getsockname()[1] == port
        assert not (tmp_path / "run/supervisor.json").exists()


def test_stale_state_cannot_signal_an_unrelated_process(tmp_path):
    (tmp_path / "supervisor.json").write_text(json.dumps({"pid": os.getpid(), "identity": "wrong-start-time"}))
    assert read_state(tmp_path) is None
    with pytest.raises(WorkflowError, match="external services were left alone"):
        stop(tmp_path)
