"""Device policy and model preparation with synthetic runtimes and weights."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from startnummer.adapters import models, runtime
from startnummer.adapters.runtime import Backend, BackendUnavailable, select_backend


@pytest.mark.parametrize(
    "system,machine,packages,cuda,expected",
    [
        ("linux", "x86_64", set(), False, "cpu"),
        ("linux", "x86_64", {"openvino"}, False, "openvino"),
        ("linux", "x86_64", {"onnxruntime-gpu"}, True, "cuda"),
        ("linux", "x86_64", {"onnxruntime-gpu"}, False, "cpu"),
        ("darwin", "arm64", {"coremltools"}, False, "apple"),
        ("darwin", "arm64", set(), False, "cpu"),
        ("darwin", "arm64", {"openvino"}, False, "cpu"),
    ],
)
def test_auto_selects_installed_backend(system, machine, packages, cuda, expected):
    assert select_backend("auto", system=system, machine=machine, packages=packages, cuda=cuda) == expected


@pytest.mark.parametrize("backend,system,machine", [("apple", "linux", "x86_64"), ("openvino", "darwin", "arm64")])
def test_explicit_backend_rejects_wrong_operating_system(backend, system, machine):
    with pytest.raises(BackendUnavailable):
        select_backend(backend, system=system, machine=machine, packages=set())


def test_apple_requests_neural_engine_and_model_only_cache(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace())
    monkeypatch.setitem(
        sys.modules, "onnxruntime", SimpleNamespace(get_available_providers=lambda: ["CoreMLExecutionProvider"])
    )
    monkeypatch.setattr(runtime, "select_backend", lambda *args, **kwargs: Backend.APPLE)
    monkeypatch.setattr(runtime, "installed", lambda _: False)
    result = runtime.prepare_runtime("apple", tmp_path)
    provider, options = result.providers[0]
    assert provider == "CoreMLExecutionProvider"
    assert options["MLComputeUnits"] == "CPUAndNeuralEngine"
    assert Path(options["ModelCacheDirectory"]).parent == tmp_path


def test_cuda_request_does_not_silently_fall_back(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False)))
    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace())
    monkeypatch.setattr(runtime, "installed", lambda _: False)
    with pytest.raises(BackendUnavailable, match="CUDA is unavailable"):
        runtime.prepare_runtime("cuda", tmp_path)


@pytest.mark.parametrize("backend,suffix", [(Backend.OPENVINO, "_openvino_model"), (Backend.APPLE, ".mlpackage")])
def test_pose_exports_are_cached_and_invalidated_by_weights(monkeypatch, tmp_path, backend, suffix):
    calls = []

    class Model:
        def __init__(self, path):
            self.path = Path(path)
            if not self.path.exists():
                self.path.write_bytes(b"synthetic-model-weights")

        def export(self, **options):
            calls.append(options)
            output = self.path.with_name("export" + suffix)
            output.mkdir()
            (output / "weights.bin").write_bytes(self.path.read_bytes())
            return output

    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=Model))
    monkeypatch.setattr(models, "version", lambda _: "test-version")
    first = models.pose_model(tmp_path, backend)
    assert first == models.pose_model(tmp_path, backend)
    assert len(calls) == 1 and first.endswith(suffix)
    assert calls[0]["quantize"] == (16 if backend is Backend.APPLE else 32)
    assert calls[0]["nms"] is False
    (tmp_path / "yolo11n-pose.pt").write_bytes(b"changed-synthetic-weights")
    second = models.pose_model(tmp_path, backend)
    assert first != second and len(calls) == 2
    assert not list((tmp_path / "exports").glob(".pose-export-*"))


def test_failed_export_does_not_publish_partial_model(monkeypatch, tmp_path):
    class Model:
        def __init__(self, path):
            Path(path).touch()

        def export(self, **options):
            raise RuntimeError("synthetic-private-error")

    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=Model))
    monkeypatch.setattr(models, "version", lambda _: "test-version")
    with pytest.raises(BackendUnavailable) as result:
        models.pose_model(tmp_path, Backend.APPLE)
    assert "synthetic-private-error" not in str(result.value)
    assert not list((tmp_path / "exports").iterdir())


@pytest.mark.parametrize("backend", [Backend.CPU, Backend.OPENVINO, Backend.CUDA, Backend.APPLE])
def test_model_factory_passes_device_policy_to_each_adapter(monkeypatch, tmp_path, backend):
    from startnummer.app import inference
    from startnummer.app.inference import load_models

    monkeypatch.setattr(inference, "DEFAULT_CACHE", SimpleNamespace(set_max_mb_bytes=lambda _: None))

    monkeypatch.setenv("STARTNUMMER_MODEL_ROOT", str(tmp_path))
    monkeypatch.delenv("STARTNUMMER_OCR_MODEL_ROOT", raising=False)
    monkeypatch.delenv("STARTNUMMER_APPLE_POSE_DEVICE", raising=False)
    monkeypatch.setattr(runtime, "prepare_runtime", lambda *_: runtime.Runtime(backend, ["expected-provider"]))
    monkeypatch.setattr(models, "pose_model", lambda root, mode: str(root / f"pose-{mode}"))
    monkeypatch.setitem(sys.modules, "startnummer.adapters.detect.yolo", SimpleNamespace(YoloDetector=lambda **kw: kw))
    monkeypatch.setitem(
        sys.modules, "startnummer.adapters.face.insight", SimpleNamespace(InsightFaceEngine=lambda **kw: kw)
    )
    monkeypatch.setitem(
        sys.modules,
        "startnummer.adapters.ocr.rapid",
        SimpleNamespace(
            RapidOcrReader=lambda **kw: kw,
            EngineType=SimpleNamespace(OPENVINO="openvino"),
        ),
    )
    detector, ocr, faces = load_models(0, True, backend=backend)
    assert detector["device"] == ("cuda" if backend is Backend.CUDA else "cpu")
    assert detector["require_coreml_ne"] == (backend is Backend.APPLE)
    assert faces["providers"] == ["expected-provider"]
    assert bool(faces["session_factory"]) == (backend is Backend.OPENVINO)
    parameters = ocr["params"]
    if backend is Backend.OPENVINO:
        assert all(parameters[f"{stage}.engine_type"] == "openvino" for stage in ("Det", "Cls", "Rec"))
    elif backend is Backend.APPLE:
        assert parameters["EngineConfig.onnxruntime.use_coreml"] is True
        assert parameters["EngineConfig.onnxruntime.coreml_ep_cfg.MLComputeUnits"] == "CPUAndNeuralEngine"
    elif backend is Backend.CUDA:
        assert parameters["EngineConfig.onnxruntime.use_cuda"] is True


@pytest.mark.parametrize("neural_engine", [False, True])
def test_apple_pose_rejects_library_cpu_only_fallback(monkeypatch, neural_engine):
    ne = object()

    class Model:
        def __init__(self, _):
            native = SimpleNamespace(compute_unit=ne if neural_engine else object())
            self.predictor = SimpleNamespace(model=SimpleNamespace(backend=SimpleNamespace(model=native)))

        def __call__(self, *args, **kwargs):
            return []

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=Model))
    monkeypatch.setitem(sys.modules, "coremltools", SimpleNamespace(ComputeUnit=SimpleNamespace(CPU_AND_NE=ne)))
    source = Path(__file__).resolve().parents[1] / "startnummer/adapters/detect/yolo.py"
    spec = importlib.util.spec_from_file_location("synthetic_yolo_adapter", source)
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    if neural_engine:
        detector = adapter.YoloDetector(
            device="cpu", cache=SimpleNamespace(load=lambda _: None), require_coreml_ne=True
        )
        assert detector.detect("synthetic") == []
    else:
        with pytest.raises(BackendUnavailable, match="fell back to CPU"):
            adapter.YoloDetector(device="cpu", cache=SimpleNamespace(load=lambda _: None), require_coreml_ne=True)
