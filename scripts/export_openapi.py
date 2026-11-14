"""Generate public HTTP contracts without credentials, database access, or ML."""

import json
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from startnummer.app.api import create_app  # noqa: E402
from startnummer.app.settings import Settings  # noqa: E402

settings = Settings(
    database_url="sqlite://",
    blob_root=Path("/tmp/startnummer-schema"),
    password="schema-generation-only",
    session_secret="s" * 32,
    worker_secret="w" * 32,
    owner_id=UUID(int=1),
)
destination = Path(__file__).resolve().parents[1] / "startnummer-web" / "openapi.json"
destination.write_text(json.dumps(create_app(settings).openapi(), indent=2) + "\n")
print(f"Generated {destination.name}")
