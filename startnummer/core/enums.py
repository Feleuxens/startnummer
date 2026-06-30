"""Cross-sport vocabularies. Sport-specific disciplines live in core.sports.*"""

from enum import StrEnum


class Sport(StrEnum):
    ATHLETICS = "athletics"
    HANDBALL = "handball"


class Lang(StrEnum):
    EN = "en"
    DE = "de"


class Source(StrEnum):
    DETECTOR = "detector"
    OCR = "ocr"
    FACE_MATCH = "face_match"
    VLM = "vlm"
    ROSTER = "roster"
    RULE = "rule"
    MANUAL = "manual"


class Status(StrEnum):
    PENDING = "pending"
    AUTO = "auto"
    NEEDS_REVIEW = "needs_review"
    CONFIRMED = "confirmed"
    FAILED = "failed"
