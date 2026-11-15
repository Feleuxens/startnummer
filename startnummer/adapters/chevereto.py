"""Chevereto 4.5.9 album imports and conditional description updates.

URL IDs use the instance's Legacy\\cheveretoID encoding. Imports support only
configured local image storage.
"""

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import quote, unquote, urlparse

import pymysql
from pymysql.cursors import DictCursor

from startnummer.core.batch import DescriptionWrite, Destination, WorkflowError, WriteResult, WriteState


@dataclass
class RemotePhoto:
    name: str
    source_url: str
    destination: Destination
    description: str | None


class Chevereto:
    def __init__(self, base_url: str, dsn: str, *, identity: str | None = None, allow_legacy: bool = False):
        self.base_url = base_url.rstrip("/")
        self.identity = identity
        self.allow_legacy = allow_legacy
        parsed = urlparse(dsn)
        if parsed.scheme not in ("mysql", "mariadb"):
            raise ValueError("Chevereto DSN must use mysql:// or mariadb://")
        self._connection = dict(
            host=parsed.hostname,
            port=parsed.port or 3306,
            user=unquote(parsed.username or ""),
            password=unquote(parsed.password or ""),
            database=unquote(parsed.path.lstrip("/")),
            charset="utf8mb4",
            cursorclass=DictCursor,
            connect_timeout=10,
            read_timeout=20,
            write_timeout=20,
        )

    def connect(self):
        return pymysql.connect(**self._connection)

    def _variables(self, cursor):
        cursor.execute(
            "SELECT variable_name, variable_value FROM chv_variables "
            "WHERE variable_name IN ('crypt_salt', 'id_padding', 'chevereto_version_installed')"
        )
        return {row["variable_name"]: row["variable_value"] for row in cursor.fetchall()}

    def _verified_identity(self, variables):
        if str(variables.get("chevereto_version_installed", "")) != "4.5.9":
            raise WorkflowError("This adapter is verified for Chevereto 4.5.9; verify other versions before use")
        salt = variables.get("crypt_salt")
        if not isinstance(salt, str) or not salt:
            raise WorkflowError("The gallery has no usable installation identity")
        identity = hashlib.sha256(("chevereto:" + salt).encode()).hexdigest()
        if self.identity is not None and identity != self.identity:
            raise WorkflowError("The database belongs to a different gallery; the connection was not used")
        return identity

    def probe(self):
        """Verify the supported schema using reads only; never return the installation salt."""
        try:
            with self.connect() as db, db.cursor() as cursor:
                identity = self._verified_identity(self._variables(cursor))
                cursor.execute("SELECT album_id,album_name FROM chv_albums LIMIT 0")
                cursor.execute("SELECT setting_name,setting_value FROM chv_settings LIMIT 0")
                cursor.execute(
                    "SELECT image_id,image_album_id,image_name,image_extension,image_date,image_storage_mode,"
                    "image_path,image_storage_id,image_description,image_original_filename FROM chv_images LIMIT 0"
                )
                return {"identity": identity, "version": "4.5.9"}
        except pymysql.MySQLError:
            raise WorkflowError("Could not read the Chevereto database; check the connection and schema") from None

    def _check_destination(self, cursor, destination):
        identity = self._verified_identity(self._variables(cursor))
        if destination.gallery_identity is None:
            if not self.allow_legacy:
                raise WorkflowError("Confirm this gallery for older batches in Administration before publishing")
        elif destination.gallery_identity != identity:
            raise WorkflowError("This photo belongs to a different gallery; its description was not accessed")

    @staticmethod
    def _alphabet(variables):
        alphabet = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        hashed = hashlib.sha256((variables.get("crypt_salt") or "").encode()).hexdigest()
        # PHP array_multisort sorts hash chars descending, then alphabet chars
        # ascending for ties. Both are ASCII, with numeric characters first.
        return "".join(sorted(alphabet, key=lambda char: (-ord(hashed[alphabet.index(char)]), char)))

    def encode(self, value: int, variables) -> str:
        value *= max(1, int(variables.get("id_padding") or 0))
        alphabet, result = self._alphabet(variables), ""
        while value:
            value, remainder = divmod(value, len(alphabet))
            result = alphabet[remainder] + result
        return result or alphabet[0]

    def decode(self, encoded: str, variables) -> int:
        alphabet, value = self._alphabet(variables), 0
        if not encoded or not re.fullmatch(r"[a-zA-Z0-9]{1,24}", encoded):
            raise WorkflowError("Invalid Chevereto album ID")
        for char in encoded:
            value = value * len(alphabet) + alphabet.index(char)
        padding = max(1, int(variables.get("id_padding") or 0))
        if value % padding or value <= 0:
            raise WorkflowError("Invalid Chevereto album ID")
        return value // padding

    def album(self, url: str) -> tuple[str, list[RemotePhoto]]:
        parsed, configured = urlparse(url), urlparse(self.base_url)
        base_path = configured.path.rstrip("/")
        if (parsed.scheme, parsed.netloc) != (configured.scheme, configured.netloc):
            raise WorkflowError("Album URL must belong to the configured gallery")
        match = re.fullmatch(re.escape(base_path) + r"/album/([^/]+)/*", parsed.path)
        if match is None or parsed.username or parsed.password:
            raise WorkflowError("Use a Chevereto album URL")
        encoded = match[1].rsplit(".", 1)[-1]
        with self.connect() as db, db.cursor() as cursor:
            variables = self._variables(cursor)
            identity = self._verified_identity(variables)
            album_id = self.decode(encoded, variables)
            cursor.execute("SELECT album_name FROM chv_albums WHERE album_id=%s", (album_id,))
            album = cursor.fetchone()
            if album is None:
                raise WorkflowError("Gallery album not found")
            cursor.execute("SELECT setting_value FROM chv_settings WHERE setting_name='upload_image_path'")
            path_setting = cursor.fetchone()
            image_root = (path_setting["setting_value"] if path_setting else "images").strip("/")
            if not re.fullmatch(r"[a-zA-Z0-9_/-]+", image_root) or ".." in image_root:
                raise WorkflowError("Unsupported gallery image storage path")
            cursor.execute(
                "SELECT image_id,image_name,image_extension,image_date,image_storage_mode,image_path,"
                "image_storage_id,image_description,image_original_filename FROM chv_images "
                "WHERE image_album_id=%s ORDER BY image_id",
                (album_id,),
            )
            photos = []
            for image in cursor.fetchall():
                if image["image_storage_id"] is not None:
                    raise WorkflowError("External Chevereto image storage is not supported yet")
                mode = image["image_storage_mode"]
                if mode == "datefolder":
                    directory = image["image_date"].strftime("%Y/%m/%d/")
                elif mode == "direct":
                    directory = ""
                elif mode == "path":
                    directory = (image["image_path"] or "").strip("/") + "/"
                else:
                    raise WorkflowError("Unsupported Chevereto image storage mode")
                if ".." in directory or ":" in directory or "\\" in directory:
                    raise WorkflowError("Invalid gallery image path")
                filename = image["image_name"] + "." + image["image_extension"]
                page_url = self.base_url + "/image/" + self.encode(image["image_id"], variables)
                photos.append(
                    RemotePhoto(
                        name=image["image_original_filename"] or filename,
                        source_url=self.base_url + "/" + image_root + "/" + directory + quote(filename, safe=""),
                        destination=Destination(
                            instance=self.base_url,
                            image_id=image["image_id"],
                            page_url=page_url,
                            gallery_identity=identity,
                        ),
                        description=image["image_description"],
                    )
                )
            return album["album_name"], photos

    def inspect(self, change: DescriptionWrite) -> WriteResult:
        """Read the live value without applying or restoring anything."""
        if change.destination.instance.rstrip("/") != self.base_url:
            return WriteResult(state=WriteState.FAILURE, error="Destination is not the configured gallery")
        try:
            with self.connect() as db, db.cursor() as cursor:
                self._check_destination(cursor, change.destination)
                cursor.execute(
                    "SELECT image_description FROM chv_images WHERE image_id=%s", (change.destination.image_id,)
                )
                row = cursor.fetchone()
                if row is None:
                    return WriteResult(state=WriteState.FAILURE, error="Gallery image no longer exists")
                live = row["image_description"]
                return WriteResult(
                    state=WriteState.UNCHANGED if live == change.replacement else WriteState.CONFLICT,
                    live_value=live,
                )
        except WorkflowError as exc:
            return WriteResult(state=WriteState.FAILURE, error=str(exc))
        except pymysql.MySQLError:
            return WriteResult(state=WriteState.FAILURE, error="Could not read the gallery description; retry later")

    def write(self, change: DescriptionWrite) -> WriteResult:
        if change.destination.instance.rstrip("/") != self.base_url:
            return WriteResult(state=WriteState.FAILURE, error="Destination is not the configured gallery")
        try:
            with self.connect() as db, db.cursor() as cursor:
                self._check_destination(cursor, change.destination)
                cursor.execute(
                    "SELECT image_description FROM chv_images WHERE image_id=%s FOR UPDATE",
                    (change.destination.image_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    return WriteResult(state=WriteState.FAILURE, error="Gallery image no longer exists")
                live = row["image_description"]
                if live == change.replacement:
                    return WriteResult(state=WriteState.UNCHANGED, live_value=live)
                if live != change.expected:
                    return WriteResult(state=WriteState.CONFLICT, live_value=live)
                # BINARY avoids the gallery's case/accent-insensitive text
                # collation. <=> provides NULL-safe equality.
                cursor.execute(
                    "UPDATE chv_images SET image_description=%s WHERE image_id=%s "
                    "AND BINARY image_description <=> BINARY %s",
                    (change.replacement, change.destination.image_id, change.expected),
                )
                if cursor.rowcount != 1:
                    db.rollback()
                    return WriteResult(state=WriteState.CONFLICT, live_value=live)
                db.commit()
                return WriteResult(state=WriteState.APPLIED, live_value=change.replacement)
        except WorkflowError as exc:
            return WriteResult(state=WriteState.FAILURE, error=str(exc))
        except pymysql.MySQLError:
            return WriteResult(state=WriteState.FAILURE, error="Gallery database write failed; retry to reconcile")
