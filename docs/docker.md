# Docker deployment

Startnummer runs as an API serving the built frontend, one analysis worker, and
PostgreSQL. A short-lived migration service runs before the API and worker start.
Docker manages the processes; the local `startnummer start` supervisor is not used
inside containers. Chevereto remains an existing, separately managed installation.

`compose.yaml` pulls published images from GHCR. Choose `cpu`, `intel`, or `nvidia`
with `STARTNUMMER_WORKER_VARIANT`; CPU is the default. NVIDIA also needs the
commented GPU reservation enabled in the worker service. There are no hardware
override files. Optional source builds use `compose.build.yaml`.

Images contain no private photos or model weights. See [device profiles](devices.md)
for runtime details and native Apple installation, and [container releases](releases.md)
for release and development tags.

## First start

Use Docker Engine with Compose v2 or later. The deployment is tested on Linux
x86-64. Docker Desktop and other architectures have not been verified. Check out
the version you want to deploy, then create the configuration:

```sh
cp .env.docker.example .env.docker
chmod 600 .env.docker
```

Replace the example credentials. This command generates a database password,
separate session/worker secrets, and a valid integration encryption key:

```sh
docker run --rm python:3.12-slim-bookworm python -c '
import base64, secrets
for name in ("POSTGRES_PASSWORD", "STARTNUMMER_SESSION_SECRET", "STARTNUMMER_WORKER_SECRET"):
    print(name + "=" + secrets.token_hex(32))
print("STARTNUMMER_INTEGRATION_KEY=" + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
'
```

Copy these values into `.env.docker` and set `STARTNUMMER_PASSWORD` for login.
Use hexadecimal for `POSTGRES_PASSWORD`: Compose embeds it in a database URL.
Set `STARTNUMMER_IMAGE_TAG` to a published version, such as `0.1.0`. `latest`
follows the latest stable release; use `edge` to try main before the first release.
Set `STARTNUMMER_WORKER_VARIANT=intel` for OpenVINO on the Intel server, or leave
it at `cpu`. NVIDIA setup is described below.
Keep `STARTNUMMER_USERNAME` stable; it determines ownership of saved records.
Keep the configuration and encryption key separately from application backups.

```sh
docker compose --env-file .env.docker pull
docker compose --env-file .env.docker up -d --wait
docker compose --env-file .env.docker ps -a
```

The API binds to `127.0.0.1:8000` on the host. Put it behind your HTTPS reverse proxy.
For a local HTTP trial, set `STARTNUMMER_COOKIE_SECURE=0` and open
<http://localhost:8000>. Use `1` when serving through HTTPS. Change
`STARTNUMMER_PORT` if another service uses 8000. The worker and PostgreSQL have no
published ports. PostgreSQL is on an internal network; the API and worker also
have outbound access for imports and model downloads.

Compose discovers `compose.yaml` automatically. The separate `compose.dev.yaml`
contains local test databases and Chevereto; select it explicitly when needed.
The commands use `.env.docker` for both Compose interpolation and the API's
environment. For a different file, set `STARTNUMMER_ENV_FILE=/absolute/path/to/file`
and pass the same path to `--env-file`.

Health checks verify API/database/storage readiness and the authenticated private
worker service. Models load only when an album starts analysis. A healthy worker
does not mean weights are downloaded or that inference has been tested on the host.
Run a small test album before processing important work.

## Build from source

To build this checkout instead of pulling images, set `STARTNUMMER_IMAGE_TAG=local`
in `.env.docker`. The build override selects the worker target from the same
`STARTNUMMER_WORKER_VARIANT` setting:

```sh
docker compose --env-file .env.docker -f compose.yaml -f compose.build.yaml build
docker compose --env-file .env.docker up -d --wait
```

The base file then starts the locally tagged images. For source updates, run this
build command in place of `pull` in the update procedure below. Builds use the
Python and npm lockfiles. API, migration, and operations services share the web
image; the selected worker is built separately.

## HTTPS proxy

The [Nginx guide](reverse-proxy.md) includes HTTPS server blocks for a proxy on the
host or in another Docker project. It covers trusted proxy addresses, secure
cookies, upload limits, buffering, Docker DNS, and troubleshooting.

Keep the API on loopback for a host proxy, or remove its published port when using
a shared proxy network. Set `STARTNUMMER_COOKIE_SECURE=1` for the public HTTPS URL
and preserve the incoming `Host`. TLS certificates and DNS stay with your proxy;
the worker and database stay private.

## Gallery connection

With both Chevereto variables absent, sign in and configure the connection under
**Administration → Configured integrations**. `STARTNUMMER_INTEGRATION_KEY` must be
a valid Fernet key. Alternatively, set both `STARTNUMMER_CHEVERETO_URL` and
`STARTNUMMER_CHEVERETO_DSN` in `.env.docker`; this makes the connection read-only
in Administration. Empty values still select environment management.

Use hosts reachable from the API container. `localhost` inside a container is that
container, not the Docker host. If the gallery database is another container,
connect the API to its network and use its service name. Do not publish the worker
port or send gallery credentials to it. Only the API and operations containers
receive the API configuration file.

## Intel OpenVINO

Set this in `.env.docker` for the i7-8700 server or another Linux x86-64 CPU host:

```dotenv
STARTNUMMER_WORKER_VARIANT=intel
```

Use the normal pull/start commands above. The worker uses OpenVINO CPU for pose,
face models, and OCR. Pose weights are converted on first use and cached in the
model volume. No Intel GPU mapping is needed for CPU execution. Benchmark a
representative album on the target server before assuming a speedup.

## NVIDIA GPU

Install a compatible NVIDIA driver and NVIDIA Container Toolkit on the Docker
host. Set `STARTNUMMER_WORKER_VARIANT=nvidia` in `.env.docker`, then uncomment the
GPU reservation under `services.worker` in `compose.yaml`:

```yaml
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

Use the normal pull/start commands. Both changes are needed: the setting chooses
the CUDA image, and the reservation gives its container GPU access. CPU/Intel
hosts leave this block commented out. Adjust the reservation if a particular GPU
must be selected.

The locked PyTorch and ONNX Runtime GPU versions use CUDA 13. The NVIDIA extra
installs only the GPU ONNX module; the pinned InsightFace metadata override lets
the selected profile supply the runtime. PyTorch loads before CUDA/cuDNN libraries
are preloaded inside each disposable inference child. Pose, face inference, and
OCR request CUDA.

Check runtime availability without loading models:

```sh
docker compose --env-file .env.docker exec worker \
  python -c 'import torch, onnxruntime as ort; ort.preload_dlls(directory=""); print("CUDA:", torch.cuda.is_available()); print(ort.get_available_providers())'
```

Follow this with an actual test album. Provider availability alone does not prove
that model execution succeeds. See the [Docker GPU instructions](https://docs.docker.com/compose/how-tos/gpu-support/)
and [ONNX Runtime CUDA requirements](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html).

## Persistent data and worker lifetime

Compose creates project-scoped named volumes:

| Volume | Contents |
| --- | --- |
| `postgres` | Startnummer's PostgreSQL records |
| `photos` | Imported original photos; read-only in the worker |
| `models` | Downloaded weights and model configuration/cache files |
| `backups` | Archives created through the operations container |

Photo storage uses `/data/photos/originals` beneath the `photos` volume mount.
Restore stages a sibling directory on that volume and replaces the storage
directory atomically. Keep this layout: a mount point itself cannot be replaced.

API/worker processes use UID/GID `10001`, a read-only root filesystem, and a
memory-backed `/tmp` limited to 4 GiB per container. Staged originals consume that
temporary space while analysis runs; budget RAM for staging, models, and inference
as well as the 512 MiB decoded-image cache. Adjust the tmpfs size and import limits
together for larger albums. Core dumps are disabled. Docker does not disable host
swap: configure the host accordingly if memory must never be paged to disk.

The worker retains temporary face boxes/groups only during the review session.
Each album's inference child exits before its result is exposed; finishing review
clears the session. Container shutdown interrupts analysis, stops its child, and
clears sessions. Saved captions survive; interrupted jobs can be retried. Model
weights are persistent and contain no per-album face data. Process exit releases
allocations but does not overwrite physical RAM/VRAM.

Do not scale the worker service yet: temporary review sessions require routing to
their owning worker, which is not implemented.

## Updates and status

Finish active face review before replacing the worker. Back up first, check out
the intended version, then pull and recreate the deployment:

```sh
docker compose --env-file .env.docker pull
docker compose --env-file .env.docker stop api worker
docker compose --env-file .env.docker up -d --wait
docker compose --env-file .env.docker ps -a
docker compose --env-file .env.docker logs --tail=100 api worker migrate
```

Keep the worker variant and any enabled NVIDIA reservation configured for this
host. Stop the API and worker before migrating an update so the old code cannot
keep editing the database during schema changes.
After a code/image update, the migration service must run successfully before the
API and worker are recreated. Keep the old source version/image until the update
is verified. Schema changes may require restoring a backup rather than simply
starting an older image.

`docker compose ... down` stops the stack and preserves named volumes. Never use
`down -v` for a deployment you want to keep. A new Compose project name creates
separate volumes; keep the project name stable for normal operation.

## Backup and restore

Back up while PostgreSQL is running:

```sh
docker compose --env-file .env.docker run --rm ops backup /backups/before-update.snbak
docker compose --env-file .env.docker run --rm ops verify-backup /backups/before-update.snbak
```

Use a new archive name each time. Copy it out of Docker's volume and store it away
from the deployment host:

```sh
umask 077
docker compose --env-file .env.docker run --rm -T --no-deps \
  --entrypoint cat ops /backups/before-update.snbak > before-update.snbak
```

Backups include saved records and referenced photo bytes, not gallery credentials,
keys, face data, weights, or the gallery database. Keep `.env.docker` separately.
Restore requires the original username and empty database/photo destinations.

For a recovery drill, use a **new** Compose project. The following uses the same
configuration but creates separate database/photo volumes, then mounts the original
archive read-only. It assumes the source project uses the default `startnummer`
name. Confirm its backup volume with `docker volume ls` before running this:

```sh
docker compose --env-file .env.docker -p startnummer-recovery up -d --wait postgres
docker compose --env-file .env.docker -p startnummer-recovery run --rm \
  -v startnummer_backups:/backups:ro ops restore /backups/before-update.snbak \
  --database-url 'postgresql+psycopg://startnummer:YOUR_POSTGRES_PASSWORD@postgres:5432/startnummer' \
  --blob-root /data/photos/originals
```

The restore migrates the empty target and restores unfinished jobs as cancelled.
Choose a different API port in the recovery configuration before starting its API
alongside the original stack. Then start the recovery stack and check saved work.
Reconfigure the gallery connection and use **Check gallery outcome** for uncertain
publishing outcomes. Restoring Startnummer never restores Chevereto descriptions.

## Deployment tests

The opt-in integration test builds the CPU images and starts a disposable Compose
project on a dynamically assigned API port. It exercises imports, a real queue and
inference subprocess with synthetic adapters, review persistence, face-session
cleanup, worker restart, and backup/restore. It never contacts an existing gallery
or database and removes only its own containers, networks, and volumes:

```sh
STARTNUMMER_TEST_DOCKER=1 uv run --no-sync pytest tests/test_docker.py -v
```

This does not benchmark real inference or validate an NVIDIA device. Test a small
album on the deployment hardware before the first production rollout.

A separate fresh-container smoke test downloaded the model weights and completed
real CPU analysis of a generated blank image, with the inference child exiting
afterward. This verifies first-use loading and paths, not recognition accuracy.
