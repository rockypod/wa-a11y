# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

import asyncio
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from fasthtml.common import (
    H1,
    H2,
    H3,
    A,
    Button,
    Caption,
    Code,
    Details,
    Div,
    Fieldset,
    Form,
    FtResponse,
    Input,
    Label,
    Legend,
    Li,
    Nav,
    P,
    Pre,
    Section,
    Span,
    Strong,
    Summary,
    Table,
    Tbody,
    Td,
    Textarea,
    Th,
    Tr,
    Ul,
)
from sqlmodel import Session, func, select
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from app import deletion, jobs, screenreader
from app.accounts import SESSION_HOURS, any_users, authenticate, end_session, start_session
from app.assessment import results as assessment
from app.icons import icon
from app.privacy import (
    CONSENT_TEXT,
    EXPORT_TEXT,
    GRANT_TEXT,
    RULE,
    VERIFY_TEXT,
    Authorization,
    NotAuthorized,
    banner,
    unreleased,
)
from app.prompts import build_prompt, for_prompt
from app.settings import COOKIE, FONTS, SPACING, THEMES, Display
from app.store.db import get_engine
from app.store.models import (
    AssessmentResult,
    Finding,
    Level,
    Outcome,
    PrivateDataGrant,
    Prompt,
    ReviewStatus,
    Scan,
    ScanStatus,
)
from app.ui import (
    AUTH_COOKIE,
    SOURCE_URL,
    csrf_input,
    csrf_ok,
    current_user,
    error_summary,
    page,
    u,
    wcag_abbr,
)
from app.urlguard import UrlRejected, allow_local_targets, check_scan_url
from app.wcag import AAA_MANUAL, SC, sc_key, sc_label, understanding_url

FASTPASS = "accessibility-insights-fastpass"
ENGINE_NAMES = {
    "axe": "axe-core",
    "alfa": "Alfa",
    FASTPASS: "Keyboard checks (Accessibility Insights FastPass style)",
}
DEFAULT_ENGINES = ["axe", "alfa", FASTPASS]
# Labels only: the scan form's allow-list is ENGINE_NAMES
ENGINE_LABELS = {**ENGINE_NAMES, "aria-tree": "Screen-reader structure"}
LEVEL_NAMES = {Level.AA: "WCAG 2.2 Level AA", Level.AAA: "WCAG 2.2 Level AAA"}


def _radio(name, value, label, checked, hint_id):
    rid = f"{name}-{value.lower().replace('.', '').replace('-', '')}"
    return Div(
        Input(
            type="radio",
            name=name,
            id=rid,
            value=value,
            checked=checked,
            cls="form-check-input",
            aria_describedby=hint_id,
        ),
        Label(label, fr=rid, cls="form-check-label"),
        cls="form-check",
    )


def _checkbox(name, value, label, checked, hint_id, invalid=False):
    cid = f"{name}-{value}"
    return Div(
        Input(
            type="checkbox",
            name=name,
            id=cid,
            value=value,
            checked=checked,
            cls="form-check-input is-invalid" if invalid else "form-check-input",
            aria_invalid="true" if invalid else None,
            aria_describedby=hint_id,
        ),
        Label(label, fr=cid, cls="form-check-label"),
        cls="form-check",
    )


def privacy_notice():
    # Privacy rule: shown on the check page and every results page
    return Section(
        H2("Privacy rule", id="privacy-rule"),
        P(Strong(RULE)),
        P(
            "Only check components and web pages — never data sets or documents with personal "
            "records. If a check finds potential private data it is hidden until someone with "
            "permission confirms, and every report needs a person to verify it. ",
            A("How wa-a11y keeps data private", href=u("/privacy")),
            ".",
        ),
        cls="alert wa-rule",
        aria_labelledby="privacy-rule",
    )


def _checkbox_row(name, text, checked=False, invalid=False, described=None):
    return Div(
        Input(
            type="checkbox",
            name=name,
            id=name,
            value="yes",
            checked=checked,
            required=True,
            cls="form-check-input is-invalid" if invalid else "form-check-input",
            aria_invalid="true" if invalid else None,
            aria_describedby=described,
        ),
        Label(text, fr=name, cls="form-check-label"),
        cls="form-check wa-consent",
    )


def scan_form(session, values=None, errors=None):
    values = values or {}
    errors = errors or {}
    level = values.get("level", Level.AA.value)
    engines = values.get("engines", DEFAULT_ENGINES)

    url_desc = "url-hint" + (" url-error" if "url" in errors else "")
    bad_engines = "engines" in errors
    engines_desc = "engines-hint" + (" engines-error" if bad_engines else "")
    return Form(
        csrf_input(session),
        Div(
            Label("Web address of the page to check", fr="url", cls="form-label"),
            P(
                # WCAG 2.2 SC 1.4.10: URL on its own line, wrapping anywhere (no sideways scroll)
                "For example: ",
                Code("https://www.example.com/"),
                A("Other kinds of addresses", href=u("/help#addresses")),
                id="url-hint",
                cls="form-text",
            ),
            P(errors["url"], id="url-error", cls="invalid-feedback") if "url" in errors else None,
            Input(
                type="url",
                name="url",
                id="url",
                value=values.get("url", ""),
                required=True,
                autocomplete="url",
                spellcheck="false",
                cls="form-control is-invalid" if "url" in errors else "form-control",
                aria_describedby=url_desc,
                aria_invalid="true" if "url" in errors else None,
            ),
            cls="wa-field",
        ),
        Fieldset(
            Legend("Which standard should the page meet?"),
            P(
                "Level AA is the usual standard for public websites. "
                "Level AAA is stricter; some of its checks need a person, not a tool.",
                id="level-hint",
                cls="form-text",
            ),
            _radio(
                "level",
                Level.AA.value,
                LEVEL_NAMES[Level.AA],
                level == Level.AA.value,
                "level-hint",
            ),
            _radio(
                "level",
                Level.AAA.value,
                LEVEL_NAMES[Level.AAA],
                level == Level.AAA.value,
                "level-hint",
            ),
            cls="wa-field",
        ),
        Fieldset(
            Legend("Which checking tools should run?"),
            P(
                "axe-core and Alfa are two checking tools. They find different problems, "
                "so using both is recommended. Keyboard checks press the Tab key through the "
                "page to find keyboard traps, controls the keyboard cannot reach and missing "
                "focus indicators.",
                id="engines-hint",
                cls="form-text",
            ),
            P(errors["engines"], id="engines-error", cls="invalid-feedback")
            if "engines" in errors
            else None,
            Div(
                _checkbox(
                    "engines", "axe", "axe-core", "axe" in engines, engines_desc, bad_engines
                ),
                _checkbox("engines", "alfa", "Alfa", "alfa" in engines, engines_desc, bad_engines),
                _checkbox(
                    "engines",
                    FASTPASS,
                    ENGINE_NAMES[FASTPASS],
                    FASTPASS in engines,
                    engines_desc,
                    bad_engines,
                ),
                id="engines",
                tabindex="-1",
            ),
            cls="wa-field",
        ),
        Fieldset(
            Legend("Permission to scan"),
            P(errors["consent"], id="consent-error", cls="invalid-feedback")
            if "consent" in errors
            else None,
            _checkbox_row(
                "consent",
                CONSENT_TEXT,
                values.get("consent") == "yes",
                "consent" in errors,
                "consent-error" if "consent" in errors else None,
            ),
            P(
                "Authorizing as: ",
                Strong(getattr(current_user.get(), "email", "you")),
                cls="form-text",
            ),
            cls="wa-field",
        ),
        Button("Start check", type="submit", cls="btn btn-primary"),
        method="post",
        action=u("/scans"),
        novalidate=True,  # WCAG 2.2 SC 3.3.1, 3.3.3: server-side error messages
    )


RECENT_ON_HOME = 5
SCANS_PER_PAGE = 25


def _delete_link(scan: Scan, back: str):
    # WCAG 2.2 SC 2.4.4, 2.4.9: the link text names the check, so every Delete link is unique
    if scan.status in deletion.PENDING or not deletion.may_delete(current_user.get(), scan):
        return None
    return A(
        f"Delete check {scan.id}",
        href=u(f"/scans/{scan.id}/delete?next={quote(back, safe='/')}"),
    )


def _scan_list(scans, back: str = "/scans"):
    return Ul(
        *[
            Li(
                A(
                    f"Check {sc.id}: {sc.url} — {LEVEL_NAMES[sc.level]} — {status_text(sc)}",
                    href=u(f"/scans/{sc.id}"),
                ),
                _delete_link(sc, back),
                cls="list-group-item",
            )
            for sc in scans
        ],
        cls="list-group wa-recent",
    )


def deleted_notice(raw: str | None):
    # Shown only to the deleter the audit log records: a crafted link cannot announce a deletion
    user = current_user.get()
    if user is None or not raw or not raw.isdecimal() or len(raw) > 9:
        return None
    with Session(get_engine()) as s:
        who = deletion.deleted_by(s, int(raw))
    if who is None or who != user.email:
        return None
    return Div(
        P(f"Check {int(raw)} was deleted."),
        role="status",
        cls="alert alert-success wa-status",
    )


def recent_scans():
    with Session(get_engine()) as s:
        scans = s.exec(select(Scan).order_by(Scan.id.desc()).limit(RECENT_ON_HOME)).all()
    if not scans:
        return P("No checks have been run yet.")
    return (
        _scan_list(scans, back="/"),
        P(A("See all recent checks", href=u("/scans"), cls="wa-standalone")),
    )


def _page_path(n: int) -> str:
    return "/scans" if n == 1 else f"/scans?page={n}"


def _page_href(n: int) -> str:
    return u(_page_path(n))


def pagination(current: int, last: int):
    # WCAG 2.2 SC 2.4.9: every pagination link names its target page
    if last <= 1:
        return None
    shown = sorted({1, last, *range(max(1, current - 2), min(last, current + 2) + 1)})
    items = []
    if current > 1:
        items.append(
            Li(A("Previous page", href=_page_href(current - 1), cls="page-link"), cls="page-item")
        )
    prev = 0
    for n in shown:
        if n - prev > 1:
            items.append(Li("…", cls="page-item wa-page-gap", aria_hidden="true"))
        if n == current:
            items.append(
                Li(Span(f"Page {n}", cls="page-link", aria_current="page"), cls="page-item active")
            )
        else:
            items.append(Li(A(f"Page {n}", href=_page_href(n), cls="page-link"), cls="page-item"))
        prev = n
    if current < last:
        items.append(
            Li(A("Next page", href=_page_href(current + 1), cls="page-link"), cls="page-item")
        )
    return Nav(Ul(*items, cls="pagination"), aria_label="Pagination")


def scans_page(number: int, notice=None):
    with Session(get_engine()) as s:
        total = s.exec(select(func.count()).select_from(Scan)).one()
        last = max(1, -(-total // SCANS_PER_PAGE))
        if number < 1 or number > last:
            return None
        scans = s.exec(
            select(Scan)
            .order_by(Scan.id.desc())
            .offset((number - 1) * SCANS_PER_PAGE)
            .limit(SCANS_PER_PAGE)
        ).all()
    title = "Recent checks" if last == 1 else f"Recent checks, page {number} of {last}"
    return page(
        title,
        H1("Recent checks"),
        notice,
        P(f"Page {number} of {last}. Newest checks first.") if last > 1 else None,
        _scan_list(scans, _page_path(number)) if scans else P("No checks have been run yet."),
        pagination(number, last),
        P(A("Check a page", href=u("/"), cls="wa-standalone")),
        crumbs=[("Home", "/"), ("Recent checks", None)]
        if number == 1
        else [("Home", "/"), ("Recent checks", "/scans"), (f"Page {number}", None)],
    )


def home_page(session, values=None, errors=None, notice=None):
    return page(
        "Check a page",
        H1("Check a web page for accessibility"),
        notice,
        P(
            "Enter the address of a public web page. We will check it with automated tools "
            "and list the problems found, grouped by guideline."
        ),
        privacy_notice(),
        error_summary(errors) if errors else None,
        Section(
            H2("Start a check", id="start"),
            scan_form(session, values, errors),
            aria_labelledby="start",
        ),
        Section(H2("Recent checks", id="recent"), recent_scans(), aria_labelledby="recent"),
    )


def status_text(scan: Scan) -> str:
    return {
        ScanStatus.QUEUED: "Waiting to start",
        ScanStatus.RUNNING: "Checking now",
        ScanStatus.DONE: "Finished",
        ScanStatus.ERROR: "Could not finish",
    }[scan.status]


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _queue_place(position: tuple[int, int] | None):
    # WCAG 2.2 SC 1.3.1, 4.1.2: queue place as text, not a progress bar
    if position is None:
        return None
    place, waiting = position
    ahead = place - 1
    return P(
        Strong("Place in the queue: "),
        f"{ordinal(place)} of {waiting} waiting. ",
        "Yours is the next check to start. "
        if ahead == 0
        else f"{ahead} check{'s' * (ahead != 1)} will start before yours. ",
        "Choose Check again to see your new place.",
    )


def _wait_hint():
    seconds = round(jobs.wait_seconds())
    if seconds <= 0:
        return None
    return P(
        f"When you choose Check again, this page waits up to {seconds} "
        f"second{'s' * (seconds != 1)} for the check to finish. If it finishes, you see the "
        "results. If not, you see this page again."
    )


def _pending(scan: Scan, position: tuple[int, int] | None = None):
    return (
        H1("Your check is in progress"),
        P(
            Strong("Status: "),
            status_text(scan),
            ". ",
            "Checks usually take under a minute. This page does not refresh by itself.",
            role="status",
        ),
        _queue_place(position),
        _wait_hint(),
        Form(
            Input(type="hidden", name="wait", value="1"),
            Button("Check again", type="submit", cls="btn btn-primary"),
            method="get",
            action=u(f"/scans/{scan.id}"),
        ),
    )


def _failed(scan: Scan, session):
    return (
        H1("The check could not finish"),
        P(scan.error or "Something went wrong.", cls="alert alert-warning wa-notice"),
        P("You can try again. If it keeps failing, the page may be blocking automated checks."),
        Form(
            csrf_input(session),
            Input(type="hidden", name="url", value=scan.url),
            Input(type="hidden", name="level", value=scan.level.value),
            *[Input(type="hidden", name="engines", value=e) for e in scan.engines],
            Button("Try again", type="submit", cls="btn btn-primary"),
            method="post",
            action=u("/scans"),
        ),
    )


def _finding(f: Finding, hide: bool = False, number: int = 1, open_: bool = False):
    if hide:
        f = f.model_copy(
            update={
                "selector": "[hidden until permission is confirmed]",
                "html_snippet": "[hidden until permission is confirmed]",
                "message": "[hidden until permission is confirmed]",
            }
        )
    scs = (f.sc or "").split(",")
    also = [s for s in scs[1:] if s]
    review = f.outcome is Outcome.CANT_TELL
    return Details(
        # WCAG 2.2 SC 1.1.1: number and outcome are real text; the icons are decorative
        Summary(
            icon("question-circle" if review else "exclamation-triangle"),
            Span(
                Span(f"Problem {number}", cls="wa-num"),
                f": {ENGINE_LABELS[f.engine.value]}: {f.rule_id}"
                + (" — needs a person or GitHub Copilot CLI to check" if review else ""),
                cls="wa-finding-title",
            ),
            icon("chevron-right", "wa-chev-closed"),
            icon("chevron-down", "wa-chev-open"),
        ),
        Ul(
            Li(Strong("Where on the page: "), Code(f.selector or "not reported")),
            Li(
                Strong("What the tool said: "),
                f.message
                or (
                    "The tool could not decide this automatically. Check it yourself, "
                    "or ask GitHub Copilot CLI using the request in the "
                    "Fix with GitHub Copilot CLI section."
                    if f.outcome is Outcome.CANT_TELL
                    else "No details were given."
                ),
            ),
            Li(Strong("Seen at screen size: "), ", ".join(f.profiles) or "not reported"),
            Li(Strong("Also relates to: "), ", ".join(sc_label(s) for s in also)) if also else None,
            Li(Strong("Severity (axe-core only): "), f.impact) if f.impact else None,
        ),
        P(Strong("The page's code (shown as text):")),
        Pre(Code(f.html_snippet or "not reported")),  # untrusted page content: always escaped
        open=open_,
        cls="wa-finding",
    )


OPEN_MAX = 5


def _group(sc: str, items: list[Finding], hide: bool = False, first: int = 1):
    fails = sum(f.outcome is Outcome.FAIL for f in items)
    review = sum(f.outcome is Outcome.CANT_TELL for f in items)
    counts = ", ".join(
        part
        for part in (
            f"{fails} problem{'s' * (fails != 1)}" if fails else "",
            f"{review} to check by hand" if review else "",
        )
        if part
    )
    return Section(
        H3(
            sc_label(sc) if sc in SC else "Not linked to a guideline",
            id=f"sc-{sc.replace('.', '-')}",
        ),
        P(
            Span(counts, cls="wa-count"),
            " · ",
            A(f"About {sc} (W3C)", href=understanding_url(sc)) if sc in SC else "",
        ),
        *[_finding(f, hide, first + i, open_=len(items) <= OPEN_MAX) for i, f in enumerate(items)],
        cls="wa-sc card card-body",
    )


def provenance_banner(scan: Scan):
    # Privacy rule: print styles must never hide .wa-provenance
    who = scan.authorized_by or "unknown (checked before authorization was required)"
    return Div(P(Strong(banner(who))), cls="alert alert-info wa-provenance", id="provenance")


def hidden_private_data(scan: Scan, grants: list[PrivateDataGrant]) -> bool:
    # Kinds flagged after a grant hide the evidence and block verification and export
    return bool(unreleased(scan.pii_flags, [g.flags for g in grants]))


def private_data_section(scan: Scan, grants: list[PrivateDataGrant], session):
    if not scan.pii_flags and not grants:
        return None
    kinds = Ul(
        *[
            Li(f"{kind}: ", Span(str(n), cls="wa-count badge rounded-pill"))
            for kind, n in scan.pii_flags.items()
        ]
    )
    granted = [
        P(
            Strong(
                f"{g.granted_by} allowed access to potential private data on "
                f"{g.granted_at:%Y-%m-%d %H:%M} UTC."
            ),
            cls="wa-grant",
        )
        for g in grants
    ]
    if not hidden_private_data(scan, grants):
        return Section(
            H2("Potential private data", id="private-data"),
            P("The tools found content that may be private:"),
            kinds,
            *granted,
            cls="wa-card card card-body",
        )
    new = unreleased(scan.pii_flags, [g.flags for g in grants])
    return Section(
        H2("Potential private data detected", id="private-data"),
        P(
            "The tools or a reviewer's notes found content that may be private. It is hidden "
            "until someone with permission confirms. wa-a11y should only be used on components "
            "and web pages."
        ),
        kinds,
        *granted,
        P(
            "New since the last permission: ",
            ", ".join(new),
            ". Confirm permission again before this report can be verified or exported.",
        )
        if grants
        else None,
        Form(
            csrf_input(session),
            _checkbox_row("grant", GRANT_TEXT),
            Button("Confirm and show the results", type="submit", cls="btn btn-primary"),
            method="post",
            action=u(f"/scans/{scan.id}/grant"),
        ),
        cls="alert alert-warning wa-notice wa-card",
    )


def _verification_section(scan: Scan, hidden: bool, session, done: tuple[int, int] = (0, 0)):
    if scan.verified_by:
        return P(
            Strong(
                f"Checked by a person: {scan.verified_by} on "
                f"{scan.verification_date:%Y-%m-%d %H:%M} UTC."
            ),
            cls="wa-verified",
        )
    body = [
        H2("Human verification required", id="verify-heading"),
        P(
            "These results are an automated pre-check. A person must review them before the "
            "report can be shared or exported."
        ),
        P(
            "Checks a person must do: ",
            assessment.progress_text(*done),
            ". Recording them is recommended, but not required to verify.",
        ),
    ]
    if hidden:
        body.append(P("First confirm permission for the potential private data above."))
    else:
        body.append(
            Form(
                csrf_input(session),
                _checkbox_row("verify", VERIFY_TEXT),
                Button("Record my verification", type="submit", cls="btn btn-primary"),
                method="post",
                action=u(f"/scans/{scan.id}/verify"),
            )
        )
    return Section(
        *body, cls="alert alert-warning wa-notice wa-card", aria_labelledby="verify-heading"
    )


def _summary_row(label: str, *value):
    # WCAG 2.2 SC 1.3.1: the label is the row's header cell
    return Tr(Th(label, scope="row"), Td(*value))


def _results(
    scan: Scan,
    findings: list[Finding],
    grants: list[PrivateDataGrant],
    session,
    reviewed: dict[str, AssessmentResult] | None = None,
):
    hidden = hidden_private_data(scan, grants)
    reviewed = reviewed or {}
    done = assessment.progress(scan, reviewed)
    verified = scan.verified_by is not None
    exportable = verified and not hidden
    requests = bool(for_prompt(findings))
    findings, aria = screenreader.split(findings)
    fails = [f for f in findings if f.outcome is Outcome.FAIL]
    review = [f for f in findings if f.outcome is Outcome.CANT_TELL]
    groups: dict[str, list[Finding]] = defaultdict(list)
    for f in sorted(findings, key=lambda f: (f.outcome is not Outcome.FAIL, f.rule_id)):
        groups[(f.sc or "").split(",")[0]].append(f)
    by_engine = {e: sum(f.engine.value == e for f in fails) for e in scan.engines}

    summary = Section(
        H2("Summary", id="summary"),
        Table(
            Caption("What was checked and what the tools found"),
            Tbody(
                _summary_row("Page", A(scan.url, href=scan.url, cls="wa-standalone")),
                _summary_row("Standard", LEVEL_NAMES[scan.level]),
                _summary_row(
                    "Problems found",
                    Span(str(len(fails)), cls="wa-count badge rounded-pill"),
                    " (",
                    "; ".join(f"{ENGINE_LABELS[e]}: {n}" for e, n in by_engine.items()),
                    ")",
                ),
                _summary_row(
                    "Items for a person or GitHub Copilot CLI to check",
                    Span(str(len(review)), cls="wa-count badge rounded-pill"),
                ),
                _summary_row(
                    "Screen-reader structure",
                    A(screenreader.summary_text(aria), href="#screen-reader"),
                ),
                _summary_row(
                    "Tools used", ", ".join(f"{k} {v}" for k, v in scan.tool_versions.items())
                )
                if scan.tool_versions
                else None,
            ),
            cls="table wa-summary",
        ),
        P(
            "These are the automated tools' results only. Checks recorded by a person are "
            "counted separately, under Checks a person must do."
        ),
        P(
            "No problems were found by the automated tools. "
            "This does not prove the page meets the standard: some checks need a person."
            if not fails
            else "Each problem below is numbered and grouped by the guideline it breaks. "
            "Open an item to see where it is and what the tool reported. Guidelines with more "
            f"than {OPEN_MAX} items start with their items closed."
        ),
        cls="wa-card card card-body",
    )
    blocked = (
        Section(
            H2("Parts of the page we did not load", id="blocked"),
            P(
                "For safety, the checker does not contact internal or private network addresses. "
                "These requests from the page were skipped:"
            ),
            P(
                Strong("Requests skipped: "),
                Span(str(len(scan.blocked_requests)), cls="wa-count badge rounded-pill"),
            ),
            Ul(
                *[Li(Code(b), cls="list-group-item") for b in scan.blocked_requests],
                cls="list-group wa-blocked",
            ),
            cls="wa-card card card-body",
        )
        if scan.blocked_requests
        else None
    )
    marks = {s: sum(r.status is s for r in reviewed.values()) for s in ReviewStatus}
    manual = Section(
        H2("Checks a person must do", id="manual"),
        P(
            "Recorded by people, separately from the automated results: ",
            Strong(assessment.progress_text(*done)),
            f" ({marks[ReviewStatus.FAIL]} fail, {marks[ReviewStatus.NEEDS_REVIEW]} need review)."
            if reviewed
            else ".",
        ),
        P(
            A(
                "Record the checks a person must do",
                href=u(f"/scans/{scan.id}/assessment"),
                cls="wa-standalone",
            )
        ),
        P(
            "Automated tools cannot confirm these Level AAA guidelines. Check them by hand:"
            if scan.level is Level.AAA
            else "Automated tools cannot find every problem. "
            "A person should also check the page with "
            "a keyboard, a screen reader and zoom."
        ),
        Ul(
            *[
                Li(A(sc_label(sc), href=understanding_url(sc)), cls="list-group-item")
                for sc in AAA_MANUAL
            ],
            cls="list-group",
        )
        if scan.level is Level.AAA
        else None,
        cls="wa-card card card-body",
    )
    order = sorted(groups, key=lambda s: sc_key(s) or (99,))
    firsts = [1 + sum(len(groups[sc]) for sc in order[:i]) for i in range(len(order))]
    details = Section(
        H2("Problems by guideline", id="details"),
        *[_group(sc, groups[sc], hidden, n) for sc, n in zip(order, firsts, strict=True)]
        if groups
        else [P("Nothing to list.")],
    )
    copilot = Section(
        H2("Fix with GitHub Copilot CLI", id="copilot"),
        P("A ready-made request for GitHub Copilot CLI that lists every problem with its location.")
        if requests
        else P("There is nothing to fix."),
        Ul(Li(A("Get the GitHub Copilot CLI request", href=u(f"/scans/{scan.id}/export"))))
        if requests and exportable
        else P("The request becomes available after the steps above are complete.", cls="form-text")
        if requests
        else None,
        cls="wa-card card card-body",
    )
    return (
        provenance_banner(scan),
        H1("Check results"),
        privacy_notice(),
        private_data_section(scan, grants, session),
        _verification_section(scan, hidden, session, done),
        summary,
        blocked,
        details,
        screenreader.section(aria, hidden),
        copilot,
        manual,
        P(A("Check another page", href=u("/"), cls="wa-standalone")),
    )


def _choice(name, value, label, checked, label_cls=None):
    rid = f"{name}-{value}"
    return Div(
        Input(
            type="radio", name=name, id=rid, value=value, checked=checked, cls="form-check-input"
        ),
        Label(label, fr=rid, cls=f"form-check-label {label_cls or ''}".strip()),
        cls="form-check",
    )


def settings_page(session, current: Display, saved=False, error=None):
    return page(
        "Display settings",
        H1("Display settings"),
        Div(
            P("Your display settings are saved."),
            role="status",
            cls="alert alert-success wa-status",
        )
        if saved
        else None,
        error_summary({"font-atkinson": error}) if error else None,
        P("Choose how this site looks for you. Your choices are kept in this browser only."),
        Form(
            csrf_input(session),
            Fieldset(
                Legend("Reading font"),
                P("Each option is shown in its own font.", id="font-hint", cls="form-text"),
                P(error, id="settings-error", cls="invalid-feedback") if error else None,
                *[
                    _choice("font", k, v, current.font == k, f"wa-font-{k}")
                    for k, v in FONTS.items()
                ],
                cls="wa-field",
                aria_describedby="settings-error" if error else None,
            ),
            Fieldset(
                Legend("Colours"),
                *[_choice("theme", k, v, current.theme == k) for k, v in THEMES.items()],
                cls="wa-field",
            ),
            Fieldset(
                Legend("Text spacing"),
                *[_choice("spacing", k, v, current.spacing == k) for k, v in SPACING.items()],
                cls="wa-field",
            ),
            P(
                "Changes apply when you save. This site never uses moving animations.",
                cls="form-text",
            ),
            Button("Save settings", type="submit", cls="btn btn-primary"),
            method="post",
            action=u("/settings"),
        ),
        crumbs=[("Home", "/"), ("Display settings", None)],
    )


MAX_FORM_BYTES = 16 * 1024  # Refuse oversized bodies before parsing


def _too_big(req: Request):
    try:
        length = int(req.headers.get("content-length", "0"))
    except ValueError:
        length = MAX_FORM_BYTES + 1
    if length > MAX_FORM_BYTES or "chunked" in req.headers.get("transfer-encoding", "").lower():
        return HTMLResponse("That request was too large.", status_code=413)
    return None


RATE_LIMIT = 10
RATE_WINDOW = 600


def _rate_ok(email: str) -> bool:
    # Counted in the database: clearing cookies must not reset the limit
    since = datetime.now(UTC) - timedelta(seconds=RATE_WINDOW)
    with Session(get_engine()) as s:
        recent = s.exec(
            select(func.count())
            .select_from(Scan)
            .where(Scan.requested_by == email, Scan.created_at >= since)
        ).one()
    return recent < RATE_LIMIT


def _safe_next(target: str | None) -> str:
    # Allow-list only: no open redirect via //evil.example or schemes
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return "/"
    return target


def login_page(session, values=None, error=None, status=200):
    values = values or {}
    with Session(get_engine()) as s:
        has_users = any_users(s)
    form = Form(
        csrf_input(session),
        Input(type="hidden", name="next", value=values.get("next", "/")),
        Div(
            Label("Email address", fr="email", cls="form-label"),
            P(error, id="email-error", cls="invalid-feedback") if error else None,
            Input(
                type="email",
                name="email",
                id="email",
                value=values.get("email", ""),
                autocomplete="username",
                required=True,
                cls="form-control is-invalid" if error else "form-control",
                aria_describedby="email-error" if error else None,
                aria_invalid="true" if error else None,
            ),
            cls="wa-field",
        ),
        Div(
            Label("Password", fr="password", cls="form-label"),
            P(
                "You can paste your password or use a password manager.",
                id="password-hint",
                cls="form-text",
            ),
            Input(
                type="password",
                name="password",
                id="password",
                autocomplete="current-password",
                required=True,
                cls="form-control",
                aria_describedby="password-hint",
            ),
            cls="wa-field",
        ),
        Button("Sign in", type="submit", cls="btn btn-primary"),
        method="post",
        action=u("/login"),
        novalidate=True,
    )
    body = page(
        "Sign in",
        H1("Sign in"),
        error_summary({"email": error}) if error else None,
        P(f"You stay signed in for {SESSION_HOURS} hours, or until you sign out."),
        form
        if has_users
        else P(
            "No accounts exist yet. An administrator creates the first one on the server with: ",
            Code("python -m app.accounts create you@example.com --admin"),
        ),
        crumbs=[("Home", "/"), ("Sign in", None)],
        user=None,
        session=session,
    )
    return FtResponse(body, status_code=status) if status != 200 else body


_SCANS_PAGE = re.compile(r"/scans\?page=([1-9][0-9]{0,5})")


def return_target(raw: str | None) -> str:
    # Allow-list of app paths only: no open redirect
    if raw in ("/", "/scans"):
        return raw
    if raw and (m := _SCANS_PAGE.fullmatch(raw)):
        return _page_path(int(m.group(1)))
    return "/scans"


def _after_delete(back: str, scan_id: int) -> str:
    if back == "/":
        return f"/?deleted={scan_id}"
    m = _SCANS_PAGE.fullmatch(back)
    number = int(m.group(1)) if m else 1
    with Session(get_engine()) as s:
        total = s.exec(select(func.count()).select_from(Scan)).one()
    number = min(number, max(1, -(-total // SCANS_PER_PAGE)))
    sep = "&" if number > 1 else "?"
    return f"{_page_path(number)}{sep}deleted={scan_id}"


def _delete_crumbs(scan_id: int, last: str = "Delete"):
    return [
        ("Home", "/"),
        ("Recent checks", "/scans"),
        (f"Check {scan_id}", f"/scans/{scan_id}"),
        (last, None),
    ]


def delete_refused(why: deletion.Refusal, scan_id: int):
    if why is deletion.Refusal.MISSING:
        body = page(
            "Check not found",
            H1(f"There is no check {scan_id}"),
            P("It may already have been deleted."),
            P(A("Go to recent checks", href=u("/scans"), cls="wa-standalone")),
            crumbs=[("Home", "/"), ("Recent checks", "/scans"), ("Check not found", None)],
        )
        return FtResponse(body, status_code=404)
    if why is deletion.Refusal.FORBIDDEN:
        title = f"You cannot delete check {scan_id}"
        reason = (
            "Only the person who started a check, or an administrator, can delete it. Checks "
            "started before this rule existed can only be deleted by an administrator."
        )
        status = 403
    else:
        title = f"Check {scan_id} cannot be deleted yet"
        reason = (
            "It is still waiting to start or being checked. A check can only be deleted once "
            "it has finished."
        )
        status = 409
    body = page(
        title,
        H1(title),
        P(reason),
        P(A(f"Go to check {scan_id}", href=u(f"/scans/{scan_id}"), cls="wa-standalone")),
        crumbs=_delete_crumbs(scan_id, "Cannot delete"),
    )
    return FtResponse(body, status_code=status)


def _delete_counts(scan_id: int) -> dict[str, int]:
    with Session(get_engine()) as s:

        def count(model):
            return s.exec(
                select(func.count()).select_from(model).where(model.scan_id == scan_id)
            ).one()

        return {
            "findings": count(Finding),
            "prompts": count(Prompt),
            "grants": count(PrivateDataGrant),
            "reviews": count(AssessmentResult),
        }


def delete_page(scan: Scan, session, back: str, error: str | None = None, status: int = 200):
    sid = scan.id
    n = _delete_counts(sid)
    verified = (
        f"checked by {scan.verified_by} on {scan.verification_date:%Y-%m-%d %H:%M} UTC"
        if scan.verified_by
        else "not verified yet"
    )
    body = page(
        f"Delete check {sid}?",
        H1(f"Delete check {sid}?"),
        error_summary({"delete": error}) if error else None,
        Section(
            H2("The check", id="delete-check"),
            Ul(
                Li(Strong("Page address: "), Code(scan.url)),
                Li(Strong("Standard: "), LEVEL_NAMES[scan.level]),
                Li(Strong("Started: "), f"{scan.created_at:%Y-%m-%d %H:%M} UTC"),
                Li(Strong("Status: "), status_text(scan)),
            ),
            cls="wa-card card card-body",
            aria_labelledby="delete-check",
        ),
        Section(
            H2("What will be removed", id="delete-what"),
            Ul(
                Li(f"Tool results (problems, items to check by hand and passes): {n['findings']}"),
                Li(f"GitHub Copilot CLI requests: {n['prompts']}"),
                Li(f"Permissions to see potential private data: {n['grants']}"),
                Li(f"Human verification: {verified}"),
                Li(f"Assessment results recorded by a person: {n['reviews']}"),
            ),
            cls="wa-card card card-body",
            aria_labelledby="delete-what",
        ),
        Div(
            P(Strong("Deleting cannot be undone.")),
            P(
                "The check and everything listed above are removed for everyone. Only a record "
                f"that you deleted check {sid}, and when, is kept. It does not include the page "
                "address or any results."
            ),
            cls="alert alert-warning wa-notice",
        ),
        Form(
            csrf_input(session),
            Input(type="hidden", name="next", value=back),
            P(error, id="delete-error", cls="invalid-feedback") if error else None,
            Div(
                Button(
                    "Delete this check",
                    type="submit",
                    id="delete",
                    cls="btn btn-primary",
                    aria_describedby="delete-error" if error else None,
                ),
                A("Keep it", href=u(back), cls="wa-standalone"),
                cls="wa-actions",
            ),
            method="post",
            action=u(f"/scans/{sid}/delete"),
        ),
        crumbs=_delete_crumbs(sid),
    )
    return FtResponse(body, status_code=status) if status != 200 else body


def register(rt):
    @rt("/", methods=["get"])
    def get(req: Request, session):
        return home_page(session, notice=deleted_notice(req.query_params.get("deleted")))

    @rt("/scans", methods=["post"])
    async def post_scan(req: Request, session):
        if (too_big := _too_big(req)) is not None:
            return too_big
        form = await req.form()
        values = {
            "url": str(form.get("url", "")).strip(),
            "level": str(form.get("level", "")),
            "engines": [e for e in form.getlist("engines") if e in ENGINE_NAMES],
            "consent": "yes" if form.get("consent") == "yes" else "",
        }
        if not csrf_ok(session, form.get("csrf")):
            # WCAG 2.2 SC 2.2.5: never lose what the user typed
            errors = {
                "url": "For your security, the form expired. Check your entries and "
                "choose Start check again."
            }
            return FtResponse(home_page(session, values, errors), status_code=403)
        errors = {}
        try:
            url = check_scan_url(values["url"])
        except UrlRejected as err:
            errors["url"] = str(err)
        if values["level"] not in {lv.value for lv in Level}:
            errors["level-2-2aa"] = "Choose a standard: Level AA or Level AAA."
            values["level"] = Level.AA.value
        if not values["engines"]:
            errors["engines"] = "Choose at least one checking tool."
        if values["consent"] != "yes":
            errors["consent"] = "Tick the permission box before the check can start."
        if errors:
            return home_page(session, values, errors)
        user = req.scope["user"]
        if not _rate_ok(user.email):
            errors = {
                "url": "You have started many checks in a short time. "
                "Please wait a few minutes and try again."
            }
            return FtResponse(home_page(session, values, errors), status_code=429)
        with Session(get_engine()) as s:
            try:
                scan = jobs.enqueue(
                    s,
                    url,
                    Level(values["level"]),
                    values["engines"],
                    ["desktop", "mobile-320"],
                    requested_by=user.email,
                    authorization=Authorization(values["consent"] == "yes", user.email),
                    created_by=user.id,
                )
            except NotAuthorized:
                errors = {"consent": "Tick the permission box before the check can start."}
                return FtResponse(home_page(session, values, errors), status_code=400)
            except jobs.QueueFull:
                errors = {
                    "url": "The checker is busy right now. Please try again in a few minutes."
                }
                return FtResponse(home_page(session, values, errors), status_code=503)
            scan_id = scan.id
        await jobs.wait_until_finished(scan_id, req.is_disconnected, who=user.id)
        return RedirectResponse(u(f"/scans/{scan_id}"), status_code=303)

    @rt("/scans", methods=["get"])
    def get_scans(req: Request):
        raw = req.query_params.get("page", "1")
        notice = deleted_notice(req.query_params.get("deleted"))
        body = scans_page(int(raw), notice) if raw.isdecimal() and len(raw) <= 6 else None
        if body is None:
            missing = page(
                "Page not found",
                H1("There is no such page of recent checks"),
                P(A("Go to the first page of recent checks", href=u("/scans"))),
                crumbs=[("Home", "/"), ("Recent checks", "/scans"), ("Page not found", None)],
            )
            return FtResponse(missing, status_code=404)
        return body

    @rt("/scans/{scan_id}", methods=["get"])
    async def get_scan(scan_id: int, req: Request, session):
        # Safe, idempotent GET: only reads state, so no CSRF token is needed
        if req.query_params.get("wait") == "1":
            who = getattr(current_user.get(), "id", None)
            if await jobs.wait_until_finished(scan_id, req.is_disconnected, who=who):
                return RedirectResponse(u(f"/scans/{scan_id}"), status_code=303)
        return await asyncio.to_thread(_scan_page, scan_id, session)

    def _scan_page(scan_id: int, session):
        with Session(get_engine()) as s:
            scan = s.get(Scan, scan_id)
            if scan is None:
                return HTMLResponse(
                    "We could not find that check. It may have been removed.", status_code=404
                )
            findings = list(s.exec(select(Finding).where(Finding.scan_id == scan_id)))
            grants = list(
                s.exec(select(PrivateDataGrant).where(PrivateDataGrant.scan_id == scan_id))
            )
            position = jobs.queue_position(s, scan)
            reviewed = assessment.saved(s, scan_id)
        crumbs = [("Home", "/"), ("Recent checks", "/scans"), (f"Check {scan_id}", None)]
        if scan.status in (ScanStatus.QUEUED, ScanStatus.RUNNING):
            body = _pending(scan, position)
        elif scan.status is ScanStatus.ERROR:
            body = _failed(scan, session)
        else:
            body = _results(scan, findings, grants, session, reviewed)
        return page(f"Check {scan_id}: {status_text(scan)}", *body, crumbs=crumbs)

    def _done_scan(scan_id: int):
        with Session(get_engine()) as s:
            scan = s.get(Scan, scan_id)
            if scan is None or scan.status is not ScanStatus.DONE:
                return None, []
            return scan, list(s.exec(select(Finding).where(Finding.scan_id == scan_id)))

    def _download(text: str, filename: str) -> PlainTextResponse:
        return PlainTextResponse(
            text,
            media_type="text/markdown; charset=utf-8",
            headers={"content-disposition": f'attachment; filename="{filename}"'},
        )

    def _load(scan_id: int):
        with Session(get_engine()) as s:
            scan = s.get(Scan, scan_id)
            if scan is None:
                return None, [], []
            findings = list(s.exec(select(Finding).where(Finding.scan_id == scan_id)))
            grants = list(
                s.exec(select(PrivateDataGrant).where(PrivateDataGrant.scan_id == scan_id))
            )
            return scan, findings, grants

    def _back(scan_id: int):
        return RedirectResponse(u(f"/scans/{scan_id}"), status_code=303)

    @rt("/scans/{scan_id}/grant", methods=["post"])
    async def post_grant(scan_id: int, req: Request, session):
        form = await req.form()
        scan, _f, grants = _load(scan_id)
        if scan is None or not scan.pii_flags:
            return _back(scan_id)
        if csrf_ok(session, form.get("csrf")) and form.get("grant") == "yes":
            with Session(get_engine()) as s:
                s.add(
                    PrivateDataGrant(
                        scan_id=scan_id,
                        granted_by=req.scope["user"].email,
                        flags=dict(scan.pii_flags),
                    )
                )
                s.commit()
        return _back(scan_id)

    @rt("/scans/{scan_id}/verify", methods=["post"])
    async def post_verify(scan_id: int, req: Request, session):
        form = await req.form()
        scan, _f, grants = _load(scan_id)
        if scan is None or scan.status is not ScanStatus.DONE or scan.verified_by:
            return _back(scan_id)
        if hidden_private_data(scan, grants):
            return _back(scan_id)  # permission must come first
        if csrf_ok(session, form.get("csrf")) and form.get("verify") == "yes":
            with Session(get_engine()) as s:
                row = s.get(Scan, scan_id)
                row.verified_by = req.scope["user"].email
                row.verification_date = datetime.now(UTC)
                s.add(row)
                s.commit()
        return _back(scan_id)

    def _exportable(scan, grants) -> bool:
        return (
            scan is not None
            and scan.status is ScanStatus.DONE
            and bool(scan.verified_by)
            and not hidden_private_data(scan, grants)
        )

    def _export_page(scan_id: int, session, error=None, status=200):
        body = page(
            "Get the GitHub Copilot CLI request",
            H1("Get the GitHub Copilot CLI request"),
            error_summary({"confirm": error}) if error else None,
            P(Strong(EXPORT_TEXT)),
            Form(
                csrf_input(session),
                P(error, id="confirm-error", cls="invalid-feedback") if error else None,
                _checkbox_row(
                    "confirm",
                    "I have checked: this report contains no raw PII or "
                    "unanonymized private records.",
                    invalid=bool(error),
                    described="confirm-error" if error else None,
                ),
                Button(
                    "Download the request (Markdown)",
                    type="submit",
                    name="action",
                    value="download",
                    cls="btn btn-primary",
                ),
                " ",
                Button(
                    "Show the request to copy",
                    type="submit",
                    name="action",
                    value="show",
                    cls="btn btn-outline-primary",
                ),
                method="post",
                action=u(f"/scans/{scan_id}/export"),
            ),
            crumbs=[
                ("Home", "/"),
                ("Recent checks", "/scans"),
                (f"Check {scan_id}", f"/scans/{scan_id}"),
                ("Get the GitHub Copilot CLI request", None),
            ],
        )
        return FtResponse(body, status_code=status) if status != 200 else body

    @rt("/scans/{scan_id}/export", methods=["get"])
    def get_export(scan_id: int, session):
        scan, _f, grants = _load(scan_id)
        if not _exportable(scan, grants):
            return HTMLResponse(
                "This report cannot be exported until it has been verified.", status_code=403
            )
        return _export_page(scan_id, session)

    @rt("/scans/{scan_id}/export", methods=["post"])
    async def post_export(scan_id: int, req: Request, session):
        form = await req.form()
        scan, findings, grants = _load(scan_id)
        if not _exportable(scan, grants):
            return HTMLResponse(
                "This report cannot be exported until it has been verified.", status_code=403
            )
        if not csrf_ok(session, form.get("csrf")) or form.get("confirm") != "yes":
            return _export_page(
                scan_id, session, "Tick the box to confirm you checked the report.", status=400
            )
        with Session(get_engine()) as s:
            reviewed = list(assessment.saved(s, scan_id).values())
        text = build_prompt(scan, findings, grants, reviewed)  # notes are never exported
        if form.get("action") == "show":
            return page(
                "GitHub Copilot CLI request",
                provenance_banner(scan),
                H1("GitHub Copilot CLI request"),
                P(
                    "In a terminal, go to your project folder and run ",
                    Code("copilot"),
                    ", then paste the request. Or save it as a file and run: ",
                    Code(f'copilot -p "$(cat wa-a11y-scan-{scan_id}.md)"'),
                    cls="form-text",
                ),
                Label("Request text", fr="prompt-text", cls="form-label"),
                Textarea(
                    text, id="prompt-text", readonly=True, rows="16", cls="form-control wa-prompt"
                ),
                crumbs=[
                    ("Home", "/"),
                    ("Recent checks", "/scans"),
                    (f"Check {scan_id}", f"/scans/{scan_id}"),
                    ("GitHub Copilot CLI request", None),
                ],
            )
        return PlainTextResponse(
            text,
            media_type="text/markdown; charset=utf-8",
            headers={"content-disposition": f'attachment; filename="wa-a11y-scan-{scan_id}.md"'},
        )

    @rt("/scans/{scan_id}/delete", methods=["get"])
    def get_delete(scan_id: int, req: Request, session):
        # A GET never deletes anything
        with Session(get_engine()) as s:
            scan = s.get(Scan, scan_id)
        if (why := deletion.refusal(req.scope["user"], scan)) is not None:
            return delete_refused(why, scan_id)
        return delete_page(scan, session, return_target(req.query_params.get("next")))

    @rt("/scans/{scan_id}/delete", methods=["post"])
    async def post_delete(scan_id: int, req: Request, session):
        if (too_big := _too_big(req)) is not None:
            return too_big
        form = await req.form()
        back = return_target(form.get("next"))
        user = req.scope["user"]
        with Session(get_engine()) as s:
            scan = s.get(Scan, scan_id)
        if (why := deletion.refusal(user, scan)) is not None:
            return delete_refused(why, scan_id)
        if not csrf_ok(session, form.get("csrf")):
            expired = "For your security, the form expired. Choose Delete this check again."
            return delete_page(scan, session, back, expired, status=403)
        with Session(get_engine()) as s:
            why = deletion.delete_scan(s, user, scan_id)
        if why is not None:  # it changed between the check above and the delete
            return delete_refused(why, scan_id)
        return RedirectResponse(u(_after_delete(back, scan_id)), status_code=303)

    @rt("/privacy", methods=["get"])
    def get_privacy():
        return page(
            "Privacy",
            H1("How wa-a11y keeps data private"),
            P(Strong(RULE)),
            H2("Local only"),
            P(
                "wa-a11y runs on your own server. It never sends what it finds to anyone else: no "
                "analytics, no tracking, no cloud services. The only page it visits is the one you "
                "ask it to check."
            ),
            H2("Components and web pages only"),
            P(
                "Check components and web pages — never data sets or documents with personal "
                "records. If a check finds content that looks private, it stays hidden until "
                "someone with permission confirms, and that decision is recorded with their name."
            ),
            H2("A person checks every report"),
            P(
                "Automated tools find many problems, but not all, and sometimes they are wrong. "
                "Every report is marked as an automated pre-check until a person reviews it, "
                "and it can only be shared after that review."
            ),
            crumbs=[("Home", "/"), ("Privacy", None)],
        )

    @rt("/settings", methods=["get"])
    def get_settings(req: Request, session, saved: int = 0):
        return settings_page(
            session, Display.from_cookie(req.cookies.get(COOKIE)), saved=bool(saved)
        )

    @rt("/settings", methods=["post"])
    async def post_settings(req: Request, session):
        if (too_big := _too_big(req)) is not None:
            return too_big
        form = await req.form()
        chosen = Display.from_values(form.get("font"), form.get("theme"), form.get("spacing"))
        if not csrf_ok(session, form.get("csrf")):
            msg = "For your security, the form expired. Check your choices and save again."
            return FtResponse(settings_page(session, chosen, error=msg), status_code=403)
        resp = RedirectResponse(u("/settings?saved=1"), status_code=303)
        resp.set_cookie(
            COOKIE,
            chosen.to_cookie(),
            max_age=365 * 24 * 3600,
            path=u("/") or "/",
            secure=True,
            httponly=True,
            samesite="strict",
        )
        return resp

    @rt("/login", methods=["get"])
    def get_login(req: Request, session):
        return login_page(session, {"next": _safe_next(req.query_params.get("next"))})

    @rt("/login", methods=["post"])
    async def post_login(req: Request, session):
        if (too_big := _too_big(req)) is not None:
            return too_big
        form = await req.form()
        values = {"email": str(form.get("email", "")).strip(), "next": _safe_next(form.get("next"))}
        if not csrf_ok(session, form.get("csrf")):
            msg = "For your security, the form expired. Please sign in again."
            return login_page(session, values, msg, status=403)
        with Session(get_engine()) as s:
            user = authenticate(s, values["email"], str(form.get("password", "")))
            token = start_session(s, user) if user else None
        if token is None:
            msg = (
                "The email address or password is not right, or the account is locked for a "
                "few minutes after several tries. Check them and try again."
            )
            return login_page(session, values, msg, status=401)
        session.pop("scan_times", None)
        resp = RedirectResponse(u(values["next"]), status_code=303)
        resp.set_cookie(
            AUTH_COOKIE,
            token,
            max_age=SESSION_HOURS * 3600,
            path=u("/") or "/",
            secure=True,
            httponly=True,
            samesite="strict",
        )
        return resp

    @rt("/logout", methods=["post"])
    async def post_logout(req: Request, session):
        form = await req.form()
        if csrf_ok(session, form.get("csrf")):
            with Session(get_engine()) as s:
                end_session(s, req.cookies.get(AUTH_COOKIE))
        resp = RedirectResponse(u("/login"), status_code=303)
        resp.delete_cookie(AUTH_COOKIE, path=u("/") or "/")
        return resp

    @rt("/about", methods=["get"])
    def get_about():
        # AGPLv3 §0/§5(d)/§13, NOTICE §7(b)/(c): Appropriate Legal Notices
        return page(
            "About and licence",
            H1("About and licence"),
            P(Strong("wa-a11y — Accessible Digital Infrastructure")),
            P("Copyright (C) 2026 Kevin Miller (rockypod)."),
            P(
                "Licensed under the GNU Affero General Public License, version 3 or (at your "
                "option) any later version (AGPL-3.0-or-later), with additional terms under "
                "Section 7(b) and 7(c): keep the wa-a11y notices, and mark modified versions."
            ),
            P(
                "This program comes with ABSOLUTELY NO WARRANTY. It is free software, and you are "
                "welcome to redistribute it under the terms of the licence."
            ),
            H2("Source code"),
            P(
                "If you use this service over a network, you can get its complete source code, "
                "free of charge: ",
                A("wa-a11y source code on GitHub", href=SOURCE_URL),
                ".",
            ),
            H2("Modified versions"),
            P(
                'Anyone who changes wa-a11y must show "Based on wa-a11y, modified by" and their '
                "name on this page and in their documentation, and offer their changed source "
                "code to the people who use their service."
            ),
            H2("Third-party software"),
            P(
                "wa-a11y uses axe-core (MPL-2.0), Siteimprove Alfa (MIT), Playwright "
                "(Apache-2.0), FastHTML (Apache-2.0), Bootstrap (MIT), ChromaDB (Apache-2.0), "
                "SQLModel (MIT), Bootstrap Icons (MIT, Copyright (c) 2019-2024 The Bootstrap "
                "Authors), and the fonts Atkinson Hyperlegible Next, Lexend and OpenDyslexic "
                "(SIL Open Font License 1.1)."
            ),
            crumbs=[("Home", "/"), ("About and licence", None)],
        )

    @rt("/help", methods=["get"])
    def get_help():
        return page(
            "Help",
            H1("Help"),
            H2("What this checker does"),
            P(
                "It opens the page in a web browser and runs two automated accessibility tools, "
                "axe-core and Alfa, against the ",
                wcag_abbr(),
                " 2.2 guidelines.",
            ),
            H2("Addresses you can check", id="addresses"),
            P(
                "Public websites that start with https://, for example ",
                Code("https://www.example.com/"),
                ". Addresses that start with http:// work only if the administrator allows them.",
            ),
            (
                (
                    P(
                        "The administrator of this installation ",
                        Strong("has also allowed local addresses"),
                        ", such as any of these (any port number is fine):",
                    ),
                    Ul(
                        Li(Code("http://localhost:3000")),
                        Li(Code("http://127.0.0.1:8080")),
                        Li(Code("http://192.168.1.20")),
                        Li(Code("http://[::1]:5173")),
                    ),
                    P(
                        "One thing to know: inside the checker's containers, “localhost” means "
                        "the checker itself, not your computer — for a server on your machine, "
                        "use its address on your network instead. This is for personal "
                        "installations; shared servers keep it off for safety."
                    ),
                )
                if allow_local_targets()
                else P(
                    "Local addresses, such as ",
                    Code("http://localhost:3000"),
                    ", are turned off for safety: on a shared server they would let a scan reach "
                    "internal systems. An administrator of a personal installation can allow "
                    "them; see the configuration table in the README.",
                )
            ),
            H2("What the results mean"),
            Ul(
                Li(Strong("Problem: "), "a tool found something that breaks a guideline."),
                Li(
                    Strong("Needs a person or GitHub Copilot CLI to check: "),
                    "a tool found something it could not decide. Look at it yourself.",
                ),
            ),
            H2("What it cannot do"),
            P(
                "Tools find many problems, but not all. Always also test with a keyboard, "
                "a screen reader and browser zoom."
            ),
            crumbs=[("Home", "/"), ("Help", None)],
        )
