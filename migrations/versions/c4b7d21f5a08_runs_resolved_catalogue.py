"""runs resolved catalogue

Revision ID: c4b7d21f5a08
Revises: b0e1d819009d
Create Date: 2026-08-08 10:12:44.108233

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c4b7d21f5a08"
down_revision: str | Sequence[str] | None = "b0e1d819009d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # The server default backfills runs opened before the catalogue was resolved at ingest;
    # every new row carries the real value, written by the ingest route.
    op.add_column(
        "runs",
        sa.Column(
            "resolved_catalogue",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("runs", "resolved_catalogue")
