"""Prepare reusable pose-model exports without caching any input photos."""

import fcntl
import hashlib
import json
import os
import shutil
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory

from startnummer.adapters.runtime import Backend, BackendUnavailable


def pose_model(root, backend):
    from ultralytics import YOLO

    root = Path(root).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    original = root / "yolo11n-pose.pt"
    if backend not in (Backend.OPENVINO, Backend.APPLE):
        return str(original)
    package = "openvino" if backend is Backend.OPENVINO else "coremltools"
    format_name = "openvino" if backend is Backend.OPENVINO else "coreml"
    precision = 16 if backend is Backend.APPLE else 32
    options = {
        "format": format_name,
        "device": "cpu",
        "imgsz": 640,
        "batch": 1,
        "dynamic": False,
        "nms": False,
        "quantize": precision,
    }
    # Serialize downloads/exports so concurrent manual preparation cannot publish partial models.
    with (root / ".pose-export.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        YOLO(str(original))  # Download the original weights if needed.
        digest = hashlib.sha256(original.read_bytes()).hexdigest()
        signature = json.dumps(
            [digest, version("ultralytics"), version("torch"), version(package), options], sort_keys=True
        )
        key = hashlib.sha256(signature.encode()).hexdigest()[:20]
        destination = root / "exports" / f"yolo11n-pose-{format_name}-{key}"
        if backend is Backend.APPLE:
            destination = destination.with_suffix(".mlpackage")
        else:
            destination = destination.with_name(destination.name + "_openvino_model")
        if destination.exists():
            return str(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with TemporaryDirectory(prefix=".pose-export-", dir=destination.parent) as temporary:
                staged = Path(temporary) / original.name
                shutil.copyfile(original, staged)
                exported = Path(YOLO(str(staged)).export(**options))
                if not exported.is_dir():
                    raise ValueError("Expected a model directory")
                if not destination.exists():
                    os.replace(exported, destination)
                return str(destination)
        except Exception:
            raise BackendUnavailable(
                f"Could not export the pose model for {format_name}; check conversion dependencies"
            ) from None
