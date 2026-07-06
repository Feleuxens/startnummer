"""Run the full analysis pipeline on a folder of photos (one album).

Usage:
    PYTHONPATH=src python scripts/try_pipeline.py <folder> [--no-faces] [--cues]

--no-faces skips InsightFace (first run downloads ~300 MB of models).
Writes <folder>/analysis.json with the serialized records.
"""

import argparse
import json
import uuid
from pathlib import Path

from startnummer.adapters.cache import DEFAULT_CACHE
from startnummer.adapters.detect.yolo import YoloDetector
from startnummer.adapters.ocr.paddle import PaddleOcrReader
from startnummer.core.enums import Sport
from startnummer.core.pipeline import analyze_album
from startnummer.core.record import Album

EXTENSIONS = {".jpg", ".jpeg", ".png"}


class _LoggingCues:
    """Prints what the cue detector finds; silence = it found nothing."""

    def __init__(self, inner):
        self._inner = inner

    def detect(self, image_path):
        labels = self._inner.detect(image_path)
        if labels:
            print(f"  cues {Path(image_path).name}: {labels}")
        return labels


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("--no-faces", action="store_true")
    parser.add_argument("--cache-mb", type=int, default=4096, help="decode-cache RAM budget")
    args = parser.parse_args()

    paths = sorted(
        str(p)
        for p in args.folder.iterdir()
        if p.suffix.lower() in EXTENSIONS and ".annotated" not in p.name
    )
    if not paths:
        print(f"no images in {args.folder}")
        raise SystemExit(1)

    faces = None
    if not args.no_faces:
        from startnummer.adapters.face.insight import InsightFaceEngine
        faces = InsightFaceEngine()

    DEFAULT_CACHE.set_max_mb_bytes(args.cache_mb)

    album = Album(owner_id=uuid.uuid4(), name=args.folder.name, sport=Sport.ATHLETICS)
    records = analyze_album(
        album, paths,
        detector=YoloDetector(),
        ocr=PaddleOcrReader(),  # enable_mkldnn=False on PaddlePaddle 3.3.x
        faces=faces,
    )

    for record in records:
        name = Path(record.source_path or "?").name
        discipline = record.event.discipline.value if record.event.discipline else "-"
        print(f"\n{name}  [{record.status}]  discipline={discipline}")
        for i, subject in enumerate(record.subjects):
            bibs = [f"{b.value}@{b.confidence:.2f}({b.source})" for b in subject.bibs]
            print(f"  subject {i}: {bibs or 'no bib'}")

    out = args.folder / "analysis.json"
    out.write_text(
        json.dumps(
            [json.loads(r.model_dump_json()) for r in records],
            indent=2,
            ensure_ascii=False,
        )
    )
    print(f"\nwrote {out}")
    print(DEFAULT_CACHE.stats())


if __name__ == "__main__":
    main()
