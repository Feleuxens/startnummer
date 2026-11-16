"""Keep older main builds from replacing a newer build's edge tags."""

import json
import os
import subprocess
import sys


def can_update_edge(repository, run_id, *, run=subprocess.check_output):
    builds = []
    for event in ("push", "workflow_dispatch"):
        # Skipped commits have no workflow run. Releases and pull requests must
        # not supersede main's development images.
        endpoint = f"repos/{repository}/actions/workflows/images.yml/runs?branch=main&event={event}&per_page=1"
        response = json.loads(run(["gh", "api", endpoint], text=True))
        builds.extend(response["workflow_runs"])
    if not builds:
        raise ValueError("No main image build found; edge tags were not changed")
    newest = max(builds, key=lambda build: build["run_number"])
    return str(newest["id"]) == str(run_id)


def main():
    try:
        allowed = can_update_edge(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_RUN_ID"])
        print("true" if allowed else "false")
    except (subprocess.CalledProcessError, ValueError, KeyError) as exc:
        print(f"Could not check the latest main image build: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
