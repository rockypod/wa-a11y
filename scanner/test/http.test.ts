/*
 * wa-a11y
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * This file is part of wa-a11y.
 * Copyright (C) 2026 Kevin Miller (rockypod)
 * Modifications must retain this wa-a11y notice and document all changes
 * pursuant to AGPLv3 Section 5 and Section 7.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { after, before, describe, test } from "node:test";
import { setAllowInternal } from "../src/egress.js";
import { closeBrowser } from "../src/scan.js";
import { server } from "../src/server.js";

const fixture = readFileSync(new URL("./fixtures/known-failures.html", import.meta.url));
let site: Server;
let api = "";
let page = "";

before(async () => {
  site = createServer((_q, r) => r.writeHead(200, { "content-type": "text/html" }).end(fixture));
  await new Promise<void>((r) => site.listen(0, "127.0.0.1", r));
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  const port = (site.address() as AddressInfo).port;
  setAllowInternal([`127.0.0.1:${port}`]);
  page = `http://127.0.0.1:${port}/`;
  api = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
});
after(async () => {
  server.close();
  site.close();
  await closeBrowser();
});

const post = (body: string) =>
  fetch(`${api}/scan`, { method: "POST", headers: { "content-type": "application/json" }, body });

describe("HTTP API", () => {
  test("GET /health reports versions", async () => {
    const r = await fetch(`${api}/health`);
    assert.equal(r.status, 200);
    const j = await r.json();
    assert.equal(j.ok, true);
    assert.ok(j.versions["axe-core"]);
  });

  test("unknown route → 404", async () => {
    assert.equal((await fetch(`${api}/nope`)).status, 404);
  });

  test("malformed JSON → 400", async () => {
    const r = await post("{not json");
    assert.equal(r.status, 400);
    assert.match((await r.json()).error, /JSON/);
  });

  test("oversized body → 400", async () => {
    const r = await post(JSON.stringify({ url: "https://x.org/", level: "2.2-AA", pad: "x".repeat(20_000) }));
    assert.equal(r.status, 400);
  });

  test("missing authorization → 400", async () => {
    const r = await post(JSON.stringify({ url: "https://example.org/", level: "2.2-AA" }));
    assert.equal(r.status, 400);
    assert.match((await r.json()).error, /authorization required/);
  });

  test("invalid request → 400 with a reason", async () => {
    const r = await post(JSON.stringify({ url: "ftp://x.org/", level: "2.2-AA", authorization: { privacy_consent: true, authorized_by: "tester@example.com" } }));
    assert.equal(r.status, 400);
    assert.match((await r.json()).error, /http/);
  });

  test("POST /scan runs both engines, plus the screen-reader structure check", async () => {
    const r = await post(JSON.stringify({ url: page, level: "2.2-AA", authorization: { privacy_consent: true, authorized_by: "tester@example.com" } }));
    assert.equal(r.status, 200);
    const j = await r.json();
    assert.equal(j.status, "done");
    assert.deepEqual(new Set(j.findings.map((f: { engine: string }) => f.engine)), new Set(["axe", "alfa", "aria-tree"]));
  });
});
