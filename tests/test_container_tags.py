"""Release tags cannot accidentally move production aliases to development builds."""

import pytest

from scripts.container_tags import image_plan

SHA = "a" * 40


def release(tag="v0.1.0", *, prerelease=False, draft=False, version="0.1.0"):
    event = {"release": {"tag_name": tag, "prerelease": prerelease, "draft": draft}}
    return image_plan("release", event, "refs/tags/" + tag, SHA, "Feleuxens", version)


@pytest.mark.parametrize("tag", ["v0.1.0", "0.1.0"])
def test_stable_release_uses_version_and_latest(tag):
    plan = release(tag)
    assert plan == {
        "namespace": "ghcr.io/feleuxens",
        "suffix": "0.1.0",
        "alias": "latest",
        "operation": "promote",
        "revision": SHA,
    }


def test_prerelease_never_updates_latest():
    plan = release("v0.2.0-rc.1", prerelease=True, version="0.2.0-rc.1")
    assert plan["suffix"] == "0.2.0-rc.1"
    assert plan["alias"] == ""
    assert plan["operation"] == "promote"


@pytest.mark.parametrize("event", ["push", "workflow_dispatch"])
def test_main_development_build_uses_commit_and_edge(event):
    plan = image_plan(event, {}, "refs/heads/main", SHA, "Feleuxens", "0.1.0")
    assert plan["suffix"] == "sha-" + SHA
    assert plan["alias"] == "edge"
    assert plan["operation"] == "build"


@pytest.mark.parametrize(
    ("event", "ref"),
    [("pull_request", "refs/pull/12/merge"), ("push", "refs/heads/topic"), ("workflow_dispatch", "refs/heads/topic")],
)
def test_untrusted_and_non_main_builds_do_not_publish(event, ref):
    plan = image_plan(event, {}, ref, SHA, "Feleuxens", "0.1.0")
    assert plan["operation"] == "check"
    assert plan["alias"] == ""


@pytest.mark.parametrize(
    "tag", ["latest", "v0.1", "v01.2.3", "v0.1.0+build.1", "v0.1.0\nlatest", "v0.1.0-01", "v1٣.2.3"]
)
def test_invalid_release_tag_is_rejected(tag):
    with pytest.raises(ValueError):
        release(tag)


def test_release_requires_matching_package_version():
    with pytest.raises(ValueError, match="must match"):
        release("v0.2.0")


def test_prerelease_version_requires_prerelease_flag():
    with pytest.raises(ValueError, match="marked"):
        release("v0.2.0-rc.1", version="0.2.0-rc.1")


def test_draft_release_is_rejected():
    with pytest.raises(ValueError, match="Draft"):
        release(draft=True)
