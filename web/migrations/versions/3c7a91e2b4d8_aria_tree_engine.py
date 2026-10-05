# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

"""aria-tree engine: screen-reader structure checks"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3c7a91e2b4d8"
down_revision: str | Sequence[str] | None = "8fd66209ca51"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENGINE_OLD = sa.Enum("AXE", "ALFA", "FASTPASS", name="engine")
ENGINE = sa.Enum("AXE", "ALFA", "FASTPASS", "ARIA_TREE", name="engine")


def upgrade() -> None:
    with op.batch_alter_table("finding", schema=None) as batch_op:
        batch_op.alter_column(
            "engine", existing_type=ENGINE_OLD, type_=ENGINE, existing_nullable=False
        )


def downgrade() -> None:
    op.execute("DELETE FROM finding WHERE engine = 'ARIA_TREE'")
    with op.batch_alter_table("finding", schema=None) as batch_op:
        batch_op.alter_column(
            "engine", existing_type=ENGINE, type_=ENGINE_OLD, existing_nullable=False
        )
