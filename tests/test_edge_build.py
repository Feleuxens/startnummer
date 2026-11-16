"""Skipped commits do not block edge tags; newer main builds do."""

import json
import subprocess

import pytest

from scripts.check_edge_build import can_update_edge

REPOSITORY = "Feleuxens/startnummer"


class Runs:
    def __init__(self, *, push=(), manual=()):
        self.responses = {"push": list(push), "workflow_dispatch": list(manual)}
        self.requests = []

    def __call__(self, arguments, *, text):
        assert text is True
        for event, builds in self.responses.items():
            endpoint = f"repos/{REPOSITORY}/actions/workflows/images.yml/runs?branch=main&event={event}&per_page=1"
            if arguments == ["gh", "api", endpoint]:
                self.requests.append(event)
                return json.dumps({"workflow_runs": builds})
        raise AssertionError(f"Unexpected request: {arguments}")


def test_skipped_commits_do_not_prevent_the_latest_build_from_updating_edge():
    runs = Runs(push=[{"id": 123, "run_number": 5, "head_sha": "built-commit"}])
    assert can_update_edge(REPOSITORY, "123", run=runs)
    # No branch-head lookup: later commits that skipped CI do not affect this decision.
    assert runs.requests == ["push", "workflow_dispatch"]


@pytest.mark.parametrize("event", ["push", "manual"])
@pytest.mark.parametrize("status", ["queued", "in_progress", "completed"])
def test_a_newer_main_build_blocks_an_older_run_even_when_it_is_retried(event, status):
    runs = Runs(**{event: [{"id": 456, "run_number": 6, "status": status}]})
    assert not can_update_edge(REPOSITORY, "123", run=runs)


@pytest.mark.parametrize("latest", ["push", "manual"])
def test_push_and_manual_runs_share_one_order(latest):
    old = {"id": 123, "run_number": 5}
    new = {"id": 456, "run_number": 6}
    runs = Runs(push=[new if latest == "push" else old], manual=[new if latest == "manual" else old])
    assert can_update_edge(REPOSITORY, "456", run=runs)


def test_a_manual_build_can_publish_without_an_earlier_push_run():
    assert can_update_edge(REPOSITORY, "123", run=Runs(manual=[{"id": 123, "run_number": 1}]))


def test_missing_runs_fail_instead_of_silently_skipping_edge():
    with pytest.raises(ValueError, match="No main image build"):
        can_update_edge(REPOSITORY, "123", run=Runs())


def test_permission_or_network_errors_fail_instead_of_silently_skipping_edge():
    def denied(arguments, **kwargs):
        raise subprocess.CalledProcessError(1, arguments)

    with pytest.raises(subprocess.CalledProcessError):
        can_update_edge(REPOSITORY, "123", run=denied)
