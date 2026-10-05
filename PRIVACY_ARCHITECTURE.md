<!--
wa-a11y
SPDX-License-Identifier: AGPL-3.0-or-later

This file is part of wa-a11y.
Copyright (C) 2026 Kevin Miller (rockypod)
Modifications must retain this wa-a11y notice and document all changes
pursuant to AGPLv3 Section 5 and Section 7.
-->

# Privacy architecture

> **NO PRIVATE DATA EXPOSURE OR AUTOMATED TRANSMISSION. ALL DATA MUST REMAIN LOCAL AND SUBJECT TO
> MANDATORY HUMAN/MANUAL AUDITING.**

WA-A11y checks **components and web pages** for accessibility. It is not meant to scan private,
confidential or sensitive records. This page explains how the rule above is enforced. Each
control has an automated test that fails if the control is removed.

## 1. Everything stays local

- WA-A11y has no telemetry, analytics or crash reporting. It makes no calls to update services or
  cloud APIs.
- The only outbound network traffic is the scan that a person asked for. Every request the browser
  makes goes through the scanner's egress guard (`scanner/src/egress.ts`). The guard records each
  host the browser contacted.
- Chromium starts with background networking, component updates, Safe Browsing updates, sync,
  domain reliability, metrics upload and pings turned off (`scanner/src/scan.ts`).
- Test: `scanner/test/scan.test.ts` asserts that the browser contacts **only** the target host.
- Results, accounts and logs live in SQLite on the local `/data` volume.

## 2. Consent before every scan (hard interlock)

The check page shows the rule, plus a required checkbox with this exact wording:

> I acknowledge and grant permission to scan content that may contain private, confidential, or
> sensitive information. I accept responsibility for ensuring this scan complies with applicable
> privacy regulations.

The signed-in user's name is shown next to it ("Authorizing as: …"). A scan cannot start without
both consent and an authorizing user. Three layers enforce this, and each one refuses on its own:

| Layer | Where | On missing consent or user |
|---|---|---|
| Web form | `POST /scans` (`web/app/routes.py`) | Error message; nothing is queued |
| Queue | `jobs.enqueue` (`web/app/jobs.py`) | Raises `NotAuthorized` |
| Runner | `jobs.run_scan` | Marks the scan as an error; the scanner is never called |
| Scanner service | `POST /scan` (`scanner/src/server.ts`) | `400 authorization required` |

Each scan records `privacy_consent`, `authorized_by` and `authorized_at`.

## 3. Provenance on every result

- The results page opens with the banner **"Scan authorized by user: {user} (Permission granted to
  scan potential private data)"**.
- A print stylesheet keeps the banner visible. The `css-gates` check fails if any rule hides
  `.wa-provenance`, or if the print rule that forces it to show is removed.
- Every exported prompt starts with the same banner and the statement "User '{user}' explicitly
  granted permission to scan potential private data." It also includes a JSON provenance block
  with these fields:
  - `authorized_by`
  - `authorized_at`
  - `automated_precheck`
  - `verified_by`
  - `verification_date`
  - `privacy_cleared`

## 4. Potential private data is flagged, not stored

- After a scan, its captured text is checked locally (`web/app/privacy.py`). The captured text is
  each finding's HTML snippet, tool message and selector. The checks look for:
  - Social Security numbers
  - personal email addresses
  - phone numbers
  - long ID-like numbers
  - tokens
- **Only the kind and the count are stored** (`scan.pii_flags`). The matched values are not stored.
- If anything is flagged, the affected findings are masked on the results page. A person must tick
  *"I have permission to view and work with this potentially private data."* to see them. The grant
  is logged in the `privatedatagrant` table (who, when, which kinds) and shown on the results page
  as "{user} allowed access to potential private data on {date}".

## 5. Mandatory human verification before anything leaves the page

- Every result is marked **Human verification required**. A person confirms that they checked the
  results by hand, and their name and the date are recorded (`verified_by`, `verification_date`).
- If a scan was flagged, it cannot be verified until a person has given permission to view the
  flagged data.
- Copilot CLI prompts are available only through `/scans/{id}/export`, after verification. Before
  each download or copy, the person must tick *"Verify that this report contains no raw PII or
  unanonymized private records before distributing."*
- Nothing is sent anywhere automatically. The person downloads or copies the prompt and decides
  where it goes.

## 6. Repository hygiene

- `scripts/pii-scan` runs in the pre-commit hook and in `scripts/check`. It rejects commits that
  contain personal data or private artifacts. Test data uses only `example.com` addresses and the
  documented fake values.
- `scripts/verify-export` checks that the public source archive (`git archive`) contains no
  internal planning or agent files. The excluded paths are listed in `.gitattributes`.
- `gitleaks` scans the full history and the working tree for secrets.

This is a technical description, not legal advice. Your organization's privacy officer decides what may
be scanned.
