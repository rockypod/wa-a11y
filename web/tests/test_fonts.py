# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

import json

from starlette.testclient import TestClient

from app import theme


def test_font_faces_use_base_path(tmp_path, monkeypatch):
    (tmp_path / "fonts.json").write_text(
        json.dumps(
            [
                {
                    "family": "Lexend",
                    "file": "lexend-latin-wght-normal.woff2",
                    "style": "normal",
                    "weight": "100 900",
                    "unicodeRange": "U+0000-00FF",
                }
            ]
        )
    )
    monkeypatch.setenv("WA_A11Y_FONTS", str(tmp_path))
    monkeypatch.setenv("WA_A11Y_BASE_PATH", "/wa-a11y")
    css = theme.font_face_css()
    assert '@font-face{font-family:"Lexend"' in css
    assert 'url("/wa-a11y/static/fonts/lexend-latin-wght-normal.woff2")' in css
    assert "font-display:swap" in css and "unicode-range:U+0000-00FF" in css


def test_missing_fonts_fall_back_quietly(tmp_path, monkeypatch):
    monkeypatch.setenv("WA_A11Y_FONTS", str(tmp_path / "nope"))
    assert theme.font_face_css() == ""


def test_fonts_are_served_and_project_files_are_not(tmp_path):
    from app.main import app

    client = TestClient(app, base_url="https://testserver")
    fonts = theme.fonts_dir()
    if fonts is not None and (fonts / "fonts.json").is_file():
        first = json.loads((fonts / "fonts.json").read_text())[0]["file"]
        r = client.get(f"/static/fonts/{first}")
        assert r.status_code == 200 and r.headers["content-type"] == "font/woff2"
    for path in (
        "/pyproject.toml",
        "/uv.lock",
        "/alembic.ini",
        "/app/main.py",
        "/tests/conftest.py",
        "/app/static/wa-a11y.css",
        "/migrations/env.py",
    ):
        assert client.get(path).status_code == 404, path
