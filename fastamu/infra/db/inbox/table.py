"""Committed SQL consumer receipts; no message payload or processing lease."""

from sqlalchemy import Column, DateTime, String, Table, func
from sqlmodel import SQLModel

inbox = Table(
    "fastamu_inbox",
    SQLModel.metadata,
    Column("consumer", String(255), primary_key=True),
    Column("message_id", String(255), primary_key=True),
    Column(
        "recorded_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
)
