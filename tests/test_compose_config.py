"""Resolve deployment configurations without starting containers or using a daemon."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="Docker Compose CLI unavailable")


@pytest.fixture(scope="module", autouse=True)
def compose_available():
    if subprocess.run(["docker", "compose", "version"], capture_output=True).returncode:
        pytest.skip("Docker Compose CLI unavailable")


@pytest.fixture
def resolve(tmp_path):
    configuration = tmp_path / "docker.env"
    configuration.write_text(
        "POSTGRES_PASSWORD=" + "a" * 32 + "\n"
        "STARTNUMMER_PASSWORD=synthetic-login\n"
        "STARTNUMMER_SESSION_SECRET=" + "s" * 32 + "\n"
        "STARTNUMMER_WORKER_SECRET=" + "w" * 32 + "\n"
        "STARTNUMMER_IMAGE_TAG=0.1.0\n"
    )
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("STARTNUMMER_", "COMPOSE_")) and key != "POSTGRES_PASSWORD"
    }
    environment["STARTNUMMER_ENV_FILE"] = str(configuration)

    def config(*files, variant="cpu"):
        command = ["docker", "compose", "--env-file", str(configuration), "--profile", "operations"]
        for file in files:
            command.extend(["-f", str(file)])
        result = subprocess.run(
            [*command, "config", "--format", "json"],
            cwd=ROOT,
            env={**environment, "STARTNUMMER_WORKER_VARIANT": variant},
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)

    return config


@pytest.mark.parametrize("variant", ["cpu", "intel", "nvidia"])
def test_default_deployment_selects_images_without_building_or_requesting_gpus(resolve, variant):
    document = resolve(variant=variant)
    services = document["services"]
    assert set(services) == {"api", "worker", "postgres", "migrate", "ops"}
    assert all("build" not in service for service in services.values())
    assert services["worker"]["image"] == f"ghcr.io/feleuxens/startnummer-worker:{variant}-0.1.0"
    assert services["api"]["image"] == services["migrate"]["image"] == services["ops"]["image"]
    assert services["api"]["image"] == "ghcr.io/feleuxens/startnummer-web:0.1.0"
    assert not services["worker"].get("deploy")
    assert not services["worker"].get("ports")
    assert not services["postgres"].get("ports")
    assert document["networks"]["database"]["internal"]
    assert services["worker"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert services["api"]["depends_on"]["worker"]["condition"] == "service_healthy"


@pytest.mark.parametrize("variant", ["cpu", "intel", "nvidia"])
def test_optional_build_uses_the_selected_device_target(resolve, variant):
    services = resolve(ROOT / "compose.yaml", ROOT / "compose.build.yaml", variant=variant)["services"]
    assert services["worker"]["build"]["target"] == f"worker-{variant}"
    for name in ("api", "migrate", "ops"):
        assert services[name]["build"]["target"] == "api"
        assert services[name]["build"]["context"] == str(ROOT)


def test_uncommenting_gpu_block_reserves_one_nvidia_device(resolve, tmp_path):
    text = (ROOT / "compose.yaml").read_text()
    block = re.search(r"(?m)^    # deploy:\n(?:    # {2,}[^\n]+\n)+", text)
    assert block is not None
    enabled = tmp_path / "compose.nvidia.yaml"
    enabled.write_text(text.replace(block[0], block[0].replace("    # ", "    ")))
    worker = resolve(enabled, variant="nvidia")["services"]["worker"]
    assert worker["image"] == "ghcr.io/feleuxens/startnummer-worker:nvidia-0.1.0"
    assert worker["deploy"]["resources"]["reservations"]["devices"] == [
        {"driver": "nvidia", "count": 1, "capabilities": ["gpu"]}
    ]


def test_user_override_applies_to_app_services_without_changing_postgres(resolve, tmp_path):
    text = (ROOT / "compose.yaml").read_text()
    override = tmp_path / "compose.user.yaml"
    override.write_text(text.replace('  # user: "1000:1000"', '  user: "2000:2000"'))
    services = resolve(override)["services"]
    for name in ("api", "worker", "migrate", "ops"):
        assert services[name]["user"] == "2000:2000"
    assert "user" not in services["postgres"]
