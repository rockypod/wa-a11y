# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

"""local accounts"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel  # noqa: F401
from alembic import op

revision: str = "df3eaeb821e5"
down_revision: str | Sequence[str] | None = "d9d3dfda5174"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("password_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("role", sa.Enum("ADMIN", "USER", name="role"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("failed_logins", sa.Integer(), nullable=False),
        sa.Column("locked_until", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True),
        sa.Column("created_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column("last_login_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_user_email"), ["email"], unique=True)

    op.create_table(
        "authsession",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column("expires_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("authsession", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_authsession_token_hash"), ["token_hash"], unique=True)
        batch_op.create_index(batch_op.f("ix_authsession_user_id"), ["user_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("authsession", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_authsession_user_id"))
        batch_op.drop_index(batch_op.f("ix_authsession_token_hash"))

    op.drop_table("authsession")
    with op.batch_alter_table("user", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_user_email"))

    op.drop_table("user")
