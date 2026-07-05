"""Detect persons, OCR (bibs + name hints), attribute bibs, and save an annotated image.

Usage:
    python scripts/try_ocr.py path/to/photo.jpg

Writes <name>.annotated<ext> beside the original.
    blue=person   green=bib candidate   orange=name hint
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from startnummer.adapters.detect.yolo import YoloDetector
from startnummer.adapters.ocr.paddle import PaddleOcrReader
from startnummer.adapters.ocr.rapid import RapidOcrReader
from startnummer.core.association import group_subjects

PERSON = (0, 0, 255)  # RGB
BIB = (0, 180, 0)
TEXT = (255, 140, 0)

_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python scripts/try_ocr.py (<image>/<folder>)")
        raise SystemExit(1)
    path = Path(sys.argv[1])
    pictures: list[Path] = []
    if path.is_file():
        pictures = [path]
    elif path.is_dir():
        for file in path.iterdir():
            if (
                file.is_file()
                and file.suffix in [".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG"]
                and "annotated" not in file.name
                and "faces" not in file.name
            ):
                pictures.append(file)
    else:
        raise ValueError(f"invalid path: {path}")

    detector = YoloDetector()
    reader = (
        RapidOcrReader()
        # PaddleOcrReader()
    )  # add enable_mkldnn=False if you're on PaddlePaddle 3.3.x

    for path in pictures:
        persons = detector.detect(str(path))
        result = reader.read(str(path))
        print(
            f"{len(persons)} persons, {len(result.bibs)} bibs, {len(result.texts)} name hints"
        )
        for b in result.bibs:
            print(f"  bib  '{b.value}'  conf={b.confidence:.2f}  box={b.box}")
        for t in result.texts:
            print(f"  text '{t.value}'  conf={t.confidence:.2f}  box={t.box}")

        groups = group_subjects(persons, result.bibs, [])
        print(f"\n{len(groups)} subject(s) after attribution:")
        for i, g in enumerate(groups):
            anchored = "orphan" if g.person_box is None else "person"
            print(f"  subject {i} ({anchored}): bibs={[c.value for c in g.bibs]}")

        image = Image.open(path).convert("RGB")
        draw = ImageDraw.Draw(image)
        h = image.size[1]
        width = max(2, h // 500)
        font = _font(max(16, h // 55))

        def _box(b, color, label):
            draw.rectangle(
                [b.x1, b.y1, b.x2, b.y2], outline=color, width=width
            )  # noqa: B023
            draw.text(
                (b.x1, max(b.y1 - font.size - 2, 0)), label, fill=color, font=font
            )  # noqa: B023

        for i, p in enumerate(persons):
            _box(p, PERSON, f"person {i}")
        for b in result.bibs:
            _box(b.box, BIB, f"{b.value} {b.confidence:.2f}")
        for t in result.texts:
            _box(t.box, TEXT, t.value)

        out = path.with_name(f"{path.stem}.annotated{path.suffix}")
        image.save(out)
        print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
