"""Real launcher fixture with an inference-free private worker service."""

import os
import signal
import sys
import threading

from startnummer.adapters.face.sessions import FaceSessions
from startnummer.app import manage
from startnummer.app.manage import child_commands, parser, supervise
from startnummer.app.settings import Settings
from startnummer.app.worker import session_server


def main():
    if sys.argv[1:] == ["worker"]:
        assert "STARTNUMMER_CHEVERETO_DSN" not in os.environ
        assert "STARTNUMMER_INTEGRATION_KEY" not in os.environ
        assert "STARTNUMMER_PASSWORD" not in os.environ
        assert "STARTNUMMER_SESSION_SECRET" not in os.environ
        if expected := os.environ.get("STARTNUMMER_EXPECT_BACKEND"):
            assert os.environ.get("STARTNUMMER_INFERENCE_BACKEND") == expected
        stopped = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stopped.set())
        server = session_server(
            FaceSessions(), os.environ["STARTNUMMER_WORKER_SECRET"], int(os.environ["STARTNUMMER_WORKER_PORT"])
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        stopped.wait()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    else:
        args = parser().parse_args()
        # Keep launcher prerequisites independent of a local Astro build.
        os.environ["PYTHONPATH"] = str(manage.ROOT)
        manage.ROOT = args.run_dir.resolve() / "application"
        frontend = manage.ROOT / "startnummer-web" / "dist"
        frontend.mkdir(parents=True)
        (frontend / "index.html").write_text("<!doctype html><title>Launcher fixture</title>")
        commands = child_commands(args.port, args.cache_mb, args.no_faces)
        commands["worker"] = [sys.executable, "-m", "tests.launcher_fixture", "worker"]
        supervise(args, Settings.from_env(), commands=commands)


if __name__ == "__main__":
    main()
