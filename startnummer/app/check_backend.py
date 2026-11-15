"""Exercise model loading and inference without an account, database, or private photos."""

from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from PIL import Image

from startnummer.app.inference import ProcessAnalyzer
from startnummer.core.batch import WorkflowError
from startnummer.core.enums import Sport
from startnummer.core.interfaces import EntryList
from startnummer.core.record import Album


def check_backend(backend, cache_mb=512, faces_enabled=True):
    with TemporaryDirectory(prefix="startnummer-backend-check-") as directory:
        path = Path(directory) / "synthetic.jpg"
        Image.new("RGB", (320, 480), "gray").save(path)
        runner = ProcessAnalyzer(cache_mb, faces_enabled, backend=backend)
        result = runner(
            Album(owner_id=uuid4(), name="Synthetic backend check", sport=Sport.ATHLETICS),
            [str(path)],
            entry_list=EntryList(athletes=[]),
            on_progress=lambda *args: None,
        )
        if len(result.records) != 1 or result.records[0].failure_reason:
            raise WorkflowError("Backend check failed during synthetic image analysis")
    print(f"Backend check passed ({backend}); inference process exited. This does not measure recognition accuracy.")
