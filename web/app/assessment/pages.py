# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

# Privacy rule: the same consent, permission and export gates as the results page

from fasthtml.common import (
    H1,
    H2,
    H3,
    A,
    Button,
    Div,
    Fieldset,
    Form,
    FtResponse,
    Input,
    Label,
    Legend,
    P,
    Section,
    Strong,
    Textarea,
)
from sqlmodel import Session, select
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse

from app.assessment import results as assessment
from app.routes import (
    LEVEL_NAMES,
    hidden_private_data,
    private_data_section,
    provenance_banner,
)
from app.store.db import get_engine
from app.store.models import PrivateDataGrant, ReviewStatus, Scan, ScanStatus
from app.ui import csrf_input, csrf_ok, error_summary, page, u
from app.wcag import SC, sc_key, sc_label

STATUS_LABELS = {
    ReviewStatus.PASS: "Pass",
    ReviewStatus.FAIL: "Fail",
    ReviewStatus.NEEDS_REVIEW: "Needs review",
    ReviewStatus.NOT_APPLICABLE: "Not applicable",
}
PRINCIPLES = {"1": "Perceivable", "2": "Operable", "3": "Understandable", "4": "Robust"}
MAX_FORM_BYTES = 600 * 1024
EXPIRED = "For your security, the form expired. Check your entries and choose Save my checks again."


def _principle(item: dict) -> str:
    return item["sc"][0].split(".")[0]


def _grouped(items: list[dict]) -> list[tuple[str, list[dict]]]:
    ordered = sorted(items, key=lambda i: sc_key(i["sc"][0]))
    return [(p, [i for i in ordered if _principle(i) == p]) for p in PRINCIPLES]


def _status_field(item: dict, chosen: str | None, error: str | None):
    iid = item["id"]
    err_id = f"status-{iid}-error"
    radios = []
    for status, label in STATUS_LABELS.items():
        rid = f"status-{iid}-{status.value}"
        radios.append(
            Div(
                Input(
                    type="radio",
                    name=f"status-{iid}",
                    id=rid,
                    value=status.value,
                    checked=chosen == status.value,
                    cls="form-check-input is-invalid" if error else "form-check-input",
                    aria_invalid="true" if error else None,
                    aria_describedby=err_id if error else None,
                ),
                Label(label, fr=rid, cls="form-check-label"),
                cls="form-check",
            )
        )
    return Fieldset(
        Legend(f"Result: {item['title']}"),
        P(error, id=err_id, cls="invalid-feedback") if error else None,
        *radios,
        cls="wa-field",
    )


def _notes_field(item: dict, notes: str | None, error: str | None):
    iid = item["id"]
    if notes is None:  # saved notes while private data is unreleased: shown nowhere, kept as-is
        return P(
            Strong("Notes: "),
            "the notes saved for this check are hidden until permission to view potential "
            "private data is confirmed. They are kept when you save.",
            cls="form-text",
        )
    hint, err_id = f"notes-{iid}-hint", f"notes-{iid}-error"
    return Div(
        Label(f"Notes: {item['title']}", fr=f"notes-{iid}", cls="form-label"),
        P(
            f"Optional. {item['evidence']} Up to {assessment.NOTES_MAX} characters. "
            "Never write personal data here.",
            id=hint,
            cls="form-text",
        ),
        P(error, id=err_id, cls="invalid-feedback") if error else None,
        Textarea(
            notes,
            name=f"notes-{iid}",
            id=f"notes-{iid}",
            rows="4",
            maxlength=str(assessment.NOTES_MAX),
            cls="form-control is-invalid" if error else "form-control",
            aria_invalid="true" if error else None,
            aria_describedby=f"{hint} {err_id}" if error else hint,
        ),
        cls="wa-field",
    )


def _item_card(item: dict, value: tuple[str | None, str | None], saved, errors: dict):
    iid = item["id"]
    status, notes = value
    return Section(
        H3(item["title"], id=f"item-{iid}"),
        P(Strong("Guideline: "), "; ".join(sc_label(s) for s in item["sc"] if s in SC)),
        P(Strong("Why: "), item["purpose"]),
        P(Strong("How to check: "), item["instructions"]),
        P(Strong("What to look for: "), item["observe"]),
        P(
            f"Recorded as {STATUS_LABELS[saved.status]} by {saved.reviewer} on "
            f"{saved.reviewed_at:%Y-%m-%d %H:%M} UTC.",
            cls="wa-verified",
        )
        if saved
        else P("Not recorded yet.", cls="form-text"),
        _status_field(item, status, errors.get(f"status-{iid}-pass")),
        _notes_field(item, notes, errors.get(f"notes-{iid}")),
        cls="wa-card card card-body",
    )


def assessment_page(scan, grants, saved, session, user, values=None, errors=None, ok=False):
    errors = errors or {}
    items = assessment.applicable(scan.level)
    hidden = hidden_private_data(scan, grants)
    if values is None:
        values = {
            i["id"]: (
                saved[i["id"]].status.value if i["id"] in saved else None,
                None
                if hidden and i["id"] in saved and saved[i["id"]].notes
                else (saved[i["id"]].notes if i["id"] in saved else ""),
            )
            for i in items
        }
    done = assessment.progress(scan, saved)
    version = assessment.checklist()["version"]
    return page(
        f"Check {scan.id}: checks a person must do",
        provenance_banner(scan),
        H1("Checks a person must do"),
        error_summary(errors) if errors else None,
        Div(
            P(f"Your checks are saved: {assessment.progress_text(*done)}."),
            role="status",
            cls="wa-status",
        )
        if ok and not errors
        else None,
        private_data_section(scan, grants, session),
        Section(
            H2("About these checks", id="about-checks"),
            P(
                "Automated tools cannot do these checks: a person has to. What you record here "
                "is kept separately from the automated results, with your name and the time."
            ),
            P(Strong("Page: "), A(scan.url, href=scan.url, cls="wa-standalone")),
            P(Strong("Standard: "), LEVEL_NAMES[scan.level]),
            P(Strong("Checklist: "), f"wa-a11y Assessment checklist, version {version}"),
            P(Strong("Progress: "), assessment.progress_text(*done)),
            P(Strong("Recording as: "), user, cls="wa-verified"),
            P(
                "You do not have to finish every check at once. Choose a result for the checks "
                "you have done, then choose Save my checks at the end of the page."
            ),
            cls="wa-card card card-body",
        ),
        Form(
            csrf_input(session),
            *[
                Section(
                    H2(PRINCIPLES[p], id=f"principle-{p}"),
                    *[_item_card(i, values[i["id"]], saved.get(i["id"]), errors) for i in group],
                )
                for p, group in _grouped(items)
                if group
            ],
            Button("Save my checks", type="submit", id="save", cls="btn btn-primary"),
            method="post",
            action=u(f"/scans/{scan.id}/assessment"),
            novalidate=True,
        ),
        P(A("Back to the check results", href=u(f"/scans/{scan.id}"), cls="wa-standalone")),
        crumbs=[
            ("Home", "/"),
            ("Recent checks", "/scans"),
            (f"Check {scan.id}", f"/scans/{scan.id}"),
            ("Checks a person must do", None),
        ],
    )


def _load(scan_id: int):
    with Session(get_engine()) as s:
        scan = s.get(Scan, scan_id)
        if scan is None:
            return None, [], {}
        grants = list(s.exec(select(PrivateDataGrant).where(PrivateDataGrant.scan_id == scan_id)))
        return scan, grants, assessment.saved(s, scan_id)


def _missing_or_unfinished(scan, scan_id: int):
    if scan is None:
        return HTMLResponse(
            "We could not find that check. It may have been removed.", status_code=404
        )
    if scan.status is not ScanStatus.DONE:
        return RedirectResponse(u(f"/scans/{scan_id}"), status_code=303)
    return None


def _too_big(req: Request):
    try:
        length = int(req.headers.get("content-length", "0"))
    except ValueError:
        length = MAX_FORM_BYTES + 1
    if length > MAX_FORM_BYTES or "chunked" in req.headers.get("transfer-encoding", "").lower():
        return HTMLResponse("That request was too large.", status_code=413)
    return None


def read_form(form, items: list[dict], hidden: bool, saved: dict):
    allowed = {s.value for s in ReviewStatus}
    values, errors = {}, {}
    for item in items:
        iid, title = item["id"], item["title"]
        status = form.get(f"status-{iid}")
        status = status if status in allowed else None
        raw = form.get(f"notes-{iid}")
        if raw is None and not (hidden and iid in saved and saved[iid].notes):
            raw = ""  # a missing field only keeps notes that are hidden from this reviewer
        notes = None if raw is None else str(raw).replace("\r\n", "\n").strip()
        values[iid] = (status, notes)
        if notes and status is None:
            errors[f"status-{iid}-pass"] = f"Choose a result for “{title}” to save its notes."
        if notes and len(notes) > assessment.NOTES_MAX:
            errors[f"notes-{iid}"] = (
                f"The notes for “{title}” are {len(notes)} characters long. "
                f"Shorten them to {assessment.NOTES_MAX} characters or fewer."
            )
    return values, errors


def register(rt):
    @rt("/scans/{scan_id}/assessment", methods=["get"])
    def get_assessment(scan_id: int, req: Request, session, saved: int = 0):
        scan, grants, results = _load(scan_id)
        if (stop := _missing_or_unfinished(scan, scan_id)) is not None:
            return stop
        return assessment_page(
            scan, grants, results, session, req.scope["user"].email, ok=bool(saved)
        )

    @rt("/scans/{scan_id}/assessment", methods=["post"])
    async def post_assessment(scan_id: int, req: Request, session):
        if (too_big := _too_big(req)) is not None:
            return too_big
        form = await req.form()
        scan, grants, results = _load(scan_id)
        if (stop := _missing_or_unfinished(scan, scan_id)) is not None:
            return stop
        user = req.scope["user"].email
        items = assessment.applicable(scan.level)
        values, errors = read_form(form, items, hidden_private_data(scan, grants), results)
        status_code = 400
        if not csrf_ok(session, form.get("csrf")):
            errors, status_code = {"save": EXPIRED, **errors}, 403
        if errors:
            body = assessment_page(scan, grants, results, session, user, values, errors)
            return FtResponse(body, status_code=status_code)
        with Session(get_engine()) as s:
            row = s.get(Scan, scan_id)
            for iid, (status, notes) in values.items():
                old = results.get(iid)
                notes = old.notes if notes is None and old else (notes or "")
                if status is None or (old and old.status.value == status and old.notes == notes):
                    continue  # unchanged: keep the original reviewer and time
                assessment.record(s, row, iid, ReviewStatus(status), user, notes)
        return RedirectResponse(u(f"/scans/{scan_id}/assessment?saved=1"), status_code=303)
