"""Versioned backups of one configured account's records and referenced photos."""

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from uuid import UUID
from zipfile import ZIP_STORED, BadZipFile, ZipFile

from sqlalchemy import DateTime, Uuid, func, inspect, select

from startnummer.adapters.blob.filesystem import FilesystemBlobStore
from startnummer.adapters.db.schema import Base
from startnummer.adapters.db.store import Store
from startnummer.core.batch import Conflict, WorkflowError, now

CHUNK = 1024 * 1024
FORMAT = 2
BACKUP_TABLES = tuple(table for table in Base.metadata.sorted_tables if table.name != "sn_integrations")


def reject_face_data(value):
    if isinstance(value, dict):
        if {
            "embedding",
            "embeddings",
            "box",
            "face_boxes",
            "match_groups",
            "face_session_id",
            "undo_id",
            "group",
        } & value.keys():
            raise WorkflowError("Temporary face records cannot be included in a backup")
        for item in value.values():
            reject_face_data(item)
    elif isinstance(value, list):
        for item in value:
            reject_face_data(item)


def encode(value):
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError("Unsupported backup value")


def digest_file(handle):
    digest, size = hashlib.sha256(), 0
    while chunk := handle.read(CHUNK):
        digest.update(chunk)
        size += len(chunk)
    return {"size": size, "sha256": digest.hexdigest()}


def backup(store, settings, destination: Path):
    destination = destination.resolve()
    if destination.exists():
        raise WorkflowError("Backup destination already exists; choose a new filename")
    if destination.is_relative_to(settings.blob_root.resolve()):
        raise WorkflowError("Store backups outside the photo storage directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".startnummer-backup-", dir=destination.parent)
    staging = Path(temporary)
    try:
        with (
            os.fdopen(descriptor, "w+b") as output,
            ZipFile(output, "w", compression=ZIP_STORED, allowZip64=True) as archive,
        ):
            with store.transaction(settings.owner_id) as session:
                tables = {}
                for table in BACKUP_TABLES:
                    rows = session.execute(select(table).where(table.c.owner_id == settings.owner_id)).mappings()
                    tables[table.name] = [dict(row) for row in rows]
                reject_face_data(tables)
                document = json.dumps({"tables": tables}, default=encode, separators=(",", ":")).encode()
                archive.writestr("database.json", document)
                files = {"database.json": {"size": len(document), "sha256": hashlib.sha256(document).hexdigest()}}
                blobs = FilesystemBlobStore(settings.blob_root)
                photos = tables["sn_photos"]
                for photo in photos:
                    name = f"photos/{photo['owner_id']}/{photo['blob_key']}"
                    if name in files:
                        if (
                            files[name]["size"] != photo["document"]["size"]
                            or "sha256:" + files[name]["sha256"] != photo["content_hash"]
                        ):
                            raise WorkflowError("Shared photo references have inconsistent metadata")
                        continue
                    path = blobs._path(photo["owner_id"], photo["blob_key"])
                    # Only referenced, complete blobs are included, never staging files.
                    with path.open("rb") as source, archive.open(name, "w", force_zip64=True) as target:
                        digest, size = hashlib.sha256(), 0
                        while chunk := source.read(CHUNK):
                            target.write(chunk)
                            digest.update(chunk)
                            size += len(chunk)
                    if size != photo["document"]["size"] or "sha256:" + digest.hexdigest() != photo["content_hash"]:
                        raise WorkflowError("A stored photo failed integrity verification; no backup was created")
                    files[name] = {"size": size, "sha256": digest.hexdigest()}
                manifest = {
                    "format": FORMAT,
                    "created_at": now().isoformat(),
                    "owner_id": str(settings.owner_id),
                    "batches": len(tables["sn_batches"]),
                    "photos": len(photos),
                    "files": files,
                }
                archive.writestr("manifest.json", json.dumps(manifest))
        with staging.open("rb") as handle:
            os.fsync(handle.fileno())
        # link refuses an existing destination, including one created during backup.
        os.link(staging, destination)
        return {key: value for key, value in manifest.items() if key != "files"}
    finally:
        staging.unlink(missing_ok=True)


def inspect_backup(source: Path):
    try:
        with ZipFile(source) as archive:
            return validate_archive(archive)[0]
    except (BadZipFile, KeyError, ValueError, TypeError, OSError) as exc:
        raise WorkflowError("Backup is invalid, incomplete, or unreadable") from exc


def validate_archive(archive):
    names = archive.namelist()
    if len(names) != len(set(names)) or archive.getinfo("manifest.json").file_size > 16 * CHUNK:
        raise WorkflowError("Invalid backup manifest")
    manifest = json.loads(archive.read("manifest.json"))
    if manifest["format"] not in {1, FORMAT}:
        raise WorkflowError("Unsupported backup format")
    owner = UUID(manifest["owner_id"])
    files = manifest["files"]
    if set(names) != {"manifest.json", *files} or "database.json" not in files:
        raise WorkflowError("Backup entries do not match the manifest")
    for name, expected in files.items():
        if name != "database.json":
            parts = PurePosixPath(name).parts
            if len(parts) < 3 or parts[:2] != ("photos", str(owner)):
                raise WorkflowError("Invalid photo path in backup")
            key = "/".join(parts[2:])
            FilesystemBlobStore(Path("/tmp/startnummer-backup-validation"))._path(owner, key)
        if archive.getinfo(name).file_size != expected["size"]:
            raise WorkflowError("Backup entry size does not match its manifest")
        with archive.open(name) as handle:
            if digest_file(handle) != expected:
                raise WorkflowError("Backup checksum verification failed")
    if files["database.json"]["size"] > 512 * CHUNK:
        raise WorkflowError("Backup metadata exceeds the supported size")
    document = json.loads(archive.read("database.json"))
    reject_face_data(document)
    tables = document["tables"]
    if manifest["format"] == 1:
        tables.setdefault("sn_gallery_bindings", [])
    if set(tables) != {table.name for table in BACKUP_TABLES}:
        raise WorkflowError("Backup schema is incompatible with this version of Startnummer")
    if manifest["batches"] != len(tables["sn_batches"]) or manifest["photos"] != len(tables["sn_photos"]):
        raise WorkflowError("Backup counts do not match its records")
    references = {"database.json"}
    for table in BACKUP_TABLES:
        for row in tables[table.name]:
            if set(row) != set(table.c.keys()) or UUID(row["owner_id"]) != owner:
                raise WorkflowError("Backup records have invalid columns or ownership")
    for row in tables["sn_settings"]:
        if set(row["document"]) != {"max_file_bytes", "max_batch_bytes", "session_ttl"}:
            raise WorkflowError("Backup contains unsupported administrator settings")
    for photo in tables["sn_photos"]:
        name = f"photos/{photo['owner_id']}/{photo['blob_key']}"
        expected = files.get(name)
        if expected is None or photo["document"]["size"] != expected["size"]:
            raise WorkflowError("A photo reference is missing or inconsistent")
        if photo["content_hash"] != "sha256:" + expected["sha256"]:
            raise WorkflowError("A photo reference has an inconsistent content hash")
        references.add(name)
    if references != set(files):
        raise WorkflowError("Backup contains unreferenced photo bytes")
    summary = {key: value for key, value in manifest.items() if key != "files"}
    tables["sn_integrations"] = []
    return summary, tables, files


def require_empty(engine, blob_root):
    known = set(inspect(engine).get_table_names())
    if known - {*Base.metadata.tables, "alembic_version"}:
        raise Conflict("Restore requires a dedicated, empty Startnummer database")
    with engine.connect() as connection:
        for table in Base.metadata.sorted_tables:
            if table.name in known and connection.scalar(select(func.count()).select_from(table)):
                raise Conflict("Restore will not overwrite existing database records")
    if blob_root.exists() and (not blob_root.is_dir() or any(blob_root.iterdir())):
        raise Conflict("Restore requires an empty photo storage directory")


def restore(engine, settings, source: Path, *, migrate):
    root = settings.blob_root.absolute()
    if root.is_symlink():
        raise Conflict("Restore destination must not be a symbolic link")
    try:
        with ZipFile(source) as archive:
            summary, tables, files = validate_archive(archive)
            if UUID(summary["owner_id"]) != settings.owner_id:
                raise Conflict("Backup belongs to another configured account; keep the original username/owner ID")
            require_empty(engine, root)
            root.parent.mkdir(parents=True, exist_ok=True)
            stage = Path(tempfile.mkdtemp(prefix=".startnummer-restore-", dir=root.parent))
            try:
                blobs = FilesystemBlobStore(stage)
                for name in files:
                    if name == "database.json":
                        continue
                    key = "/".join(PurePosixPath(name).parts[2:])
                    target = blobs._path(settings.owner_id, key)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(name) as original, target.open("xb") as output:
                        os.chmod(target, 0o600)
                        shutil.copyfileobj(original, output, CHUNK)
                        output.flush()
                        os.fsync(output.fileno())
                migrate(engine)
                with Store(engine).transaction(settings.owner_id) as session:
                    require_empty(engine, root)
                    for table in Base.metadata.sorted_tables:
                        rows = []
                        for original in tables[table.name]:
                            row = dict(original)
                            for column in table.c:
                                if row[column.name] is not None and isinstance(column.type, Uuid):
                                    row[column.name] = UUID(row[column.name])
                                elif row[column.name] is not None and isinstance(column.type, DateTime):
                                    row[column.name] = datetime.fromisoformat(row[column.name])
                            if table.name == "sn_jobs" and row["state"] in {"running", "queued"}:
                                row.update(
                                    state="cancelled",
                                    phase="cancelled",
                                    lease_token=None,
                                    lease_until=None,
                                    error="Restored from backup; explicitly queue analysis to run it again",
                                )
                            rows.append(row)
                        if rows:
                            session.execute(table.insert(), rows)
                    if root.exists():
                        root.rmdir()
                    # Keep these bytes if the commit result is uncertain; the
                    # database may already contain references to them.
                    os.replace(stage, root)
                return summary
            finally:
                if stage.exists():
                    shutil.rmtree(stage)
    except (BadZipFile, KeyError, ValueError, TypeError) as exc:
        raise WorkflowError("Backup is invalid or incompatible; restore was not completed") from exc
