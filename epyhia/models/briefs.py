import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from epyhia.models import Base


class Brief(Base):
    """The client-data boundary (data-model.md "briefs"). Every fact about a client lives in
    `payload` and nowhere else — Principle I.
    """

    __tablename__ = "briefs"
    __table_args__ = (UniqueConstraint("content_sha256", name="uq_briefs_content_sha256"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String, nullable=False)
    guardrail_decision: Mapped[str] = mapped_column(String, nullable=False)
    guardrail_reason: Mapped[str | None] = mapped_column(String)
    guardrail_model: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
