from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from epyhia.models import Base


class AgentCacheEntry(Base):
    """Memoised structured results (data-model.md "agent_cache"). A cache, not a ledger —
    droppable at any time, never read for a correctness decision (FR-048, Principle V).
    """

    __tablename__ = "agent_cache"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
