# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

"""initial schema"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel  # noqa: F401
from alembic import op

revision: str = "b5991b679034"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scan",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("url", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("level", sa.Enum("AA", "AAA", name="level"), nullable=False),
        sa.Column("engines", sa.JSON(), nullable=False),
        sa.Column("profiles", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("QUEUED", "RUNNING", "DONE", "ERROR", name="scanstatus"),
            nullable=False,
        ),
        sa.Column("tool_versions", sa.JSON(), nullable=False),
        sa.Column("requested_by", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("error", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column("started_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True),
        sa.Column("finished_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("scan", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_scan_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_scan_status"), ["status"], unique=False)
        batch_op.create_index(batch_op.f("ix_scan_url"), ["url"], unique=False)

    op.create_table(
        "finding",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scan_id", sa.Integer(), nullable=False),
        sa.Column("engine", sa.Enum("AXE", "ALFA", name="engine"), nullable=False),
        sa.Column(
            "outcome", sa.Enum("FAIL", "CANT_TELL", "PASS", "ERROR", name="outcome"), nullable=False
        ),
        sa.Column("rule_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("sc", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("wcag_level", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("selector", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("html_snippet", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("message", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("impact", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("profiles", sa.JSON(), nullable=False),
        sa.Column("fingerprint", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(["scan_id"], ["scan.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("finding", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_finding_fingerprint"), ["fingerprint"], unique=False)
        batch_op.create_index(batch_op.f("ix_finding_sc"), ["sc"], unique=False)
        batch_op.create_index(batch_op.f("ix_finding_scan_id"), ["scan_id"], unique=False)

    op.create_table(
        "urlstatus",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("url", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("sc", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "latest_outcome",
            sa.Enum("FAIL", "CANT_TELL", "PASS", "ERROR", name="outcome"),
            nullable=False,
        ),
        sa.Column("last_scan_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["last_scan_id"], ["scan.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url", "sc"),
    )
    with op.batch_alter_table("urlstatus", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_urlstatus_url"), ["url"], unique=False)

    op.create_table(
        "prompt",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scan_id", sa.Integer(), nullable=False),
        sa.Column("finding_id", sa.Integer(), nullable=True),
        sa.Column("text", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["finding_id"], ["finding.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scan_id"], ["scan.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("prompt", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_prompt_scan_id"), ["scan_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("prompt", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_prompt_scan_id"))

    op.drop_table("prompt")
    with op.batch_alter_table("urlstatus", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_urlstatus_url"))

    op.drop_table("urlstatus")
    with op.batch_alter_table("finding", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_finding_scan_id"))
        batch_op.drop_index(batch_op.f("ix_finding_sc"))
        batch_op.drop_index(batch_op.f("ix_finding_fingerprint"))

    op.drop_table("finding")
    with op.batch_alter_table("scan", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_scan_url"))
        batch_op.drop_index(batch_op.f("ix_scan_status"))
        batch_op.drop_index(batch_op.f("ix_scan_created_at"))

    op.drop_table("scan")
