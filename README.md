# WA-A11y

Checks a web page for accessibility problems against **WCAG 2.2 Level AA or AAA**, using two
independent tools — **axe-core** and **Siteimprove Alfa** — and explains the results in plain
language for non-technical staff.

WA-A11y's own pages meet **WCAG 2.2 AAA** (checked on every change by both tools; see
[Quality gates](#quality-gates)). Automated tools cannot find every problem: results always list
what a person still needs to check.

> **Status:** v0.2.3 — Milestone 2: Accessibility Insights-style checks, screen-reader structure checks,
> guided manual checklist.

## What it does

- Enter a public web address and choose **WCAG 2.2 AA** or **AAA** and the checking tools.
- The page is opened in a real browser (desktop and 320 px wide) and checked by axe-core and Alfa.
- Results are grouped by WCAG success criterion, with where each problem is, what the tool said,
  and a link to the W3C guidance. AAA checks also list the criteria a person must review.
- Display settings: reading font (Atkinson Hyperlegible Next, Lexend, OpenDyslexic or your
  browser's font), light / dark / extra-contrast colours, and wider text spacing.
- No JavaScript is sent to the browser.
- **Copilot CLI prompts:** every scan with problems gives a ready-made fix request to run with
  GitHub Copilot CLI in your project, once a person has verified the results.
- **Privacy first:** every scan needs explicit permission from the signed-in user; potential
  private data is flagged and hidden until someone with permission confirms; nothing is sent
  anywhere automatically. See [PRIVACY_ARCHITECTURE.md](PRIVACY_ARCHITECTURE.md).

## Standards

- **WCAG 2.2** (W3C Recommendation), Level AA and AAA. A Level AA check also covers every WCAG 2.1
  Level AA requirement.

Confirm your obligations with your organization's accessibility coordinator — this is not legal
advice.

## Install

These steps work on Windows, Mac and Linux. They take about 15 minutes, most of it waiting for
downloads. You only type a few short commands; each step says what you should see.

### 1. Install Docker Desktop

wa-a11y runs inside Docker, a free program that keeps it separate from the rest of your computer.

1. Go to <https://www.docker.com/products/docker-desktop/>, download Docker Desktop for your
   computer, and install it like any other program.
2. Open Docker Desktop and wait until it says **Engine running** (bottom left).

### 2. Download wa-a11y

1. On this page, click the green **Code** button, then **Download ZIP**.
2. Unzip it (double-click the file). You get a folder called `wa-a11y-main`. Move it somewhere
   easy to find, such as your Documents folder.

### 3. Open a terminal in that folder

A terminal is a window where you type commands.

- **Windows:** open the `wa-a11y-main` folder, click the address bar at the top, type
  `powershell`, and press Enter.
- **Mac:** open **Terminal** (Applications → Utilities). Type `cd ` (with a space), drag the
  `wa-a11y-main` folder into the window, and press Enter.
- **Linux:** right-click inside the folder and choose **Open in Terminal**.

### 4. Create the settings file

Copy and paste this line, then press Enter:

- **Windows:** `copy .env.example .env`
- **Mac and Linux:** `cp .env.example .env`

Nothing appears; that is normal. The default settings work as they are.

### 5. Start wa-a11y

```
docker compose up -d --build
```

The first time, this downloads and builds everything and can take 5–10 minutes. It is finished
when you see three lines ending in **Started** (or **Healthy**). Later starts take seconds.

### 6. Create your account

Replace `you@example.com` with your email address:

```
docker compose exec web /app/.venv/bin/python -m app.accounts create you@example.com --admin
```

It asks for a password twice (at least 12 characters). Nothing shows while you type; that is
normal.

### 7. Open wa-a11y

Go to <http://127.0.0.1:8580/> in your web browser and sign in with your email and password.
wa-a11y only runs on your own computer; nobody else can reach it.

### Everyday use

- **Stop:** `docker compose stop` (in the same folder). **Start again:** `docker compose start`.
- **Something went wrong?** Check that Docker Desktop shows **Engine running**, then run step 5
  again.

Installing for a team on a server, HTTPS, upgrades and backups: see [INSTALL.md](INSTALL.md).
It also has a ready-made prompt to let GitHub Copilot CLI walk you through the install.

## Configuration (`.env`)

| Setting | Default | Purpose |
|---|---|---|
| `WA_A11Y_SESSION_SECRET` | empty (generated) | Leave empty: wa-a11y creates and keeps a strong session secret in the data volume. |
| `WA_A11Y_BIND` / `WA_A11Y_PORT` | `127.0.0.1` / `8580` | Where the site is published |
| `WA_A11Y_BASE_PATH` | empty | Path prefix when served behind another proxy, e.g. `/wa-a11y` |
| `WA_A11Y_ALLOW_HTTP` | off | Allow `http://` targets (default: `https://` only) |
| `WA_A11Y_ALLOWED_DOMAINS` | any public site | Limit scans to these domains and subdomains |
| `WA_A11Y_ALLOW_LOCAL_TARGETS` | off | Allow loopback/LAN targets (`localhost`, `127.0.0.1`, LAN) — local installs only |
| `WA_A11Y_MAX_QUEUED` | `20` | Most checks waiting at once |
| `WA_A11Y_SCAN_TIMEOUT_S` | `300` | Time limit per check |
| `WA_A11Y_MODIFIED_BY` | empty | Modified deployments (NOTICE §7(c)): shows "Based on wa-a11y, modified by …" in the footer |

## How it works

```
Browser ──► Caddy (body limit) ──► web (FastHTML, SQLite, sign-in) ──► scanner (Node, Playwright)
                                            │  queue + runner            axe-core + Alfa
                                            └─ /data volume              egress guard
```

- **web** — FastHTML app; SQLite via SQLModel with Alembic migrations; background runner
  processes the scan queue; security headers with a hash-based Content Security Policy.
- **scanner** — stateless service. Every request the browser makes goes through an egress guard
  that refuses internal, private and tailnet addresses (including after redirects).
- **caddy** — the only published port.
- **Accounts** — local accounts in SQLite (argon2id), server-side sessions, lockout after
  repeated failures, per-user scan limits. Sign-in allows paste and password managers (WCAG 3.3.8).


## Development

Package managers: **uv** (Python) and **pnpm** (Node) only.

```bash
pnpm install && pnpm -C styles build                  # theme + fonts
pnpm -C scanner exec playwright install chromium      # browser for the scanner and its tests
pnpm -C scanner dev                                   # scanner on :3001 (separate terminal)

cd web && uv sync
export WA_A11Y_DB_URL=sqlite:///$PWD/dev.db WA_A11Y_SESSION_SECRET=dev SCANNER_URL=http://127.0.0.1:3001
uv run alembic upgrade head && uv run uvicorn app.main:app --reload
```

The session cookie is `Secure`; browsers allow it on `http://127.0.0.1` and `http://localhost`.
Local scans of `127.0.0.1` sites are refused by design (internal address); a personal
installation can opt in with `WA_A11Y_ALLOW_LOCAL_TARGETS=1` — both guards then allow
loopback/LAN targets, while link-local and cloud-metadata addresses stay blocked.

### Quality gates

`scripts/check` runs everything below; `scripts/install-hooks` runs it before every push.

| Check | What it guards |
|---|---|
| ruff (incl. security rules `S`), pytest | Python quality, security patterns, behaviour |
| pip-audit, pnpm audit | Known vulnerabilities in dependencies |
| fallow, TypeScript | Dead code, duplication, complexity in the scanner |
| styles | Theme build + every colour pair ≥ 7:1 (text) / 3:1 (controls) in every theme |
| css-gates | No justified text, removed focus outlines, opacity, floating labels, Bootstrap JS, visited styling |
| selfscan | WA-A11y's own pages: axe-core + Alfa at AAA across fonts, themes, spacing and widths, plus focus, reflow, text-spacing, no-JS and CSP checks |
| gitleaks, ignore guards | No secrets or git-ignored files in the repository |

`scripts/docker-engine-check` proves the stack on a real Docker Engine from a clean checkout
(Docker-in-Docker inside Podman), for hosts that only have Podman.

Some AAA criteria need a person: [`docs/aaa-manual-checklist.md`](docs/aaa-manual-checklist.md)
is signed off for every release.

### Known engine gotchas

- **Alfa ignores linked stylesheets**, so the theme is inlined in each page.
- **Playwright's `networkidle` can hang**; pages load to `load` plus a short settle.
- **axe-core 4.13 has no `wcag22a` / `wcag21aaa` tags**; `scanner/levels.json` is the single
  source of truth and is tested against the installed axe-core.

## Licence

wa-a11y is free software: **GNU Affero General Public License v3 or later**
([LICENSE](LICENSE), SPDX `AGPL-3.0-or-later`), Copyright (C) 2026 Kevin Miller (rockypod), with
additional terms under **Section 7(b) and 7(c)** in [NOTICE](NOTICE).

- **Network use (Section 13):** if you run a modified wa-a11y as a service, you must offer every
  user the complete corresponding source of your modified version, free of charge. wa-a11y links to
  its source on every page (footer and the About and licence page) — keep that link and point it at
  your modified source. Public source: <https://github.com/rockypod/wa-a11y>.
- **Keep the lineage (Section 7(b)):** retain the wa-a11y name, copyright notice, NOTICE file and
  the SPDX header in every source file.
- **Mark your changes (Section 7(c), Section 5):** each modified file states that you changed it,
  when, and what; the About and licence page and your README say
  "Based on wa-a11y, modified by [Entity Name]".
- Every source file carries the SPDX header; `scripts/license-headers` checks it (and `--fix` adds
  it). Bundled fonts are under the SIL Open Font License 1.1.

This is not legal advice.
