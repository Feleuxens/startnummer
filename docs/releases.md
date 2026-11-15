# Container releases

`.github/workflows/images.yml` runs the Python checks and browser tests before
building images. Pull requests build the web and CPU worker without registry
credentials. Pushes to `main` and published GitHub releases build and push all four
Linux x86-64 images to GHCR. A manual run publishes only when run against `main`.
Apple inference remains a native macOS installation; there is no Apple worker image.

## Images and tags

The web image contains the API and built frontend. There is no separate API image.
The worker variants share one package with a device prefix in each tag.

| Image | Stable release | Moving stable tag | Development |
| --- | --- | --- | --- |
| `ghcr.io/feleuxens/startnummer-web` | `0.1.0` | `latest` | `edge`, `sha-<commit>` |
| `ghcr.io/feleuxens/startnummer-worker` | `cpu-0.1.0` | `cpu-latest` | `cpu-edge`, `cpu-sha-<commit>` |
| `ghcr.io/feleuxens/startnummer-worker` | `intel-0.1.0` | `intel-latest` | `intel-edge`, `intel-sha-<commit>` |
| `ghcr.io/feleuxens/startnummer-worker` | `nvidia-0.1.0` | `nvidia-latest` | `nvidia-edge`, `nvidia-sha-<commit>` |

`<commit>` is the full Git SHA, not the version from `pyproject.toml`. Development
builds never move stable tags. A prerelease such as `v0.2.0-rc.1` publishes
`0.2.0-rc.1`, `cpu-0.2.0-rc.1`, and the other worker variants, without moving
`latest`. Stable release tags may have a leading `v`; the image version omits it.

Moving tags are updated by digest only after every image has built and pushed.
An older release does not replace the aliases when GitHub identifies another
release as latest. An outdated main build cannot replace `edge`. Registry updates
are separate operations; if promotion fails partway, rerun the failed jobs.
Use a version tag for deliberate production updates, or a digest when exact image
identity is required. Rebuilding the same source may pick up newer base images.

## Publishing a release

1. Set `project.version` in `pyproject.toml` and refresh `uv.lock`. Set the frontend
   package version as appropriate and keep its lockfile consistent.
2. Commit the intended source, Docker files, and workflow. Wait for the main build
   and tests to pass.
3. Create a GitHub release from that commit, using a tag such as `v0.1.0`. The tag
   must match `project.version`. Mark versions with a prerelease suffix as
   prereleases. Draft releases do not publish images.
4. Publish the release. Inspect the workflow results and image digests in its job
   summaries. Make the stable release GitHub's latest release when it should move
   the stable image aliases.

A tag push alone does not publish release images. The trigger is publication of
the GitHub release. If a release is made latest only after its publishing run,
rerun that release's workflow to update the aliases.

The workflow uses the repository's `GITHUB_TOKEN` with `packages: write` only in
publishing jobs; no personal access token needs to be stored as an Actions secret.
Actions are pinned to commit SHAs. Builds include OCI source/revision/version
labels, BuildKit provenance, and an SBOM. These describe the build; they do not
prove accelerator execution or model accuracy. Weights download separately at
runtime and are not bundled or described by the image SBOM.

GHCR package visibility is separate from repository visibility. The workflow does
not change it. Until a package is public, clients must authenticate before pulling:

```sh
docker login ghcr.io -u Feleuxens
```

Use a GitHub personal access token (classic) with `read:packages` at the password
prompt. See GitHub's
[container registry documentation](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
for token and package access requirements.

## Deploying published images

Create `.env.docker` and configure credentials as described in
[Docker deployment](docker.md). Once version `0.1.0` has been published, set:

```dotenv
STARTNUMMER_IMAGE_TAG=0.1.0
```

For the Intel server:

```sh
docker compose --env-file .env.docker -f compose.yaml -f compose.intel.yaml pull
docker compose --env-file .env.docker -f compose.yaml -f compose.intel.yaml up -d --no-build --wait
```

Omit the override for CPU, or use `compose.gpu.yaml` for NVIDIA. `latest`, `edge`,
`sha-<commit>`, and prerelease versions use the same setting; Compose adds the
worker's device prefix. Do not include that prefix in `STARTNUMMER_IMAGE_TAG`.

Back up and finish active face review before updating an existing deployment.
Follow the stop/migration/restart sequence in the Docker guide.
