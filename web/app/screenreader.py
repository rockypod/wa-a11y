# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

from fasthtml.common import H2, H3, A, Li, P, Section, Span, Strong, Ul

from app.assessment.results import checklist
from app.store.models import Engine, Finding, Outcome
from app.wcag import understanding_url

CHECKS = {
    "aria-page-title": "Page title",
    "aria-main-landmark": "One main landmark",
    "aria-h1": "A level 1 heading",
    "aria-heading-order": "Heading levels in order",
    "aria-control-names": "Form controls have names",
    "aria-link-names": "Links have names",
    "aria-button-names": "Buttons have names",
    "aria-landmark-names": "Repeated landmarks have distinct names",
    "aria-tree-partial": "Very large page",
}
STATUS = {Outcome.FAIL: "Problem", Outcome.CANT_TELL: "Check by hand", Outcome.PASS: "Passed"}
SCREEN_READER_ITEMS = (
    "sr-names-roles",
    "sr-live",
    "headings-labels",
    "link-purpose",
    "labels-instructions",
    "focus-order",
)
HIDDEN = "[hidden until permission is confirmed]"
_ORDER = {Outcome.FAIL: 0, Outcome.CANT_TELL: 1, Outcome.PASS: 2}


def split(findings: list[Finding]) -> tuple[list[Finding], list[Finding]]:
    aria = [f for f in findings if f.engine is Engine.ARIA_TREE]
    return [f for f in findings if f.engine is not Engine.ARIA_TREE], aria


def summary_text(aria: list[Finding]) -> str:
    if not aria or any(f.outcome is Outcome.ERROR for f in aria):
        return "Not run"
    n = {o: sum(f.outcome is o for f in aria) for o in _ORDER}
    return (
        f"{n[Outcome.FAIL]} problem{'s' * (n[Outcome.FAIL] != 1)}, "
        f"{n[Outcome.CANT_TELL]} to check by hand, {n[Outcome.PASS]} passed"
    )


def _observation(f: Finding, hide: bool):
    where = HIDDEN if hide else f.selector
    return Li(
        Strong(f"{STATUS.get(f.outcome, 'Check by hand')}: "),
        CHECKS.get(f.rule_id, f.rule_id),
        ". ",
        HIDDEN if hide else f.message,
        Span(" Where: ", where) if where and f.outcome is not Outcome.PASS else None,
    )


def _still_check():
    items = {i["id"]: i for i in checklist()["items"]}
    return (
        H3("Still check with a screen reader", id="screen-reader-manual"),
        P(
            "A person must still use the page with a screen reader, such as NVDA, JAWS or "
            "VoiceOver, to know whether it works. These Assessment checklist items cover it:"
        ),
        Ul(
            *[
                Li(A(items[i]["title"], href=understanding_url(items[i]["sc"][0])))
                for i in SCREEN_READER_ITEMS
                if i in items
            ]
        ),
    )


def section(aria: list[Finding], hide: bool = False):
    not_run = [f for f in aria if f.outcome is Outcome.ERROR]
    shown = sorted(
        (f for f in aria if f.outcome in _ORDER), key=lambda f: (_ORDER[f.outcome], f.rule_id)
    )
    if not aria:
        body = [
            P(
                Strong("Not run. "),
                "This check did not run for this page, so nothing here is a pass.",
            )
        ]
    elif not_run:
        body = [P(Strong("Not run. "), HIDDEN if hide else not_run[0].message)]
    else:
        body = [
            P(Span(summary_text(aria), cls="wa-count"), "."),
            Ul(*[_observation(f, hide) for f in shown]),
        ]
    return Section(
        H2("Screen-reader structure (exposed to assistive technology)", id="screen-reader"),
        P(
            "These checks read the accessibility tree: the page title, landmarks, headings, and "
            "the names of form controls, links and buttons that the browser gives to screen "
            "readers. They are not a screen-reader test, and they are separate from the axe-core "
            "and Alfa results. A problem here needs fixing; a pass does not mean the page works "
            "with a screen reader."
        ),
        *body,
        *_still_check(),
        cls="wa-card card card-body",
    )
