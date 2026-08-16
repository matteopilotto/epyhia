import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from epyhia.models import Base


class Action(Base):
    """The audit log and the idempotency ledger, at once (data-model.md "actions").

    `run_id` and `task_id` are plain UUID columns, not foreign keys: the gate is built
    before `runs` and `tasks` exist (DESIGN.md §12 step 2) and has no upstream dependency
    on the rest of the schema.
    """

    __tablename__ = "actions"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_actions_idempotency_key"),
        CheckConstraint(
            "state <> 'succeeded' OR evidence IS NOT NULL",
            name="ck_actions_succeeded_evidence",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    requested_by: Mapped[str] = mapped_column(String, nullable=False)
    action_type: Mapped[str] = mapped_column(String, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    request: Mapped[dict] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)
    approval_decision: Mapped[str | None] = mapped_column(String)
    approved_by: Mapped[str | None] = mapped_column(String)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    projected_cost_usd: Mapped[float | None] = mapped_column(Numeric)
    cost_usd: Mapped[float | None] = mapped_column(Numeric)
    # `execute()`'s raw return, persisted in the same commit that sets `verifying`, so every
    # re-drive path — sweeper orphan pass, approval resume, operator re-verify (T146) — has
    # something to hand `verify()`. Distinct from `evidence` on purpose: this is the
    # provider's word for what happened; `evidence` is the probe's proof of it (§7.4).
    result: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    evidence: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    verify_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
