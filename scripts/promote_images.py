"""Promote a successful main build to release tags without rebuilding its images."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from scripts.container_tags import environment_plan

VARIANTS = ("web", "cpu", "intel", "nvidia")
INDEX = "application/vnd.oci.image.index.v1+json"
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


class PromotionError(Exception):
    pass


def execute(arguments):
    return subprocess.check_output(arguments, text=True, stderr=subprocess.PIPE)


def inspect_image(reference, run, *, optional=False):
    try:
        manifest = json.loads(
            run(["docker", "buildx", "imagetools", "inspect", "--format", "{{json .Manifest}}", reference])
        )
    except subprocess.CalledProcessError as exc:
        if optional and re.search(r"manifest unknown|not found|\b404\b", exc.stderr or "", re.I):
            return None
        raise PromotionError(f"Cannot read {reference}; check registry access and the main image build") from exc
    if not isinstance(manifest.get("digest"), str) or not DIGEST.fullmatch(manifest["digest"]):
        raise PromotionError(f"Registry returned no valid digest for {reference}")
    return manifest


def sources(plan, repository, run):
    result, attempts, run_ids = {}, [], set()
    for variant in VARIANTS:
        image = f"{plan['namespace']}/startnummer-{'web' if variant == 'web' else 'worker'}"
        prefix = "" if variant == "web" else variant + "-"
        reference = f"{image}:{prefix}sha-{plan['revision']}"
        manifest = inspect_image(reference, run)
        annotations = manifest.get("annotations", {})
        if (
            manifest.get("mediaType") != INDEX
            or annotations.get("org.opencontainers.image.source") != f"https://github.com/{repository}"
            or annotations.get("org.opencontainers.image.revision") != plan["revision"]
        ):
            raise PromotionError(f"{reference} has incompatible build metadata; run the updated main image workflow")
        run_id = annotations.get("io.startnummer.build.run-id", "")
        attempt = annotations.get("io.startnummer.build.run-attempt", "")
        if (
            not isinstance(run_id, str)
            or not re.fullmatch(r"[1-9][0-9]*", run_id)
            or not isinstance(attempt, str)
            or not re.fullmatch(r"[1-9][0-9]*", attempt)
        ):
            raise PromotionError(f"{reference} has no build-run record; run the updated main image workflow")
        run_ids.add(run_id)
        attempts.append(int(attempt))
        result[variant] = (image, prefix, manifest["digest"])
    if len(run_ids) != 1:
        raise PromotionError(
            "The commit images come from different workflow runs; complete one main build for all variants"
        )
    run_id = run_ids.pop()
    build = json.loads(run(["gh", "api", f"repos/{repository}/actions/runs/{run_id}"]))
    if (
        build.get("head_sha") != plan["revision"]
        or build.get("head_branch") != "main"
        or build.get("event") not in {"push", "workflow_dispatch"}
        or build.get("path", "").partition("@")[0] != ".github/workflows/images.yml"
        or build.get("status") != "completed"
        or build.get("conclusion") != "success"
        or build.get("run_attempt", 0) < max(attempts)
    ):
        raise PromotionError(f"Image workflow run {run_id} is not a successful main build of the release commit")
    return result


def tag(image, digest, destination, run):
    run(["docker", "buildx", "imagetools", "create", "--prefer-index=false", "--tag", destination, f"{image}@{digest}"])
    if inspect_image(destination, run)["digest"] != digest:
        raise PromotionError(f"Digest verification failed for {destination}")
    return f"Published {destination} at {digest}"


def promote(plan, repository, release_tag, *, run=execute):
    if plan["operation"] != "promote":
        raise PromotionError("Image promotion requires a published release")
    if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", repository):
        raise PromotionError("Invalid GitHub repository")
    if plan["namespace"] != "ghcr.io/" + repository.split("/")[0].lower():
        raise PromotionError("Image namespace does not match the repository")
    if release_tag.removeprefix("v") != plan["suffix"]:
        raise PromotionError("Release tag does not match the planned image version")
    resolved = sources(plan, repository, run)
    # Preflight the entire set before writing any release tags.
    for image, prefix, digest in resolved.values():
        destination = f"{image}:{prefix}{plan['suffix']}"
        existing = inspect_image(destination, run, optional=True)
        if existing is not None and existing["digest"] != digest:
            raise PromotionError(
                f"{destination} already identifies another image; release versions cannot be overwritten"
            )
    messages = []
    for image, prefix, digest in resolved.values():
        messages.append(tag(image, digest, f"{image}:{prefix}{plan['suffix']}", run))
    if plan["alias"] == "latest":
        try:
            latest = json.loads(run(["gh", "api", f"repos/{repository}/releases/latest"]))
        except subprocess.CalledProcessError as exc:
            if not re.search(r"\b404\b", exc.stderr or ""):
                raise
            latest = {}
        if latest.get("tag_name") == release_tag:
            for image, prefix, digest in resolved.values():
                messages.append(tag(image, digest, f"{image}:{prefix}latest", run))
        else:
            messages.append("Version images published; this is not GitHub's latest release.")
    return messages


def main():
    try:
        messages = promote(environment_plan(), os.environ["GITHUB_REPOSITORY"], os.environ["RELEASE_TAG"])
        report = "\n".join(messages) + "\n"
        print(report, end="")
        if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
            with Path(summary).open("a") as output:
                output.write(report)
    except (PromotionError, subprocess.CalledProcessError, ValueError, KeyError) as exc:
        print(f"Release promotion failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
