"""Environment precedence, encrypted connections, and gallery identity bindings."""

import json
from urllib.parse import quote, unquote, urlparse

from cryptography.fernet import Fernet, InvalidToken
from pydantic import ValidationError
from sqlalchemy import select

from startnummer.adapters.chevereto import Chevereto
from startnummer.adapters.db.schema import GalleryBindingRow, IntegrationRow, PhotoRow
from startnummer.app.contracts import CheveretoConnection, ConnectionTest, IntegrationStatus
from startnummer.core.batch import Conflict, WorkflowError


class Integrations:
    def __init__(self, store, settings, *, factory=Chevereto):
        self.store, self.settings, self.factory = store, settings, factory

    @property
    def environment_managed(self):
        return self.settings.chevereto_url is not None or self.settings.chevereto_dsn is not None

    def _cipher(self):
        key = self.settings.integration_key
        if not key:
            raise WorkflowError("Set STARTNUMMER_INTEGRATION_KEY on the server to save encrypted connections")
        try:
            return Fernet(key.encode())
        except (ValueError, TypeError):
            raise WorkflowError("STARTNUMMER_INTEGRATION_KEY must be a valid Fernet key") from None

    def _decode(self, row):
        try:
            payload = self._cipher().decrypt(row.credentials.encode())
            return CheveretoConnection.model_validate_json(payload)
        except (InvalidToken, ValidationError, UnicodeError, ValueError):
            raise WorkflowError(
                "The saved connection cannot be decrypted; restore its original integration key"
            ) from None

    def _environment(self):
        if not self.settings.chevereto_url or not self.settings.chevereto_dsn:
            raise WorkflowError(
                "Set both STARTNUMMER_CHEVERETO_URL and STARTNUMMER_CHEVERETO_DSN; "
                "environment configuration is incomplete"
            )
        try:
            parsed = urlparse(self.settings.chevereto_dsn)
            if parsed.scheme not in {"mysql", "mariadb"} or not parsed.hostname or parsed.query or parsed.fragment:
                raise ValueError
            return CheveretoConnection(
                url=self.settings.chevereto_url,
                host=parsed.hostname,
                port=parsed.port or 3306,
                database=unquote(parsed.path.lstrip("/")),
                username=unquote(parsed.username or ""),
                password=unquote(parsed.password or ""),
            )
        except (ValueError, ValidationError):
            raise WorkflowError("The Chevereto environment connection is invalid; check its URL and DSN") from None

    def _configuration(self, session):
        if self.environment_managed:
            return self._environment()
        row = session.get(IntegrationRow, self.settings.owner_id)
        if row is None:
            return None
        return self._decode(row).model_copy(update={"revision": row.revision})

    @staticmethod
    def _dsn(config):
        password = config.password.get_secret_value() if config.password is not None else ""
        host = f"[{config.host}]" if ":" in config.host else config.host
        credentials = quote(config.username, safe="") + ":" + quote(password, safe="")
        return f"mysql://{credentials}@{host}:{config.port}/{quote(config.database, safe='')}"

    def _adapter(self, config):
        return self.factory(config.url, self._dsn(config))

    def _legacy(self, session, url):
        return sum(
            1
            for photo in session.scalars(select(PhotoRow).where(PhotoRow.owner_id == self.settings.owner_id))
            if (target := photo.document.get("destination"))
            and target["instance"].rstrip("/") == url
            and not target.get("gallery_identity")
        )

    def status(self):
        environment = self.environment_managed
        status = IntegrationStatus(source="environment" if environment else "administration")
        try:
            self._cipher()
            status.encryption_ready = True
        except WorkflowError as exc:
            if not environment:
                status.error = str(exc)
        status.editable = not environment and status.encryption_ready
        with self.store.transaction() as session:
            row = session.get(IntegrationRow, self.settings.owner_id)
            status.revision = row.revision if row else 0
            try:
                config = self._configuration(session)
            except WorkflowError as exc:
                status.error = str(exc)
                return status
            if config is not None:
                status.configured = True
                for field in ("url", "host", "port", "database", "username"):
                    setattr(status, field, getattr(config, field))
                status.password_set = config.password is not None
                status.legacy_photos = self._legacy(session, config.url)
                binding = session.get(GalleryBindingRow, (self.settings.owner_id, config.url))
                status.legacy_confirmed = bool(binding and binding.legacy_confirmed)
        return status

    def public_url(self):
        # A broken integration must not prevent sign-in or reviewing saved work.
        with self.store.transaction() as session:
            try:
                config = self._configuration(session)
                return config.url if config else None
            except WorkflowError:
                return None

    def _draft(self, session, request):
        if self.environment_managed:
            if request is not None:
                raise Conflict("This connection is managed by environment variables and cannot be edited here")
            return self._environment()
        row = session.get(IntegrationRow, self.settings.owner_id)
        if request is None:
            config = self._configuration(session)
            if config is None:
                raise WorkflowError("Configure a Chevereto connection first")
            return config
        if request.revision != (row.revision if row else 0):
            raise Conflict("The connection changed; reload it before testing or saving")
        if request.password is None:
            if row is None:
                raise WorkflowError("Enter the database password for the new connection")
            request = request.model_copy(update={"password": self._decode(row).password})
        return request

    def _pin(self, session, config, identity):
        key = (self.settings.owner_id, config.url)
        binding = session.get(GalleryBindingRow, key)
        targets = [
            photo.document["destination"]
            for photo in session.scalars(select(PhotoRow).where(PhotoRow.owner_id == self.settings.owner_id))
            if photo.document.get("destination") and photo.document["destination"]["instance"].rstrip("/") == config.url
        ]
        if binding is not None and binding.identity != identity and targets:
            raise Conflict("This URL is already bound to a different gallery database; restore the original connection")
        for target in targets:
            if target.get("gallery_identity") not in {None, identity}:
                raise Conflict("Saved photos at this URL belong to a different gallery database")
        if binding is None:
            binding = GalleryBindingRow(
                owner_id=self.settings.owner_id, url=config.url, identity=identity, legacy_confirmed=False
            )
            session.add(binding)
        elif binding.identity != identity:
            binding.identity, binding.legacy_confirmed = identity, False
        return binding

    def test(self, request=None):
        with self.store.transaction() as session:
            config = self._draft(session, request)
        info = self._adapter(config).probe()
        # Check existing bindings without changing configuration or trust records.
        with self.store.transaction() as session:
            binding = session.get(GalleryBindingRow, (self.settings.owner_id, config.url))
            referenced = session.scalars(select(PhotoRow).where(PhotoRow.owner_id == self.settings.owner_id))
            has_targets = any(
                photo.document.get("destination")
                and photo.document["destination"]["instance"].rstrip("/") == config.url
                for photo in referenced
            )
            if binding and binding.identity != info["identity"] and has_targets:
                raise Conflict("This connection reaches a different gallery than the saved destination binding")
        return ConnectionTest(version=info["version"])

    def save(self, request):
        if self.environment_managed:
            raise Conflict("This connection is managed by environment variables and cannot be edited here")
        cipher = self._cipher()
        with self.store.transaction() as session:
            config = self._draft(session, request)
        info = self._adapter(config).probe()
        document = config.model_dump(mode="json", exclude={"revision", "password"})
        document["password"] = config.password.get_secret_value()
        encrypted = cipher.encrypt(json.dumps(document).encode()).decode()
        with self.store.transaction(self.settings.owner_id) as session:
            self._draft(session, request)
            self._pin(session, config, info["identity"])
            row = session.get(IntegrationRow, self.settings.owner_id)
            if row is None:
                row = IntegrationRow(owner_id=self.settings.owner_id, revision=0)
                session.add(row)
            row.credentials, row.revision = encrypted, row.revision + 1
        return self.status()

    def confirm_legacy(self, revision):
        with self.store.transaction() as session:
            config = self._draft(session, None)
            row = session.get(IntegrationRow, self.settings.owner_id)
            if revision != (row.revision if row else 0):
                raise Conflict("The connection changed; reload it before confirming older batches")
        info = self._adapter(config).probe()
        with self.store.transaction(self.settings.owner_id) as session:
            current = self._draft(session, None)
            row = session.get(IntegrationRow, self.settings.owner_id)
            if revision != (row.revision if row else 0) or current.url != config.url:
                raise Conflict("The connection changed; reload it before confirming older batches")
            self._pin(session, config, info["identity"]).legacy_confirmed = True
        return self.status()

    def snapshot(self):
        with self.store.transaction() as session:
            config = self._configuration(session)
        if config is None:
            raise WorkflowError("No gallery is configured")
        adapter = self._adapter(config)
        info = adapter.probe()
        with self.store.transaction(self.settings.owner_id) as session:
            binding = self._pin(session, config, info["identity"])
            adapter.identity = binding.identity
            adapter.allow_legacy = binding.legacy_confirmed
        return adapter
