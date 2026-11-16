# Container releases

Startnummer publishes a combined web/API image and CPU, Intel, and NVIDIA workers
to GitHub Container Registry. Images target Linux x86-64. Apple inference runs
[natively on macOS](devices.md).

## Choose an image tag

Use a published version for deliberate production updates. Moving tags track new
builds; a digest identifies an exact image. The versions below are examples.

| Image                                  | Version example | Stable alias    | Main builds                          |
| -------------------------------------- | --------------- | --------------- | ------------------------------------ |
| `ghcr.io/feleuxens/startnummer-web`    | `0.1.0`         | `latest`        | `edge`, `sha-<commit>`               |
| `ghcr.io/feleuxens/startnummer-worker` | `cpu-0.1.0`     | `cpu-latest`    | `cpu-edge`, `cpu-sha-<commit>`       |
| `ghcr.io/feleuxens/startnummer-worker` | `intel-0.1.0`   | `intel-latest`  | `intel-edge`, `intel-sha-<commit>`   |
| `ghcr.io/feleuxens/startnummer-worker` | `nvidia-0.1.0`  | `nvidia-latest` | `nvidia-edge`, `nvidia-sha-<commit>` |

Set the common version and worker variant in `.env.docker`:

```dotenv
STARTNUMMER_IMAGE_TAG=0.1.0
STARTNUMMER_WORKER_VARIANT=intel
```

Compose adds the worker prefix, so leave it out of `STARTNUMMER_IMAGE_TAG`.
Use `edge` for main before a stable release is available. `<commit>` means the
full Git SHA. A prerelease such as `v0.2.0-rc.1` produces `0.2.0-rc.1` image suffixes
without moving stable aliases. A leading `v` is removed from image versions.

Follow the [Docker guide](docker.md) for installation and
[Operations](operations.md#update-startnummer) for updates. NVIDIA also needs the
commented [GPU reservation](docker.md#nvidia-gpu) enabled.

## Pull a private package

If a GHCR package is private, authenticate before pulling:

```sh
docker login ghcr.io -u Feleuxens
```

Use an account with package access and enter a classic personal access token with
`read:packages` at the password prompt. See GitHub's
[registry documentation](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
for access requirements. Package visibility is separate from repository visibility;
the publishing workflow does not change it.

## Publish a release

1. Set `project.version` in `pyproject.toml` and refresh `uv.lock`. Keep any frontend
   version change consistent with its package lockfile.
2. Commit the release source and wait for main's checks and images to succeed.
3. Create a GitHub release from that commit with a tag matching the version,
   such as `v0.1.0`. Mark versions with a prerelease suffix as prereleases.
4. Publish the release. Its workflow verifies and promotes the images from that
   commit; it does not rebuild them or repeat the checks already passed on main.
   Inspect the image digests in its summary. Set a stable release as GitHub's
   latest when it should move stable image aliases.

Draft releases and tag pushes alone do not publish release images. If you make a
release latest after its workflow finished, rerun that release workflow to update
the aliases. See `.github/workflows/images.yml` for the build and promotion jobs.

## Understand publication triggers

| Event              | Result                                                        |
| ------------------ | ------------------------------------------------------------- |
| Pull request       | Run checks; build web and CPU images without pushing          |
| Push to main       | Run checks; publish all variants with development tags        |
| Manual run on main | Run checks; publish all variants with development tags        |
| Published release  | Verify the successful main build; promote its existing images |

## How release promotion works

Main builds attach the source commit, repository, workflow run ID, and run attempt
to each image index. The release job resolves all four commit-specific tags and
checks that they belong to one successful main workflow run for the release commit.
Retries of failed jobs can reuse successful variants from an earlier attempt of
that same run.

Promotion copies the resolved image indexes by digest and verifies the destination
digests. It transfers registry metadata without rebuilding or downloading the
image layers. The image contents, build labels, provenance, and SBOM stay the same;
the release version is added as a tag. It does not resolve the moving `edge` alias.

Release promotion does not depend on expiring Actions artifacts. If an image is
missing, build metadata is absent, or the source run has not completed successfully,
the job stops before writing release tags. Wait for the main workflow to finish
and rerun the promotion job. Images made before this promotion workflow need one
main build with the updated metadata before they can be released this way.

Existing version tags may be reused only when their digests match. A later rebuild
of the same commit cannot overwrite an already published release version. Main
reruns may refresh commit tags with newer base images; use a new version for a
new release image set.

Stable aliases move only after every version tag is verified and GitHub identifies
this release as latest. Prereleases and older releases receive version tags without
moving stable aliases. Main's `edge` aliases move only while its commit remains
current. Registry updates are separate operations; if promotion fails partway,
rerun the failed promotion job. No image rebuild is needed for that retry.

Publishing jobs use `GITHUB_TOKEN`; the release job needs `actions: read` to check
the source workflow and `packages: write` to add registry tags. No publishing PAT
is required. Actions are pinned to commit SHAs. Weights download separately at
runtime and are outside the image SBOM.
