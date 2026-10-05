# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

"""scan blocked_requests"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel  # noqa: F401
from alembic import op

revision: str = "d9d3dfda5174"
down_revision: str | Sequence[str] | None = "b5991b679034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("scan", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("blocked_requests", sa.JSON(), server_default="[]", nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("scan", schema=None) as batch_op:
        batch_op.drop_column("blocked_requests")
