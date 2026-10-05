# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

"""privacy consent provenance verification grants"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel  # noqa: F401
from alembic import op

revision: str = "0106893a0156"
down_revision: str | Sequence[str] | None = "df3eaeb821e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "privatedatagrant",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scan_id", sa.Integer(), nullable=False),
        sa.Column("granted_by", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("granted_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column("flags", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["scan_id"], ["scan.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("privatedatagrant", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_privatedatagrant_scan_id"), ["scan_id"], unique=False)

    with op.batch_alter_table("scan", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("privacy_consent", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch_op.add_column(
            sa.Column("authorized_by", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("authorized_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("automated_precheck", sa.Boolean(), server_default=sa.true(), nullable=False)
        )
        batch_op.add_column(
            sa.Column("verified_by", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("verification_date", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True)
        )
        batch_op.add_column(sa.Column("pii_flags", sa.JSON(), server_default="{}", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("scan", schema=None) as batch_op:
        batch_op.drop_column("pii_flags")
        batch_op.drop_column("verification_date")
        batch_op.drop_column("verified_by")
        batch_op.drop_column("automated_precheck")
        batch_op.drop_column("authorized_at")
        batch_op.drop_column("authorized_by")
        batch_op.drop_column("privacy_consent")

    with op.batch_alter_table("privatedatagrant", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_privatedatagrant_scan_id"))

    op.drop_table("privatedatagrant")
