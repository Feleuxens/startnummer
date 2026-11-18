"""First-admin setup, invitations, session revocation, and private user workspaces."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from startnummer.adapters.db.schema import Base, InstanceRow, InvitationRow, SessionRow, UserRow
from startnummer.adapters.db.store import Store
from startnummer.adapters.face.sessions import FaceSessions
from startnummer.app.api import create_app
from startnummer.app.settings import Settings
from startnummer.core.batch import Conflict, now
from tests.test_workflow import HTML, image_bytes

HEADERS = {"X-Requested-With": "Startnummer"}
PASSWORD = "synthetic-account-password"


@pytest.fixture
def accounts(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "accounts.db"), connect_args={"timeout": 15})
    Base.metadata.create_all(engine)
    settings = Settings(
        database_url=str(engine.url),
        blob_root=tmp_path / "photos",
        password="",
        session_secret="s" * 32,
        worker_secret="w" * 32,
        cookie_secure=False,
        owner_id=uuid4(),
    )
    faces = FaceSessions()
    app = create_app(settings, store=Store(engine), sessions=faces)
    yield app, engine, settings, faces
    engine.dispose()


def client(app):
    return TestClient(app, headers=HEADERS)


def setup(app):
    admin = client(app)
    response = admin.post(
        "/api/auth/setup",
        json={"username": "admin", "password": PASSWORD, "code": app.state.authentication.setup_code()},
    )
    assert response.status_code == 200, response.text
    return admin


def invite(admin, app, username="athlete"):
    invitation = admin.post("/api/admin/invitations", json={"label": "Synthetic invitation", "hours": 48})
    assert invitation.status_code == 200, invitation.text
    member = client(app)
    response = member.post(
        "/api/auth/register",
        json={"username": username, "password": PASSWORD, "invitation": invitation.json()["token"]},
    )
    assert response.status_code == 200, response.text
    return member, invitation.json()


def imported(client):
    response = client.post(
        "/api/batches",
        data={"name": "Private batch"},
        files=[
            ("photos", ("example.jpg", image_bytes(), "image/jpeg")),
            ("roster_file", ("roster.html", HTML, "text/html")),
        ],
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_setup_requires_code_is_single_use_and_hashes_credentials(accounts):
    app, engine, _, _ = accounts
    visitor = client(app)
    assert visitor.get("/api/auth/status").json() == {"setup_required": True, "registration_enabled": False}
    assert (
        visitor.post(
            "/api/auth/setup", json={"username": "admin", "password": PASSWORD, "code": "incorrect"}
        ).status_code
        == 400
    )
    admin = setup(app)
    assert admin.get("/api/session").json()["is_admin"]
    assert not visitor.get("/api/auth/status").json()["setup_required"]
    assert (
        visitor.post(
            "/api/auth/setup", json={"username": "another", "password": PASSWORD, "code": "incorrect"}
        ).status_code
        != 200
    )
    raw_token = admin.cookies.get("startnummer_session")
    with Session(engine) as db:
        user = db.scalar(select(UserRow))
        assert user.password_hash.startswith("$argon2id$")
        assert PASSWORD not in user.password_hash
        assert db.scalar(select(SessionRow.token_hash)) != raw_token
        assert db.get(InstanceRow, 1).admin_owner_id == user.id


@pytest.mark.parametrize("secure", [True, False])
def test_session_cookie_secure_attribute_and_http_behavior(accounts, secure):
    _, engine, settings, faces = accounts
    app = create_app(replace(settings, cookie_secure=secure), store=Store(engine), sessions=faces)
    url = "https://testserver" if secure else "http://testserver"
    with TestClient(app, base_url=url, headers=HEADERS) as browser:
        response = browser.post(
            "/api/auth/setup",
            json={"username": "admin", "password": PASSWORD, "code": app.state.authentication.setup_code()},
        )
        assert response.status_code == 200
        assert ("; secure" in response.headers["set-cookie"].lower()) is secure
        assert browser.get("/api/session").status_code == 200
        assert browser.get("http://testserver/api/session").status_code == (401 if secure else 200)


def test_only_one_first_administrator_can_win_concurrent_setup(accounts):
    app, engine, _, _ = accounts
    code = app.state.authentication.setup_code()

    def claim(name):
        with client(app) as browser:
            return browser.post(
                "/api/auth/setup", json={"username": name, "password": PASSWORD, "code": code}
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(claim, ["first", "second"]))
    assert outcomes.count(200) == 1
    with Session(engine) as db:
        assert len(db.scalars(select(UserRow).where(UserRow.is_admin.is_(True))).all()) == 1


def test_registration_policy_and_administrator_endpoints(accounts):
    app, _, _, _ = accounts
    admin = setup(app)
    visitor = client(app)
    body = {"username": "newuser", "password": PASSWORD}
    assert visitor.post("/api/auth/register", json=body).status_code == 400
    assert admin.put("/api/admin/registration", json={"revision": 0, "registration_enabled": True}).status_code == 200
    assert visitor.post("/api/auth/register", json=body).status_code == 200
    assert not visitor.get("/api/session").json()["is_admin"]
    for path in ("/api/admin", "/api/admin/accounts", "/api/admin/integrations/chevereto"):
        assert visitor.get(path).status_code == 403
    assert (
        visitor.put("/api/admin/registration", json={"revision": 1, "registration_enabled": False}).status_code == 403
    )
    assert admin.put("/api/admin/registration", json={"revision": 0, "registration_enabled": False}).status_code == 409
    assert admin.put("/api/admin/registration", json={"revision": 1, "registration_enabled": False}).status_code == 200
    assert client(app).post("/api/auth/register", json={**body, "username": "closed"}).status_code == 400
    assert client(app).post("/api/session", json=body).status_code == 200


def test_invitation_is_single_use_expiring_revocable_and_never_grants_admin(accounts):
    app, engine, _, _ = accounts
    admin = setup(app)
    member, invitation = invite(admin, app)
    assert not member.get("/api/session").json()["is_admin"]
    assert (
        client(app)
        .post("/api/auth/register", json={"username": "reuse", "password": PASSWORD, "invitation": invitation["token"]})
        .status_code
        == 400
    )
    expired = admin.post("/api/admin/invitations", json={"hours": 1}).json()
    with Session(engine) as db, db.begin():
        db.get(InvitationRow, UUID(expired["id"])).expires_at = now() - timedelta(seconds=1)
    assert (
        client(app)
        .post("/api/auth/register", json={"username": "expired", "password": PASSWORD, "invitation": expired["token"]})
        .status_code
        == 400
    )
    revoked = admin.post("/api/admin/invitations", json={}).json()
    assert admin.delete(f"/api/admin/invitations/{revoked['id']}").status_code == 200
    assert (
        client(app)
        .post("/api/auth/register", json={"username": "revoked", "password": PASSWORD, "invitation": revoked["token"]})
        .status_code
        == 400
    )
    listing = admin.get("/api/admin/accounts").text
    for token in (invitation["token"], expired["token"], revoked["token"]):
        assert token not in listing


def test_private_batches_and_photos_cannot_be_read_by_other_users_or_admin(accounts):
    app, _, _, _ = accounts
    admin = setup(app)
    first, _ = invite(admin, app, "first")
    second, _ = invite(admin, app, "second")
    batch = imported(first)
    identity, photo = batch["album"]["id"], batch["photos"][0]["id"]
    assert first.get(f"/api/batches/{identity}").status_code == 200
    assert first.get(f"/api/photos/{photo}").status_code == 200
    for other in (second, admin):
        assert other.get("/api/batches").json() == []
        assert other.get(f"/api/batches/{identity}").status_code == 404
        assert other.get(f"/api/photos/{photo}").status_code == 404
    assert first.post(f"/api/batches/{identity}/apply", json={"photos": []}).status_code == 403
    assert (
        first.post(
            "/api/batches",
            data={"name": "Forbidden gallery", "gallery_url": "https://gallery.example/album/a"},
            files={"roster_file": ("roster.html", HTML, "text/html")},
        ).status_code
        == 403
    )


def test_logout_and_administrator_revocation_invalidate_replayed_cookies(accounts):
    app, _, _, faces = accounts
    admin = setup(app)
    member, _ = invite(admin, app)
    another = client(app)
    assert another.post("/api/session", json={"username": "ATHLETE", "password": PASSWORD}).status_code == 200
    token = member.cookies.get("startnummer_session")
    assert member.delete("/api/session").status_code == 200
    member.cookies.set("startnummer_session", token)
    assert member.get("/api/session").status_code == 401
    assert another.get("/api/session").status_code == 200
    batch = imported(another)
    owner = app.state.authentication.accounts.find("athlete")[0].id
    faces.put(owner, UUID(batch["album"]["id"]), {})
    user = next(row for row in admin.get("/api/admin/accounts").json()["users"] if row["username"] == "athlete")
    assert admin.delete(f"/api/admin/users/{user['id']}/sessions").status_code == 200
    assert another.get("/api/session").status_code == 401
    assert not faces.get(owner, UUID(batch["album"]["id"]))["available"]


def test_administrator_can_contain_and_recover_a_compromised_account(accounts):
    app, engine, _, faces = accounts
    admin = setup(app)
    member, _ = invite(admin, app)
    old_login = {"username": "athlete", "password": PASSWORD}
    second = client(app)
    assert second.post("/api/session", json=old_login).status_code == 200
    batch = imported(member)["album"]
    owner, batch_id = UUID(batch["owner_id"]), UUID(batch["id"])
    review_url = f"/api/batches/{batch_id}"
    base = f"/api/admin/users/{owner}"
    assert member.post(f"{review_url}/analysis").status_code == 200
    saved = member.get(review_url).json()
    faces.put(owner, batch_id, {})

    replacement = "synthetic-replacement-password"
    reset = {"password": replacement, "administrator_password": PASSWORD}
    assert member.put(f"{base}/access", json={"disabled": True}).status_code == 403
    assert member.put(f"{base}/password", json=reset).status_code == 403
    admin_id = next(user["id"] for user in admin.get("/api/admin/accounts").json()["users"] if user["is_admin"])
    assert admin.put(f"/api/admin/users/{admin_id}/access", json={"disabled": True}).status_code == 400
    assert admin.put(f"/api/admin/users/{admin_id}/password", json=reset).status_code == 400

    assert admin.put(f"{base}/access", json={"disabled": True}).json() == {"disabled": True, "review_cleared": True}
    assert member.get(review_url).status_code == 401
    assert second.get("/api/session").status_code == 401
    assert client(app).post("/api/session", json=old_login).status_code == 401
    assert not faces.get(owner, batch_id)["available"]
    assert app.state.services.store.jobs(owner, batch_id)[0].state == "cancelled"
    assert admin.put(f"{base}/password", json={**reset, "administrator_password": "wrong"}).status_code == 400
    assert admin.put(f"{base}/password", json=reset).json() == {"disabled": True, "review_cleared": True}
    new_login = {**old_login, "password": replacement}
    assert client(app).post("/api/session", json=new_login).status_code == 401
    assert admin.put(f"{base}/access", json={"disabled": False}).json()["disabled"] is False
    assert second.get("/api/session").status_code == 401
    assert member.post("/api/session", json=old_login).status_code == 401
    assert member.post("/api/session", json=new_login).status_code == 200
    assert member.get(review_url).json()["batch"] == saved["batch"]
    assert admin.get(review_url).status_code == 404
    with Session(engine) as db:
        password_hash = db.get(UserRow, owner).password_hash
        assert password_hash.startswith("$argon2id$") and replacement not in password_hash


def test_admin_password_reset_revokes_sessions_and_cancels_jobs_while_worker_is_unreachable(accounts, monkeypatch):
    app, _, _, faces = accounts
    admin = setup(app)
    member, _ = invite(admin, app)
    album = imported(member)["album"]
    owner, batch_id = UUID(album["owner_id"]), UUID(album["id"])
    assert member.post(f"/api/batches/{batch_id}/analysis").status_code == 200

    def unavailable(*args):
        raise Conflict("Worker unreachable")

    monkeypatch.setattr(faces, "finish", unavailable)
    replacement = "synthetic-replacement-password"
    response = admin.put(
        f"/api/admin/users/{owner}/password", json={"administrator_password": PASSWORD, "password": replacement}
    )
    assert response.status_code == 200
    assert response.json() == {"disabled": False, "review_cleared": False}
    assert app.state.services.store.jobs(owner, batch_id)[0].state == "cancelled"
    assert member.get("/api/session").status_code == 401
    assert member.post("/api/session", json={"username": "athlete", "password": replacement}).status_code == 200


def test_legacy_account_is_imported_once_with_existing_owner_and_password_changes_revoke_sessions(accounts):
    app, engine, settings, faces = accounts
    legacy = replace(settings, password="legacy-password", username="legacy")
    old_app = create_app(legacy, store=Store(engine), sessions=faces)
    browser = client(old_app)
    assert browser.post("/api/session", json={"username": "legacy", "password": "legacy-password"}).status_code == 200
    batch = imported(browser)
    assert batch["album"]["owner_id"] == str(settings.owner_id)
    second = client(old_app)
    second.post("/api/session", json={"username": "legacy", "password": "legacy-password"})
    assert (
        browser.put(
            "/api/account/password", json={"current_password": "legacy-password", "password": PASSWORD}
        ).status_code
        == 200
    )
    assert second.get("/api/session").status_code == 401
    restarted = client(create_app(legacy, store=Store(engine), sessions=faces))
    assert restarted.post("/api/session", json={"username": "legacy", "password": "legacy-password"}).status_code == 401
    assert restarted.post("/api/session", json={"username": "legacy", "password": PASSWORD}).status_code == 200
    assert restarted.get(f"/api/batches/{batch['album']['id']}").status_code == 200


def test_backup_restore_preserves_new_owner_and_excludes_authentication_state(accounts, tmp_path):
    from zipfile import ZipFile

    from startnummer.app.backup import backup, restore
    from startnummer.app.manage import migrate

    app, engine, settings, faces = accounts
    admin = setup(app)
    batch = imported(admin)
    user = app.state.authentication.accounts.find("admin")[0]
    archive = tmp_path / "account.snbak"
    backup(Store(engine), replace(settings, owner_id=user.id), archive)
    with ZipFile(archive) as stored:
        metadata = stored.read("database.json").decode()
        for excluded in ("sn_users", "sn_sessions", "sn_invitations", "password_hash", "$argon2", PASSWORD):
            assert excluded not in metadata
    recovered_settings = replace(
        settings,
        database_url="sqlite:///" + str(tmp_path / "restored.db"),
        blob_root=tmp_path / "restored",
        owner_id=user.id,
    )
    recovered = create_engine(recovered_settings.database_url)
    try:
        restore(recovered, recovered_settings, archive, migrate=migrate)
        mismatched = create_app(
            replace(recovered_settings, username="wrong-legacy", password=PASSWORD),
            store=Store(recovered),
            sessions=faces,
        )
        response = client(mismatched).get("/api/auth/status")
        assert response.status_code == 409 and "STARTNUMMER_PASSWORD" in response.text
        with Session(recovered) as db:
            assert len(db.scalars(select(UserRow)).all()) == 1
        fresh = create_app(recovered_settings, store=Store(recovered), sessions=faces)
        browser = client(fresh)
        assert browser.post("/api/session", json={"username": "admin", "password": PASSWORD}).status_code == 401
        assert (
            browser.post(
                "/api/auth/setup",
                json={"username": "different", "password": PASSWORD, "code": fresh.state.authentication.setup_code()},
            ).status_code
            == 409
        )
        claimed = setup(fresh)
        assert claimed.get(f"/api/batches/{batch['album']['id']}").status_code == 200
        assert fresh.state.authentication.accounts.find("admin")[0].id == user.id
        assert not claimed.get("/api/auth/status").json()["registration_enabled"]
    finally:
        recovered.dispose()


def test_concurrent_invitation_claims_and_session_expiry(accounts):
    app, engine, _, _ = accounts
    admin = setup(app)
    invitation = admin.post("/api/admin/invitations", json={}).json()

    def register(name):
        with client(app) as visitor:
            return visitor.post(
                "/api/auth/register", json={"username": name, "password": PASSWORD, "invitation": invitation["token"]}
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(register, ["claim-one", "claim-two"]))
    assert sorted(results) == [200, 400]
    with Session(engine) as db, db.begin():
        for session in db.scalars(select(SessionRow)):
            session.expires_at = now() - timedelta(seconds=1)
    assert admin.get("/api/session").status_code == 401


def test_registration_rejects_privilege_fields_and_short_password_without_echoing_secrets(accounts):
    app, _, _, _ = accounts
    admin = setup(app)
    admin.put("/api/admin/registration", json={"revision": 0, "registration_enabled": True})
    body = {"username": "forged", "password": PASSWORD, "is_admin": True}
    response = client(app).post("/api/auth/register", json=body)
    assert response.status_code == 422 and PASSWORD not in response.text
    assert client(app).post("/api/auth/register", json={"username": "short", "password": "weak"}).status_code == 422


def test_installation_import_limits_apply_to_ordinary_users(accounts):
    app, _, _, _ = accounts
    admin = setup(app)
    member, _ = invite(admin, app)
    response = admin.put(
        "/api/admin/settings",
        json={"revision": 0, "max_file_bytes": 1024 * 1024, "max_batch_bytes": 1024 * 1024, "session_ttl": 600},
    )
    assert response.status_code == 200
    from startnummer.app.operations import effective_settings

    scoped = replace(app.state.services.settings, owner_id=app.state.authentication.accounts.find("athlete")[0].id)
    assert effective_settings(app.state.services.store, scoped).session_ttl == 600
    oversized = member.post(
        "/api/batches",
        files=[
            ("photos", ("large.jpg", b"x" * (1024 * 1024 + 1), "image/jpeg")),
            ("roster_file", ("roster.html", HTML, "text/html")),
        ],
    )
    assert oversized.status_code == 400
