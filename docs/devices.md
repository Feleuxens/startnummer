# Device profiles and native installation

Choose one device extra alongside `api` to install the complete application.
Each profile includes the shared worker and model adapters. `api` and `worker`
contain no ML runtimes on their own.

| Extra | Target | Backend |
| --- | --- | --- |
| `cpu` | Linux or Apple-silicon macOS CPU inference | CPU-only PyTorch and ONNX Runtime |
| `intel` | Linux x86-64, including the i7-8700 | OpenVINO CPU for pose, OCR, and faces |
| `nvidia` | Linux x86-64 with an NVIDIA GPU | CUDA PyTorch and ONNX Runtime GPU |
| `apple` | Native macOS 14+ on Apple silicon | CoreML/Neural Engine, with an optional MPS pose path |

```sh
uv sync --extra api --extra intel
# Or select one of the other profiles:
uv sync --extra api --extra nvidia
uv sync --extra api --extra apple
uv sync --extra api --extra cpu
```

Use one profile at a time. `uv sync` removes packages belonging only to the previous
profile; the lockfile declares device profiles incompatible. Finish face review and
stop services before changing the environment they use. Do not use `--all-extras`.
The older `inference` and `face` extras are CPU compatibility aliases. `ocr` and
`vlm` remain experimental dependencies, outside the supported application profiles.

Linux CPU/Intel profiles use the official PyTorch CPU wheel index. Other packages
come from PyPI. The NVIDIA profile installs only `onnxruntime-gpu`; CPU, Intel, and
Apple install `onnxruntime`. InsightFace's pinned dependency metadata is adjusted
in `pyproject.toml` because it names the CPU distribution even though both provide
the same Python module. Use uv so these source/metadata rules apply; do not
manually install overlapping ONNX packages or both OpenCV distributions.

## Selecting the runtime

Set `STARTNUMMER_INFERENCE_BACKEND` in `.env`, or pass `--backend` to the launcher
or worker. Values are `cpu`, `openvino`, `cuda`, `apple`, and `auto`.

```sh
uv run --no-sync startnummer start --backend openvino --detach
uv run --no-sync startnummer start --backend cuda --detach
uv run --no-sync startnummer start --backend apple --detach
```

Run only the command for your machine. An explicit backend reports an error when
its required runtime/device is unavailable. `auto` selects installed Apple support
on native Apple silicon, CUDA when available, then OpenVINO, and finally CPU.
Use an explicit backend when checking a deployment so a CPU fallback cannot mask
an unavailable accelerator.

Test loading and inference without a database or private photos:

```sh
uv run --no-sync startnummer-worker --backend openvino --check-backend
uv run --no-sync startnummer-worker --backend cuda --check-backend
uv run --no-sync startnummer-worker --backend apple --check-backend
```

The check uses a generated blank image in a disposable inference process. It may
download weights and prepare model exports. It verifies startup, inference, and
process exit, not athlete recognition, face matching accuracy, or the placement
of every operation on an accelerator. Follow it with a representative album test.

For local application setup, configure PostgreSQL and `.env`, migrate, and build
the frontend as described in the README. The launcher supports Linux and macOS;
Node.js is needed to build the frontend for a source installation. On macOS it
uses process birth times to guard against stale/reused PIDs.

## Apple silicon

Run the worker natively on macOS to access Apple hardware. A Linux Docker image
cannot execute CoreML/MPS through the Mac's native frameworks.

The default `apple` backend exports YOLO11 pose weights to an FP16 CoreML model.
The Ultralytics CoreML backend requests CPU and Neural Engine execution. Face
models and OCR use ONNX Runtime's CoreML provider with `CPUAndNeuralEngine`.
A whole-model CPU-only fallback in the pose backend is rejected. CoreML may still
execute unsupported operations on CPU; verify actual placement and
performance on the target Mac. Conversion success is not proof of Neural Engine
utilization or equivalent matching results.

To use the Apple GPU for pose inference instead, set:

```sh
STARTNUMMER_APPLE_POSE_DEVICE=mps
```

This keeps faces and OCR on the CoreML path. MPS is a GPU backend, not the Neural
Engine. The default value is `coreml`. Converted models retain the existing pose
and caption pipeline; they do not introduce a different caption generator.

## Model storage and process lifetime

`STARTNUMMER_MODEL_ROOT` defaults to `~/.cache/startnummer/models`. Docker sets it
to `/data/models`. This directory holds public weights, versioned pose exports,
and compiled model caches. `STARTNUMMER_OCR_MODEL_ROOT` can override the OCR
weight location. It never holds album photos, extracted faces, embeddings, or
review-session records.

Pose exports are cached by source-weight hash, converter/PyTorch/Ultralytics
versions, format, and precision. Exports use a file lock and publish a completed
directory atomically. A failed conversion leaves no published partial model.
OpenVINO pose exports and face execution use FP32; Apple pose exports use FP16 for the
Neural Engine path. Compare detection and matching results across backends before
assuming numerical equivalence.

Every album still runs in a fresh spawned process. Linux uses a parent-death
signal. On macOS, a separate lightweight watchdog observes a pipe held only by the
queue worker and kills inference if that pipe closes unexpectedly. This works
independently of native code holding the inference process's Python GIL. The
watchdog holds no model objects or face records. Normal completion waits for
inference to exit before exposing review data. Review-session expiry checks both
wall and monotonic deadlines, so laptop suspend cannot extend the original TTL.

## Docker

`Dockerfile` selects the same extras as native installations:

- `worker`: `cpu`
- `worker-intel`: `intel`
- `worker-gpu`: `nvidia`

For Intel, use `-f compose.yaml -f compose.intel.yaml`. For NVIDIA, use
`-f compose.yaml -f compose.gpu.yaml`. The base Compose stack uses CPU inference.
See [Docker deployment](docker.md) for configuration, persistent data, backups,
and updates. Native Apple installation is supported separately from these Linux
containers.


## Verification status

Linux x86-64 CPU and Intel runtime checks passed on generated images. OpenVINO
recognition outputs were also compared with CPU ONNX on synthetic input without
logging embeddings. The NVIDIA image passes library-loading checks; actual CUDA
execution on the RTX 4070 Super remains to be tested. The macOS ARM64 installation
plan and FP16 CoreML export are verified; native execution, Neural Engine placement,
and matching quality still need testing on the M5 Pro. No inference accuracy or
representative-album speedup is claimed by these checks.
