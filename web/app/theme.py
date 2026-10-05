# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

import base64
import hashlib
import json
import logging
import os
from functools import cache
from pathlib import Path

log = logging.getLogger("wa_a11y.theme")

_HERE = Path(__file__).parent
_CANDIDATES = (
    _HERE / "static" / "wa-a11y.css",
    _HERE.parents[1] / "styles" / "dist" / "wa-a11y.css",
)
_FONT_DIRS = (_HERE / "static" / "fonts", _HERE.parents[1] / "styles" / "dist" / "fonts")


def css_path() -> Path | None:
    env = os.environ.get("WA_A11Y_CSS")
    if env:
        return Path(env)
    return next((p for p in _CANDIDATES if p.is_file()), None)


def fonts_dir() -> Path | None:
    env = os.environ.get("WA_A11Y_FONTS")
    if env:
        return Path(env)
    return next((p for p in _FONT_DIRS if (p / "fonts.json").is_file()), None)


def font_face_css() -> str:
    directory = fonts_dir()
    if directory is None or not (directory / "fonts.json").is_file():
        log.warning("fonts not found (build them: pnpm -C styles build); system fonts will be used")
        return ""
    base = os.environ.get("WA_A11Y_BASE_PATH", "").rstrip("/")
    rules = []
    for face in json.loads((directory / "fonts.json").read_text(encoding="utf-8")):
        rules.append(
            "@font-face{"
            f'font-family:"{face["family"]}";font-style:{face["style"]};'
            f"font-weight:{face['weight']};font-display:swap;"
            f'src:url("{base}/static/fonts/{face["file"]}") format("woff2");'
            + (f"unicode-range:{face['unicodeRange']};" if face.get("unicodeRange") else "")
            + "}"
        )
    return "".join(rules)


@cache
def theme_css() -> str:
    path = css_path()
    if path is None or not path.is_file():
        log.error("theme CSS not found (build it: pnpm -C styles build); pages will be unstyled")
        return font_face_css()
    return font_face_css() + path.read_text(encoding="utf-8")


def style_hash() -> str:
    digest = hashlib.sha256(theme_css().encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(digest).decode() + "'"
