# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

import re
from pathlib import Path

from starlette.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_index_renders_semantic_page():
    r = client.get("/")
    assert r.status_code == 200
    assert '<html lang="en">' in r.text
    assert "<title>Check a page — WA-A11y</title>" in r.text
    assert re.search(r'<main[^>]*\bid="main"', r.text)
    assert 'href="#main"' in r.text


def test_index_ships_no_javascript():
    r = client.get("/")
    assert "<script" not in r.text.lower()
    assert not re.search(r"\son[a-z]+\s*=", r.text, re.IGNORECASE)  # no inline on*= handlers


def test_no_canonical_host_echo():
    r = client.get("/", headers={"host": "evil.example"})
    assert "evil.example" not in r.text


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.text == "ok"


def test_no_sesskey_file_written():
    assert not Path(".sesskey").exists()
    assert not (Path(__file__).parents[1] / ".sesskey").exists()
