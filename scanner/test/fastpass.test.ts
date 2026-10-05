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
import { once } from "node:events";
import { readFileSync } from "node:fs";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { after, before, describe, test } from "node:test";
import { setAllowInternal } from "../src/egress.js";
import { getLevel } from "../src/levels.js";
import { closeBrowser, scan } from "../src/scan.js";
import { parseScanRequest } from "../src/server.js";
import { EVIDENCE_LIMITS, type EngineName } from "../src/types.js";

const FP = "accessibility-insights-fastpass" as const;
let site: Server;
let base = "";

before(async () => {
  site = createServer((req, res) => {
    const name = (req.url ?? "/").replace(/[^a-z-]/g, "");
    try {
      const body = readFileSync(new URL(`./fixtures/fastpass/${name}.html`, import.meta.url));
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end(body);
    } catch {
      res.writeHead(404).end();
    }
  });
  site.listen(0, "127.0.0.1");
  await once(site, "listening");
  const host = `127.0.0.1:${(site.address() as AddressInfo).port}`;
  setAllowInternal([host]); // fixtures only; everything else internal stays blocked
  base = `http://${host}/`;
});
after(() => closeBrowser().finally(() => site.close()));

const run = (fixture: string, level = "2.2-AA", engines: EngineName[] = [FP]) =>
  scan({ url: base + fixture, level, spec: getLevel(level)!, engines, profiles: ["desktop"],
    authorization: { privacy_consent: true, authorized_by: "tester@example.com" } });

type Result = Awaited<ReturnType<typeof run>>;
const pick = (r: Result, ruleId: string, outcome: "fail" | "cantTell") =>
  r.findings.filter((f) => f.engine === FP && f.ruleId === ruleId && f.outcome === outcome);

describe("FastPass keyboard checks", () => {
  test("pass: a well-behaved page has no findings, even at AAA", async () => {
    const r = await run("pass", "2.2-AAA");
    assert.equal(r.status, "done", r.error);
    assert.deepEqual(r.findings.filter((f) => f.engine === FP), []);
    assert.equal(r.profiles[0]?.engines[FP]?.passes, 6, "all six rules pass at AAA");
    assert.equal(r.toolVersions["wa-a11y-fastpass"], "1");
  });

  test("fail 2.1.2: a keyboard trap outside any dialog", async () => {
    const r = await run("trap");
    assert.equal(r.status, "done", r.error);
    const [trap] = pick(r, "fastpass-keyboard-trap", "fail");
    assert.ok(trap, "trap not reported");
    assert.deepEqual(trap.sc, ["2.1.2"]);
    assert.equal(trap.wcagLevel, "A");
    assert.equal(trap.impact, "critical");
    assert.match(trap.message, /cannot move focus away/);
  });

  test("fail 2.1.1: a widget role that cannot take focus; click-only and tabindex=-1 need a person", async () => {
    const r = await run("unreachable");
    assert.equal(r.status, "done", r.error);
    assert.deepEqual(pick(r, "fastpass-keyboard-reachable", "fail").map((f) => f.selector), ["#fake"]);
    assert.deepEqual(pick(r, "fastpass-keyboard-reachable", "cantTell").map((f) => f.selector).sort(), ["#clicky", "#roving"]);
    assert.equal(pick(r, "fastpass-keyboard-trap", "fail").length, 0);
  });

  test("fail 2.4.7: no visible change with focus (confirmed by screenshot)", async () => {
    const r = await run("no-focus");
    assert.equal(r.status, "done", r.error);
    assert.deepEqual(pick(r, "fastpass-focus-visible", "fail").map((f) => f.selector), ["#hidden-focus"]);
    assert.equal(r.findings.filter((f) => f.selector === "#ok").length, 0);
  });

  test("cantTell 2.4.3 order and 2.4.13 appearance — never fail on heuristics", async () => {
    const r = await run("cant-tell", "2.2-AAA");
    assert.equal(r.status, "done", r.error);
    const mine = r.findings.filter((f) => f.engine === FP);
    assert.ok(mine.every((f) => f.outcome === "cantTell"), JSON.stringify(mine.map((f) => [f.ruleId, f.selector])));
    const order = pick(r, "fastpass-focus-order", "cantTell").map((f) => f.selector).sort();
    assert.deepEqual(order, ["#first", "#high"]);
    const appearance = pick(r, "fastpass-focus-appearance", "cantTell");
    assert.deepEqual(appearance.map((f) => f.selector), ["#shadow"]);
    assert.equal(appearance[0]?.wcagLevel, "AAA");
  });

  test("levels.json filtering: 2.4.13 (AAA) never appears in an AA scan", async () => {
    const r = await run("cant-tell", "2.2-AA");
    assert.equal(r.status, "done", r.error);
    assert.equal(r.findings.filter((f) => f.sc.includes("2.4.13")).length, 0);
    assert.ok(pick(r, "fastpass-focus-order", "cantTell").length > 0);
  });

  test("findings follow the result contract and evidence stays bounded", async () => {
    const r = await run("unreachable", "2.2-AAA", ["axe", "alfa", FP]);
    assert.equal(r.status, "done", r.error);
    const fp = r.findings.filter((f) => f.engine === FP);
    assert.ok(fp.length > 0);
    assert.ok(fp.every((f) => f.source === "automated" && f.helpUrl.startsWith("https://www.w3.org/WAI/WCAG22/")));
    assert.ok(fp.every((f) => f.html.length <= EVIDENCE_LIMITS.html && f.selector.length <= EVIDENCE_LIMITS.selector));
    assert.ok(fp.every((f) => f.sc.length > 0 && f.wcagLevel !== null && f.profiles.length > 0));
    assert.deepEqual(r.contactedHosts, [new URL(base).host], "keyboard checks must not reach other hosts");
  });
});

describe("request validation", () => {
  const ok = { url: "https://example.org/", level: "2.2-AA", authorization: { privacy_consent: true, authorized_by: "tester@example.com" } };
  test("accepts the FastPass engine; the default stays axe + Alfa", () => {
    assert.deepEqual(parseScanRequest({ ...ok, engines: [FP] }).engines, [FP]);
    assert.deepEqual(parseScanRequest(ok).engines, ["axe", "alfa"]);
  });
  test("still requires authorization", () => {
    assert.throws(() => parseScanRequest({ ...ok, engines: [FP], authorization: undefined }), /authorization required/);
  });
});
