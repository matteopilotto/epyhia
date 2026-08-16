"""actions result

Revision ID: e7a94d02c6f1
Revises: c4b7d21f5a08
Create Date: 2026-08-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e7a94d02c6f1"
down_revision: str | Sequence[str] | None = "c4b7d21f5a08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Nullable and left NULL for existing rows: nothing durable ever held `execute()`'s
    # return before this column, so a backfill here would be an invention. The 19 publish
    # rows from the outreach incident are reconstructed from the sink's own records by
    # `scripts/backfill_action_results.py` — an operator decision, not a deploy side effect.
    op.add_column(
        "actions",
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("actions", "result")
