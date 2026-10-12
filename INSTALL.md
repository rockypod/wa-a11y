<!--
wa-a11y
SPDX-License-Identifier: AGPL-3.0-or-later

This file is part of wa-a11y.
Copyright (C) 2026 Kevin Miller (rockypod)
Modifications must retain this wa-a11y notice and document all changes
pursuant to AGPLv3 Section 5 and Section 7.
-->

# Installing wa-a11y

This guide installs wa-a11y on **one Linux server** with Docker or Podman. It is written for an IT
person who has not seen the project before. Every step has commands you can copy, and a way to
check that the step worked.

macOS and Windows with **Docker Desktop** also work: see
[Notes for macOS and Windows](#notes-for-macos-and-windows).

Prefer to have an assistant run the steps? See
[14. Install with GitHub Copilot CLI](#14-install-with-github-copilot-cli).

In the commands below, `docker compose` is shown first. With Podman, use `podman-compose` (or
`podman compose`) in the same place; the rest of the command is the same unless a step says
otherwise. Run every command from the `wa-a11y` folder.

## Contents

1. [What you get](#1-what-you-get)
2. [Requirements](#2-requirements)
3. [Get the code](#3-get-the-code)
4. [Configure `.env`](#4-configure-env)
5. [Start wa-a11y](#5-start-wa-a11y)
6. [Create accounts](#6-create-accounts)
7. [Sign in and run a first check](#7-sign-in-and-run-a-first-check)
8. [HTTPS, another reverse proxy, or a sub-path](#8-https-another-reverse-proxy-or-a-sub-path)
9. [Upgrades](#9-upgrades)
10. [Backups and restore](#10-backups-and-restore)
11. [Troubleshooting](#11-troubleshooting)
12. [Uninstall](#12-uninstall)
13. [Licence](#13-licence)
14. [Install with GitHub Copilot CLI](#14-install-with-github-copilot-cli)

## 1. What you get

wa-a11y runs as **three containers**, defined in `compose.yaml`:

| Container | What it does | Network |
|---|---|---|
| `caddy` | Small web server in front of the app. Limits request size. **The only container with a published port** (default `127.0.0.1:8580`). | `front` |
| `web` | The website: sign-in, the check form, results, the scan queue. Stores everything in SQLite. | `front` and `back` |
| `scanner` | Opens the page you want to check in Chromium and runs axe-core and Siteimprove Alfa. Stores nothing. | `back` only |

- **Data:** one named volume, `wa-a11y-data`, mounted at `/data` in the `web` container. It holds
  the SQLite database (`/data/wa_a11y.db`), the local search index (`/data/chroma`) and backups
  you make (`/data/backups/`).
- **No telemetry.** No analytics, crash reports, update checks or cloud APIs.
- **No outbound traffic at run time except the pages you check.** The scanner sends every browser
  request through an egress guard that refuses internal and private addresses, even after
  redirects. See [PRIVACY_ARCHITECTURE.md](PRIVACY_ARCHITECTURE.md).
- **Building the images does need the internet:** it downloads base images, Python and Node
  packages, and a small text-embedding model that is then stored inside the `web` image.
- All three containers run as non-root users.
- There is no self-registration. An administrator creates every account from the command line.

## 2. Requirements

**Hardware (rough guidance for one server):**

| | Minimum | Recommended |
|---|---|---|
| CPU | 2 cores | 4 cores |
| RAM | 3 GB | 4 GB or more (Chromium alone needs about 1–2 GB while a check runs) |
| Free disk | 10 GB | 20 GB (images take several GB; the database grows with each check) |

The scanner runs **one check at a time**; other checks wait in a queue.

**Software:**

- One of:
  - **Docker Engine** with the **Compose plugin** (`docker compose`), or
  - **Podman** with **podman-compose** (`podman-compose`) or `podman compose`.
- **git** (to get the code and to upgrade).
- **openssl** (to create the session secret).
- **curl** (only used to check that the site answers).

Check what you have:

```bash
docker compose version     # or: podman-compose --version  /  podman compose version
git --version
openssl version
```

**Check it worked:** each command prints a version number. If `docker compose version` fails but
`docker --version` works, install the Docker Compose plugin from your distribution or from Docker.

## 3. Get the code

### Option A: git clone (recommended)

```bash
git clone https://github.com/rockypod/wa-a11y.git
cd wa-a11y
git tag --list            # shows the released versions, for example v0.2.3
git checkout v0.2.3       # use the newest tag from the list
```

**Check it worked:** `git describe --tags` prints the tag you chose, and `ls` shows
`compose.yaml`, `.env.example` and `INSTALL.md`.

### Option B: a release archive

1. On <https://github.com/rockypod/wa-a11y>, open **Releases** (or **Tags**) and download the
   source archive (`.tar.gz`) for the newest version.
2. Work out its SHA-256 checksum:

   ```bash
   sha256sum wa-a11y-0.2.3.tar.gz      # macOS: shasum -a 256 wa-a11y-0.2.3.tar.gz
   ```

3. If the release page lists a SHA-256 value, compare it with what you got. They must be
   identical. If they differ, delete the file and download it again. If no value is published,
   use Option A instead, so git can confirm what you have.
4. Unpack and enter the folder:

   ```bash
   tar -xzf wa-a11y-0.2.3.tar.gz
   cd wa-a11y-0.2.3
   ```

**Check it worked:** `ls` shows `compose.yaml` and `.env.example`.

With an archive, upgrades mean downloading the next archive and copying your `.env` across; git
makes this easier (see [Upgrades](#9-upgrades)).

## 4. Configure `.env`

All settings live in one file, `.env`, in the `wa-a11y` folder. It is never committed to git.

1. Copy the example file and make it readable only by you:

   ```bash
   cp .env.example .env
   chmod 600 .env
   ```

2. The **session secret** (signs the sign-in cookie) needs nothing from you: leave
   `WA_A11Y_SESSION_SECRET` empty and wa-a11y generates a strong one on first start, stored on the
   data volume (`/data/session-secret`, readable only by the app). To use your own instead, write
   32+ random characters into `.env` without printing them:

   ```bash
   sed -i "s/^WA_A11Y_SESSION_SECRET=.*/WA_A11Y_SESSION_SECRET=$(openssl rand -hex 32)/" .env
   ```

   On macOS use `sed -i ''` instead of `sed -i`. A value shorter than 32 characters is refused.

3. Open `.env` in a text editor and review the other settings (table below). To turn on a setting
   that starts with `#`, remove the `#`.

**Check it worked:** `.env` exists in the `wa-a11y` folder (`ls -la .env` shows it).

On first start, the web container creates the secret in the data volume when this setting is empty
or `change-me`. Confirm that startup worked with the health check in section 5; never print the
secret. A custom value shorter than 32 characters is refused.

### Every setting

| Setting | Default | What it does |
|---|---|---|
| `WA_A11Y_SESSION_SECRET` | empty (generated) | Signs the session cookie. Leave empty to have a strong one generated and kept on the data volume, or set 32+ random characters (`openssl rand -hex 32`). Keep it secret. |
| `WA_A11Y_BIND` | `127.0.0.1` | The address the `caddy` port is published on. Keep `127.0.0.1` when a reverse proxy on the same server sits in front (recommended). Use a specific private IP of the server only when a proxy on another machine connects to it. |
| `WA_A11Y_PORT` | `8580` | The published port. |
| `WA_A11Y_BASE_PATH` | empty | Set only when wa-a11y is served under a sub-path of another site, for example `/wa-a11y`. Your outer proxy must remove this prefix before passing requests on (see [section 8](#8-https-another-reverse-proxy-or-a-sub-path)). No trailing slash. |
| `WA_A11Y_WAIT_S` | `60` | How many seconds the browser waits on "Start check" before it is shown a progress page instead. Range 0–120; `0` means never wait. **Every proxy in front must allow longer than this** (see [section 8](#8-https-another-reverse-proxy-or-a-sub-path)). |
| `WA_A11Y_MAX_WAITERS` | `8` | How many browser requests may wait for a result at the same time (1–64). Extra requests go straight to the progress page. |
| `WA_A11Y_MAX_WAITERS_PER_USER` | `2` | How many of those waiting slots one account may hold. |
| `WA_A11Y_MAX_QUEUED` | `20` | Most checks waiting in the queue at once. When full, users see "The checker is busy right now". Commented out in `.env.example`; uncomment to change it. |
| `WA_A11Y_SCAN_TIMEOUT_S` | `300` | Time limit in seconds for one check. Commented out in `.env.example`; uncomment to change it. |
| `WA_A11Y_ALLOW_HTTP` | off | Set to `1` to allow `http://` addresses as well as `https://`. |
| `WA_A11Y_ALLOWED_DOMAINS` | empty (any public website) | Comma-separated list of domains. When set, only these domains **and their subdomains** can be checked, for example `example.org,example.net`. |
| `WA_A11Y_ALLOW_LOCAL_TARGETS` | off | **Security setting. Keep off on shared servers.** Set to `1` to allow checks of `localhost`, `127.0.0.1` and private LAN addresses (10.x, 172.16–31.x, 192.168.x, IPv6 `::1` and `fd00::/8`). It turns off this protection in both the `web` container and the scanner's egress guard, so anyone with an account could make the scanner open internal services. Link-local and cloud-metadata addresses stay blocked. Meant only for a personal install on your own computer. |
| `WA_A11Y_MODIFIED_BY` | empty | Only if you changed the source code. Shows "Based on wa-a11y, modified by …" in the footer, as required by the licence's Section 7(c) terms (see [NOTICE](NOTICE)). Leave unset for the original software. |

On/off settings accept `1`, `true`, `yes` or `on`.

Other `WA_A11Y_*` variables found in the code (database path, search index path, runner switches)
are for development and tests. Leave them unset.

## 5. Start wa-a11y

1. Build the images and start the containers. The first build takes several minutes.

   ```bash
   docker compose up -d --build
   ```

   With Podman:

   ```bash
   podman-compose up -d --build        # or: podman compose up -d --build
   ```

2. Wait about a minute, then look at the container status:

   ```bash
   docker compose ps
   ```

   With Podman:

   ```bash
   podman ps --format "{{.Names}}  {{.Status}}"
   ```

   **Check it worked:** all three containers (`scanner`, `web`, `caddy`) show `Up` and
   `(healthy)`. The containers start in order: `scanner` first, then `web`, then `caddy`.

3. Ask the site whether it is running:

   ```bash
   curl -fsS http://127.0.0.1:8580/healthz
   ```

   **Check it worked:** it prints `ok`. (Use your `WA_A11Y_PORT` if you changed it.)

4. Optional: confirm that pages need a sign-in:

   ```bash
   curl -sI http://127.0.0.1:8580/ | head -1     # HTTP/1.1 303 See Other (redirect to /login)
   ```

The database is created and updated automatically each time the `web` container starts.

If a container is not healthy, see [Troubleshooting](#11-troubleshooting).

## 6. Create accounts

Accounts are managed with a command inside the `web` container. It asks for the password twice,
without showing it. Passwords must be **12 to 256 characters**; a short sentence works well.
Never put a password on the command line.

**First administrator:**

```bash
docker compose exec web /app/.venv/bin/python -m app.accounts create admin@example.org --admin
```

**Check it worked:** it prints `created admin@example.org (admin)`.

**More users** (without `--admin` they are ordinary users). `--name` is optional:

```bash
docker compose exec web /app/.venv/bin/python -m app.accounts create someone@example.org --name "Sam Example"
```

**Other account commands:**

| Task | Command (after `docker compose exec web /app/.venv/bin/python -m app.accounts`) |
|---|---|
| List accounts, roles, state and last sign-in | `list` |
| Set a new password (signs the user out everywhere) | `reset-password someone@example.org` |
| Block an account (signs the user out everywhere) | `disable someone@example.org` |
| Unblock an account | `enable someone@example.org` |

With Podman, replace `docker compose exec` with `podman-compose exec` (or `podman compose exec`).

After 5 wrong passwords in a row an account is locked for 15 minutes. Sessions last 12 hours.

## 7. Sign in and run a first check

1. Open <http://127.0.0.1:8580/> in a browser **on the server itself** (or through an SSH tunnel:
   `ssh -L 8580:127.0.0.1:8580 you@server`, then open the same address on your computer). For
   access from other computers, set up HTTPS first ([section 8](#8-https-another-reverse-proxy-or-a-sub-path)).
2. Sign in with the administrator account.
3. On the home page, enter a public web address you are allowed to check, for example
   `https://example.org/`. Choose **WCAG 2.2 Level AA** or **AAA** and the checking tools.
4. Tick the **permission box**. A check cannot start without it; your name is recorded as the
   person who authorised it.
5. Choose **Start check**. The page waits for the result (up to `WA_A11Y_WAIT_S` seconds), or
   shows a progress page you can reload.

**Check it worked:** a results page opens with the "Scan authorized by user" banner, problems
grouped by WCAG success criterion, and a list of things a person still needs to check.

What else you will see:

- **Manual checklist:** a guided checklist for the criteria that tools cannot decide.
- **Privacy gates:** if the captured text looks like private data (for example phone numbers or
  ID numbers), those findings are hidden until someone ticks that they have permission to view
  them. A person must also confirm that they checked the results before anything can be exported.
- **GitHub Copilot CLI request:** after verification, "Get the GitHub Copilot CLI request" gives a
  ready-made fix request to copy or download and run with GitHub Copilot CLI in the website's own
  code. Nothing is sent anywhere automatically.

## 8. HTTPS, another reverse proxy, or a sub-path

The built-in `caddy` container speaks **plain HTTP only** and listens on `127.0.0.1:8580` by
default. To let people use wa-a11y from other computers, put an HTTPS reverse proxy in front.

**Why HTTPS is required:** the sign-in cookie is marked `Secure`. Browsers only send it over
HTTPS, with one exception: `http://localhost` and `http://127.0.0.1`. Over plain `http://` to any
other address, sign-in looks like it works but you are sent straight back to the sign-in page.

**Timeouts:** "Start check" keeps the request open for up to `WA_A11Y_WAIT_S` seconds (maximum
120). Every proxy in front must allow a longer wait for the response. The built-in Caddy allows
150 seconds; use 150 seconds in your proxy too. nginx's default (60 seconds) is **too short**.

**Headers:** wa-a11y does not read `X-Forwarded-Prefix` or other `X-Forwarded-*` headers. The
sub-path comes only from `WA_A11Y_BASE_PATH`, and the proxy must remove the prefix itself.

**Request size:** the built-in Caddy refuses request bodies over 64 KB. You do not need a limit in
your proxy, but a smaller one would break forms.

Replace `wa-a11y.example.org` and the certificate paths with your own.

### Caddy on the host, own hostname

```caddy
wa-a11y.example.org {
	reverse_proxy 127.0.0.1:8580 {
		transport http {
			response_header_timeout 150s
		}
	}
}
```

Caddy gets and renews the certificate itself if the name is reachable from the internet;
otherwise add a `tls /path/to/cert.pem /path/to/key.pem` line.

### nginx on the host, own hostname

```nginx
server {
    listen 443 ssl;
    server_name wa-a11y.example.org;
    ssl_certificate     /etc/ssl/wa-a11y.example.org.crt;
    ssl_certificate_key /etc/ssl/wa-a11y.example.org.key;

    location / {
        proxy_pass http://127.0.0.1:8580;
        proxy_set_header Host $host;
        proxy_read_timeout 150s;
    }
}
```

### Under a sub-path of an existing site

Example: `https://tools.example.org/wa-a11y/`.

1. In `.env`, set `WA_A11Y_BASE_PATH=/wa-a11y` (leading slash, no trailing slash).
2. Recreate the containers so they read it (see the Podman note in [Upgrades](#9-upgrades)):

   ```bash
   docker compose up -d
   ```

3. Configure the proxy to **remove** `/wa-a11y` before passing the request on.

Caddy (`handle_path` removes the prefix):

```caddy
tools.example.org {
	redir /wa-a11y /wa-a11y/
	handle_path /wa-a11y/* {
		reverse_proxy 127.0.0.1:8580 {
			transport http {
				response_header_timeout 150s
			}
		}
	}
}
```

nginx (the trailing `/` on `proxy_pass` removes the prefix):

```nginx
location = /wa-a11y { return 301 /wa-a11y/; }
location /wa-a11y/ {
    proxy_pass http://127.0.0.1:8580/;
    proxy_set_header Host $host;
    proxy_read_timeout 150s;
}
```

**Check it worked:** `https://tools.example.org/wa-a11y/healthz` prints `ok`, and after signing in
the links on the page start with `/wa-a11y/`. The cookies are limited to that path, so other apps
on the same site never receive them.

### A proxy on another machine

Set `WA_A11Y_BIND` to the server's private IP address (not `0.0.0.0` on a server reachable from
the internet), recreate the containers, and point the proxy at `http://<that IP>:8580`. Use a
firewall so that only the proxy can reach that port.

## 9. Upgrades

1. **Back up first** ([section 10](#10-backups-and-restore)).
2. Get the new version:

   ```bash
   git fetch --tags
   git tag --list
   git diff v0.2.3 v0.3.0 -- .env.example      # new or changed settings (use your tags)
   git checkout v0.3.0
   ```

   Add any new settings you need to your `.env`.
3. Rebuild and restart.

   Docker:

   ```bash
   docker compose up -d --build
   ```

   Podman with **podman-compose**: `up -d --build` rebuilds the images but **does not replace
   containers that are already running**, so you would keep running the old version. Build, then
   stop and start:

   ```bash
   podman-compose build
   podman-compose down
   podman-compose up -d
   ```

   **Never add `-v` to `down`**: `down -v` deletes the data volume with all accounts and results.

   The same applies whenever you change `.env`: with podman-compose, run `podman-compose down`
   and then `podman-compose up -d`.

4. Database updates (migrations) run automatically when the `web` container starts.

**Check it worked:** all containers are `(healthy)`, `curl -fsS http://127.0.0.1:8580/healthz`
prints `ok`, and the page footer or the About page shows the new version. Your accounts and old
results are still there.

## 10. Backups and restore

Everything important is in the SQLite database `/data/wa_a11y.db` on the `wa-a11y-data` volume.
wa-a11y includes a backup command that uses SQLite's online backup, so it is safe to run while
the site is in use.

### Make a backup

```bash
docker compose exec web /app/.venv/bin/python -m app.store.backup
```

It prints the file it wrote, for example `/data/backups/wa_a11y-20261004T120000Z.db`. That file is
**inside the data volume**, so it is lost if the volume is deleted. Copy it off the server's
volume:

```bash
docker compose exec -T web cat /data/backups/wa_a11y-20261004T120000Z.db > wa_a11y-20261004T120000Z.db
chmod 600 wa_a11y-20261004T120000Z.db
```

(Use the file name that was printed. With Podman, `podman-compose exec -T web …`.) Store the copy
somewhere safe: it contains account names, password hashes and scan results.

**Check it worked:** the copied file is larger than zero bytes, and this prints `ok`:

```bash
python3 -c "import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute('pragma integrity_check').fetchone()[0])" wa_a11y-20261004T120000Z.db
```

To run backups every night, put the two commands in a script and call it from cron or a systemd
timer. Old files in `/data/backups/` are not deleted automatically.

The search index in `/data/chroma` does not need a backup; it can be rebuilt from the database.

### Restore a backup

1. Copy the backup into the volume (the site may still be running):

   ```bash
   docker compose exec -T web sh -c 'cat > /data/backups/restore.db' < wa_a11y-20261004T120000Z.db
   ```

2. Stop the site:

   ```bash
   docker compose stop caddy web
   ```

3. Copy the backup over the live database with SQLite's backup function (this runs a one-off
   `web` container as the same non-root user, so file ownership stays correct):

   ```bash
   docker compose run --rm --no-deps web /app/.venv/bin/python -c "from pathlib import Path; from app.store.backup import backup; print(backup(Path('/data/wa_a11y.db'), Path('/data/backups/restore.db')))"
   ```

4. Start the site again, then rebuild the search index:

   ```bash
   docker compose up -d
   docker compose exec web /app/.venv/bin/python -m app.rag reindex
   ```

With Podman, use `podman-compose` in place of `docker compose` in every step.

**Check it worked:** the containers are `(healthy)`, you can sign in with an account from the
backup, and the reindex command prints `reindexed … findings, … guidance records`. If the backup
came from an older version, its database is updated automatically when `web` starts.

## 11. Troubleshooting

**See what the containers are doing:**

```bash
docker compose ps
docker compose logs --tail 100 web
docker compose logs --tail 100 scanner
docker compose logs --tail 100 caddy
docker compose logs -f web          # follow live; Ctrl+C to stop
```

With Podman: `podman ps`, `podman-compose logs web` and so on.

| What you see | Likely cause and fix |
|---|---|
| Your proxy shows **502 Bad Gateway** | wa-a11y is not running or not healthy. Check `docker compose ps` and the logs. Also check that the proxy points at `WA_A11Y_BIND:WA_A11Y_PORT`. |
| Proxy shows **504** or the page stops loading after about 60 seconds on "Start check" | The proxy timeout is shorter than `WA_A11Y_WAIT_S`. Set it to 150 seconds ([section 8](#8-https-another-reverse-proxy-or-a-sub-path)). The check itself still finishes; open **Recent checks**. |
| `web` keeps restarting; log says `WA_A11Y_SESSION_SECRET is too short` | Your own secret is under 32 characters. Set a longer one, or leave it empty to have one generated, then run `docker compose up -d` again. |
| Sign-in "works" but you land on the sign-in page again | You are using plain `http://` with an address other than `localhost` or `127.0.0.1`. The cookie is `Secure`; use HTTPS. Also check that the browser allows cookies for the site. |
| Links or styles are broken under a sub-path | `WA_A11Y_BASE_PATH` does not match the proxy path, or the proxy does not remove the prefix. |
| "The checker is busy right now. Please try again in a few minutes." | The queue holds `WA_A11Y_MAX_QUEUED` checks already. Wait, or raise the limit. |
| "You have started many checks in a short time." | Per-account rate limit. Wait a few minutes. |
| "This address points to an internal or private network." | By design: `localhost`, `127.0.0.1`, LAN and other internal addresses are refused so the scanner cannot reach internal services. Only on a personal install, `WA_A11Y_ALLOW_LOCAL_TARGETS=1` allows loopback and LAN addresses. |
| "The address must start with https://" | Only `https://` is allowed unless `WA_A11Y_ALLOW_HTTP=1`. |
| "This checker only scans approved … websites." | The domain is not in `WA_A11Y_ALLOWED_DOMAINS`. |
| "We could not find the website …" | The server cannot resolve that name in DNS. Check DNS from the server. |
| A check fails although the site opens in your browser | The scanner must reach the site directly over the internet. Sites on private addresses, or sites that redirect to one, are blocked by the egress guard. Some sites block automated browsers. Check `docker compose logs scanner`. A corporate outbound proxy is not supported. |
| Containers stay `starting` or never become `healthy` with Podman | Podman runs health checks with systemd timers. Run `podman healthcheck run <container name>` to test by hand, and see `podman ps` for names. |
| Build fails while downloading | Building needs internet access to container registries and package mirrors. |

## 12. Uninstall

1. Stop and remove the containers and networks (your data stays on the volume):

   ```bash
   docker compose down
   ```

2. **Destructive, cannot be undone:** delete the data volume with every account, result and
   backup inside it. Make and copy a backup first if you might need it.

   ```bash
   docker volume rm wa-a11y_wa-a11y-data      # Podman: podman volume rm wa-a11y_wa-a11y-data
   ```

   (`docker volume ls` shows the exact name.)

3. Remove the images:

   ```bash
   docker image rm localhost/wa-a11y-caddy:dev localhost/wa-a11y-web:dev localhost/wa-a11y-scanner:dev
   ```

4. Delete the `wa-a11y` folder, including `.env`.

**Check it worked:** `docker ps -a`, `docker volume ls` and `docker image ls` no longer list
anything named `wa-a11y`.

## 13. Licence

wa-a11y is free software under the **GNU Affero General Public License, version 3 or later**
(`AGPL-3.0-or-later`), with additional terms in [NOTICE](NOTICE). See [LICENSE](LICENSE).

- Running the unmodified software for your users needs nothing extra. Every page already links
  to the source code.
- If you **modify** wa-a11y and let people use it over a network, Section 13 of the licence
  requires you to offer them the complete source of your modified version. Keep the source link
  on every page and point it at your modified source. Also set `WA_A11Y_MODIFIED_BY` and mark
  your changes as described in [NOTICE](NOTICE).

This is not legal advice.

## Notes for macOS and Windows

- Install **Docker Desktop**; it includes Docker Compose. Give it at least 4 GB of memory
  (Settings → Resources).
- On **Windows**, run the commands in a WSL 2 terminal (for example Ubuntu). There, `sed`,
  `openssl` and `curl` work as shown.
- On **macOS**, use `sed -i ''` in place of `sed -i`, and `shasum -a 256` in place of
  `sha256sum`.
- Open <http://127.0.0.1:8580/> on the same computer. Sign-in works over plain `http` there,
  because the address is `127.0.0.1`.

## 14. Install with GitHub Copilot CLI

You can ask GitHub Copilot CLI to perform this install for you. First do
[3. Get the code](#3-get-the-code) yourself, then start Copilot CLI (`copilot`) in a terminal
**inside the `wa-a11y` folder** on the server, and paste the prompt below.

> **Copilot CLI runs commands on your machine. Read each command before you approve it.**

```text
Install wa-a11y on this server by following INSTALL.md in the current directory, step by step,
in order (sections 2, 4, 5, 6 and, if I ask for it, 8). Rules:

1. Work only inside this wa-a11y directory. Do not read, create or change files outside it,
   except where INSTALL.md says so and I approve it.
2. Detect whether Docker (with `docker compose`) or Podman (with `podman-compose` or
   `podman compose`) is installed and use that one throughout. If neither is, stop and tell me.
3. Before every command that changes the system, show it and ask me first. That includes:
   installing packages, creating or editing .env, building images, starting or stopping
   containers, and creating accounts. Read-only checks (versions, `ps`, logs, `curl` of
   /healthz) may run without asking.
4. Session secret: leave WA_A11Y_SESSION_SECRET empty (wa-a11y generates one and keeps it on the
   data volume). Only if I ask for my own, generate it on this machine with `openssl rand -hex 32`
   and write it straight into .env with the `sed` command from INSTALL.md section 4. Never print
   it, show it, repeat it, or put it anywhere other than .env.
5. Passwords: never put a password on a command line, in an environment variable, or in shell
   history. Create accounts only with the interactive command from section 6
   (`... python -m app.accounts create <email> --admin`) and let me type the password at its
   prompt.
6. Keep WA_A11Y_ALLOW_LOCAL_TARGETS off (unset) unless I explicitly ask for it.
7. Do not open firewall ports, change system services, or edit proxy configuration without
   asking me first.
8. After each step, verify it with the check that INSTALL.md gives for that step (for example:
   the secret check in section 4, every container `(healthy)` and
   `curl -fsS http://127.0.0.1:8580/healthz` printing `ok` in section 5).
9. If any command fails or a check does not pass, stop and report exactly what happened and the
   relevant log lines. Do not improvise fixes, change settings, or try other approaches unless I
   approve them.
10. Never run `down -v` or delete volumes, images or files.
11. Use example.org placeholders only in examples; ask me for the real email address for the
    first administrator account.

At the end, summarise what was done, which settings in .env differ from .env.example (do not
show the secret), and the address where I can sign in.
```

**Check it worked:** the same checks as [section 5](#5-start-wa-a11y) and
[section 6](#6-create-accounts): all containers healthy, `/healthz` prints `ok`, and you can sign in.
