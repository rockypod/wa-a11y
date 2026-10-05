# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

import json
import re
from pathlib import Path

CHECKLIST = Path(__file__).resolve().parents[1] / "app" / "assessment" / "checklist.json"
LEVELS = Path(__file__).resolve().parents[2] / "scanner" / "levels.json"

ITEM_KEYS = {
    "id",
    "title",
    "sc",
    "level",
    "purpose",
    "instructions",
    "observe",
    "evidence",
    "advisory",
}
SC_RE = re.compile(r"^\d+\.\d+\.\d+$")
from app.wcag import SC  # noqa: E402

PLAIN_LANGUAGE_BLOCKLIST = ("thus", "hence", "utilize", "aforementioned", "heretofore")
PRIVACY_BLOCKLIST = ("ssn", "social security", "credit card", "password:", "api key")


def load():
    text = CHECKLIST.read_text(encoding="utf-8")
    body = "".join(ln for ln in text.splitlines() if not ln.startswith("#"))
    return json.loads(body)


def test_file_is_valid_json_with_expected_comment():
    data = load()
    assert "wa-a11y" in data.get("$comment", ""), "missing wa-a11y provenance comment"
    assert "AGPL" in data.get("$comment", "") or "2026" in data.get("$comment", ""), (
        "licence note missing from $comment"
    )


def test_top_level_shape():
    data = load()
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["items"], list) and len(data["items"]) >= 20


def test_items_have_exactly_the_schema_keys():
    for item in load()["items"]:
        assert set(item) == ITEM_KEYS, f"{item.get('id')}: keys {sorted(set(item) ^ ITEM_KEYS)}"


def test_ids_are_unique_and_kebab_case():
    ids = [i["id"] for i in load()["items"]]
    assert len(ids) == len(set(ids)), "duplicate ids"
    for i in ids:
        assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", i), f"bad id: {i}"


def test_sc_numbers_exist_in_wcag_and_scanner():
    for item in load()["items"]:
        assert item["sc"], f"{item['id']}: empty sc list"
        for sc in item["sc"]:
            assert SC_RE.fullmatch(sc), f"{item['id']}: malformed SC {sc}"
            assert sc in SC, f"{item['id']}: SC {sc} not in WCAG 2.2 (app.wcag)"


def test_levels_are_valid_and_match_the_primary_sc():
    for item in load()["items"]:
        assert item["level"] in {"A", "AA", "AAA"}, f"{item['id']}: level {item['level']}"
        expected = SC[item["sc"][0]][1]
        assert item["level"] == expected, (
            f"{item['id']}: level {item['level']} != primary SC level {expected}"
        )


def test_advisory_is_a_bool():
    for item in load()["items"]:
        assert isinstance(item["advisory"], bool), f"{item['id']}: advisory not a bool"


def test_every_item_states_what_to_observe_and_what_evidence():
    for item in load()["items"]:
        for key in ("purpose", "instructions", "observe", "evidence"):
            text = item[key]
            assert isinstance(text, str) and len(text) >= 20, f"{item['id']}: thin {key}"
            assert text.strip().endswith((".", "?", ")")), f"{item['id']}: {key} not a sentence"


def test_plain_language_and_no_private_data_prompts():
    for item in load()["items"]:
        for key in ("title", "purpose", "instructions", "observe", "evidence"):
            low = item[key].lower()
            for word in PLAIN_LANGUAGE_BLOCKLIST:
                assert word not in low, f"{item['id']}: jargon '{word}' in {key}"
            for secret in PRIVACY_BLOCKLIST:
                assert secret not in low, f"{item['id']}: privacy-risk wording '{secret}' in {key}"


def test_scanner_levels_json_is_wellformed():
    levels = json.loads(LEVELS.read_text(encoding="utf-8"))
    for key in ("2.2-AA", "2.2-AAA"):
        assert key in levels, f"scanner/levels.json missing {key}"
        assert levels[key]["maxLevel"] in ("AA", "AAA")


def test_mandated_areas_are_covered():
    mandated = {
        "1.1.1": "non-text alternatives",
        "1.2.2": "captions",
        "1.4.10": "reflow",
        "2.1.1": "keyboard",
        "2.1.3": "keyboard no exception",
        "2.2.1": "timing",
        "2.4.3": "focus order",
        "2.4.9": "link purpose",
        "2.4.11": "focus not obscured",
        "2.4.13": "focus appearance",
        "2.5.7": "dragging",
        "2.5.8": "target size",
        "3.1.5": "reading level",
        "3.2.6": "consistent help",
        "3.3.1": "errors",
        "3.3.7": "redundant entry",
        "3.3.8": "auth minimum",
        "3.3.9": "auth enhanced",
        "4.1.2": "screen-reader names",
    }
    covered = {sc for item in load()["items"] for sc in item["sc"]}
    for sc, name in mandated.items():
        assert sc in covered, f"no checklist item covers {sc} ({name})"
