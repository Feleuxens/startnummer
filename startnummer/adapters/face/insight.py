"""InsightFace face engine. Detects on the full frame, returns ArcFace embeddings.

buffalo_l downloads (~300 MB) on first use. Only detection + recognition modules
are loaded; age/gender estimation is deliberately excluded.

Defaults are measured on a real 93-photo album, not guessed:
- det_size (960, 960): found more of the relevant faces than 640 without the
  extra background noise 1280 pulled in. Dimensions must be divisible by 32
  (SCRFD constraint) — (1000, 1000) fails outright.
- min_confidence 0.7: clear quality improvement over 0.5; higher starts losing
  real faces.
- min_face_height 80 px (original-image scale): drops small faces. Size is the
  blur proxy here — background people are small AND defocused, and their noisy
  embeddings are what poison identity clusters. Raise/lower to trade background
  coverage against cluster quality; a true sharpness gate (variance of
  Laplacian) is the follow-up only if large-but-blurred faces cause bad matches.

Uses CUDA when onnxruntime-gpu is installed (provider list filtered against what
the installed runtime offers, so plain onnxruntime runs CPU without warnings).
"""

from startnummer.adapters.cache import DEFAULT_CACHE, ImageCache
from startnummer.core.types import BoundingBox, FaceDetection

try:
    import cv2
    import onnxruntime
    from insightface.app import FaceAnalysis
except ImportError as exc:  # pragma: no cover - import guard for the face extra
    raise ImportError("InsightFaceEngine requires the 'face' extra (insightface, onnxruntime)") from exc

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
    ) -> None:
        self._app = FaceAnalysis(
            name=model,
            allowed_modules=["detection", "recognition"],
            providers=_available_providers(),
        )
        self._app.prepare(ctx_id=0, det_size=det_size)
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