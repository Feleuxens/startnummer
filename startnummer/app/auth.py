"""Password hashing, setup-code verification, and opaque login sessions."""

import hashlib
import hmac
import re
import secrets
import threading
import time
from collections import OrderedDict
from ipaddress import ip_address

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from startnummer.adapters.db.accounts import Accounts, username_key
from startnummer.adapters.db.login_attempts import LoginAttempts
from startnummer.core.batch import WorkflowError

SESSION_SECONDS = 12 * 3600
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")


def source_address(host):
    try:
        address = ip_address(host)
    except ValueError:
        return "unknown"
    address = getattr(address, "ipv4_mapped", None) or address
    return str(address).partition("%")[0]


class Authentication:
    def __init__(self, engine, settings):
        self.accounts = Accounts(engine)
        self.login_attempts = LoginAttempts(self.accounts)
        self.settings = settings
        self.hasher = PasswordHasher()
        self._initialized = False
        self._lock = threading.Lock()
        self._hash_slots = threading.BoundedSemaphore(4)
        self._attempts = OrderedDict()
        self._dummy = None

    def initialize(self):
        with self._lock:
            if not self._initialized:
                password_hash = self.hash_password(self.settings.password) if self.settings.password else None
                self.accounts.initialize(self.settings, password_hash)
                self._initialized = True

    def digest(self, value, purpose="session"):
        return hmac.new(
            self.settings.session_secret.encode(), f"{purpose}:{value}".encode(), hashlib.sha256
        ).hexdigest()

    def setup_code(self):
        self.initialize()
        if not self.accounts.status()["setup_required"]:
            raise WorkflowError("Administrator setup has already been completed")
        return self.digest("first-administrator", "setup")

    def hash_password(self, password):
        with self._hash_slots:
            return self.hasher.hash(password)

    def verify(self, password_hash, password):
        with self._hash_slots:
            try:
                return self.hasher.verify(password_hash, password)
            except (VerificationError, InvalidHashError):
                return False

    def throttle(self, key, limit):
        stamp = time.monotonic()
        key = self.digest(key, "attempt")
        with self._lock:
            while self._attempts and next(iter(self._attempts.values()))[0] <= stamp:
                self._attempts.popitem(last=False)
            expiry, count = self._attempts.get(key, (stamp + 600, 0))
            if count >= limit or len(self._attempts) >= 4096:
                return False
            self._attempts[key] = (expiry, count + 1)
            return True

    def setup(self, code, username, password):
        self.initialize()
        if not hmac.compare_digest(self.digest(code, "setup-input"), self.digest(self.setup_code(), "setup-input")):
            raise WorkflowError("The setup code is incorrect")
        return self.accounts.setup(username, self.hash_password(password), self.settings.owner_id)

    def login(self, username, password):
        self.initialize()
        found = self.accounts.find(username)
        if found is None or found[1] is None:
            if self._dummy is None:
                self._dummy = self.hash_password(secrets.token_urlsafe(32))
            self.verify(self._dummy, password)
            return None
        user, password_hash = found
        if not self.verify(password_hash, password) or user.disabled:
            return None
        return user

    def login_from(self, username, password, peer):
        source = self.digest(source_address(peer), "login-source")
        name = self.digest(username_key(username) if len(username) <= 128 else "", "login-name")
        reservation = self.login_attempts.reserve(source, name)
        success = None
        try:
            user = self.login(username, password) if len(username) <= 128 and len(password) <= 1024 else None
            success = user is not None
            return user
        finally:
            self.login_attempts.settle(reservation, success=success)

    def register(self, username, password, invitation=None):
        self.initialize()
        if invitation and not TOKEN.fullmatch(invitation):
            raise WorkflowError("This invitation is invalid, expired, or already used")
        return self.accounts.register(
            username, self.hash_password(password), self.digest(invitation, "invite") if invitation else None
        )

    def issue(self, user):
        token = secrets.token_urlsafe(32)
        self.accounts.create_session(user, self.digest(token))
        return token

    def authenticate(self, token):
        self.initialize()
        if not TOKEN.fullmatch(token):
            return None
        return self.accounts.authenticate(self.digest(token))

    def revoke(self, user_id, token=None):
        self.accounts.revoke(user_id, self.digest(token) if token else None)

    def invite(self, creator, label, hours):
        token = secrets.token_urlsafe(32)
        return {**self.accounts.invite(creator, label, self.digest(token, "invite"), hours), "token": token}
