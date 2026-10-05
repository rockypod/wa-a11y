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
import axe from "axe-core";
import { LEVELS, getLevel } from "../src/levels.js";
import { setAllowInternal } from "../src/egress.js";
import { closeBrowser, scan } from "../src/scan.js";
import { parseScanRequest } from "../src/server.js";
import { EVIDENCE_LIMITS, type EngineName } from "../src/types.js";

const fixture = readFileSync(new URL("./fixtures/known-failures.html", import.meta.url));
let site: Server;
let base = "";

before(async () => {
  site = createServer((_req, res) => {
    res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    res.end(fixture);
  });
  await new Promise<void>((r) => site.listen(0, "127.0.0.1", r));
  const port = (site.address() as AddressInfo).port;
  setAllowInternal([`127.0.0.1:${port}`]); // fixture only; everything else internal stays blocked
  base = `http://127.0.0.1:${port}/`;
});
after(async () => {
  site.close();
  await closeBrowser();
});

const run = (level: string, engines: EngineName[] = ["axe", "alfa"]) =>
  scan({ url: base, level, spec: getLevel(level)!, engines, profiles: ["desktop"], authorization: { privacy_consent: true, authorized_by: "tester@example.com" } });

const fails = (r: Awaited<ReturnType<typeof run>>, engine: EngineName, sc: string) =>
  r.findings.filter((f) => f.engine === engine && f.outcome === "fail" && f.sc.includes(sc));

describe("levels.json", () => {
  test("every axe tag exists in the installed axe-core", () => {
    const known = new Set(axe.getRules().flatMap((r) => r.tags));
    for (const [name, spec] of Object.entries(LEVELS))
      for (const tag of spec.axeTags) assert.ok(known.has(tag), `${name}: axe has no tag "${tag}"`);
  });
  test("never includes best-practice", () => {
    for (const spec of Object.values(LEVELS)) assert.ok(!spec.axeTags.includes("best-practice"));
  });
});

describe("engine regression fixture", () => {
  test("AA: both engines report 1.1.1; no AAA-only 1.4.6 findings", async () => {
    const r = await run("2.2-AA");
    assert.equal(r.status, "done", r.error);
    assert.ok(fails(r, "axe", "1.1.1").length > 0, "axe stopped reporting image-alt (1.1.1)");
    assert.ok(fails(r, "alfa", "1.1.1").length > 0, "Alfa stopped reporting 1.1.1 — outcome parsing broken?");
    assert.equal(r.findings.filter((f) => f.sc.includes("1.4.6")).length, 0, "AAA finding leaked into AA scan");
    assert.ok(r.findings.every((f) => f.wcagLevel === "A" || f.wcagLevel === "AA"));
  });

  test("AAA: both engines additionally report 1.4.6 enhanced contrast", async () => {
    const r = await run("2.2-AAA");
    assert.equal(r.status, "done", r.error);
    assert.ok(fails(r, "axe", "1.1.1").length > 0);
    assert.ok(fails(r, "alfa", "1.1.1").length > 0);
    assert.ok(fails(r, "axe", "1.4.6").length > 0, "axe stopped reporting color-contrast-enhanced (1.4.6)");
    assert.ok(fails(r, "alfa", "1.4.6").length > 0, "Alfa stopped reporting 1.4.6 at AAA");
  });

  test("every finding follows the result contract: automated provenance, mapped SCs, bounded evidence", async () => {
    const r = await run("2.2-AAA");
    assert.equal(r.status, "done", r.error);
    assert.ok(r.findings.length > 0);
    assert.deepEqual([...new Set(r.findings.map((f) => f.source))], ["automated"]);
    assert.deepEqual([...new Set(r.findings.map((f) => f.engine))].sort(), ["alfa", "aria-tree", "axe"]);
    const fs = r.findings.filter((f) => f.engine !== "aria-tree");
    assert.ok(fs.every((f) => f.outcome === "fail" || f.outcome === "cantTell"), "engines list problems only");
    assert.ok(fs.every((f) => f.sc.length > 0 && f.wcagLevel !== null), "an unmapped finding was not filtered");
    assert.ok(!fs.some((f) => f.sc.includes("4.1.1")), "4.1.1 is obsolete in WCAG 2.2");
    assert.ok(fs.every((f) => f.html.length <= EVIDENCE_LIMITS.html && f.selector.length <= EVIDENCE_LIMITS.selector));
    assert.ok(fs.every((f) => f.message.length <= EVIDENCE_LIMITS.message && f.profiles.length > 0));
  });

  test("Alfa has no impact; axe does", async () => {
    const r = await run("2.2-AA");
    assert.ok(r.findings.filter((f) => f.engine === "alfa").every((f) => f.impact === null));
    assert.ok(fails(r, "axe", "1.1.1").every((f) => typeof f.impact === "string"));
  });

  test("tool versions are reported", async () => {
    const r = await run("2.2-AA", ["axe"]);
    for (const v of Object.values(r.toolVersions)) assert.notEqual(v, "unknown");
  });

  test("an unreachable page is an error, never an empty pass", async () => {
    const r = await scan({ url: "http://127.0.0.1:9/", level: "2.2-AA", spec: getLevel("2.2-AA")!, engines: ["axe", "alfa"], profiles: ["desktop"], authorization: { privacy_consent: true, authorized_by: "tester@example.com" } });
    assert.equal(r.status, "error");
    assert.equal(r.findings.length, 0);
    assert.match(r.error ?? "", /did not load|not allowed/);
  });
});

describe("request validation", () => {
  const ok = { url: "https://example.org/", level: "2.2-AA", authorization: { privacy_consent: true, authorized_by: "tester@example.com" } };
  test("defaults engines to both and profiles to desktop", () => {
    const r = parseScanRequest(ok);
    assert.deepEqual(r.engines, ["axe", "alfa"]);
    assert.deepEqual(r.profiles, ["desktop"]);
  });
  for (const [why, body] of [
    ["unknown level", { ...ok, level: "2.1-AA" }],
    ["inherited key as level", { ...ok, level: "toString" }],
    ["non-http scheme", { ...ok, url: "file:///etc/passwd" }],
    ["unknown engine", { ...ok, engines: ["wave"] }],
    ["empty engines", { ...ok, engines: [] }],
    ["unknown profile", { ...ok, profiles: ["iphone"] }],
    ["not an object", "scan please"],
  ] as const) {
    test(`rejects ${why}`, () => assert.throws(() => parseScanRequest(body)));
  }
});


describe("privacy rule", () => {
  test("scan() refuses without authorization", async () => {
    const base = { url: "https://example.org/", level: "2.2-AA", spec: getLevel("2.2-AA")!, engines: ["axe"] as EngineName[], profiles: ["desktop"] as const };
    await assert.rejects(scan({ ...base, profiles: ["desktop"] } as never), /privacy consent/);
    await assert.rejects(scan({ ...base, profiles: ["desktop"], authorization: { privacy_consent: false, authorized_by: "x" } } as never), /privacy consent/);
    await assert.rejects(scan({ ...base, profiles: ["desktop"], authorization: { privacy_consent: true, authorized_by: "  " } } as never), /privacy consent/);
  });

  test("request validation refuses without authorization", () => {
    for (const authorization of [undefined, {}, { privacy_consent: false, authorized_by: "x" }, { privacy_consent: true, authorized_by: "" }])
      assert.throws(() => parseScanRequest({ url: "https://example.org/", level: "2.2-AA", authorization }), /authorization required/);
  });

  test("the browser contacts only the requested site (no background traffic)", async () => {
    const r = await run("2.2-AA", ["axe", "alfa"]);
    assert.equal(r.status, "done", r.error);
    const host = new URL(base).host;
    assert.deepEqual(r.contactedHosts, [host], `unexpected outbound: ${r.contactedHosts.join(", ")}`);
  });
});
