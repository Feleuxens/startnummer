"""Full-frame face detection and ArcFace embeddings using InsightFace.

The default buffalo_l model downloads on first use. Only detection and
recognition modules are loaded. The 80-pixel minimum face height filters small
background faces; detection dimensions must be divisible by 32.

Uses CUDA when available, with CPU as a fallback.
"""

from startnummer.adapters.cache import DEFAULT_CACHE, ImageCache
from startnummer.adapters.runtime import BackendUnavailable
from startnummer.core.types import BoundingBox, FaceDetection

try:
    import cv2  # noqa: F401 -- check the face runtime's required dependencies
    import onnxruntime
    from insightface.app import FaceAnalysis
except ImportError as exc:  # pragma: no cover - import guard for the face extra
    raise ImportError("InsightFaceEngine requires a device extra: cpu, intel, nvidia, or apple") from exc

_PREFERRED_PROVIDERS = ["CUDAExecutionProvider", "CPUExecutionProvider"]
_DUPLICATE_IOU = 0.5  # two detections overlapping this much are the same face


def _iou(a, b) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(ix2 - ix1, 0) * max(iy2 - iy1, 0)
    if inter == 0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter)


def _available_providers() -> list[str]:
    available = set(onnxruntime.get_available_providers())
    return [p for p in _PREFERRED_PROVIDERS if p in available]


class InsightFaceEngine:
    def __init__(
        self,
        model: str = "buffalo_l",
        min_confidence: float = 0.7,
        det_size: tuple[int, int] = (960, 960),  # both dimensions must be divisible by 32
        min_face_height: int = 80,  # px in the original image; 0 disables the gate
        cache: ImageCache | None = None,
        providers: list | None = None,
        session_factory=None,
        root: str | None = None,
    ) -> None:
        self._app = FaceAnalysis(
            name=model,
            allowed_modules=["detection", "recognition"],
            providers=providers if providers is not None else _available_providers(),
            **({"root": root} if root else {}),
        )
        if session_factory is not None:
            # InsightFace's loader drops SessionOptions, so replace sessions before preparation.
            for model in self._app.models.values():
                model.session = session_factory(model.model_file)
        self._app.prepare(ctx_id=0, det_size=det_size)
        if providers:
            expected = providers[0][0] if isinstance(providers[0], tuple) else providers[0]
            if expected != "CPUExecutionProvider" and any(
                expected not in model.session.get_providers() for model in self._app.models.values()
            ):
                raise BackendUnavailable("The requested face inference provider failed to initialize")
        self._min_confidence = min_confidence
        self._min_face_height = min_face_height
        self._cache = cache or DEFAULT_CACHE

    def detect(self, image_path: str) -> list[FaceDetection]:
        image = self._cache.load(image_path)  # BGR (as insightface expects), read-only

        # Highest-score first, then IoU-dedupe: the detector occasionally emits
        # two near-identical boxes for one face; keep only the stronger.
        faces = sorted(self._app.get(image), key=lambda f: float(f.det_score), reverse=True)
        kept_boxes: list[tuple[int, int, int, int]] = []
        detections: list[FaceDetection] = []
        for face in faces:
            if float(face.det_score) < self._min_confidence:
                continue
            x1, y1, x2, y2 = (int(round(float(v))) for v in face.bbox)
            if (y2 - y1) < self._min_face_height:
                continue  # background face: too small to embed reliably
            box = (x1, y1, x2, y2)
            if any(_iou(box, kept) >= _DUPLICATE_IOU for kept in kept_boxes):
                continue  # duplicate detection of an already-kept face
            kept_boxes.append(box)
            detections.append(
                FaceDetection(
                    box=BoundingBox(x1, y1, x2, y2),
                    embedding=[float(v) for v in face.normed_embedding],
                )
            )
        return detections
