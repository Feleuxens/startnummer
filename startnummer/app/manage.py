"""Local process supervision, health status, migrations, and backup commands."""

import argparse
import fcntl
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path

import httpx
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy import create_engine

from startnummer.adapters.db.store import Store
from startnummer.app.backup import backup, inspect_backup, restore
from startnummer.app.operations import database_healthy, worker_health
from startnummer.app.settings import Settings
from startnummer.core.batch import WorkflowError, now

ROOT = Path(__file__).resolve().parents[2]


def migrate(engine):
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def process_identity(pid):
    try:
        stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        if stat[0] == "Z":
            return None
        return stat[19]  # Linux process start time, to reject reused PIDs.
    except (OSError, IndexError):
        return None


def read_state(directory):
    try:
        state = json.loads((directory / "supervisor.json").read_text())
        return state if process_identity(state["pid"]) == state["identity"] else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_state(directory, state):
    descriptor, name = tempfile.mkstemp(dir=directory)
    try:
        with os.fdopen(descriptor, "w") as output:
            json.dump(state, output)
        os.replace(name, directory / "supervisor.json")
    finally:
        Path(name).unlink(missing_ok=True)


def probe_api(url):
    try:
        response = httpx.get(url + "/api/health/ready", timeout=2, trust_env=False)
        return response.json() if response.status_code in (200, 503) else {}
    except (httpx.HTTPError, ValueError):
        return {}


def local_port(port):
    if not 1 <= port <= 65535:
        raise WorkflowError("Ports must be between 1 and 65535")
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            raise WorkflowError(
                f"Port {port} is already in use; stop that service yourself or choose another port"
            ) from exc


def status(directory, settings, port=8000):
    state = read_state(directory)
    api_url = state["api_url"] if state else f"http://127.0.0.1:{port}"
    worker_url = state["worker_url"] if state else settings.worker_url
    worker = worker_health(worker_url, settings.worker_secret)
    api_health = probe_api(api_url)
    return {
        "supervisor": ("stopping" if state.get("stopping") else "running") if state else "not managed",
        "api": "ready" if api_health.get("ready") else "not ready" if api_health else "unavailable",
        "database": api_health.get("database"),
        "storage": api_health.get("storage"),
        "worker": worker.state,
        "active_face_sessions": worker.active_sessions,
    }


def child_commands(port, cache_mb, no_faces):
    worker = [sys.executable, "-m", "startnummer.app.worker", "--cache-mb", str(cache_mb)]
    if no_faces:
        worker.append("--no-faces")
    return {
        "api": [
            sys.executable,
            "-m",
            "uvicorn",
            "startnummer.app.api:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        "worker": worker,
    }


def supervise(args, settings, *, commands=None):
    directory = args.run_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / "supervisor.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise WorkflowError("A launcher is already running in this runtime directory") from exc
        if args.port == args.worker_port:
            raise WorkflowError("API and worker ports must be different")
        for port in (args.port, args.worker_port):
            local_port(port)
        if not database_healthy(Store(create_engine(settings.database_url))):
            raise WorkflowError("Database unavailable or migrations missing; run `startnummer migrate` first")
        if not (ROOT / "startnummer-web/dist/index.html").is_file():
            raise WorkflowError("Frontend build missing; run `npm ci && npm run build` in startnummer-web")
        state = {
            "pid": os.getpid(),
            "identity": process_identity(os.getpid()),
            "started_at": now().isoformat(),
            "api_url": f"http://127.0.0.1:{args.port}",
            "worker_url": f"http://127.0.0.1:{args.worker_port}",
            "stopping": False,
        }
        environment = {
            **os.environ,
            "STARTNUMMER_WORKER_URL": state["worker_url"],
            "STARTNUMMER_WORKER_PORT": str(args.worker_port),
        }
        worker_environment = {key: value for key, value in environment.items() if key != "STARTNUMMER_CHEVERETO_DSN"}
        commands = commands or child_commands(args.port, args.cache_mb, args.no_faces)
        stopped = threading.Event()
        previous = {sig: signal.signal(sig, lambda *_: stopped.set()) for sig in (signal.SIGTERM, signal.SIGINT)}
        children, attempts, due = {}, {name: 0 for name in commands}, {}

        def record_children():
            state["children"] = {
                name: {"pid": child.pid, "identity": process_identity(child.pid), "restarts": attempts[name]}
                for name, child in children.items()
            }
            write_state(directory, state)

        try:
            for name, cmd in commands.items():
                children[name] = subprocess.Popen(
                    cmd, cwd=ROOT, env=worker_environment if name == "worker" else environment
                )
            record_children()
            print(f"Started API at {state['api_url']}; worker may take time to load its models.", flush=True)
            while not stopped.wait(0.5):
                for name, child in list(children.items()):
                    if child.poll() is None:
                        continue
                    if attempts[name] >= 3:
                        raise WorkflowError(
                            f"{name} exited repeatedly; stopping managed services. Check the launcher log"
                        )
                    if name not in due:
                        due[name] = time.monotonic() + 2 ** attempts[name]
                        print(f"{name} exited; retrying. Worker restarts discard temporary face sessions.", flush=True)
                    if time.monotonic() >= due[name]:
                        attempts[name] += 1
                        children[name] = subprocess.Popen(
                            commands[name], cwd=ROOT, env=worker_environment if name == "worker" else environment
                        )
                        del due[name]
                        record_children()
        finally:
            state["stopping"] = True
            write_state(directory, state)
            for child in children.values():
                if child.poll() is None:
                    child.terminate()
            for child in children.values():
                child.wait()
            (directory / "supervisor.json").unlink(missing_ok=True)
            for sig, handler in previous.items():
                signal.signal(sig, handler)


def start(args, settings):
    if not args.detach:
        return supervise(args, settings)
    args.run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if read_state(args.run_dir):
        raise WorkflowError("A launcher is already running")
    command_line = [
        sys.executable,
        "-m",
        "startnummer.app.manage",
        "--env-file",
        str(args.env_file.resolve()),
        "--run-dir",
        str(args.run_dir.resolve()),
        "start",
        "--port",
        str(args.port),
        "--worker-port",
        str(args.worker_port),
        "--cache-mb",
        str(args.cache_mb),
    ]
    if args.no_faces:
        command_line.append("--no-faces")
    descriptor = os.open(args.run_dir / "launcher.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(descriptor, "ab") as log:
        process = subprocess.Popen(command_line, cwd=ROOT, stdout=log, stderr=log, start_new_session=True)
    for _ in range(50):
        if process.poll() is not None:
            raise WorkflowError("Launcher failed; check its launcher.log. Existing services were not stopped")
        if read_state(args.run_dir):
            print("Launcher started. Use `startnummer status` to check readiness.")
            return
        time.sleep(0.1)
    raise WorkflowError("Launcher is still starting; check its log and status")


def stop(directory):
    state = read_state(directory)
    if state is None:
        raise WorkflowError("No matching managed launcher is running; external services were left alone")
    os.kill(state["pid"], signal.SIGTERM)
    print("Stop requested. The worker finishes its current job, then exits and clears temporary face sessions.")


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--env-file", type=Path, default=ROOT / ".env")
    result.add_argument("--run-dir", type=Path, default=ROOT / ".startnummer/run")
    sub = result.add_subparsers(dest="command", required=True)
    launch = sub.add_parser("start")
    launch.add_argument("--port", type=int, default=8000)
    launch.add_argument("--worker-port", type=int)
    launch.add_argument("--cache-mb", type=int, default=512)
    launch.add_argument("--no-faces", action="store_true")
    launch.add_argument("--detach", action="store_true")
    check = sub.add_parser("status")
    check.add_argument("--port", type=int, default=8000, help="API port for services started without the launcher")
    sub.add_parser("stop")
    sub.add_parser("migrate")
    create = sub.add_parser("backup")
    create.add_argument("destination", type=Path)
    verify = sub.add_parser("verify-backup")
    verify.add_argument("source", type=Path)
    recover = sub.add_parser("restore")
    recover.add_argument("source", type=Path)
    recover.add_argument("--database-url", required=True, help="Dedicated empty PostgreSQL or SQLite destination")
    recover.add_argument("--blob-root", type=Path, required=True, help="Empty photo storage destination")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    load_dotenv(args.env_file, override=False)
    try:
        if args.command == "verify-backup":
            print(json.dumps(inspect_backup(args.source), indent=2))
            return
        settings = Settings.from_env()
        if args.command == "start":
            if args.worker_port is None:
                args.worker_port = int(os.environ.get("STARTNUMMER_WORKER_PORT", "8766"))
            if args.cache_mb < 0:
                raise WorkflowError("Cache size must be nonnegative")
            start(args, settings)
        elif args.command == "stop":
            stop(args.run_dir)
        elif args.command == "status":
            report = status(args.run_dir, settings, args.port)
            print(json.dumps(report, indent=2))
            if report["api"] != "ready" or report["worker"] not in {"idle", "busy"}:
                raise SystemExit(1)
        elif args.command == "restore":
            settings = replace(settings, database_url=args.database_url, blob_root=args.blob_root)
            engine = create_engine(settings.database_url)
            if engine.dialect.name not in {"postgresql", "sqlite"}:
                raise WorkflowError("Restore supports only a dedicated PostgreSQL or SQLite database")
            print(json.dumps(restore(engine, settings, args.source, migrate=migrate), indent=2))
        elif args.command == "migrate":
            migrate(create_engine(settings.database_url))
            print("Migrations applied.")
        elif args.command == "backup":
            print(json.dumps(backup(Store(create_engine(settings.database_url)), settings, args.destination), indent=2))
    except WorkflowError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    except Exception as exc:
        print(
            f"Operation failed ({type(exc).__name__}); check configuration and service availability.", file=sys.stderr
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
