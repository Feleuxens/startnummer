"""YOLO person detector (ultralytics). Returns person boxes to crop before OCR.

Uses the pretrained COCO person class rather than a trained bib detector; the
torso/bib region is a sub-crop of these boxes (applied later if needed).
"""

from startnummer.core.types import BoundingBox

try:
    from ultralytics import YOLO
except ImportError as exc:  # pragma: no cover - import guard for the worker extra
    raise ImportError("YoloDetector requires the 'worker' extra (ultralytics)") from exc

_PERSON_CLASS = 0  # COCO 'person'


class YoloDetector:
    def __init__(self, model: str = "yolo11n.pt", min_confidence: float = 0.25) -> None:
        # The weights file auto-downloads on first use (needs network).
        self._model = YOLO(model)
        self._min_confidence = min_confidence

    def detect(self, image_path: str) -> list[BoundingBox]:
        results = self._model(
            image_path, classes=[_PERSON_CLASS], conf=self._min_confidence, verbose=False
        )
        boxes: list[BoundingBox] = []
        for result in results:
            for xyxy in result.boxes.xyxy.tolist():
                x1, y1, x2, y2 = (int(round(v)) for v in xyxy)
                boxes.append(BoundingBox(x1, y1, x2, y2))
        return boxes
