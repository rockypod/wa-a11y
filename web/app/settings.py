# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

from dataclasses import dataclass

COOKIE = "wa_a11y_display"

FONTS = {
    "atkinson": "Atkinson Hyperlegible Next (default)",
    "lexend": "Lexend",
    "opendyslexic": "OpenDyslexic",
    "browser": "My browser's own font",
}
THEMES = {
    "device": "Match my device (default)",
    "light": "Light",
    "dark": "Dark",
    "contrast": "Extra contrast",
}
SPACING = {
    "standard": "Standard (default)",
    "wide": "Wider letter, word and line spacing",
}


@dataclass(frozen=True)
class Display:
    font: str = "atkinson"
    theme: str = "device"
    spacing: str = "standard"

    @classmethod
    def from_values(cls, font: str | None, theme: str | None, spacing: str | None) -> "Display":
        d = cls()
        return cls(
            font=font if font in FONTS else d.font,
            theme=theme if theme in THEMES else d.theme,
            spacing=spacing if spacing in SPACING else d.spacing,
        )

    @classmethod
    def from_cookie(cls, raw: str | None) -> "Display":
        parts = (raw or "").split("|")
        return cls.from_values(*(parts + [None] * 3)[:3])

    def to_cookie(self) -> str:
        return f"{self.font}|{self.theme}|{self.spacing}"

    def html_attrs(self) -> dict[str, str]:
        attrs = {}
        if self.font != "atkinson":
            attrs["data-font"] = self.font
        if self.theme != "device":
            attrs["data-theme"] = self.theme
        if self.spacing != "standard":
            attrs["data-spacing"] = self.spacing
        return attrs
