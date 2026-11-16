"""Choose GHCR tags for release and development builds."""

import json
import os
import re
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(
    r"v?((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?)", re.ASCII
)


def image_plan(event_name, event, ref, revision, owner, project_version):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Expected the full checked-out Git commit SHA")
    if not re.fullmatch(r"[A-Za-z0-9-]+", owner):
        raise ValueError("Invalid GitHub owner")
    suffix = f"sha-{revision}"
    alias = ""
    operation = "check"
    if event_name == "release":
        release = event["release"]
        match = VERSION.fullmatch(release["tag_name"])
        if not match or len(match[1]) > 100:
            raise ValueError("Release tags must look like v0.1.0 or v0.1.0-rc.1")
        suffix = match[1]
        if any(
            part.isdecimal() and len(part) > 1 and part.startswith("0") for part in suffix.partition("-")[2].split(".")
        ):
            raise ValueError("Numeric prerelease identifiers cannot have leading zeros")
        if suffix != project_version:
            raise ValueError("The release tag must match project.version in pyproject.toml")
        if "-" in suffix and not release["prerelease"]:
            raise ValueError("A prerelease version must be marked as a GitHub prerelease")
        if release["draft"]:
            raise ValueError("Draft releases cannot publish images")
        operation = "promote"
        alias = "" if release["prerelease"] else "latest"
    elif event_name in {"push", "workflow_dispatch"} and ref == "refs/heads/main":
        operation = "build"
        alias = "edge"
    return {
        "namespace": f"ghcr.io/{owner.lower()}",
        "suffix": suffix,
        "alias": alias,
        "operation": operation,
        "revision": revision,
    }


def environment_plan():
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    return image_plan(
        os.environ["GITHUB_EVENT_NAME"],
        event,
        os.environ["GITHUB_REF"],
        revision,
        os.environ["GITHUB_REPOSITORY_OWNER"],
        version,
    )


def main():
    for key, value in environment_plan().items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
