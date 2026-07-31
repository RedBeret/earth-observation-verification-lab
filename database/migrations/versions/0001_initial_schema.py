"""Create the initial TerraWatch integration schema."""

from __future__ import annotations

from alembic import op

from terrawatch.database import Base

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    for table_name in (
        "dead_letters",
        "processing_attempts",
        "outbox_events",
        "analysis_results",
        "correlations",
        "telemetry_events",
        "scenes",
    ):
        op.execute(f'DROP TABLE IF EXISTS "{table_name}" CASCADE')
