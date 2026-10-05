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
import { type Browser, chromium, type Page } from "playwright";
import { type AxNode, NOT_RUN, fromCdp, observe, readTree, runAriaTree } from "../src/engines/aria.js";
import { setAllowInternal } from "../src/egress.js";
import { getLevel } from "../src/levels.js";
import { closeBrowser, scan } from "../src/scan.js";
import { EVIDENCE_LIMITS, type RawFinding } from "../src/types.js";

const fixture = (name: string) => readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8");
const GOOD = fixture("aria-good.html");
const BAD = fixture("aria-bad.html");

let browser: Browser;
let site: Server;
let base = "";

const PAGES: Record<string, string> = { "/good": GOOD, "/bad": BAD };

before(async () => {
  browser = await chromium.launch();
  site = createServer((req, res) => res.writeHead(200, { "content-type": "text/html" }).end(PAGES[req.url ?? ""] ?? GOOD));
  site.listen(0, "127.0.0.1");
  await once(site, "listening");
  const { port } = site.address() as AddressInfo;
  setAllowInternal([`127.0.0.1:${port}`]);
  base = `http://127.0.0.1:${port}`;
});
after(async () => {
  site.close();
  await browser.close();
  await closeBrowser();
});

async function onPage<T>(html: string, fn: (p: Page) => Promise<T>): Promise<T> {
  const page = await browser.newPage();
  try {
    await page.setContent(html);
    return await fn(page);
  } finally {
    await page.close();
  }
}

const tally = (fs: RawFinding[]) => {
  const t: Record<string, number> = {};
  for (const f of fs) t[`${f.ruleId}:${f.outcome}`] = (t[`${f.ruleId}:${f.outcome}`] ?? 0) + 1;
  return t;
};

describe("aria-tree on the known-good fixture", () => {
  test("every observation passes; nothing fails or needs review", async () => {
    const run = await onPage(GOOD, (p) => runAriaTree(p));
    assert.deepEqual(tally(run.findings), {
      "aria-page-title:pass": 1,
      "aria-main-landmark:pass": 1,
      "aria-h1:pass": 1,
      "aria-heading-order:pass": 1,
      "aria-control-names:pass": 1,
      "aria-link-names:pass": 1,
      "aria-button-names:pass": 1,
      "aria-landmark-names:pass": 1,
    });
    assert.equal(run.passes, 8);
  });
});

describe("aria-tree on the known-bad fixture", () => {
  test("deterministic names fail; structural heuristics need review, never fail", async () => {
    const run = await onPage(BAD, (p) => runAriaTree(p));
    assert.deepEqual(tally(run.findings), {
      "aria-page-title:fail": 1,
      "aria-main-landmark:cantTell": 1,
      "aria-h1:cantTell": 1,
      "aria-heading-order:cantTell": 1,
      "aria-control-names:fail": 2,
      "aria-link-names:fail": 1,
      "aria-button-names:fail": 1,
      "aria-landmark-names:cantTell": 2,
    });
    assert.equal(run.passes, 0);
  });

  test("failures carry a route-safe locator, the tree line, a remediation hint and WCAG SCs", async () => {
    const run = await onPage(BAD, (p) => runAriaTree(p));
    const control = run.findings.filter((f) => f.ruleId === "aria-control-names");
    assert.deepEqual(control.map((f) => f.selector), ["page › textbox 1", "page › combobox 1"]);
    assert.deepEqual(control.map((f) => f.html), ["- textbox", "- combobox"]);
    assert.match(control[0]!.message, /label/);
    const skip = run.findings.find((f) => f.ruleId === "aria-heading-order")!;
    assert.equal(skip.selector, 'page › heading 2 "Skipped a level"');
    assert.match(skip.message, /level 4 follows level 2/);
    const link = run.findings.find((f) => f.ruleId === "aria-link-names")!;
    assert.equal(link.selector, 'page › navigation › link 2');
    assert.equal(link.html, "- link [url=/news]");
    for (const f of run.findings) {
      assert.equal(f.source, "automated");
      assert.equal(f.engine, "aria-tree");
      assert.ok(f.sc.length > 0 && f.wcagLevel !== null, `${f.ruleId} is not mapped to WCAG`);
      assert.match(f.helpUrl, /^https:\/\/www\.w3\.org\/WAI\/WCAG22\/Understanding\//);
      assert.ok(f.selector.length <= EVIDENCE_LIMITS.selector && f.html.length <= 300);
    }
  });
});

describe("accessibility-tree sources", () => {
  for (const [name, html] of [["good", GOOD], ["bad", BAD]] as const)
    test(`the CDP fallback gives the same observations as the aria snapshot (${name})`, async () => {
      const [snap, cdp] = await onPage(html, async (p) => [
        await runAriaTree(p, { snapshot: true, cdp: false }),
        await runAriaTree(p, { snapshot: false, cdp: true }),
      ]);
      assert.deepEqual(tally(cdp.findings), tally(snap.findings));
    });

  test("no source available → an explicit not-run item, never an empty pass", async () => {
    const page = await browser.newPage();
    await page.close();
    const run = await runAriaTree(page);
    assert.equal(run.passes, 0);
    assert.equal(run.findings.length, 1);
    assert.equal(run.findings[0]!.ruleId, NOT_RUN);
    assert.equal(run.findings[0]!.outcome, "cantTell");
    assert.match(run.findings[0]!.message, /could not run/);
  });

  test("readTree reports why when every source is off", async () => {
    await onPage(GOOD, (p) => assert.rejects(readTree(p, { snapshot: false, cdp: false }), /no accessibility-tree source/));
  });

  test("fromCdp skips ignored nodes and unnamed regions, keeps heading levels", () => {
    const tree = fromCdp([
      { nodeId: "1", role: { value: "RootWebArea" }, childIds: ["2", "3", "4"] },
      { nodeId: "2", ignored: true, role: { value: "none" }, childIds: ["5"] },
      { nodeId: "3", role: { value: "region" }, name: { value: "" }, childIds: [] },
      { nodeId: "4", role: { value: "heading" }, name: { value: "Hi" }, properties: [{ name: "level", value: { value: 1 } }] },
      { nodeId: "5", role: { value: "button" }, name: { value: "Go" } },
    ]);
    assert.deepEqual(tree, [
      { role: "button", name: "Go", children: [] },
      { role: "heading", name: "Hi", level: 1, children: [] },
    ]);
  });
});

describe("observe() bounds", () => {
  test("long names are clipped and listed items are capped", () => {
    const links: AxNode[] = Array.from({ length: 40 }, () => ({ role: "link" }));
    const tree: AxNode[] = [{ role: "main", name: "x".repeat(5000), children: [{ role: "heading", name: "y".repeat(5000), level: 1 }, ...links] }];
    const fs = observe("Title", tree);
    const nameless = fs.filter((f) => f.ruleId === "aria-link-names");
    assert.equal(nameless.length, 25);
    assert.match(nameless[0]!.message, /25 of 40 listed/);
    assert.ok(fs.every((f) => f.selector.length < 300 && f.html.length < 300));
  });

  test("a huge tree is checked up to the node cap and says so", () => {
    const tree: AxNode[] = Array.from({ length: 20_050 }, () => ({ role: "paragraph" }));
    const partial = observe("T", tree).find((f) => f.ruleId === "aria-tree-partial");
    assert.equal(partial?.outcome, "cantTell");
  });

  test("several main landmarks need review; role=heading without a level counts as 2", () => {
    const fs = observe("T", [
      { role: "main", children: [{ role: "heading", name: "A", level: 1 }, { role: "heading", name: "B" }] },
      { role: "main" },
    ]);
    assert.equal(fs.find((f) => f.ruleId === "aria-main-landmark")?.outcome, "cantTell");
    assert.equal(fs.find((f) => f.ruleId === "aria-heading-order")?.outcome, "pass");
  });

  test("a page with no headings needs review rather than passing", () => {
    const fs = observe("T", [{ role: "main" }]);
    assert.equal(fs.find((f) => f.ruleId === "aria-h1")?.outcome, "cantTell");
    assert.equal(fs.find((f) => f.ruleId === "aria-heading-order"), undefined);
  });
});

describe("scan() integration", () => {
  const auth = { privacy_consent: true, authorized_by: "tester@example.com" } as const;

  test("runs once per scan on the desktop profile, beside the engines, without failing the scan", async () => {
    const r = await scan({ url: `${base}/bad`, level: "2.2-AA", spec: getLevel("2.2-AA")!, engines: ["axe"], profiles: ["desktop", "mobile-320"], authorization: auth });
    assert.equal(r.status, "done", r.error);
    const aria = r.findings.filter((f) => f.engine === "aria-tree");
    assert.ok(aria.some((f) => f.ruleId === "aria-page-title" && f.outcome === "fail"));
    assert.ok(aria.every((f) => f.profiles.length === 1 && f.profiles[0] === "desktop"));
    assert.ok(r.findings.some((f) => f.engine === "axe"), "axe results still reported separately");
    assert.ok(r.profiles[0]!.engines["aria-tree"]);
    assert.equal(r.profiles[1]!.engines["aria-tree"], undefined);
  });

  test("without desktop, runs on the first requested profile", async () => {
    const r = await scan({ url: `${base}/good`, level: "2.2-AA", spec: getLevel("2.2-AA")!, engines: ["axe"], profiles: ["mobile-320"], authorization: auth });
    const aria = r.findings.filter((f) => f.engine === "aria-tree");
    assert.ok(aria.length > 0 && aria.every((f) => f.outcome === "pass" && f.profiles[0] === "mobile-320"));
  });
});
