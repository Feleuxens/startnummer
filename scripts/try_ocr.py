"""Detect persons, OCR (bibs + name hints), attribute bibs, and save an annotated image.

Usage:
    uv run --no-sync python scripts/try_ocr.py path/to/photo.jpg [--engine rapid|paddle]

--engine paddle uses PaddleOCR on PaddlePaddle; the default uses RapidOCR on ONNX Runtime.

Writes <name>.annotated<ext> beside the original. Labels are drawn with PIL + a
TrueType font so umlauts render correctly (OpenCV's Hershey fonts are ASCII-only).
    blue=person   green=bib candidate   orange=name hint
"""

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from startnummer.adapters.cache import DEFAULT_CACHE
from startnummer.adapters.detect.yolo import YoloDetector
from startnummer.core.association import group_subjects

PERSON = (0, 0, 255)  # RGB
BIB = (0, 180, 0)
TEXT = (255, 140, 0)

_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Aria.ttf",  # for macOS support
]


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("--engine", choices=["paddle", "rapid"], default="rapid")
    args = parser.parse_args()
    path = args.image
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
    if args.engine == "paddle":
        from startnummer.adapters.ocr.paddle import PaddleOcrReader

        reader = PaddleOcrReader()
    else:
        from startnummer.adapters.ocr.rapid import RapidOcrReader

        reader = RapidOcrReader()

    for path in pictures:
        persons = detector.detect(str(path))
        result = reader.read(str(path))
        print(f"{len(persons)} persons, {len(result.bibs)} bibs, {len(result.texts)} name hints")
        for b in result.bibs:
            print(f"  bib  '{b.value}'  conf={b.confidence:.2f}  box={b.box}")
        for t in result.texts:
            print(f"  text '{t.value}'  conf={t.confidence:.2f}  box={t.box}")

        groups = group_subjects(persons, result.bibs, [])
        print(f"\n{len(groups)} subject(s) after attribution:")
        for i, g in enumerate(groups):
            anchored = "orphan" if g.person_box is None else "person"
            print(f"  subject {i} ({anchored}): bibs={[c.value for c in g.bibs]}")

        # Cached BGR array -> RGB copy: same pixels the models saw (cv2 applies EXIF
        # orientation; Image.open does not), and no extra decode.
        image = Image.fromarray(DEFAULT_CACHE.load(str(path))[:, :, ::-1].copy())
        draw = ImageDraw.Draw(image)
        h = image.size[1]
        width = max(2, h // 500)
        font = _font(max(16, h // 55))

        def _box(b, color, label, *, draw=draw, width=width, font=font):
            draw.rectangle([b.x1, b.y1, b.x2, b.y2], outline=color, width=width)
            draw.text((b.x1, max(b.y1 - font.size - 2, 0)), label, fill=color, font=font)

        for i, p in enumerate(persons):
            _box(p.box, PERSON, f"person {i}")
        for b in result.bibs:
            _box(b.box, BIB, f"{b.value} {b.confidence:.2f}")
        for t in result.texts:
            _box(t.box, TEXT, t.value)

        out = path.with_name(f"{path.stem}.annotated{path.suffix}")
        image.save(out)
        print(f"\nwrote {out}")
    print(DEFAULT_CACHE.stats())


if __name__ == "__main__":
    main()
