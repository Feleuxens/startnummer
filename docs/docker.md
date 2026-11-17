# Docker quick start

Install Startnummer on a Linux x86-64 host with Docker Engine and Compose v2.
The default CPU worker needs no accelerator configuration. This guide takes you
from a fresh installation to your first analyzed album.

Startnummer runs its own PostgreSQL database. Your existing Chevereto installation
stays separate. You can try uploads before connecting a gallery.

## 1. Get the deployment files

Clone the repository and open its directory:

```sh
git clone https://github.com/Feleuxens/startnummer.git
cd startnummer
cp .env.docker.example .env.docker
chmod 600 .env.docker
```

Run the commands below from this directory. Keep its Compose project name stable;
Docker uses it to identify the installation's volumes.

## 2. Set passwords and secrets

Generate separate values for the database, sessions, worker, and integration key:

```sh
docker run --rm python:3.12-slim-bookworm python -c '
import base64, secrets
for name in ("POSTGRES_PASSWORD", "STARTNUMMER_SESSION_SECRET", "STARTNUMMER_WORKER_SECRET"):
    print(name + "=" + secrets.token_hex(32))
print("STARTNUMMER_INTEGRATION_KEY=" + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
'
```

Copy those four lines into `.env.docker`, replacing the empty values. Keep this
file private and store a separate copy with your server configuration backups.
The session and worker secrets need at least 32 characters. Use the generated
hexadecimal database password so it can be embedded in the connection URL.

For this first local test, also set:

```dotenv
STARTNUMMER_IMAGE_TAG=edge
STARTNUMMER_WORKER_VARIANT=cpu
STARTNUMMER_COOKIE_SECURE=0
```

`edge` follows the latest main build. For production, choose a published release
from the [image tag guide](releases.md) and set up [HTTPS](reverse-proxy.md) with
`STARTNUMMER_COOKIE_SECURE=1` before signing in through the public hostname.

Leave `STARTNUMMER_USERNAME` and `STARTNUMMER_PASSWORD` commented out for a new
installation. If you keep an existing configured login, see
[environment-configured accounts](accounts.md#use-an-environment-configured-account).

## 3. Start Startnummer

```sh
docker compose --env-file .env.docker pull
docker compose --env-file .env.docker up -d --wait
docker compose --env-file .env.docker ps -a
```

The API, worker, and PostgreSQL should be running and healthy. The migration
service should have exited with code 0. If startup fails, see
[status and troubleshooting](operations.md#check-service-status).

The API listens on `127.0.0.1:8000`; the worker and database have no published
ports. For a server reached over SSH, forward this port from your computer:

```sh
ssh -L 8000:127.0.0.1:8000 user@server
```

Keep that connection open while trying the app at <http://localhost:8000>.

## 4. Create the administrator

Retrieve the one-time setup code:

```sh
docker compose --env-file .env.docker run --rm ops setup-code
```

Open <http://localhost:8000>, enter the code, and choose a username and password.
Once setup completes, you should see **Saved albums**. The first account is the
administrator. You can [invite other users](accounts.md#invite-a-user) later.

## 5. Analyze a small album

1. Choose **New batch**, then **Upload images**.
2. Select a few original photos. Supply a Competitoroverview or Resultoverview HTML
   roster, or choose **No roster** to name people manually after analysis.
3. Choose **Import and preview** and check the photo count and any supplied roster.
4. Choose **Analyze batch**. The first run downloads model weights and can take
   longer than later runs.
5. Open a photo and review its suggested caption. Save a correction if needed.
6. Choose **Save review and finish face session** when face review is complete.

You can reopen the album with its saved photos, names, and captions. See
[Review an album](review.md) for corrections and approval. To update existing
gallery descriptions, [connect Chevereto](chevereto.md) and import a gallery album.
Uploaded photos have no automatic gallery destination.

## Use Intel OpenVINO

For an Intel CPU server, set this in `.env.docker`:

```dotenv
STARTNUMMER_WORKER_VARIANT=intel
```

Use the same pull/start commands. The worker runs pose, face, and OCR models on
OpenVINO CPU; no Intel GPU mapping is needed. The first run converts and caches
pose weights. Measure a representative album on your server to compare speed.

When changing a running installation, follow the [update procedure](operations.md#update-startnummer).

## NVIDIA GPU

Install a compatible NVIDIA driver and NVIDIA Container Toolkit on the host.
Set `STARTNUMMER_WORKER_VARIANT=nvidia` in `.env.docker`, then uncomment this
reservation under `services.worker` in `compose.yaml`:

```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: 1
          capabilities: [gpu]
```

The variant selects the CUDA image; the reservation gives it access to a GPU.
Leave the reservation commented out for CPU and Intel workers. The locked GPU
packages use CUDA 13; check the host driver against the
[ONNX Runtime CUDA requirements](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html).
Docker's [GPU guide](https://docs.docker.com/compose/how-tos/gpu-support/) covers
host setup and device selection.

After starting the worker, check runtime availability:

```sh
docker compose --env-file .env.docker exec worker \
  python -c 'from startnummer.app.inference import preload_gpu_runtime; preload_gpu_runtime(); import torch, onnxruntime as ort; print("CUDA:", torch.cuda.is_available()); print(ort.get_available_providers())'
```

Then analyze a small album. A provider appearing in this output confirms runtime
availability; successful model execution needs the album test.

## Build from source

To use the code in your checkout, set `STARTNUMMER_IMAGE_TAG=local` in
`.env.docker`, then build and start:

```sh
docker compose --env-file .env.docker -f compose.yaml -f compose.build.yaml build
docker compose --env-file .env.docker up -d --wait
```

The build override uses the selected worker variant. The main Compose file starts
the locally tagged images without that override. For later source updates, use
this build command in place of `pull` in the [update procedure](operations.md#update-startnummer).

## Use another environment file

The examples use `.env.docker` for both Compose variables and the API environment.
To use another file, set its absolute path and pass it to Compose:

```sh
export STARTNUMMER_ENV_FILE=/absolute/path/to/startnummer.env
docker compose --env-file "$STARTNUMMER_ENV_FILE" up -d --wait
```

## Next steps

- [Serve the app through your HTTPS proxy](reverse-proxy.md).
- [Connect Chevereto](chevereto.md) and try a reviewed description update.
- [Create a backup and test recovery](backups.md).
- [Check storage, limits, and service status](operations.md).
- For Apple silicon, use [native installation](devices.md); Apple acceleration
  needs the macOS frameworks.
