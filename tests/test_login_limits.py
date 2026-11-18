"""Sign-in throttling shares failures and trusts only the resolved client address."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from startnummer.adapters.db import login_attempts
from startnummer.adapters.db.accounts import Accounts
from startnummer.adapters.db.store import Store
from startnummer.app.api import create_app
from startnummer.app.manage import migrate
from tests.test_accounts import HEADERS, PASSWORD, setup
from tests.test_accounts import accounts as accounts
from tests.test_database_integration import postgres as postgres


@pytest.fixture
def clock(monkeypatch):
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(login_attempts, "now", lambda: stamp)

    def advance(seconds):
        nonlocal stamp
        stamp += timedelta(seconds=seconds)

    return advance


async def sign_in(app, source, username="admin", password="wrong-password", headers=None):
    transport = httpx.ASGITransport(app, client=(source, 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", headers=HEADERS) as client:
        return await client.post("/api/session", json={"username": username, "password": password}, headers=headers)


@pytest.mark.parametrize("username", ["admin", "absent"])
def test_normalized_username_cooldown_is_shared_across_instances_and_sources(accounts, clock, username):
    first, engine, settings, faces = accounts
    setup(first)
    second = create_app(settings, store=Store(engine), sessions=faces)
    fullwidth = "".join(chr(ord(char) + 0xFEE0) for char in username.upper())

    async def scenario():
        for index in range(5):
            app = first if index % 2 == 0 else second
            response = await sign_in(app, f"192.0.2.{index + 1}", f" {fullwidth} ")
            assert response.status_code == 401
        response = await sign_in(second, "198.51.100.1", username, PASSWORD)
        assert response.status_code == 429 and response.headers["retry-after"] == "2"
        clock(1)
        response = await sign_in(first, "198.51.100.2", username)
        assert response.status_code == 429 and response.headers["retry-after"] == "1"
        clock(1)
        assert (await sign_in(first, "198.51.100.2", username)).status_code == 401
        response = await sign_in(second, "198.51.100.1", username)
        assert response.status_code == 429 and response.headers["retry-after"] == "4"
        clock(4)
        if username == "admin":
            assert (await sign_in(second, "198.51.100.1", username, PASSWORD)).status_code == 200
        else:
            clock(600)
        for _ in range(5):  # A success or ten quiet minutes clears the previous streak.
            assert (await sign_in(first, "198.51.100.2", username)).status_code == 401
        response = await sign_in(second, "198.51.100.1", username)
        assert response.status_code == 429 and response.headers["retry-after"] == "2"

    asyncio.run(scenario())


def test_source_limit_counts_only_failures_and_expires(accounts, clock, monkeypatch):
    first, engine, settings, faces = accounts
    setup(first)
    second = create_app(settings, store=Store(engine), sessions=faces)
    monkeypatch.setattr(login_attempts, "SOURCE_LIMIT", 3)

    async def scenario():
        source = "192.0.2.1"
        for index in range(2):
            assert (await sign_in(first, source, f"absent-{index}")).status_code == 401
        for _ in range(4):
            assert (await sign_in(second, source, password=PASSWORD)).status_code == 200
        assert (await sign_in(first, "::ffff:192.0.2.1", "another-name")).status_code == 401
        response = await sign_in(second, source, password=PASSWORD)
        assert response.status_code == 429 and response.headers["retry-after"] == "600"
        assert (await sign_in(second, "192.0.2.2", password=PASSWORD)).status_code == 200
        clock(600)
        assert (await sign_in(second, source, password=PASSWORD)).status_code == 200

    asyncio.run(scenario())


def test_proxy_headers_only_count_for_a_trusted_peer(accounts, clock, monkeypatch):
    app, *_ = accounts
    setup(app)
    monkeypatch.setattr(login_attempts, "SOURCE_LIMIT", 1)
    proxy = ProxyHeadersMiddleware(app, trusted_hosts="172.30.20.2")

    async def scenario():
        forwarded = {"X-Forwarded-For": "192.0.2.1"}
        assert (await sign_in(proxy, "172.30.20.2", "first-name", headers=forwarded)).status_code == 401
        assert (await sign_in(proxy, "172.30.20.2", "second-name", headers=forwarded)).status_code == 429
        other = {"X-Forwarded-For": "192.0.2.2"}
        assert (await sign_in(proxy, "172.30.20.2", password=PASSWORD, headers=other)).status_code == 200

        direct = "198.51.100.5"
        assert (await sign_in(proxy, direct, "direct-name", headers=forwarded)).status_code == 401
        assert (await sign_in(proxy, direct, password=PASSWORD, headers=other)).status_code == 429

    asyncio.run(scenario())


def test_postgres_instances_reserve_source_capacity_atomically(postgres, monkeypatch):
    migrate(postgres.engine)
    monkeypatch.setattr(login_attempts, "SOURCE_LIMIT", 2)

    def try_reserve(index):
        limiter = login_attempts.LoginAttempts(Accounts(postgres.engine))
        try:
            return limiter.reserve("source", f"name-{index}")
        except login_attempts.LoginThrottled:
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        admitted = [reservation for reservation in pool.map(try_reserve, range(6)) if reservation is not None]
    assert len(admitted) == 2

    limiter = login_attempts.LoginAttempts(Accounts(postgres.engine))
    limiter.settle(admitted[0], success=True)
    limiter.settle(admitted[1], success=False)
    assert try_reserve(9) is not None
    assert try_reserve(10) is None
