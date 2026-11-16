"""Atomic account creation, invitation claims, and revocable sessions."""

import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from startnummer.adapters.db.schema import (
    BatchRow,
    InstanceRow,
    IntegrationRow,
    InvitationRow,
    SessionRow,
    SettingsRow,
    UserRow,
)
from startnummer.core.batch import Conflict, WorkflowError, now

AUTH_TABLES = {"sn_users", "sn_instance", "sn_sessions", "sn_invitations"}


def username_key(username):
    return unicodedata.normalize("NFKC", username).strip().casefold()


@dataclass(frozen=True)
class Account:
    id: UUID
    username: str
    is_admin: bool
    credential_hash: str | None = field(default=None, repr=False)


def account(row):
    return Account(row.id, row.username, row.is_admin, row.password_hash)


def utc(value: datetime):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class Accounts:
    def __init__(self, engine):
        self.engine = engine

    @contextmanager
    def write(self):
        # Serialize first-admin creation, registration policy, and invitation claims.
        with Session(self.engine, expire_on_commit=False) as db:
            if self.engine.dialect.name == "sqlite":
                db.execute(text("BEGIN IMMEDIATE"))
            elif self.engine.dialect.name == "postgresql":
                db.execute(text("SELECT pg_advisory_xact_lock(-738390521327)"))
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def initialize(self, legacy, password_hash=None):
        with self.write() as db:
            config = db.get(InstanceRow, 1)
            if config is None:
                config = InstanceRow(id=1, registration_enabled=False, revision=0)
                db.add(config)
                db.flush()
            if config.admin_owner_id is None and password_hash:
                user = db.scalar(select(UserRow).where(UserRow.username_key == username_key(legacy.username)))
                if user is None:
                    if db.scalar(select(UserRow.id).limit(1)) is not None:
                        raise Conflict("Remove STARTNUMMER_PASSWORD and use setup with the restored account's username")
                    user = UserRow(
                        id=legacy.owner_id,
                        username=legacy.username,
                        username_key=username_key(legacy.username),
                        password_hash=password_hash,
                        is_admin=True,
                        created_at=now(),
                    )
                    db.add(user)
                elif user.password_hash is not None:
                    raise Conflict("An existing account must be claimed through setup")
                else:
                    user.password_hash, user.is_admin = password_hash, True
                db.flush()
                config.admin_owner_id = user.id

    def status(self):
        with Session(self.engine) as db:
            config = db.get(InstanceRow, 1)
            return {
                "setup_required": config.admin_owner_id is None,
                "registration_enabled": config.registration_enabled and config.admin_owner_id is not None,
            }

    def get(self, identity):
        with Session(self.engine) as db:
            row = db.get(UserRow, identity)
            if row is None:
                raise WorkflowError("Account not found")
            return account(row)

    def find(self, username):
        with Session(self.engine) as db:
            row = db.scalar(select(UserRow).where(UserRow.username_key == username_key(username)))
            return (account(row), row.password_hash) if row else None

    def setup(self, username, password_hash, legacy_owner_id):
        with self.write() as db:
            config = db.get(InstanceRow, 1)
            if config.admin_owner_id is not None:
                raise Conflict("Setup has already been completed")
            pending = db.scalars(select(UserRow)).all()
            if pending:
                if (
                    len(pending) != 1
                    or pending[0].password_hash is not None
                    or pending[0].username_key != username_key(username)
                ):
                    raise Conflict("Use the restored account's username to finish setup")
                user = pending[0]
                user.password_hash, user.is_admin = password_hash, True
            else:
                owners = set()
                for table in (BatchRow, SettingsRow, IntegrationRow):
                    owners.update(db.scalars(select(table.owner_id).distinct()))
                if len(owners) > 1 and legacy_owner_id not in owners:
                    raise Conflict("Set STARTNUMMER_USERNAME to the original account before claiming existing albums")
                identity = (
                    legacy_owner_id
                    if legacy_owner_id in owners
                    else next(iter(owners))
                    if len(owners) == 1
                    else uuid4()
                )
                user = UserRow(
                    id=identity,
                    username=username,
                    username_key=username_key(username),
                    password_hash=password_hash,
                    is_admin=True,
                    created_at=now(),
                )
                db.add(user)
            db.flush()
            config.admin_owner_id = user.id
            return account(user)

    def register(self, username, password_hash, invitation_hash=None):
        with self.write() as db:
            config = db.get(InstanceRow, 1)
            if config.admin_owner_id is None:
                raise Conflict("Complete administrator setup first")
            invitation = None
            if invitation_hash:
                invitation = db.scalar(
                    select(InvitationRow).where(
                        InvitationRow.token_hash == invitation_hash,
                        InvitationRow.used_at.is_(None),
                        InvitationRow.revoked_at.is_(None),
                        InvitationRow.expires_at > now(),
                    )
                )
                if invitation is None:
                    raise WorkflowError("This invitation is invalid, expired, or already used")
            elif not config.registration_enabled:
                raise WorkflowError("Registration is closed; ask an administrator for an invitation")
            if db.scalar(select(UserRow.id).where(UserRow.username_key == username_key(username))):
                raise Conflict("That username is already in use")
            user = UserRow(
                id=uuid4(),
                username=username,
                username_key=username_key(username),
                password_hash=password_hash,
                is_admin=False,
                created_at=now(),
            )
            db.add(user)
            db.flush()
            if invitation:
                invitation.used_at = now()
            return account(user)

    def create_session(self, user, token_hash):
        with self.write() as db:
            current = db.get(UserRow, user.id)
            if current is None or not current.password_hash or current.password_hash != user.credential_hash:
                raise Conflict("The account password changed; sign in again")
            db.execute(delete(SessionRow).where(SessionRow.expires_at <= now()))
            db.add(
                SessionRow(
                    token_hash=token_hash, user_id=user.id, created_at=now(), expires_at=now() + timedelta(hours=12)
                )
            )

    def authenticate(self, token_hash):
        with Session(self.engine) as db:
            row = db.scalar(
                select(UserRow)
                .join(SessionRow, SessionRow.user_id == UserRow.id)
                .where(
                    SessionRow.token_hash == token_hash,
                    SessionRow.expires_at > now(),
                    UserRow.password_hash.is_not(None),
                )
            )
            return account(row) if row else None

    def revoke(self, user_id, token_hash=None):
        with self.write() as db:
            statement = delete(SessionRow).where(SessionRow.user_id == user_id)
            if token_hash:
                statement = statement.where(SessionRow.token_hash == token_hash)
            db.execute(statement)

    def change_password(self, user, password_hash):
        with self.write() as db:
            row = db.get(UserRow, user.id)
            if row.password_hash != user.credential_hash:
                raise Conflict("The account password changed; sign in again")
            row.password_hash = password_hash
            db.execute(delete(SessionRow).where(SessionRow.user_id == user.id))
            db.flush()
            return account(row)

    def administration(self):
        with Session(self.engine) as db:
            config = db.get(InstanceRow, 1)
            return {
                "revision": config.revision,
                "registration_enabled": config.registration_enabled,
                "users": [
                    {"id": row.id, "username": row.username, "is_admin": row.is_admin, "created_at": row.created_at}
                    for row in db.scalars(select(UserRow).order_by(UserRow.created_at))
                ],
                "invitations": [
                    {
                        "id": row.id,
                        "label": row.label,
                        "expires_at": utc(row.expires_at),
                        "state": "used"
                        if row.used_at
                        else "revoked"
                        if row.revoked_at
                        else "expired"
                        if utc(row.expires_at) <= now()
                        else "available",
                    }
                    for row in db.scalars(select(InvitationRow).order_by(InvitationRow.created_at.desc()))
                ],
            }

    def set_registration(self, revision, enabled):
        with self.write() as db:
            config = db.get(InstanceRow, 1)
            if config.revision != revision:
                raise Conflict("Registration settings changed; reload before saving")
            config.registration_enabled, config.revision = enabled, revision + 1
            return {"revision": config.revision, "registration_enabled": enabled}

    def invite(self, creator, label, token_hash, hours):
        with self.write() as db:
            row = InvitationRow(
                id=uuid4(),
                token_hash=token_hash,
                label=label,
                created_by=creator,
                created_at=now(),
                expires_at=now() + timedelta(hours=hours),
            )
            db.add(row)
            return {"id": row.id, "label": label, "expires_at": row.expires_at, "state": "available"}

    def revoke_invitation(self, identity):
        with self.write() as db:
            row = db.get(InvitationRow, identity)
            if row is None:
                raise WorkflowError("Invitation not found")
            row.revoked_at = now()
