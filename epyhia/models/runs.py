import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from epyhia.models import Base


class Run(Base):
    """One execution against one brief (data-model.md "runs"). Its `id` threads through every
    agent call and every action.
    """

    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brief_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("briefs.id"), nullable=False
    )
    brand_doc_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brand_docs.id")
    )
    prompt_version: Mapped[str] = mapped_column(String, nullable=False)
    grounding_set: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # `brief.products[]` with the slug derived at ingest (research.md R11). Written once,
    # beside the grounding set, and read by the site, by Ops and by `/checkout`.
    resolved_catalogue: Mapped[list] = mapped_column(JSONB, nullable=False)
    budget_usd: Mapped[float] = mapped_column(Numeric, nullable=False)
    spend_usd: Mapped[float] = mapped_column(Numeric, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String, nullable=False)
    alias: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
