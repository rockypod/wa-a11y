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
import { describe, test } from "node:test";
import { automatedFinding, mapSc } from "../src/finding.js";
import { EVIDENCE_LIMITS, type RawFinding } from "../src/types.js";

const base = {
  engine: "axe" as const,
  outcome: "fail" as const,
  ruleId: "image-alt",
  sc: ["1.1.1"],
  selector: "img",
  html: "<img src=x>",
  message: "Fix: add alt",
  impact: "critical",
  helpUrl: "https://dequeuniversity.com/rules/axe/4.13/image-alt",
};

describe("finding contract", () => {
  test("automated findings carry source and engine provenance", () => {
    const f = automatedFinding(base);
    assert.equal(f.source, "automated");
    assert.equal(f.engine, "axe");
    assert.deepEqual(f.sc, ["1.1.1"]);
    assert.equal(f.wcagLevel, "A");
  });

  test("serialises to exactly the contract's keys", () => {
    const keys: (keyof RawFinding)[] = ["source", "engine", "outcome", "ruleId", "sc", "wcagLevel",
      "selector", "html", "message", "impact", "helpUrl"];
    const round = JSON.parse(JSON.stringify(automatedFinding(base)));
    assert.deepEqual(Object.keys(round).sort(), [...keys].sort());
  });

  test("sc keeps only WCAG 2.2 criteria; the level is the lowest of them", () => {
    assert.deepEqual(mapSc(["4.1.2", "1.4.6", "4.1.2", "1.4.3"]), { sc: ["1.4.3", "1.4.6", "4.1.2"], wcagLevel: "A" });
    // 4.1.1 Parsing is obsolete in WCAG 2.2; 9.9.9 does not exist
    assert.deepEqual(mapSc(["4.1.1", "9.9.9"]), { sc: [], wcagLevel: null });
  });

  test("unmapped checks are advisory (wcagLevel null), never a WCAG level", () => {
    const f = automatedFinding({ ...base, sc: [] });
    assert.equal(f.wcagLevel, null);
    assert.deepEqual(f.sc, []);
  });

  test("evidence is bounded and whitespace-collapsed", () => {
    const f = automatedFinding({
      ...base,
      ruleId: "r".repeat(1000),
      selector: "s".repeat(10_000),
      html: `<p>\n\n${"x".repeat(50_000)}</p>`,
      message: "m".repeat(10_000),
      helpUrl: `https://example.org/${"h".repeat(5000)}`,
    });
    assert.equal(f.ruleId.length, EVIDENCE_LIMITS.ruleId);
    assert.equal(f.selector.length, EVIDENCE_LIMITS.selector);
    assert.equal(f.html.length, EVIDENCE_LIMITS.html);
    assert.equal(f.message.length, EVIDENCE_LIMITS.message);
    assert.equal(f.helpUrl.length, EVIDENCE_LIMITS.helpUrl);
    assert.ok(f.html.startsWith("<p> x"));
  });

  test("non-string page values are stringified, never passed through", () => {
    const f = automatedFinding({ ...base, html: { toString: () => "<b>" }, selector: null, message: undefined });
    assert.equal(f.html, "<b>");
    assert.equal(f.selector, "");
    assert.equal(f.message, "");
  });
});
