# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.store.db import db_url


def sqlite_path(url: str) -> Path:
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        raise ValueError(f"not a SQLite URL: {url}")
    return Path(url[len(prefix) :])


def backup(dest: Path, src: Path | None = None) -> Path:
    src = src or sqlite_path(db_url())
    dest.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(src) as source, sqlite3.connect(dest) as target:
        source.backup(target)
    return dest


def main() -> int:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(f"/data/backups/wa_a11y-{stamp}.db")
    print(backup(dest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
