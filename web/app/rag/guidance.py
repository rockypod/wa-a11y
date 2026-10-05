# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

GUIDANCE_VERSION = "2026-10-03.1"

GUIDANCE: dict = {
    "1.1.1": "Give every meaningful image a text alternative (alt) that says what it shows or "
    'does; use alt="" for decorative images. Icon buttons need an accessible name.',
    "1.3.1": "Use real structure: headings, lists, tables with headers, and form fields with a "
    "<label for> tied to each input. Don't fake structure with styling.",
    "1.4.3": "Text needs 4.5:1 contrast with its background (3:1 for large text).",
    "1.4.6": "For AAA, text needs 7:1 contrast (4.5:1 for large text). Darken text or lighten "
    "the background; check every state (hover, focus, disabled is exempt).",
    "1.4.11": "Controls and their borders, focus rings and meaningful graphics need 3:1 contrast.",
    "2.4.4": "Link text (with its context) must say where the link goes; avoid 'click here'.",
    "2.4.7": "Keyboard focus must always be visible; never remove outlines without a replacement.",
    "2.4.13": "Focus indicator at least 2px thick around the control with 3:1 contrast change.",
    "2.5.5": "Make targets at least 44 by 44 CSS pixels (links in sentences are exempt).",
    "2.5.8": "Make targets at least 24 by 24 CSS pixels or space them apart.",
    "3.3.2": "Every input needs a visible label or instructions; placeholders are not labels.",
    "4.1.2": "Custom controls need a name, role and state exposed to assistive technology; "
    "prefer native HTML elements (button, a, input) over divs with ARIA.",
    "patterns": {
        "aaa-tokens": (
            "1.4.6",
            "WA-A11y AAA colour tokens: text #1a202c on #f8f9fa (15:1), links "
            "#1d5556 (7.5:1), white on #1d5556 buttons (8.45:1). Express hierarchy "
            "with size and weight, not lighter grey.",
        ),
        "forms": (
            "3.3.2",
            "Forms: persistent visible labels above fields, hints linked with "
            "aria-describedby, an error summary linking to each field, input kept on error.",
        ),
        "focus": (
            "2.4.13",
            "Focus ring: 3px solid outline with 3px offset in a colour with 3:1 "
            "contrast in every theme; never outline:none for keyboard users.",
        ),
        "targets": (
            "2.5.5",
            "Navigation, list and standalone links: display inline-flex with "
            "min-height and min-width 44px.",
        ),
    },
}
