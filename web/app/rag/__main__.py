# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

import json
import sys

from app.rag import reindex, search
from app.store.db import get_engine

USAGE = 'Usage: python -m app.rag reindex | search <findings|guidance> "query"'

if __name__ == "__main__":
    if sys.argv[1:2] == ["reindex"]:
        findings, guidance = reindex(get_engine())
        print(f"reindexed {findings} findings, {guidance} guidance records")
    elif len(sys.argv) >= 4 and sys.argv[1] == "search":
        print(json.dumps(search(sys.argv[2], sys.argv[3], k=5), indent=2, default=str))
    else:
        raise SystemExit(USAGE)
