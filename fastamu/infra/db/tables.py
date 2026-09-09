from sqlalchemy import BigInteger, Column, Float, String
from sqlalchemy.orm import declared_attr
from sqlmodel import Field, SQLModel


class ProjectionVersionTable(SQLModel, table=True):
    @declared_attr.directive
    def __tablename__(cls) -> str:
        return "fastamu_projection_versions"

    key: str = Field(sa_column=Column(String(64), primary_key=True))
    projection: str = Field(sa_column=Column(String(512), nullable=False))
    target_id: int = Field(sa_column=Column(BigInteger, nullable=False))
    last_version: int = Field(sa_column=Column(BigInteger, nullable=False))
    version_id: str = Field(sa_column=Column(String(32), nullable=False))
    completed_version: int | None = Field(
        default=None, sa_column=Column(BigInteger, nullable=True)
    )
    completed_id: str | None = Field(
        default=None, sa_column=Column(String(32), nullable=True)
    )
    expires_at: float = Field(sa_column=Column(Float, nullable=False))
    updated_at: float = Field(sa_column=Column(Float, nullable=False))
