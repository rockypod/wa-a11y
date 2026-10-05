# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

import re

import pytest
from sqlmodel import Session, select
from starlette.testclient import TestClient

from app import routes
from app.main import app
from app.store.db import get_engine
from app.store.models import Engine, Finding, Level, Outcome, Scan, ScanStatus
from app.urlguard import UrlRejected


@pytest.fixture
def client():
    return TestClient(app, base_url="https://testserver", follow_redirects=False)


@pytest.fixture
def ok_urls(monkeypatch):
    def fake(url):
        if "internal" in url:
            raise UrlRejected("This address points to an internal or private network.")
        return url.strip()

    monkeypatch.setattr(routes, "check_scan_url", fake)


def csrf(client) -> str:
    html = client.get("/").text
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def add_scan(**kw) -> int:
    defaults = dict(
        url="https://example.org/",
        level=Level.AA,
        engines=["axe", "alfa"],
        profiles=["desktop"],
        status=ScanStatus.DONE,
    )
    with Session(get_engine()) as s:
        scan = Scan(**{**defaults, **kw})
        s.add(scan)
        s.commit()
        s.refresh(scan)
        return scan.id


def add_finding(scan_id, **kw):
    defaults = dict(
        engine=Engine.AXE,
        outcome=Outcome.FAIL,
        rule_id="image-alt",
        sc="1.1.1",
        wcag_level="A",
        selector="img",
        html_snippet="<img src=x>",
        message="Add alt text",
        impact="critical",
        profiles=["desktop"],
        fingerprint="fp",
    )
    with Session(get_engine()) as s:
        s.add(Finding(scan_id=scan_id, **{**defaults, **kw}))
        s.commit()


def test_home_form_is_accessible_and_scriptless(client):
    html = client.get("/").text
    assert "<script" not in html.lower()
    assert '<label for="url"' in html and 'id="url"' in html
    assert "<legend>Which standard should the page meet?</legend>" in html
    assert 'value="2.2-AA" checked' in html
    assert html.count('type="checkbox"') == 4
    assert 'aria-describedby="url-hint"' in html
    assert 'aria-label="Breadcrumb"' in html and 'aria-current="page"' in html
    assert "<title>Check a page — WA-A11y</title>" in html


def test_post_without_csrf_is_rejected_but_keeps_input(client, ok_urls):
    r = client.post(
        "/scans", data={"url": "https://example.org/kept", "level": "2.2-AAA", "engines": "axe"}
    )
    assert r.status_code == 403
    assert "the form expired" in r.text
    assert 'value="https://example.org/kept"' in r.text  # WCAG 2.2 SC 2.2.5: no data loss
    assert 'value="2.2-AAA" checked' in r.text
    with Session(get_engine()) as s:
        assert s.exec(select(Scan)).all() == []


def test_valid_post_queues_scan_and_redirects(client, ok_urls):
    token = csrf(client)
    r = client.post(
        "/scans",
        data={
            "csrf": token,
            "url": "https://example.org/",
            "level": "2.2-AAA",
            "engines": ["axe", "alfa"],
            "consent": "yes",
        },
    )
    assert r.status_code == 303
    scan_id = int(r.headers["location"].rsplit("/", 1)[1])
    with Session(get_engine()) as s:
        scan = s.get(Scan, scan_id)
    assert scan.status is ScanStatus.QUEUED and scan.level is Level.AAA
    assert scan.engines == ["axe", "alfa"]


def test_keyboard_checks_engine_is_offered_checked_and_queued(client, ok_urls):
    html = client.get("/").text
    box = _tag(html, "input", "engines-accessibility-insights-fastpass")
    assert 'value="accessibility-insights-fastpass"' in box and "checked" in box
    assert 'aria-describedby="engines-hint"' in box
    assert "Keyboard checks (Accessibility Insights FastPass style)</label>" in html
    assert "Keyboard checks press the Tab key" in html
    r = client.post(
        "/scans",
        data={
            "csrf": csrf(client),
            "url": "https://example.org/",
            "level": "2.2-AA",
            "engines": ["axe", "accessibility-insights-fastpass", "wave"],
            "consent": "yes",
        },
    )
    assert r.status_code == 303
    with Session(get_engine()) as s:
        scan = s.get(Scan, int(r.headers["location"].rsplit("/", 1)[1]))
    assert scan.engines == ["axe", Engine.FASTPASS.value]
    assert scan.privacy_consent is True and scan.authorized_by  # consent still required


def test_engine_names_cover_every_stored_engine():
    from app.routes import ENGINE_LABELS, ENGINE_NAMES

    assert set(ENGINE_LABELS) == {e.value for e in Engine}
    assert "aria-tree" not in ENGINE_NAMES


def test_errors_are_listed_linked_and_keep_input(client, ok_urls):
    token = csrf(client)
    r = client.post(
        "/scans", data={"csrf": token, "url": "https://internal.example/", "level": "2.2-AAA"}
    )
    assert r.status_code == 200
    html = r.text
    assert 'role="alert"' in html
    assert 'href="#url"' in html and 'href="#engines"' in html
    assert 'aria-invalid="true"' in html
    assert 'value="https://internal.example/"' in html  # WCAG 2.2 SC 3.3.7 / 2.2.5: input kept
    assert 'value="2.2-AAA" checked' in html
    assert "Choose at least one checking tool." in html


def _tag(html: str, el: str, id_: str) -> str:
    return re.search(rf'<{el}[^>]*id="{id_}"[^>]*>', html).group(0)


def test_invalid_fields_use_bootstrap_styles_and_link_their_message(client, ok_urls):
    # WCAG 2.2 SC 1.4.1 / 3.3.1: error text (not colour alone) linked by aria-describedby
    r = client.post("/scans", data={"csrf": csrf(client), "url": "https://internal.example/"})
    html = r.text
    assert html.index('id="error-summary"') < html.index('action="/scans"')
    for href in ("#url", "#engines", "#consent"):
        assert f'href="{href}"' in html
    url = _tag(html, "input", "url")
    assert "is-invalid" in url and 'aria-invalid="true"' in url
    assert 'aria-describedby="url-hint url-error"' in url
    assert 'class="invalid-feedback"' in _tag(html, "p", "url-error")
    for cid in ("engines-axe", "engines-alfa", "engines-accessibility-insights-fastpass"):
        box = _tag(html, "input", cid)
        assert "is-invalid" in box and 'aria-invalid="true"' in box
        assert 'aria-describedby="engines-hint engines-error"' in box
    assert 'class="invalid-feedback"' in _tag(html, "p", "engines-error")
    consent = _tag(html, "input", "consent")
    assert "is-invalid" in consent and 'aria-describedby="consent-error"' in consent
    assert 'class="invalid-feedback"' in _tag(html, "p", "consent-error")
    assert "wa-field-error" not in html


def test_notice_boxes_are_bootstrap_alerts_with_unchanged_roles(client, ok_urls):
    html = client.post("/scans", data={"csrf": csrf(client), "url": ""}).text
    summary = _tag(html, "div", "error-summary")
    assert 'role="alert"' in summary and 'class="alert alert-warning wa-error-summary"' in summary
    assert 'class="alert wa-rule"' in html
    saved = client.get("/settings?saved=1").text
    assert '<div role="status" class="alert alert-success wa-status">' in saved
    sid = add_scan(pii_flags={"email address": 1})
    report = client.get(f"/scans/{sid}").text
    assert 'class="alert alert-info wa-provenance"' in _tag(report, "div", "provenance")
    assert report.count('class="alert alert-warning wa-notice wa-card"') == 2
    failed = client.get(f"/scans/{add_scan(status=ScanStatus.ERROR, error='x')}").text
    assert 'class="alert alert-warning wa-notice"' in failed
    for page in (html, saved, report, failed):
        assert "alert-dismissible" not in page and "btn-close" not in page


def test_valid_form_has_no_invalid_markers(client):
    html = client.get("/").text
    assert "is-invalid" not in html and "invalid-feedback" not in html
    assert "aria-invalid" not in html


def test_pending_page_has_no_auto_refresh(client):
    sid = add_scan(status=ScanStatus.QUEUED)
    html = client.get(f"/scans/{sid}").text
    assert "Waiting to start" in html and "Check again" in html
    assert "http-equiv" not in html.lower()  # WCAG 2.2 SC 2.2.4 / 3.2.5: no meta refresh


def test_pending_page_says_place_in_queue_in_words(client):
    # WCAG 2.2 SC 3.2.5: no progress bar, script or refresh; only "Check again" updates
    ids = [add_scan(status=ScanStatus.QUEUED, url=f"https://example.org/q{i}") for i in range(5)]
    add_scan(status=ScanStatus.RUNNING)
    html = client.get(f"/scans/{ids[2]}").text
    assert "<strong>Place in the queue: </strong>3rd of 5 waiting. " in html
    assert "2 checks will start before yours." in html
    assert "Check again" in html and "progressbar" not in html and 'class="progress' not in html
    assert "<script" not in html.lower() and "http-equiv" not in html.lower()
    first = client.get(f"/scans/{ids[0]}").text
    assert "1st of 5 waiting. Yours is the next check to start." in first
    running = client.get(f"/scans/{ids[-1] + 1}").text
    assert "Checking now" in running and "Place in the queue" not in running


@pytest.mark.parametrize(
    ("n", "word"),
    [(1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"), (11, "11th"), (12, "12th"), (13, "13th")]
    + [(21, "21st"), (22, "22nd"), (101, "101st"), (111, "111th")],
)
def test_ordinal(n, word):
    assert routes.ordinal(n) == word


def test_results_grouped_by_sc_and_snippets_escaped(client):
    sid = add_scan()
    add_finding(sid, html_snippet='<script>alert("x")</script>', selector="#a")
    add_finding(
        sid,
        engine=Engine.ALFA,
        outcome=Outcome.CANT_TELL,
        rule_id="sia-r14",
        sc="2.5.3,4.1.2",
        impact=None,
        fingerprint="fp2",
    )
    html = client.get(f"/scans/{sid}").text
    assert "<script>alert" not in html
    assert "&lt;script&gt;alert" in html
    assert "1.1.1 Non-text Content (Level A)" in html
    assert "2.5.3 Label in Name (Level A)" in html
    assert "Also relates to: </strong>4.1.2 Name, Role, Value" in html
    assert "needs a person or GitHub Copilot CLI to check" in html
    assert html.index("1.1.1 Non-text Content") < html.index("2.5.3 Label in Name")


def test_aaa_results_list_manual_checks_and_never_claim_conformance(client):
    sid = add_scan(level=Level.AAA)
    html = client.get(f"/scans/{sid}").text
    assert "Checks a person must do" in html
    assert "3.1.5 Reading Level (Level AAA)" in html
    assert "No problems were found by the automated tools" in html
    assert "conformant" not in html.lower() and "passes aaa" not in html.lower()


def test_results_summary_is_a_table_with_row_headers(client):
    sid = add_scan(tool_versions={"axe-core": "4.10.0"})
    add_finding(sid)
    html = client.get(f"/scans/{sid}").text
    table = re.search(r'<table class="table wa-summary">.*?</table>', html, re.S).group(0)
    assert "<caption>What was checked and what the tools found</caption>" in table
    rows = re.findall(r"<tr>\s*<th scope=\"row\">([^<]+)</th>\s*<td>", table)
    assert rows == [
        "Page",
        "Standard",
        "Problems found",
        "Items for a person or GitHub Copilot CLI to check",
        "Screen-reader structure",
        "Tools used",
    ]
    assert 'href="https://example.org/"' in table and "axe-core 4.10.0" in table
    assert html.count("<table") == 1
    assert "<ul" not in html[html.index('id="summary"') : html.index("</table>")]


def _section_of(html: str, heading_id: str) -> str:
    return html[: html.index(f'id="{heading_id}"')].rsplit("<section", 1)[1].split(">", 1)[0]


def test_result_sections_are_cards_but_provenance_is_not(client):
    sid = add_scan(
        level=Level.AAA,
        blocked_requests=["GET http://10.0.0.1/x.png — non-public"],
        pii_flags={"email": 1},
    )
    add_finding(sid)
    html = client.get(f"/scans/{sid}").text
    for heading in ("summary", "blocked", "manual", "copilot"):
        section = _section_of(html, heading)
        assert "card card-body" in section and "wa-card" in section, heading
    for heading in ("private-data", "verify-heading"):
        section = _section_of(html, heading)
        assert "alert alert-warning wa-notice wa-card" in section and "card-body" not in section
    provenance = _tag(html, "div", "provenance")
    assert "wa-provenance" in provenance and "card" not in provenance
    assert "card" not in _section_of(html, "privacy-rule")


def test_blocked_requests_are_shown(client):
    sid = add_scan(blocked_requests=["GET http://10.0.0.1/x.png — non-public"])
    html = client.get(f"/scans/{sid}").text
    assert "Parts of the page we did not load" in html and "10.0.0.1" in html


BADGE = '<span class="wa-count badge rounded-pill">'


def _flat(html: str) -> str:
    return re.sub(r"\s*\n\s*", "", html)


def test_lists_are_list_groups_and_counts_are_labelled_badges(client):
    # WCAG 2.2 SC 1.3.1 / 1.4.1: a badge follows its text label, never stands alone
    sid = add_scan(
        level=Level.AAA, blocked_requests=["GET http://10.0.0.1/a", "GET http://10.0.0.2/b"]
    )
    add_finding(sid)
    html = _flat(client.get(f"/scans/{sid}").text)
    blocked = re.search(r'<ul class="list-group wa-blocked">(.*?)</ul>', html, re.S).group(1)
    assert blocked.count('<li class="list-group-item"><code>') == 2
    assert f"<strong>Requests skipped: </strong>{BADGE}2</span>" in html
    manual = html[html.index('id="manual"') :]
    assert '<ul class="list-group"><li class="list-group-item"><a href=' in manual
    assert f'<th scope="row">Problems found</th><td>{BADGE}1</span>' in html
    assert f"to check</th><td>{BADGE}0</span>" in html
    flagged = _flat(client.get(f"/scans/{add_scan(pii_flags={'email address': 2})}").text)
    assert f"<li>email address: {BADGE}2</span>" in flagged

    home = _flat(client.get("/").text)
    recent = home[home.index('id="recent"') :]
    assert re.search(r'<ul class="list-group wa-recent"><li class="list-group-item"><a', recent)
    assert '<ul class="list-group wa-recent">' in client.get("/scans").text


def test_failed_scan_offers_retry_with_csrf(client):
    sid = add_scan(status=ScanStatus.ERROR, error="The check took too long and was stopped.")
    html = client.get(f"/scans/{sid}").text
    assert "The check could not finish" in html and "took too long" in html
    assert 'name="csrf"' in html and "Try again" in html


def test_unknown_scan_is_404(client):
    assert client.get("/scans/999").status_code == 404


def test_help_page(client):
    assert "What the results mean" in client.get("/help").text


def _main_nav(html: str) -> str:
    return re.search(r'<nav aria-label="Main"[^>]*>.*?</nav>', html, re.S).group(0)


def _crumbs(html: str) -> str:
    return re.search(r'<nav aria-label="Breadcrumb">.*?</nav>', html, re.S).group(0)


@pytest.mark.parametrize(
    ("path", "current"),
    [
        ("/", "Check a page"),
        ("/scans", "Recent checks"),
        ("/settings", "Display settings"),
        ("/help", "Help"),
        ("/about", "About"),
    ],
)
def test_header_nav_marks_current_page(client, path, current):
    nav = _main_nav(client.get(path).text)
    assert '<ul class="nav">' in nav
    assert "nav-tabs" not in nav and "nav-pills" not in nav and 'role="tab' not in nav
    assert nav.count('class="nav-link"') == 5 and 'class="nav-link wa-brand"' in nav
    assert nav.count('aria-current="page"') == 1
    link = re.search(rf"<a [^>]*>{current}</a>", nav).group(0)
    assert 'aria-current="page"' in link and 'class="nav-link"' in link


def test_header_nav_has_no_current_link_elsewhere(client):
    assert 'aria-current="page"' not in _main_nav(client.get("/privacy").text)


def test_breadcrumbs_use_bootstrap_breadcrumb_markup(client):
    crumbs = _crumbs(client.get("/settings").text)
    assert '<ol class="breadcrumb">' in crumbs
    assert crumbs.count('<li class="breadcrumb-item">') == 2
    assert re.search(r'<li class="breadcrumb-item">\s*<a href="/">Home</a>', crumbs)
    assert '<span aria-current="page">Display settings</span>' in crumbs
    assert crumbs.count('aria-current="page"') == 1


def test_base_path_prefixes_links_forms_and_redirects(client, ok_urls, monkeypatch):
    monkeypatch.setenv("WA_A11Y_BASE_PATH", "/wa-a11y")
    html = client.get("/").text
    assert 'href="/wa-a11y/"' in html and 'href="/wa-a11y/help"' in html
    assert 'action="/wa-a11y/scans"' in html
    assert not re.search(r'(?:href|action)="/(?!wa-a11y)', html)
    token = csrf(client)
    r = client.post(
        "/scans",
        data={
            "csrf": token,
            "url": "https://example.org/",
            "level": "2.2-AA",
            "engines": "axe",
            "consent": "yes",
        },
    )
    assert r.headers["location"].startswith("/wa-a11y/scans/")


def test_settings_page_lists_choices_in_their_own_font(client):
    html = client.get("/settings").text
    assert "<legend>Reading font</legend>" in html
    assert 'class="form-check-label wa-font-opendyslexic"' in html
    assert (
        'id="font-atkinson" value="atkinson" checked' in html or 'value="atkinson" checked' in html
    )
    assert 'href="/settings"' in html
    assert 'href="/settings"' in client.get("/help").text


def test_saving_settings_sets_cookie_and_html_attributes(client):
    token = csrf(client)
    r = client.post(
        "/settings",
        data={"csrf": token, "font": "opendyslexic", "theme": "contrast", "spacing": "wide"},
    )
    assert r.status_code == 303 and r.headers["location"] == "/settings?saved=1"
    cookie = r.headers["set-cookie"]
    assert (
        "wa_a11y_display=" in cookie and "httponly" in cookie.lower() and "secure" in cookie.lower()
    )
    page = client.get("/settings?saved=1").text
    assert 'role="status"' in page and "saved" in page
    assert re.search(r'<html[^>]*data-font="opendyslexic"', page)
    assert re.search(r'<html[^>]*data-theme="contrast"', page)
    assert re.search(r'<html[^>]*data-spacing="wide"', page)
    assert re.search(r'<html[^>]*data-font="opendyslexic"', client.get("/").text)


def test_defaults_add_no_attributes_and_bad_cookie_is_ignored(client):
    assert not re.search(r"<html[^>]*data-(font|theme|spacing)", client.get("/").text)
    client.cookies.set("wa_a11y_display", "evil|<script>|x")
    html = client.get("/").text
    assert not re.search(r"<html[^>]*data-", html) and "<script>" not in html


def test_settings_post_without_csrf_keeps_choices(client):
    r = client.post("/settings", data={"font": "lexend", "theme": "dark", "spacing": "wide"})
    assert r.status_code == 403
    assert 'value="lexend" checked' in r.text and 'value="dark" checked' in r.text
    assert 'id="settings-error" class="invalid-feedback"' in r.text
    assert 'aria-describedby="settings-error"' in r.text and "is-invalid" not in r.text
    assert "wa_a11y_display" not in r.headers.get("set-cookie", "")


def test_get_routes_reject_post(client):
    for path in ("/", "/help", "/scans/1"):
        assert client.post(path).status_code == 405, path


def test_error_status_pages_are_full_themed_documents(client, ok_urls, monkeypatch):
    r = client.post(
        "/scans", data={"url": "https://example.org/", "level": "2.2-AA", "engines": "axe"}
    )
    assert r.status_code == 403
    assert r.text.lstrip().lower().startswith("<!doctype html>")
    assert '<html lang="en"' in r.text and "<title>" in r.text and "<style>" in r.text


def test_scan_form_example_url_and_help_link(client):
    html = client.get("/").text
    assert "For example:" in html
    assert "https://www.example.com/" in html
    assert "Other kinds of addresses" in html
    assert 'href="/help#addresses"' in html


def test_help_addresses_section_tracks_the_local_opt_in(client, monkeypatch):
    html = client.get("/help").text
    assert 'id="addresses"' in html and "Addresses you can check" in html
    assert "https://www.example.com/" in html
    assert "http://[::1]:5173" not in html
    assert "turned off for safety" in html
    monkeypatch.setenv("WA_A11Y_ALLOW_LOCAL_TARGETS", "1")
    html = client.get("/help").text
    for address in (
        "http://localhost:3000",
        "http://127.0.0.1:8080",
        "http://192.168.1.20",
        "http://[::1]:5173",
    ):
        assert address in html
    assert "has also allowed local addresses" in html
    assert "not your computer" in html


def test_about_page_and_source_link_on_every_page(client):
    about = client.get("/about").text
    assert "wa-a11y — Accessible Digital Infrastructure" in about
    assert "Copyright (C) 2026 Kevin Miller (rockypod)" in about
    assert "AGPL-3.0-or-later" in about and "https://github.com/rockypod/wa-a11y" in about
    for path in ("/", "/help", "/settings", "/about"):
        html = client.get(path).text
        assert 'href="/about"' in html and 'href="https://github.com/rockypod/wa-a11y"' in html, (
            path
        )


def test_home_lists_five_latest_checks_then_link_to_all(client):
    assert "See all recent checks" not in client.get("/").text
    ids = [add_scan(url=f"https://example.org/p{i}") for i in range(7)]
    html = client.get("/").text
    recent = html[html.index('id="recent"') :]
    listed = re.findall(r'href="/scans/(\d+)"', recent)
    assert listed == [str(i) for i in reversed(ids[-5:])]
    assert re.search(r'<a href="/scans"[^>]*>See all recent checks</a>', recent)


def test_scans_page_newest_first_25_per_page_with_link_pagination(client):
    ids = [add_scan(url=f"https://example.org/p{i}") for i in range(60)]
    html = client.get("/scans").text
    assert "<script" not in html.lower()
    links = re.findall(r'href="/scans/(\d+)"', html)
    assert links == [str(i) for i in sorted(ids, reverse=True)[:25]]
    nav = re.search(r'<nav aria-label="Pagination">(.*?)</nav>', html, re.S).group(1)
    assert '<span aria-current="page" class="page-link">Page 1</span>' in nav
    assert '<a href="/scans?page=2" class="page-link">Page 2</a>' in nav
    assert '<a href="/scans?page=3" class="page-link">Page 3</a>' in nav
    assert '<a href="/scans?page=2" class="page-link">Next page</a>' in nav
    assert "Previous page" not in nav

    html = client.get("/scans?page=2").text
    links = re.findall(r'href="/scans/(\d+)"', html)
    assert links == [str(i) for i in sorted(ids, reverse=True)[25:50]]
    assert "<title>Recent checks, page 2 of 3" in html
    nav = re.search(r'<nav aria-label="Pagination">(.*?)</nav>', html, re.S).group(1)
    assert '<a href="/scans" class="page-link">Previous page</a>' in nav
    assert '<a href="/scans" class="page-link">Page 1</a>' in nav
    assert '<span aria-current="page" class="page-link">Page 2</span>' in nav
    assert '<a href="/scans?page=3" class="page-link">Next page</a>' in nav

    last = client.get("/scans?page=3").text
    assert len(re.findall(r'href="/scans/(\d+)"', last)) == 10
    assert "Next page" not in last


def test_scans_pagination_skips_far_pages_but_keeps_first_and_last(client):
    for i in range(10 * routes.SCANS_PER_PAGE):
        add_scan(url=f"https://example.org/p{i}")
    nav = re.search(
        r'<nav aria-label="Pagination">(.*?)</nav>', client.get("/scans?page=5").text, re.S
    )
    pages = re.findall(r">Page (\d+)<", nav.group(1))
    assert pages == ["1", "3", "4", "5", "6", "7", "10"]
    assert nav.group(1).count('aria-hidden="true"') == 2


def test_scans_page_hides_pagination_with_one_page(client):
    html = client.get("/scans").text
    assert client.get("/scans").status_code == 200
    assert "No checks have been run yet." in html and "pagination" not in html
    add_scan()
    html = client.get("/scans").text
    assert 'href="/scans/1"' in html and "pagination" not in html


def test_scans_page_out_of_range_is_404_not_clamped(client):
    add_scan()
    for q in ("?page=2", "?page=0", "?page=-1", "?page=abc", "?page=99999999"):
        r = client.get(f"/scans{q}")
        assert r.status_code == 404, q
        assert r.text.lstrip().lower().startswith("<!doctype html>")
        assert '<a href="/scans">Go to the first page of recent checks</a>' in r.text
    assert client.get("/scans?page=1").status_code == 200


def test_scans_page_is_get_only_for_reads(client):
    # Without a CSRF token, POST /scans must not list or create anything.
    assert client.post("/scans").status_code == 403
