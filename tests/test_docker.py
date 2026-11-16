"""Opt-in deployment test using an isolated Compose project and synthetic inference."""

import base64
import json
import os
import subprocess
import time
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest

httpx = pytest.importorskip("httpx")
Image = pytest.importorskip("PIL.Image")

pytestmark = pytest.mark.skipif(
    os.environ.get("STARTNUMMER_TEST_DOCKER") != "1", reason="Opt-in Docker deployment test"
)
ROOT = Path(__file__).resolve().parents[1]


def test_compose_import_review_restart_and_restore(tmp_path):
    project = "startnummer-test-" + uuid4().hex[:10]
    recovery_volume = project + "-recovery-photos"
    configuration = tmp_path / "docker.env"
    configuration.write_text(
        "POSTGRES_PASSWORD=" + "a" * 32 + "\n"
        "STARTNUMMER_SESSION_SECRET=" + "s" * 32 + "\n"
        "STARTNUMMER_WORKER_SECRET=" + "w" * 32 + "\n"
        "STARTNUMMER_INTEGRATION_KEY=" + base64.urlsafe_b64encode(b"k" * 32).decode() + "\n"
        "STARTNUMMER_COOKIE_SECURE=0\n"
        "STARTNUMMER_PORT=0\n"
        "STARTNUMMER_IMAGE_TAG=docker-test\n"
        "STARTNUMMER_WORKER_VARIANT=cpu\n"
    )
    configuration.chmod(0o600)
    override = tmp_path / "compose.json"
    override.write_text(
        json.dumps(
            {
                "services": {
                    "worker": {
                        "command": ["python", "-m", "docker_fixture"],
                        "volumes": [f"{ROOT / 'tests/docker_fixture.py'}:/app/docker_fixture.py:ro"],
                    }
                }
            }
        )
    )
    environment = {k: v for k, v in os.environ.items() if not k.startswith("STARTNUMMER_") and k != "POSTGRES_PASSWORD"}
    environment["STARTNUMMER_ENV_FILE"] = str(configuration)
    command = [
        "docker",
        "compose",
        "--env-file",
        str(configuration),
        "-f",
        str(ROOT / "compose.yaml"),
        "-f",
        str(ROOT / "compose.build.yaml"),
        "-f",
        str(override),
        "--project-name",
        project,
    ]

    def compose(*args, timeout=120):
        result = subprocess.run(
            [*command, *args], cwd=ROOT, env=environment, capture_output=True, text=True, timeout=timeout
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout.strip()

    def await_job(client, batch_id):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            document = client.get(f"/api/batches/{batch_id}").json()
            if document["jobs"] and document["jobs"][0]["state"] == "done":
                return document["batch"]
            time.sleep(0.2)
        pytest.fail("Synthetic container analysis did not finish")

    try:
        resolved = json.loads(compose("config", "--format", "json"))
        worker_environment = resolved["services"]["worker"]["environment"]
        assert not {"STARTNUMMER_CHEVERETO_DSN", "STARTNUMMER_INTEGRATION_KEY", "STARTNUMMER_PASSWORD"}.intersection(
            worker_environment
        )
        assert not resolved["services"]["worker"].get("ports")
        assert not resolved["services"]["postgres"].get("ports")
        compose("build", timeout=1800)
        compose("up", "-d", "--wait", "--wait-timeout", "90")
        for name in ("api", "worker"):
            compose(
                "exec",
                "-T",
                name,
                "python",
                "-c",
                "import os; assert (os.getuid(), os.getgid()) == (1000, 1000)",
            )
        compose("exec", "-T", "worker", "python", "-c", "import torch; assert torch.version.cuda is None")
        compose(
            "exec",
            "-T",
            "api",
            "python",
            "-c",
            "import importlib.util; assert importlib.util.find_spec('torch') is None",
        )
        address = compose("port", "api", "8000")
        with httpx.Client(
            base_url="http://" + address, headers={"X-Requested-With": "Startnummer"}, timeout=10
        ) as client:
            assert client.get("/").status_code == 200
            assert client.get("/api/batches").status_code == 401
            assert client.get("/api/auth/status").json()["setup_required"]
            code = compose("run", "--rm", "ops", "setup-code").splitlines()[-1]
            login = client.post(
                "/api/auth/setup",
                json={"username": "synthetic-photographer", "password": "synthetic-login-password", "code": code},
            )
            assert login.is_success, login.text
            assert client.get("/api/admin").json()["worker"]["reachable"]
            assert client.get("/api/admin/integrations/chevereto").json()["editable"]
            image = BytesIO()
            Image.new("RGB", (100, 200), "gray").save(image, "JPEG")
            roster = (
                '<div class="entryline"><div></div><div>12</div><div></div><div>Example Alex</div>'
                "<div>Example Club</div><div></div><div></div><div>2000</div><div><a>100</a></div></div>"
            )

            def import_album(name):
                response = client.post(
                    "/api/batches",
                    data={"name": name, "meet_name": "Synthetic Docker meet"},
                    files=[
                        ("photos", ("example.jpg", image.getvalue(), "image/jpeg")),
                        ("roster_file", ("roster.html", roster.encode(), "text/html")),
                    ],
                )
                assert response.is_success, response.text
                return response.json()["album"]["id"]

            first = import_album("First synthetic album")
            owner = client.get(f"/api/batches/{first}").json()["batch"]["album"]["owner_id"]
            assert client.post(f"/api/batches/{first}/analysis").is_success
            photo = await_job(client, first)["photos"][0]
            assert photo["caption"]
            assert client.get(f"/api/batches/{first}/faces").json()["available"]
            edited = client.patch(
                f"/api/batches/{first}/photos/{photo['id']}",
                json={"revision": photo["revision"], "caption": "Reviewed Docker caption", "conflicts_resolved": True},
            )
            assert edited.is_success
            assert client.get(f"/api/batches/{first}/faces").json()["available"]
            assert client.get(f"/api/photos/{photo['id']}").status_code == 200
            compose("restart", "worker")
            compose("up", "-d", "--wait", "--wait-timeout", "60")
            assert not client.get(f"/api/batches/{first}/faces").json()["available"]
            assert (
                client.get(f"/api/batches/{first}").json()["batch"]["photos"][0]["caption"] == "Reviewed Docker caption"
            )
            second = import_album("Second synthetic album")
            assert client.post(f"/api/batches/{second}/analysis").is_success
            await_job(client, second)
            assert client.get(f"/api/batches/{second}/faces").json()["available"]
            assert client.post(f"/api/batches/{second}/finish").is_success
            assert not client.get(f"/api/batches/{second}/faces").json()["available"]
            assert client.get("/api/admin").json()["worker"]["active_sessions"] == 0

        compose("run", "--rm", "ops", "backup", "/backups/synthetic.snbak")
        compose("run", "--rm", "ops", "verify-backup", "/backups/synthetic.snbak")
        compose("exec", "-T", "postgres", "createdb", "-U", "startnummer", "recovered")
        recovered_url = "postgresql+psycopg://startnummer:" + "a" * 32 + "@postgres:5432/recovered"
        compose(
            "run",
            "--rm",
            "--volume",
            recovery_volume + ":/data/photos",
            "ops",
            "restore",
            "/backups/synthetic.snbak",
            "--database-url",
            recovered_url,
            "--blob-root",
            "/data/photos/originals",
        )
        check_restore = (
            "from sqlalchemy import create_engine; from startnummer.app.settings import Settings; "
            "from startnummer.adapters.db.store import Store; "
            "from startnummer.adapters.blob.filesystem import FilesystemBlobStore; "
            "from startnummer.app.services import run; "
            "s=Settings.from_env(); store=Store(create_engine(s.database_url)); "
            f"s=__import__('dataclasses').replace(s,owner_id=__import__('uuid').UUID('{owner}')); "
            "assert len(store.list_batches(s.owner_id))==2; "
            f"photo=store.get(s.owner_id, __import__('uuid').UUID('{first}')).photos[0]; "
            "assert photo.caption=='Reviewed Docker caption'; "
            "assert run(FilesystemBlobStore(s.blob_root).read(s.owner_id, photo.blob_key))"
        )
        compose(
            "run",
            "--rm",
            "--volume",
            recovery_volume + ":/data/photos",
            "-e",
            "STARTNUMMER_DATABASE_URL=" + recovered_url,
            "--entrypoint",
            "python",
            "ops",
            "-c",
            check_restore,
        )
    finally:
        compose("down", "--volumes", "--remove-orphans")
        subprocess.run(
            ["docker", "volume", "rm", recovery_volume], capture_output=True, text=True, check=False, timeout=30
        )
