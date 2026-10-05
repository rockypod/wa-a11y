# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

from fasthtml.common import H1, H2, A, Li, P, Ul

from app.ui import SOURCE_URL, page, u, wcag_abbr

ISSUES_URL = f"{SOURCE_URL}/issues"


def statement_page():
    return page(
        "Accessibility statement",
        H1("Accessibility statement"),
        P(
            "We want everyone to be able to use wa-a11y, including people who use a keyboard, "
            "a screen reader, screen magnification, speech input, or their own fonts and colours."
        ),
        H2("Our target"),
        P(
            "Every page of wa-a11y aims to meet ",
            wcag_abbr(),
            " 2.2 at level AAA, the highest level. This goes beyond level AA, the level most "
            "laws ask for.",
        ),
        H2("How we test it"),
        P("Every change to wa-a11y is tested before it is released:"),
        Ul(
            Li(
                "Automated checks: wa-a11y checks its own pages with axe-core and Siteimprove "
                "Alfa at level AAA, in every reading font, colour theme and text spacing, at "
                "desktop width and at 320 pixels wide."
            ),
            Li(
                "Structure checks: with JavaScript turned off, we check what the browser gives to "
                "screen readers: page titles, landmarks, headings, form labels and the order "
                "that the keyboard moves through the page."
            ),
            Li(
                "A person checks the rest with a manual checklist: keyboard use, browser zoom, "
                "and reading order. Automated tools cannot do these checks."
            ),
        ),
        H2("Known limits"),
        Ul(
            Li(
                "Automated tools cannot find every problem, and our structure checks are not a "
                "test with a real screen reader."
            ),
            Li(
                "This statement covers wa-a11y itself, not the web pages you check with it, "
                "and not files you download from it."
            ),
            Li(
                "Some technical results, such as code samples and page addresses, use the words "
                "of the tools that found them and can be hard to read."
            ),
        ),
        H2("Report a problem"),
        P(
            "If something in wa-a11y is hard or impossible for you to use, please tell us. "
            "Say which page it was, what you were trying to do, and what happened. Do not "
            "include private or personal data."
        ),
        Ul(
            Li(A("Report a problem on the wa-a11y issue tracker", href=ISSUES_URL)),
            Li(A("Read the help page", href=u("/help"))),
        ),
        P(
            "You can also ask the person who runs this installation, for example whoever "
            "created your account."
        ),
        P("This statement was last reviewed in October 2026."),
        crumbs=[("Home", "/"), ("Accessibility statement", None)],
    )


def register(rt):
    @rt("/accessibility", methods=["get"])
    def get_accessibility():
        return statement_page()
