import os

from alembic import context
from sqlalchemy import create_engine

from startnummer.adapters.db.schema import Base

config = context.config
if context.is_offline_mode():
    url = os.environ["STARTNUMMER_DATABASE_URL"]
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:

    def migrate(connection):
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()

    supplied = config.attributes.get("connection")
    if supplied is not None:
        migrate(supplied)
    else:
        with create_engine(os.environ["STARTNUMMER_DATABASE_URL"]).connect() as connection:
            migrate(connection)
