# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

import base64
import hashlib

from starlette.testclient import TestClient

from app.main import app
from app.theme import style_hash, theme_css


def test_theme_is_inlined_not_linked():
    html = TestClient(app).get("/").text
    assert "<style>" in html and "--surface-bg" in html
    assert 'rel="stylesheet"' not in html


def test_style_hash_matches_inline_css():
    digest = base64.b64encode(hashlib.sha256(theme_css().encode()).digest()).decode()
    assert style_hash() == f"'sha256-{digest}'"
