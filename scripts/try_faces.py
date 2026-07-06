"""Visualize face matching across an album folder.

Runs detection + OCR + faces over every image, clusters the faces across photos,
and writes an annotated copy per image: person boxes in blue, and each face box
colored by its cluster, labeled "F<cluster>" plus the cluster's donor bib when
one photo in the cluster read it confidently. Same color + same label across two
photos = the pipeline considers it the same person.

Usage:
    PYTHONPATH=src python scripts/try_faces.py <folder>
Writes <name>.faces<ext> beside each image.
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from startnummer.adapters.cache import DEFAULT_CACHE
from startnummer.adapters.detect.yolo import YoloDetector
from startnummer.adapters.face.insight import InsightFaceEngine
from startnummer.adapters.ocr.rapid import RapidOcrReader
from startnummer.core.association import group_subjects
from startnummer.core.identity import FaceItem, cluster_faces
from startnummer.core.pipeline import face_cannot_links, strong_bib

EXTENSIONS = {".jpg", ".jpeg", ".png"}
PERSON = (0, 0, 255)
# Cluster colors cycle; two faces sharing a color+label were matched.
CLUSTER_COLORS = [
    (230, 25, 75), (60, 180, 75), (255, 140, 0), (145, 30, 180),
    (0, 180, 180), (240, 50, 230), (170, 110, 40), (128, 128, 0),
]

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
    if len(sys.argv) < 2:
        print("usage: python scripts/try_faces.py <folder>")
        raise SystemExit(1)
    folder = Path(sys.argv[1])
    paths = sorted(
        p for p in folder.iterdir()
        if p.suffix.lower() in EXTENSIONS and "annotated" not in p.name and "faces" not in p.name
    )
    if not paths:
        print(f"no images in {folder}")
        raise SystemExit(1)

    detector = YoloDetector()
    ocr = RapidOcrReader() # PaddleOcrReader()  # enable_mkldnn=False on PaddlePaddle 3.3.x
    faces = InsightFaceEngine()

    # Pass 1: analyze every photo, collect grouped subjects.
    grouped_by_photo = []
    persons_by_photo = []
    for path in paths:
        persons = detector.detect(str(path))
        result = ocr.read(str(path))
        detections = faces.detect(str(path))
        grouped_by_photo.append(group_subjects(persons, result.bibs, detections))
        persons_by_photo.append(persons)
        print(f"{path.name}: {len(persons)} persons, {len(result.bibs)} bibs, {len(detections)} faces")

    # Pass 2: cluster with the same constraints the pipeline applies.
    items = [
        FaceItem(key=(pi, si), embeddings=[f.embedding for f in g.faces])
        for pi, grouped in enumerate(grouped_by_photo)
        for si, g in enumerate(grouped)
        if g.faces
    ]
    def _pick(key):
        subject = grouped_by_photo[key[0]][key[1]]
        return strong_bib(subject.bibs, subject.bib_boxes)

    strong_bibs = {
        item.key: pick.bib.value for item in items if (pick := _pick(item.key)) is not None
    }
    contested_keys = {
        item.key for item in items if (pick := _pick(item.key)) is not None and pick.contested
    }
    clusters = cluster_faces(items, cannot_link=face_cannot_links(items, strong_bibs))
    cluster_of = {key: ci for ci, cluster in enumerate(clusters) for key in cluster}

    # Donor bib per cluster: the single confident value, if the cluster agrees.
    donor_bib: dict[int, str] = {}
    for ci, cluster in enumerate(clusters):
        values = {strong_bibs[key] for key in cluster if key in strong_bibs}
        if len(values) == 1:
            value = values.pop()
            contested = any(key in contested_keys for key in cluster)
            donor_bib[ci] = f"{value}?" if contested else value  # "?" = tiebroken, review

    multi = sum(1 for c in clusters if len(c) > 1)
    print(f"\n{len(clusters)} face cluster(s), {multi} spanning multiple subjects")

    # Pass 3: draw.
    for pi, path in enumerate(paths):
        # Cached BGR -> RGB copy (EXIF-consistent with the models; see try_ocr)
        image = Image.fromarray(DEFAULT_CACHE.load(str(path))[:, :, ::-1].copy())
        draw = ImageDraw.Draw(image)
        height = image.size[1]
        width = max(2, height // 500)
        font = _font(max(16, height // 55))

        for person in persons_by_photo[pi]:
            box = person.box
            draw.rectangle([box.x1, box.y1, box.x2, box.y2], outline=PERSON, width=width)

        for si, g in enumerate(grouped_by_photo[pi]):
            ci = cluster_of.get((pi, si))
            if ci is None:
                continue
            color = CLUSTER_COLORS[ci % len(CLUSTER_COLORS)]
            label = f"F{ci}" + (f" #{donor_bib[ci]}" if ci in donor_bib else "")
            for face in g.faces:
                b = face.box
                draw.rectangle([b.x1, b.y1, b.x2, b.y2], outline=color, width=width)
                draw.text((b.x1, max(b.y1 - font.size - 2, 0)), label, fill=color, font=font)

        out = path.with_name(f"{path.stem}.faces{path.suffix}")
        image.save(out)
        print(f"wrote {out}")
    print(DEFAULT_CACHE.stats())


if __name__ == "__main__":
    main()