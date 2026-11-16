"""Release promotion validates a complete successful build before changing tags."""

import copy
import json
import subprocess

import pytest

from scripts.container_tags import image_plan
from scripts.promote_images import INDEX, VARIANTS, PromotionError, promote

SHA = "a" * 40
REPOSITORY = "Feleuxens/startnummer"


def plan(version="0.1.0", prerelease=False):
    event = {"release": {"tag_name": "v" + version, "prerelease": prerelease, "draft": False}}
    return image_plan("release", event, "refs/tags/v" + version, SHA, "Feleuxens", version)


class Registry:
    def __init__(self):
        self.commands = []
        self.references = {}
        self.digests = {}
        self.failures = {}
        self.build = {
            "head_sha": SHA,
            "head_branch": "main",
            "event": "push",
            "path": ".github/workflows/images.yml",
            "status": "completed",
            "conclusion": "success",
            "run_attempt": 1,
        }
        self.latest = "v0.1.0"
        for index, variant in enumerate(VARIANTS, 1):
            image = "ghcr.io/feleuxens/startnummer-" + ("web" if variant == "web" else "worker")
            prefix = "" if variant == "web" else variant + "-"
            manifest = {
                "mediaType": INDEX,
                "digest": "sha256:" + str(index) * 64,
                "annotations": {
                    "org.opencontainers.image.source": "https://github.com/" + REPOSITORY,
                    "org.opencontainers.image.revision": SHA,
                    "io.startnummer.build.run-id": "123",
                    "io.startnummer.build.run-attempt": "1",
                },
                "manifests": [{"digest": "image-manifest"}, {"digest": "attestation-manifest"}],
            }
            self.references[f"{image}:{prefix}sha-{SHA}"] = manifest
            self.digests[f"{image}@{manifest['digest']}"] = manifest

    def source(self, variant):
        return next(
            value
            for key, value in self.references.items()
            if (f":{variant}-sha-" if variant != "web" else ":sha-") in key
        )

    def writes(self):
        return [cmd for cmd in self.commands if cmd[:4] == ["docker", "buildx", "imagetools", "create"]]

    def __call__(self, arguments):
        self.commands.append(arguments)
        if arguments[:2] == ["gh", "api"]:
            return json.dumps(self.build if arguments[2].endswith("/actions/runs/123") else {"tag_name": self.latest})
        if arguments[3] == "inspect":
            reference = arguments[-1]
            if reference in self.failures:
                raise subprocess.CalledProcessError(1, arguments, stderr=self.failures[reference])
            if reference not in self.references:
                raise subprocess.CalledProcessError(1, arguments, stderr="manifest unknown: not found")
            return json.dumps(self.references[reference])
        assert arguments[3:6] == ["create", "--prefer-index=false", "--tag"]
        self.references[arguments[6]] = copy.deepcopy(self.digests[arguments[7]])
        return ""


def test_release_tags_reuse_exact_source_digests_and_attestations():
    registry = Registry()
    messages = promote(plan(), REPOSITORY, "v0.1.0", run=registry)
    assert len(registry.writes()) == 8 and len(messages) == 8
    for command in registry.writes():
        assert "@sha256:" in command[-1] and ":sha-" not in command[-1]
        assert registry.references[command[6]] == registry.digests[command[7]]
    assert not any(command[:2] == ["docker", "build"] for command in registry.commands)


@pytest.mark.parametrize("variant", VARIANTS)
def test_missing_variant_fails_before_publishing_any_version(variant):
    registry = Registry()
    source = registry.source(variant)
    registry.references = {key: value for key, value in registry.references.items() if value is not source}
    with pytest.raises(PromotionError, match="Cannot read"):
        promote(plan(), REPOSITORY, "v0.1.0", run=registry)
    assert not registry.writes()


@pytest.mark.parametrize(
    "change",
    [
        {"conclusion": "failure"},
        {"status": "in_progress"},
        {"head_sha": "b" * 40},
        {"head_branch": "topic"},
        {"event": "pull_request"},
        {"path": ".github/workflows/other.yml"},
        {"run_attempt": 0},
    ],
)
def test_unsuccessful_or_unrelated_build_fails_before_writing(change):
    registry = Registry()
    registry.build.update(change)
    with pytest.raises(PromotionError, match="not a successful main build"):
        promote(plan(), REPOSITORY, "v0.1.0", run=registry)
    assert not registry.writes()


@pytest.mark.parametrize(
    "key,value",
    [
        ("org.opencontainers.image.revision", "b" * 40),
        ("org.opencontainers.image.source", "https://github.com/another/repository"),
        ("io.startnummer.build.run-id", ""),
        ("io.startnummer.build.run-attempt", "0"),
    ],
)
def test_missing_or_mismatched_source_metadata_is_rejected(key, value):
    registry = Registry()
    registry.source("nvidia")["annotations"][key] = value
    with pytest.raises(PromotionError):
        promote(plan(), REPOSITORY, "v0.1.0", run=registry)
    assert not registry.writes()


def test_mixed_runs_cannot_be_promoted_as_a_complete_set():
    registry = Registry()
    registry.source("nvidia")["annotations"]["io.startnummer.build.run-id"] = "456"
    with pytest.raises(PromotionError, match="different workflow runs"):
        promote(plan(), REPOSITORY, "v0.1.0", run=registry)
    assert not registry.writes()


def test_successful_retry_can_reuse_variants_from_earlier_attempts():
    registry = Registry()
    registry.build.update(run_attempt=2, event="workflow_dispatch")
    registry.source("nvidia")["annotations"]["io.startnummer.build.run-attempt"] = "2"
    promote(plan(), REPOSITORY, "v0.1.0", run=registry)
    assert len(registry.writes()) == 8


def test_prerelease_never_touches_stable_aliases():
    registry = Registry()
    promote(plan("0.1.0-rc.1", True), REPOSITORY, "v0.1.0-rc.1", run=registry)
    assert len(registry.writes()) == 4
    assert all(command[6].endswith("0.1.0-rc.1") for command in registry.writes())
    assert not any(command[-1].endswith("/releases/latest") for command in registry.commands)


def test_older_release_gets_version_tags_without_moving_latest():
    registry = Registry()
    registry.latest = "v0.2.0"
    messages = promote(plan(), REPOSITORY, "v0.1.0", run=registry)
    assert len(registry.writes()) == 4
    assert "not GitHub's latest release" in messages[-1]


def test_existing_version_cannot_be_replaced_by_a_later_build_of_the_same_commit():
    registry = Registry()
    registry.references["ghcr.io/feleuxens/startnummer-worker:nvidia-0.1.0"] = {"digest": "sha256:" + "f" * 64}
    with pytest.raises(PromotionError, match="cannot be overwritten"):
        promote(plan(), REPOSITORY, "v0.1.0", run=registry)
    assert not registry.writes()


def test_existing_version_with_same_digest_can_be_promoted_again():
    registry = Registry()
    promote(plan(), REPOSITORY, "v0.1.0", run=registry)
    promote(plan(), REPOSITORY, "v0.1.0", run=registry)
    assert len(registry.writes()) == 16


def test_permission_errors_are_not_treated_as_missing_version_tags():
    registry = Registry()
    registry.failures["ghcr.io/feleuxens/startnummer-worker:intel-0.1.0"] = "unauthorized"
    with pytest.raises(PromotionError, match="Cannot read"):
        promote(plan(), REPOSITORY, "v0.1.0", run=registry)
    assert not registry.writes()


def test_source_tag_changes_do_not_change_already_resolved_promotion_digests():
    registry = Registry()

    def changing_tags(arguments):
        result = registry(arguments)
        if arguments[:2] == ["gh", "api"]:
            registry.references = {
                key: ({**value, "digest": "sha256:" + "f" * 64} if "sha-" + SHA in key else value)
                for key, value in registry.references.items()
            }
        return result

    promote(plan(), REPOSITORY, "v0.1.0", run=changing_tags)
    assert all(command[-1].split("@", 1)[1] != "sha256:" + "f" * 64 for command in registry.writes())


def test_partial_version_failure_does_not_update_latest_and_can_be_retried():
    registry = Registry()

    def interrupted(arguments):
        if arguments[3:4] == ["create"] and arguments[6].endswith("intel-0.1.0"):
            raise subprocess.CalledProcessError(1, arguments, stderr="synthetic interruption")
        return registry(arguments)

    with pytest.raises(subprocess.CalledProcessError):
        promote(plan(), REPOSITORY, "v0.1.0", run=interrupted)
    assert not any(command[6].endswith("latest") for command in registry.writes())
    promote(plan(), REPOSITORY, "v0.1.0", run=registry)
    assert "ghcr.io/feleuxens/startnummer-worker:nvidia-latest" in registry.references
