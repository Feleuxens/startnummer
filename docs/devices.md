# Device profiles and native installation

Use Docker for Linux deployments. Choose its worker variant in the
[Docker guide](docker.md). On Apple silicon, install natively to use CoreML and
the Neural Engine; Linux containers cannot access those macOS frameworks.

| Profile  | Target                             | Inference backend                           |
| -------- | ---------------------------------- | ------------------------------------------- |
| `cpu`    | Linux or Apple-silicon macOS       | CPU PyTorch and ONNX Runtime                |
| `intel`  | Linux x86-64, including an i7-8700 | OpenVINO CPU                                |
| `nvidia` | Linux x86-64 with an NVIDIA GPU    | CUDA PyTorch and ONNX Runtime GPU           |
| `apple`  | Native macOS 14+ on Apple silicon  | CoreML/Neural Engine; optional MPS for pose |

## Install on Apple silicon

You need Python 3.12, uv, Node.js 24, and PostgreSQL. The database example below
uses Docker Compose; skip it if you already have a PostgreSQL database.

### 1. Install the application

```sh
git clone https://github.com/Feleuxens/startnummer.git
cd startnummer
uv sync --extra api --extra apple
cp .env.example .env
```

To use the bundled development database:

```sh
docker compose -f compose.dev.yaml -p startnummer-dev up -d postgres
```

It listens on `127.0.0.1:5432` and matches the example `.env` database URL. Use a
different project name from any production deployment on the same Docker host.

### 2. Configure the app

Generate secrets and an integration key:

```sh
uv run --no-sync python -c '
import base64, secrets
for name in ("STARTNUMMER_SESSION_SECRET", "STARTNUMMER_WORKER_SECRET"):
    print(name + "=" + secrets.token_hex(32))
print("STARTNUMMER_INTEGRATION_KEY=" + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
'
```

Copy these values into `.env`. Set your database URL and photo-storage path, and
set `STARTNUMMER_INFERENCE_BACKEND=apple`. Remove both Chevereto connection
variables if you will configure the gallery later through Administration. Leave
legacy username/password variables commented out for a new account.

### 3. Build and start

```sh
uv run --no-sync startnummer migrate
cd startnummer-web
npm ci
npm run build
cd ..
uv run --no-sync startnummer start --backend apple --detach
uv run --no-sync startnummer status
uv run --no-sync startnummer setup-code
```

Open <http://127.0.0.1:8000>, enter the setup code, and create the administrator.
**Saved albums** confirms setup is complete. Try a small album using the
[review guide](review.md). See [Operations](operations.md#run-or-stop-a-native-installation)
for status, logs, and stopping the app.

## Install another native profile

For local Linux use, replace `apple` in the install command with one profile:

```sh
uv sync --extra api --extra intel
```

Use `cpu` for CPU inference or `nvidia` for CUDA. The corresponding backend values
are `cpu`, `openvino`, and `cuda`; set that value in `.env` and pass it to
`startnummer start --backend NAME`.

Finish face review and stop services before changing their Python environment.
Choose one device profile at a time; `uv sync` removes dependencies belonging
only to the previous profile. Do not use `--all-extras`.

Use uv so the lockfile's package rules apply. Linux CPU/Intel profiles use the
PyTorch CPU index; NVIDIA installs `onnxruntime-gpu`. The other profiles install
`onnxruntime`. Do not install both ONNX distributions or overlapping OpenCV
packages. The older `inference` and `face` extras are CPU aliases; `ocr` and `vlm`
are experimental and are not application profiles.

## Check a runtime

Run the check for your selected backend, without a database or private photos:

```sh
uv run --no-sync startnummer-worker --backend apple --check-backend
```

Replace `apple` with `cpu`, `openvino`, or `cuda` for another profile. The check
uses a generated blank image in a disposable inference process. It may download
weights or convert models. A successful check verifies loading, inference, and
process exit. Follow it with a representative album to assess results and speed.

An explicit backend reports an error when its required runtime is unavailable.
`auto` tries installed Apple support on native Apple silicon, available CUDA,
OpenVINO, then CPU. Use an explicit value while checking accelerator availability.

## Choose Apple Neural Engine or GPU pose inference

The default `apple` backend uses FP16 CoreML pose weights. Face models and OCR
request CoreML's `CPUAndNeuralEngine` mode. CoreML may place unsupported operations
on CPU; actual operation placement and performance need checking on the Mac.
The pose loader rejects a whole-model CPU-only fallback.

To use the Apple GPU for pose inference, set this in `.env` before starting:

```dotenv
STARTNUMMER_APPLE_POSE_DEVICE=mps
```

Faces and OCR keep the CoreML path. MPS uses the GPU; it does not use the Neural
Engine. Set `coreml` to return to the default pose path.

## Store model weights

`STARTNUMMER_MODEL_ROOT` defaults to `~/.cache/startnummer/models`; Docker uses
`/data/models`. Set it before starting the worker to choose another model disk.
`STARTNUMMER_OCR_MODEL_ROOT` can select a separate OCR weight directory.

This storage contains public weights, converted models, and compiled caches.
It contains no album photos or extracted face data. See
[Architecture](architecture.md#face-data-lifetime) for inference and review memory.

## Hardware verification

Linux CPU and Intel checks have passed on generated images, including a synthetic
OpenVINO/CPU recognition comparison. NVIDIA library/image checks and Apple model
conversion checks have also passed. Native CUDA execution on the RTX 4070 Super
and Neural Engine execution on the M5 Pro still need target-hardware checks.
These checks do not establish recognition accuracy or an album speedup.
