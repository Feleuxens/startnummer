"""PaddleOCR reader. OCRs the full frame once and classifies each token.

read() returns an OcrResult: digit tokens become bib candidates, alphabetic tokens
become text hints (names) for the roster matcher to fuzzy-match. Boxes are in
full-image coordinates; core.association.group_subjects attributes them to persons.

Document preprocessing (orientation-classify + unwarping) is disabled: on an action
photo it perspective-warps the frame and returns boxes in the warped space, which
misplaces every box. rec_polys is index-aligned with rec_texts; dt_polys is not, so
it is never used as a fallback.
"""

import re

from startnummer.core.types import BibRead, BoundingBox, OcrResult, TextRead

try:
    import cv2
    import numpy as np
    import paddle
    from paddleocr import PaddleOCR
except ImportError as exc:  # pragma: no cover - import guard for the ocr extra
    raise ImportError(
        "PaddleOcrReader requires the 'ocr' extra (paddleocr) + opencv"
    ) from exc

_BIB = re.compile(r"^\d{1,5}$")  # digits only; widen if your bibs carry a letter prefix
_TEXT = re.compile(
    r"[A-Za-zÄÖÜäöüß]{2,}"
)  # >=2 letters (umlauts included) to count as a name hint


def _resolve_device(device: str) -> str:
    if device != "auto":
        return device
    return "gpu" if paddle.device.is_compiled_with_cuda() else "cpu"


def _poly_to_box(poly, scale: float = 1) -> BoundingBox:
    pts = np.array(poly, dtype=float).reshape(-1, 2)
    x1, y1 = pts.min(axis=0)
    x2, y2 = pts.max(axis=0)
    return BoundingBox(
        int(x1 / scale), int(y1 / scale), int(x2 / scale), int(y2 / scale)
    )


class PaddleOcrReader:
    def __init__(
        self,
        lang: str = "en",
        bib_pattern: re.Pattern[str] = _BIB,
        text_pattern: re.Pattern[str] = _TEXT,
        detection_model: str = "PP-OCRv5_mobile_det",
        recognition_model: str = "PP-OCRv5_mobile_rec",
        max_side: int | None = 2500,  # in-memory downscale cap; None = full resolution
        device: str = "auto",  # "auto" | "cpu" | "gpu"
        cpu_threads: int | None = None,  # None = library default
        enable_mkldnn: bool = True,  # False works around the PaddlePaddle 3.3.x CPU regression
    ) -> None:
        # enable_mkldnn=False works around a PaddlePaddle 3.3.x CPU regression;
        # unnecessary on 3.2.x. Models download on first use (needs network).
        options: dict = {}
        if cpu_threads is not None:
            options["cpu_threads"] = cpu_threads
        self._ocr = PaddleOCR(
            lang=lang,
            text_detection_model_name=detection_model,
            text_recognition_model_name=recognition_model,
            device=_resolve_device(device),
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            enable_mkldnn=enable_mkldnn,
            **options,
        )

        self._bib = bib_pattern
        self._text = text_pattern
        self._max_side = max_side

    def read(self, image_path: str) -> OcrResult:
        image = cv2.imread(image_path)  # BGR
        if image is None:
            raise FileNotFoundError(image_path)
        image = cv2.imread(image_path)
        scale = 1.0
        if self._max_side and max(image.shape[:2]) > self._max_side:
            scale = self._max_side / max(image.shape[:2])
            image = cv2.resize(
                image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
            )

        result = self._ocr.predict(image)
        if not result:
            return OcrResult(bibs=[], texts=[])
        res = result[0]
        texts = res.get("rec_texts", [])
        scores = res.get("rec_scores", [])
        polys = res.get("rec_polys", [])  # aligned with rec_texts; dt_polys is not

        bibs: list[BibRead] = []
        hints: list[TextRead] = []
        for text, score, poly in zip(texts, scores, polys):
            value = text.strip()
            box = _poly_to_box(poly, scale=scale)
            conf = float(score)
            if self._bib.match(value) and conf > 0.5:
                bibs.append(BibRead(box=box, value=value, confidence=conf))
            elif self._text.search(value) and conf > 0.5:
                hints.append(TextRead(box=box, value=value, confidence=conf))
        return OcrResult(bibs=bibs, texts=hints)
