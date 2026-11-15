"""YOLO pose detector (ultralytics, yolo11n-pose). Returns person detections
with the keypoints association needs: head (nose, falling back to eye/ear
midpoints) plus shoulders and hips for the torso quad. Keypoints below
min_keypoint_confidence come back as None and association uses its box
fallback for that person.
"""

from startnummer.adapters.cache import DEFAULT_CACHE, ImageCache
from startnummer.adapters.runtime import BackendUnavailable
from startnummer.core.types import BoundingBox, Keypoint, PersonDetection

try:
    import torch
    from ultralytics import YOLO
except ImportError as exc:  # pragma: no cover - import guard for the worker extra
    raise ImportError("YoloDetector requires a device extra: cpu, intel, nvidia, or apple") from exc

# COCO-17 keypoint indices
_NOSE, _L_EYE, _R_EYE, _L_EAR, _R_EAR = 0, 1, 2, 3, 4
_L_SHOULDER, _R_SHOULDER, _L_HIP, _R_HIP = 5, 6, 11, 12


def _resolve_device(device: str) -> str:
    if device != "auto":
        return device
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class YoloDetector:
    def __init__(
        self,
        model: str = "yolo11n-pose.pt",
        min_confidence: float = 0.25,
        min_keypoint_confidence: float = 0.5,
        device: str = "auto",
        cache: ImageCache | None = None,
        require_coreml_ne: bool = False,
    ) -> None:
        # Weights auto-download on first use (needs network).
        self._model = YOLO(model)
        self._min_confidence = min_confidence
        self._min_kp = min_keypoint_confidence
        self._device = _resolve_device(device)
        self._cache = cache or DEFAULT_CACHE
        self._require_coreml_ne = require_coreml_ne
        if require_coreml_ne:
            from PIL import Image

            # Check the library's CPU fallback before it sees any album input.
            with Image.new("RGB", (640, 640)) as blank:
                self._model(blank, conf=self._min_confidence, device=self._device, verbose=False, save=False)
            self._verify_coreml()

    def _verify_coreml(self):
        import coremltools as ct

        native_model = self._model.predictor.model.backend.model
        if native_model.compute_unit != ct.ComputeUnit.CPU_AND_NE:
            raise BackendUnavailable("CoreML pose initialization fell back to CPU; use the explicit MPS pose option")

    def detect(self, image_path: str) -> list[PersonDetection]:
        image = self._cache.load(image_path)  # BGR; ultralytics accepts arrays directly
        results = self._model(image, conf=self._min_confidence, device=self._device, verbose=False)
        if self._require_coreml_ne:
            self._verify_coreml()
        detections: list[PersonDetection] = []
        for result in results:
            keypoints = result.keypoints
            xy = keypoints.xy.tolist() if keypoints is not None else []
            conf = keypoints.conf.tolist() if keypoints is not None and keypoints.conf is not None else []
            for i, xyxy in enumerate(result.boxes.xyxy.tolist()):
                x1, y1, x2, y2 = (int(round(v)) for v in xyxy)
                points = xy[i] if i < len(xy) else []
                scores = conf[i] if i < len(conf) else []

                def kp(index: int, points=points, scores=scores) -> Keypoint | None:
                    if index >= len(points) or index >= len(scores):
                        return None
                    if scores[index] < self._min_kp:
                        return None
                    x, y = points[index]
                    return Keypoint(float(x), float(y))

                head = kp(_NOSE) or _midpoint(kp(_L_EYE), kp(_R_EYE)) or _midpoint(kp(_L_EAR), kp(_R_EAR))
                detections.append(
                    PersonDetection(
                        box=BoundingBox(x1, y1, x2, y2),
                        head=head,
                        left_shoulder=kp(_L_SHOULDER),
                        right_shoulder=kp(_R_SHOULDER),
                        left_hip=kp(_L_HIP),
                        right_hip=kp(_R_HIP),
                    )
                )
        return detections


def _midpoint(a: Keypoint | None, b: Keypoint | None) -> Keypoint | None:
    if a is not None and b is not None:
        return Keypoint((a.x + b.x) / 2, (a.y + b.y) / 2)
    return a or b
