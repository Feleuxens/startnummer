"""Inference backend selection. Native imports happen only when models are loaded."""

import platform
import sys
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version

from startnummer.core.batch import WorkflowError


class Backend(StrEnum):
    AUTO = "auto"
    CPU = "cpu"
    OPENVINO = "openvino"
    CUDA = "cuda"
    APPLE = "apple"


class BackendUnavailable(WorkflowError):
    """A configuration error whose message is safe to show without input data."""


def installed(package):
    try:
        version(package)
        return True
    except PackageNotFoundError:
        return False


def select_backend(requested, *, system=None, machine=None, packages=None, cuda=False):
    requested = Backend(requested)
    system, machine = system or sys.platform, machine or platform.machine()
    packages = (
        packages
        if packages is not None
        else {name for name in ("coremltools", "openvino", "onnxruntime-gpu") if installed(name)}
    )
    if requested is Backend.AUTO:
        if system == "darwin" and machine == "arm64" and "coremltools" in packages:
            return Backend.APPLE
        if cuda and "onnxruntime-gpu" in packages:
            return Backend.CUDA
        if system == "linux" and machine == "x86_64" and "openvino" in packages:
            return Backend.OPENVINO
        return Backend.CPU
    if requested is Backend.APPLE and (system != "darwin" or machine != "arm64"):
        raise BackendUnavailable("The apple backend requires native macOS on Apple silicon")
    if requested is Backend.OPENVINO and (system != "linux" or machine != "x86_64"):
        raise BackendUnavailable("The openvino backend requires Linux x86-64; install the intel extra there")
    return requested


def require_provider(ort, provider):
    if provider not in ort.get_available_providers():
        raise BackendUnavailable(f"{provider} is unavailable; install the matching device extra")


@lru_cache(maxsize=1)
def openvino_core():
    from openvino import Core

    core = Core()
    if "CPU" not in core.available_devices:
        raise BackendUnavailable("OpenVINO exposes no CPU device; check the intel installation")
    return core


class OpenVinoFaceSession:
    """The run() boundary used by InsightFace, executed by OpenVINO on CPU."""

    def __init__(self, path):
        core = openvino_core()
        self.model = core.compile_model(core.read_model(str(path)), "CPU", {"INFERENCE_PRECISION_HINT": "f32"})
        self.request = self.model.create_infer_request()

    def run(self, output_names, inputs):
        result = self.request.infer(inputs, share_inputs=False, share_outputs=False)
        return [result[self.model.output(name)] for name in output_names]


def openvino_session(path):
    return OpenVinoFaceSession(path)


@dataclass
class Runtime:
    backend: Backend
    providers: list


def prepare_runtime(requested, model_root):
    # GPU ONNX imports need the CUDA libraries that PyTorch loads first.
    import torch

    requested = Backend(requested)
    cuda = torch.cuda.is_available() if requested in (Backend.AUTO, Backend.CUDA) else False
    backend = select_backend(requested, cuda=cuda)
    import onnxruntime as ort

    if installed("onnxruntime-gpu"):
        ort.preload_dlls(directory="")
    if backend is Backend.CUDA:
        if not cuda:
            raise BackendUnavailable("CUDA is unavailable; check the NVIDIA driver and container GPU access")
        require_provider(ort, "CUDAExecutionProvider")
        return Runtime(backend, ["CUDAExecutionProvider", "CPUExecutionProvider"])
    if backend is Backend.APPLE:
        require_provider(ort, "CoreMLExecutionProvider")
        (model_root / "coreml").mkdir(parents=True, exist_ok=True)
        return Runtime(
            backend,
            [
                (
                    "CoreMLExecutionProvider",
                    {
                        "ModelFormat": "MLProgram",
                        "MLComputeUnits": "CPUAndNeuralEngine",
                        "ModelCacheDirectory": str(model_root / "coreml"),
                    },
                ),
                "CPUExecutionProvider",
            ],
        )
    if backend is Backend.OPENVINO:
        openvino_core()
    return Runtime(backend, ["CPUExecutionProvider"])
