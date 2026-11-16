"""Account HTTP endpoints and administrator authorization."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, Response

from startnummer.adapters.db.accounts import Account
from startnummer.app.auth import SESSION_SECONDS
from startnummer.app.contracts import (
    AccountAdministration,
    AuthStatus,
    InvitationCreated,
    InvitationRequest,
    Login,
    PasswordChange,
    Registration,
    RegistrationPolicy,
    SessionInfo,
    Setup,
)


def account_routes(app, authentication, settings, service_for):
    def principal(request: Request) -> Account:
        user = authentication.authenticate(request.cookies.get("startnummer_session", ""))
        if user is None:
            raise HTTPException(401, "Sign in to Startnummer")
        return user

    User = Annotated[Account, Depends(principal)]

    def administrator(user: User):
        if not user.is_admin:
            raise HTTPException(403, "Administrator access required")
        return user

    Admin = Annotated[Account, Depends(administrator)]

    def info(user):
        service = service_for(user)
        gallery = service.gallery
        url = gallery.public_url() if hasattr(gallery, "public_url") else settings.chevereto_url if gallery else None
        return {"username": user.username, "is_admin": user.is_admin, "gallery_url": url}

    def signed_in(user, response):
        response.set_cookie(
            "startnummer_session",
            authentication.issue(user),
            httponly=True,
            secure=settings.cookie_secure,
            samesite="strict",
            max_age=SESSION_SECONDS,
        )
        return info(user)

    def throttled(request, action, limit):
        peer = request.client.host if request.client else "unknown"
        if not authentication.throttle(f"{action}:{peer}", limit):
            raise HTTPException(429, "Too many attempts; try again in ten minutes", headers={"Retry-After": "600"})

    def clear_review(user):
        service = service_for(user)
        for batch in service.store.list_batches(user.id):
            service.cancel_analysis(user.id, batch["id"])

    @app.get("/api/auth/status", response_model=AuthStatus)
    def auth_status():
        authentication.initialize()
        return authentication.accounts.status()

    @app.post("/api/auth/setup", response_model=SessionInfo)
    def setup(body: Setup, request: Request, response: Response):
        throttled(request, "setup", 20)
        if body.invitation is not None:
            raise HTTPException(400, "Setup does not use an invitation")
        return signed_in(
            authentication.setup(body.code.get_secret_value(), body.username, body.password.get_secret_value()),
            response,
        )

    @app.post("/api/auth/register", response_model=SessionInfo)
    def register(body: Registration, request: Request, response: Response):
        throttled(request, "registration", 20)
        return signed_in(
            authentication.register(
                body.username,
                body.password.get_secret_value(),
                body.invitation.get_secret_value() if body.invitation else None,
            ),
            response,
        )

    @app.post("/api/session", response_model=SessionInfo)
    def login(body: Login, request: Request, response: Response):
        throttled(request, "login", 120)
        if len(body.username) > 128 or len(body.password) > 1024:
            raise HTTPException(401, "Invalid username or password")
        user = authentication.login(body.username, body.password)
        if user is None:
            raise HTTPException(401, "Invalid username or password")
        return signed_in(user, response)

    @app.get("/api/session", response_model=SessionInfo)
    def session_info(user: User):
        return info(user)

    @app.delete("/api/session")
    def logout(user: User, request: Request, response: Response):
        authentication.revoke(user.id, request.cookies.get("startnummer_session"))
        clear_review(user)
        response.delete_cookie("startnummer_session", secure=settings.cookie_secure, httponly=True, samesite="strict")
        return {"signed_out": True}

    @app.delete("/api/account/sessions")
    def revoke_own_sessions(user: User, response: Response):
        authentication.revoke(user.id)
        clear_review(user)
        response.delete_cookie("startnummer_session", secure=settings.cookie_secure, httponly=True, samesite="strict")
        return {"signed_out": True}

    @app.put("/api/account/password", response_model=SessionInfo)
    def change_password(body: PasswordChange, user: User, request: Request, response: Response):
        throttled(request, "password", 120)
        if authentication.login(user.username, body.current_password.get_secret_value()) is None:
            raise HTTPException(400, "The current password is incorrect")
        user = authentication.accounts.change_password(
            user, authentication.hash_password(body.password.get_secret_value())
        )
        clear_review(user)
        return signed_in(user, response)

    @app.get("/api/admin/accounts", response_model=AccountAdministration)
    def accounts(user: Admin):
        return authentication.accounts.administration()

    @app.put("/api/admin/registration", response_model=RegistrationPolicy)
    def registration_policy(body: RegistrationPolicy, user: Admin):
        return authentication.accounts.set_registration(body.revision, body.registration_enabled)

    @app.post("/api/admin/invitations", response_model=InvitationCreated)
    def invite(body: InvitationRequest, user: Admin):
        return authentication.invite(user.id, body.label.strip(), body.hours)

    @app.delete("/api/admin/invitations/{invitation_id}")
    def revoke_invitation(invitation_id: UUID, user: Admin):
        authentication.accounts.revoke_invitation(invitation_id)
        return {"revoked": True}

    @app.delete("/api/admin/users/{user_id}/sessions")
    def revoke_sessions(user_id: UUID, user: Admin):
        target = authentication.accounts.get(user_id)
        authentication.revoke(target.id)
        clear_review(target)
        return {"revoked": True}

    return principal, administrator
