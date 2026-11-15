"""Private worker binding and authenticated container probes."""

import threading

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
pytest.importorskip("multipart")

from startnummer.adapters.face.sessions import FaceSessions
from startnummer.app.healthcheck import main
from startnummer.app.worker import session_server


def test_container_worker_probe_requires_authentication(monkeypatch):
    server = session_server(FaceSessions(), "s" * 32, 0, host="0.0.0.0")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert server.server_address[0] == "0.0.0.0"
        monkeypatch.setenv("STARTNUMMER_WORKER_PORT", str(server.server_port))
        for secret, expected in [("s" * 32, 0), ("incorrect", 1)]:
            monkeypatch.setenv("STARTNUMMER_WORKER_SECRET", secret)
            with pytest.raises(SystemExit) as result:
                main(["worker"])
            assert result.value.code == expected
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
