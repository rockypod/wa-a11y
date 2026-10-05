# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

# Privacy rule: no private data exposure or automated transmission; all data stays local

import re
from collections import Counter
from dataclasses import dataclass

RULE = (
    "NO PRIVATE DATA EXPOSURE OR AUTOMATED TRANSMISSION. ALL DATA MUST REMAIN LOCAL AND "
    "SUBJECT TO MANDATORY HUMAN/MANUAL AUDITING."
)
CONSENT_TEXT = (
    "I acknowledge and grant permission to scan content that may contain private, "
    "confidential, or sensitive information. I accept responsibility for ensuring this "
    "scan complies with applicable privacy regulations."
)
GRANT_TEXT = "I have permission to view and work with this potentially private data."
VERIFY_TEXT = "I have checked these results by hand and confirm they are accurate enough to share."
EXPORT_TEXT = (
    "Verify that this report contains no raw PII or unanonymized private records "
    "before distributing."
)


def statement(user: str) -> str:
    return f"User '{user}' explicitly granted permission to scan potential private data."


def banner(user: str) -> str:
    return f"Scan authorized by user: {user} (Permission granted to scan potential private data)"


class NotAuthorized(PermissionError):
    """A scan was requested or run without explicit privacy consent and an authorizing user."""


@dataclass(frozen=True)
class Authorization:
    privacy_consent: bool
    authorized_by: str

    def require(self) -> None:
        if self.privacy_consent is not True or not (self.authorized_by or "").strip():
            raise NotAuthorized("privacy consent and an authorizing user are required to scan")


MOCK_EMAIL_DOMAINS = re.compile(
    r"@(?:[\w-]+\.)*(?:example\.(?:com|org|net)|[\w-]+\.example|localhost)$", re.IGNORECASE
)
PATTERNS: dict[str, re.Pattern[str]] = {
    "US Social Security number": re.compile(
        r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"
    ),
    "email address": re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"),
    "phone number": re.compile(r"(?<![\w-])(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b"),
    "long ID-like number": re.compile(r"(?<![\w.#-])\d{9,}(?![\w.-])"),
    "access token or key": re.compile(
        r"\b(?:AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{36,}|sk-[A-Za-z0-9]{20,}|xox[abpr]-[\w-]{10,})\b"
    ),
}


def detect(*texts: str) -> dict[str, int]:
    # Never keep the values: kinds and counts only
    found: Counter[str] = Counter()
    for text in texts:
        if not text:
            continue
        for kind, pattern in PATTERNS.items():
            for m in pattern.finditer(text):
                if kind == "email address" and MOCK_EMAIL_DOMAINS.search(m.group(0)):
                    continue
                found[kind] += 1
    return dict(found)


def unreleased(flags: dict[str, int], granted: list[dict[str, int]]) -> list[str]:
    # Kinds flagged after a grant stay hidden and block export until permission is given again
    released = {kind for flags_then in granted for kind in flags_then}
    return [kind for kind in flags if kind not in released]
