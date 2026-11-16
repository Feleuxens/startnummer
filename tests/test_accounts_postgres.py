"""Atomic account setup and invitation claims in disposable PostgreSQL schemas."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from startnummer.adapters.db.accounts import Accounts
from startnummer.adapters.db.schema import UserRow
from startnummer.app.manage import migrate
from startnummer.core.batch import WorkflowError
from tests.test_database_integration import postgres as postgres
from tests.test_workflow import environment as environment


def test_postgres_setup_and_invitation_claims_are_single_use(postgres, environment):
    service, _ = environment
    migrate(postgres.engine)
    accounts = Accounts(postgres.engine)
    accounts.initialize(replace(service.settings, password=""))

    def setup(name):
        try:
            return accounts.setup(name, "synthetic-hash", uuid4())
        except WorkflowError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(setup, ["first", "second"]))
    admin = next(user for user in results if user)
    assert sum(user is not None for user in results) == 1
    accounts.invite(admin.id, "Synthetic", "a" * 64, 1)

    def register(name):
        try:
            return accounts.register(name, "synthetic-hash", "a" * 64)
        except WorkflowError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(register, ["member-one", "member-two"]))
    assert sum(user is not None for user in results) == 1
    with Session(postgres.engine) as db:
        users = db.scalars(select(UserRow)).all()
        assert len(users) == 2 and sum(user.is_admin for user in users) == 1
