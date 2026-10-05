# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

"""unified result model and assessment results"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel  # noqa: F401
from alembic import op

revision: str = "8fd66209ca51"
down_revision: str | Sequence[str] | None = "0106893a0156"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE = sa.Enum("AUTOMATED", "GUIDED", "MANUAL", name="source")
ENGINE_M1 = sa.Enum("AXE", "ALFA", name="engine")
ENGINE = sa.Enum("AXE", "ALFA", "FASTPASS", name="engine")


def upgrade() -> None:
    op.create_table(
        "assessmentresult",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scan_id", sa.Integer(), nullable=False),
        sa.Column("source", SOURCE, nullable=False),
        sa.Column("checklist_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("checklist_version", sa.Integer(), nullable=False),
        sa.Column("item_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("sc", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("advisory", sa.Boolean(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("PASS", "FAIL", "NEEDS_REVIEW", "NOT_APPLICABLE", name="reviewstatus"),
            nullable=False,
        ),
        sa.Column("reviewer", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("reviewed_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column("notes", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(["scan_id"], ["scan.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scan_id", "checklist_id", "checklist_version", "item_id"),
    )
    with op.batch_alter_table("assessmentresult", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_assessmentresult_scan_id"), ["scan_id"], unique=False)

    with op.batch_alter_table("finding", schema=None) as batch_op:
        batch_op.add_column(sa.Column("source", SOURCE, server_default="AUTOMATED", nullable=False))
        batch_op.add_column(
            sa.Column("advisory", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch_op.alter_column(
            "engine", existing_type=ENGINE_M1, type_=ENGINE, existing_nullable=False
        )

    op.execute("UPDATE finding SET advisory = 1 WHERE sc IS NULL OR wcag_level IS NULL")


def downgrade() -> None:
    op.execute("DELETE FROM finding WHERE engine NOT IN ('AXE', 'ALFA')")
    with op.batch_alter_table("finding", schema=None) as batch_op:
        batch_op.alter_column(
            "engine", existing_type=ENGINE, type_=ENGINE_M1, existing_nullable=False
        )
        batch_op.drop_column("advisory")
        batch_op.drop_column("source")

    with op.batch_alter_table("assessmentresult", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_assessmentresult_scan_id"))

    op.drop_table("assessmentresult")
