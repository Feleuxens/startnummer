"""Short database transactions reserve and settle password checks."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import ceil
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select

from startnummer.adapters.db.accounts import utc
from startnummer.adapters.db.schema import LoginAttemptRow
from startnummer.core.batch import now

SOURCE_LIMIT = 30
WINDOW = timedelta(minutes=10)
RESERVATION_TTL = timedelta(seconds=30)
MAX_TRACKED_KEYS = 16384
FREE_FAILURES = 4
DELAYS = (2, 4, 8, 16, 32, 60)
LOGIN_LOCK = -738390521328


class LoginThrottled(Exception):
    def __init__(self, seconds):
        self.seconds = seconds
        super().__init__(seconds)


@dataclass(frozen=True)
class LoginReservation:
    source_key: str
    name_key: str
    source_expiry: datetime
    token: UUID


class LoginAttempts:
    def __init__(self, accounts):
        self.accounts = accounts

    def reserve(self, source_key, name_key):
        # Use a separate lock from account management and release it before hashing.
        with self.accounts.write(lock_key=LOGIN_LOCK) as db:
            stamp = now()
            source = active_counter(db, source_key, stamp)
            name = active_counter(db, name_key, stamp)
            until = []
            if source is not None and source.count >= SOURCE_LIMIT:
                until.append(utc(source.expires_at))
            if name is not None and name.retry_at is not None and utc(name.retry_at) > stamp:
                retry_at = utc(name.retry_at)
                if name.reservation is not None:
                    retry_at = min(retry_at, stamp + timedelta(seconds=1))
                until.append(retry_at)
            if until:
                raise LoginThrottled(ceil((max(until) - stamp).total_seconds()))

            missing = int(source is None) + int(name is None)
            if missing:
                db.execute(
                    delete(LoginAttemptRow)
                    .where(LoginAttemptRow.expires_at <= stamp)
                    .execution_options(synchronize_session="fetch")
                )
                if db.scalar(select(func.count()).select_from(LoginAttemptRow)) + missing > MAX_TRACKED_KEYS:
                    raise LoginThrottled(5)
            if source is None:
                source = LoginAttemptRow(key=source_key, count=0, expires_at=stamp + WINDOW)
                db.add(source)
            if name is None:
                name = LoginAttemptRow(key=name_key, count=0, expires_at=stamp + WINDOW)
                db.add(name)
            source.count += 1  # Success or an internal error refunds this slot.
            name.reservation = uuid4()
            name.retry_at = stamp + RESERVATION_TTL
            name.expires_at = max(utc(name.expires_at), name.retry_at)
            return LoginReservation(source_key, name_key, utc(source.expires_at), name.reservation)

    def settle(self, reservation, *, success):
        with self.accounts.write(lock_key=LOGIN_LOCK) as db:
            if success is not False:
                source = db.get(LoginAttemptRow, reservation.source_key)
                if source is not None and utc(source.expires_at) == reservation.source_expiry:
                    source.count -= 1
                    if not source.count:
                        db.delete(source)
            name = db.get(LoginAttemptRow, reservation.name_key)
            if name is None or name.reservation != reservation.token:
                return  # The reservation expired and another request took its place.
            if success is True or (success is None and name.count == 0):
                db.delete(name)
                return
            name.reservation = name.retry_at = None
            if success is False:
                stamp = now()
                name.expires_at = stamp + WINDOW
                name.count = min(name.count + 1, FREE_FAILURES + len(DELAYS))
                if name.count > FREE_FAILURES:
                    name.retry_at = stamp + timedelta(seconds=DELAYS[name.count - FREE_FAILURES - 1])


def active_counter(db, key, stamp):
    row = db.get(LoginAttemptRow, key)
    return row if row is not None and utc(row.expires_at) > stamp else None
