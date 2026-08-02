import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from epyhia.models import Base


class Order(Base):
    """A paid checkout (data-model.md "orders"). Written in the same transaction that
    records `stripe_event_id`, so a repeat webhook delivery cannot produce a second order
    (FR-032).
    """

    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("stripe_event_id", name="uq_orders_stripe_event_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id"), nullable=False
    )
    stripe_event_id: Mapped[str] = mapped_column(String, nullable=False)
    stripe_session_id: Mapped[str] = mapped_column(String, nullable=False)
    product_slug: Mapped[str] = mapped_column(String, nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String, nullable=False)
    paid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
