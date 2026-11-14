"""Full-frame bib and name OCR using RapidOCR on ONNX Runtime.

Images can be downscaled for inference; returned boxes use original image
coordinates. Defaults select English PP-OCRv6 small models. Numeric tokens
become bib candidates and alphabetic tokens become name hints.
"""

import re

from startnummer.adapters.cache import DEFAULT_CACHE, ImageCache
from startnummer.core.types import BibRead, BoundingBox, OcrResult, TextRead

try:
    import cv2
    import numpy as np
    from rapidocr import EngineType, LangDet, LangRec, ModelType, OCRVersion, RapidOCR
except ImportError as exc:
    raise ImportError("RapidOcrReader requires rapidocr + opencv") from exc

_BIB = re.compile(r"^\d{1,5}$")  # numeric bibs, one to five digits
_TEXT = re.compile(r"[A-Za-zÄÖÜäöüß]{2,}")  # >=2 letters (umlauts included) = name hint


def _poly_to_box(poly, scale: float) -> BoundingBox:
    pts = np.array(poly, dtype=float).reshape(-1, 2) / scale
    x1, y1 = pts.min(axis=0)
    x2, y2 = pts.max(axis=0)
    return BoundingBox(int(x1), int(y1), int(x2), int(y2))


def _parse(result) -> list[tuple[str, float, object]]:
    if result is None:
        return []
    if hasattr(result, "txts"):  # v3 RapidOCROutput
        txts = result.txts or ()
        scores = result.scores or ()
        boxes = result.boxes if result.boxes is not None else ()
        return list(zip(txts, (float(s) for s in scores), boxes, strict=True))
    if isinstance(result, (list, tuple)):  # legacy: [[poly, (text, score)], ...]
        triples = []
        for entry in result:
            poly, payload = entry[0], entry[1]
            text, score = payload[0], float(payload[1])
            triples.append((text, score, poly))
        return triples
    raise TypeError(
        "Unrecognized RapidOCR result shape; adjust _parse. "
        f"type={type(result)!r} attrs={[a for a in dir(result) if not a.startswith('_')]}"
    )


class RapidOcrReader:
    def __init__(
        self,
        bib_pattern: re.Pattern[str] = _BIB,
        text_pattern: re.Pattern[str] = _TEXT,
        max_side: int | None = 2500,  # maximum image side in pixels; None disables resizing
        text_score: float = 0.5,  # OCR-level floor: recognitions below this are dropped
        params: dict | None = None,  # overrides merged over the defaults below
        cache: ImageCache | None = None,
    ) -> None:
        defaults: dict = {
            "Det.engine_type": EngineType.ONNXRUNTIME,
            "Rec.engine_type": EngineType.ONNXRUNTIME,
            "Det.lang_type": LangDet.EN,
            "Rec.lang_type": LangRec.EN,
            "Det.ocr_version": OCRVersion.PPOCRV6,
            "Rec.ocr_version": OCRVersion.PPOCRV6,
            "Det.model_type": ModelType.SMALL,
            "Rec.model_type": ModelType.SMALL,
            "Global.text_score": text_score,
            "Global.max_side_len": max_side if max_side is not None else 100_000,
        }
        self._ocr = RapidOCR(params={**defaults, **(params or {})})
        self._bib = bib_pattern
        self._text = text_pattern
        self._max_side = max_side
        self._cache = cache or DEFAULT_CACHE

    def read(self, image_path: str) -> OcrResult:
        image = self._cache.load(image_path)  # BGR, read-only; resize below copies

        scale = 1.0
        longest = max(image.shape[:2])
        if self._max_side is not None and longest > self._max_side:
            scale = self._max_side / longest
            image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

        bibs: list[BibRead] = []
        hints: list[TextRead] = []
        for text, score, poly in _parse(self._ocr(image, use_cls=False)):
            value = text.strip()
            box = _poly_to_box(poly, scale)
            if self._bib.match(value):
                bibs.append(BibRead(box=box, value=value, confidence=score))
            elif self._text.search(value):
                hints.append(TextRead(box=box, value=value, confidence=score))
        return OcrResult(bibs=bibs, texts=hints)
