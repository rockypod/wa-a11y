# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

"""Scan creator and deletion audit"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel  # noqa: F401
from alembic import op

revision: str = "7e2b4c9d1a63"
down_revision: str | Sequence[str] | None = "3c7a91e2b4d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scandeletion",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scan_id", sa.Integer(), nullable=False),
        sa.Column("deleted_by", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("deleted_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column("rag_cleared", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("scandeletion", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_scandeletion_scan_id"), ["scan_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_scandeletion_rag_cleared"), ["rag_cleared"], unique=False
        )

    with op.batch_alter_table("scan", schema=None) as batch_op:
        batch_op.add_column(sa.Column("created_by", sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f("ix_scan_created_by"), ["created_by"], unique=False)
        batch_op.create_foreign_key(
            "fk_scan_created_by_user", "user", ["created_by"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    with op.batch_alter_table("scan", schema=None) as batch_op:
        batch_op.drop_constraint("fk_scan_created_by_user", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_scan_created_by"))
        batch_op.drop_column("created_by")

    with op.batch_alter_table("scandeletion", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_scandeletion_rag_cleared"))
        batch_op.drop_index(batch_op.f("ix_scandeletion_scan_id"))

    op.drop_table("scandeletion")
