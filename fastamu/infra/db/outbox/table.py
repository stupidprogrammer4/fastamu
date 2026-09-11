"""Outbox tables registered on the application's migration metadata."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    String,
    Table,
    Text,
    Uuid,
    event,
    func,
)
from sqlmodel import SQLModel

outbox = Table(
    "fastamu_outbox",
    SQLModel.metadata,
    Column("id", Uuid, primary_key=True),
    Column("kind", String(16), nullable=False),
    Column("target", String(255), nullable=False),
    Column("payload", LargeBinary, nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column(
        "available_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("claim_token", Uuid),
    Column("batch_id", Uuid, index=True),
    Column("last_error", Text),
    CheckConstraint("kind IN ('event', 'projection')", name="ck_outbox_kind"),
    Index(
        "ix_fastamu_outbox_ready",
        "available_at",
        "id",
    ),
)

outbox_batches = Table(
    "fastamu_outbox_batches",
    SQLModel.metadata,
    Column("id", Uuid, primary_key=True),
    Column("worker_token", Uuid),
    Column("expires_at", DateTime(timezone=True), nullable=False),
)

outbox_control = Table(
    "fastamu_outbox_control",
    SQLModel.metadata,
    Column("id", Integer, primary_key=True, autoincrement=False),
    info={"preserve_on_test_cleanup": True},
)


@event.listens_for(outbox_control, "after_create")
def initialize_control(table, connection, **kwargs):
    connection.execute(table.insert().values(id=1))
