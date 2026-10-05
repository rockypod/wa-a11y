# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

import contextvars
import os
import secrets
import tomllib
from hmac import compare_digest
from pathlib import Path

from fasthtml.common import (
    H2,
    A,
    Abbr,
    Button,
    Div,
    Footer,
    Form,
    Header,
    Input,
    Li,
    Main,
    Nav,
    Ol,
    P,
    Span,
    Strong,
    Title,
    Ul,
)

SITE = "WA-A11y"
SOURCE_URL = "https://github.com/rockypod/wa-a11y"  # AGPLv3 §13: Corresponding Source for users
AUTH_COOKIE = "wa_a11y_auth"
COPYRIGHT = "Copyright (C) 2026 Kevin Miller (rockypod)"
# NOTICE §7(c): a modified deployment names who changed it
MODIFIED_BY_ENV = "WA_A11Y_MODIFIED_BY"


def _version() -> str:
    with (Path(__file__).parents[1] / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)["project"]["version"]


VERSION = f"v{_version()}"

current_user: contextvars.ContextVar = contextvars.ContextVar("current_user", default=None)
current_session: contextvars.ContextVar = contextvars.ContextVar("current_session", default=None)
# WCAG 2.2 SC 2.4.8: marks the current header link with aria-current="page"
current_path: contextvars.ContextVar = contextvars.ContextVar("current_path", default="")

# WCAG 2.2 SC 2.4.4, 3.2.3: fixed header link texts
NAV_LINKS = (
    ("Check a page", "/"),
    ("Recent checks", "/scans"),
    ("Display settings", "/settings"),
    ("Help", "/help"),
    ("About", "/about"),
)


def u(path: str) -> str:
    base = os.environ.get("WA_A11Y_BASE_PATH", "").rstrip("/")
    return f"{base}{path}"


def wcag_abbr() -> Abbr:
    return Abbr("WCAG", title="Web Content Accessibility Guidelines")


def breadcrumbs(*trail: tuple[str, str | None]) -> Nav:
    # WCAG 2.2 SC 2.4.8: last item is the current page (no link, aria-current)
    items = []
    for i, (label, href) in enumerate(trail):
        last = i == len(trail) - 1
        items.append(
            Li(
                Span(label, aria_current="page") if last or not href else A(label, href=u(href)),
                cls="breadcrumb-item",
            )
        )
    return Nav(Ol(*items, cls="breadcrumb"), aria_label="Breadcrumb")


def _nav_link(label: str, path: str, here: str) -> Li:
    current = {"aria_current": "page"} if path == here else {}
    return Li(A(label, href=u(path), cls="nav-link", **current))


def _account(user, session, here: str) -> Nav:
    # WCAG 2.2 SC 2.4.3: its own labelled landmark, after the main navigation
    # CSRF required: sign-out is a state-changing POST
    if user is not None and session is not None:
        items = (
            Li(P("Signed in as ", Strong(user.name or user.email), cls="wa-who")),
            Li(
                Form(
                    csrf_input(session),
                    Button("Sign out", type="submit", cls="btn btn-outline-primary"),
                    method="post",
                    action=u("/logout"),
                )
            ),
        )
    else:
        items = (_nav_link("Sign in", "/login", here),)
    return Nav(Ul(*items, cls="nav wa-account"), aria_label="Account", cls="wa-nav-account")


def site_footer() -> Footer:
    # WCAG 2.2 SC 3.2.3, 3.2.4: identical on every page
    # AGPLv3 §13: source link on every page
    modified_by = os.environ.get(MODIFIED_BY_ENV, "").strip()
    return Footer(
        P(
            f"{SITE} checks web pages against the ",
            wcag_abbr(),
            " 2.2 accessibility guidelines. Automated checks cannot find every problem.",
        ),
        # WCAG 2.2 SC 2.4.3: Source code group first, so Tab never jumps back up between columns
        Nav(
            Div(
                H2("Source code", cls="wa-footer-title"),
                Ul(
                    Li(A("Source code (AGPL-3.0-or-later)", href=SOURCE_URL)),
                    cls="wa-footer-links",
                ),
                P(f"wa-a11y {VERSION}"),
                P(COPYRIGHT),
                P(f"Based on wa-a11y, modified by {modified_by}") if modified_by else None,
                cls="wa-footer-group",
            ),
            Div(
                H2("About wa-a11y", cls="wa-footer-title"),
                Ul(
                    Li(A("About and licence", href=u("/about"))),
                    Li(A("Privacy", href=u("/privacy"))),
                    Li(A("Help", href=u("/help"))),
                    Li(A("Accessibility statement", href=u("/accessibility"))),
                    cls="wa-footer-links",
                ),
                cls="wa-footer-group",
            ),
            aria_label="Footer",
            cls="wa-footer-nav",
        ),
        cls="wa-footer",
    )


def page(
    title: str,
    *content,
    crumbs: list[tuple[str, str | None]] | None = None,
    user=None,
    session=None,
):
    # WCAG 2.2 SC 3.2.3, 3.2.4, 3.2.6: same header, nav and footer on every page
    user = user if user is not None else current_user.get()
    session = session if session is not None else current_session.get()
    here = current_path.get()
    return (
        Title(f"{title} — {SITE}"),
        A("Skip to main content", href="#main", cls="skip-link"),
        Header(
            Nav(
                Ul(
                    Li(A(SITE, href=u("/"), cls="nav-link wa-brand")),
                    *(_nav_link(label, path, here) for label, path in NAV_LINKS),
                    cls="nav",
                ),
                aria_label="Main",
                cls="wa-nav-main",
            ),
            _account(user, session, here),
            cls="wa-header",
        ),
        Main(
            breadcrumbs(*(crumbs or [("Home", None)])),
            *content,
            id="main",
            tabindex="-1",
            cls="wa-main",
        ),
        site_footer(),
    )


def error_summary(errors: dict[str, str]) -> Div:
    # WCAG 2.2 SC 3.3.1, 3.3.3: list every problem at the top, each linking to its field
    return Div(
        P("Please fix the following:", cls="wa-error-title"),
        Ul(*[Li(A(msg, href=f"#{field}")) for field, msg in errors.items()]),
        role="alert",
        id="error-summary",
        cls="alert alert-warning wa-error-summary",
    )


# CSRF: session token, compared in constant time


def csrf_token(session: dict) -> str:
    token = session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf"] = token
    return token


def csrf_input(session: dict) -> Input:
    return Input(type="hidden", name="csrf", value=csrf_token(session))


def csrf_ok(session: dict, submitted: str | None) -> bool:
    expected = session.get("csrf")
    return bool(expected and submitted and compare_digest(expected, submitted))
