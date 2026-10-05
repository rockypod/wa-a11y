/*
 * wa-a11y
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * This file is part of wa-a11y.
 * Copyright (C) 2026 Kevin Miller (rockypod)
 * Modifications must retain this wa-a11y notice and document all changes
 * pursuant to AGPLv3 Section 5 and Section 7.
 */

import { Playwright } from "@siteimprove/alfa-playwright";
import { Audit, Rules } from "@siteimprove/alfa-test-utils";
import type { Page } from "playwright";
import type { LevelSpec } from "../levels.js";
import { automatedFinding, clip, mapSc } from "../finding.js";
import type { EngineRun, RawFinding } from "../types.js";
import { withinLevel } from "../wcag.js";

type AnyOutcome = { toJSON?: () => any; _target?: any; target?: any };

function firstMessage(j: any): string {
  const expectations: unknown[] = j?.expectations ?? [];
  for (const e of expectations) {
    const v: any = Array.isArray(e) ? e[1] : e;
    const msg = v?.error?.message ?? v?.value?.message;
    if (msg) return String(msg);
  }
  return "";
}

function requirementsOf(j: any): string[] {
  const reqs: any[] = j?.rule?.requirements ?? [];
  return [...new Set(reqs.map((r) => r?.chapter).filter(Boolean) as string[])].sort();
}

function toFinding(ruleUri: string, o: AnyOutcome, level: LevelSpec): RawFinding | null {
  const j = typeof o?.toJSON === "function" ? o.toJSON() : o;
  if (j?.outcome !== "failed" && j?.outcome !== "cantTell") return null;
  const sc = requirementsOf(j);
  if (!withinLevel(mapSc(sc).wcagLevel, level.maxLevel)) return null;
  const target = o._target ?? o.target;
  return automatedFinding({
    engine: "alfa",
    outcome: j.outcome === "failed" ? "fail" : "cantTell",
    ruleId: ruleUri.split("/").pop() ?? ruleUri,
    sc,
    selector: typeof target?.path === "function" ? target.path() : "",
    html: target,
    message: firstMessage(j),
    impact: null,
    helpUrl: ruleUri,
  });
}

const isPassed = (o: AnyOutcome) => (typeof o?.toJSON === "function" ? o.toJSON() : o)?.outcome === "passed";

export async function runAlfa(page: Page, level: LevelSpec): Promise<EngineRun> {
  try {
    const handle = await page.evaluateHandle(() => window.document);
    const alfaPage = await Playwright.toPage(handle);
    // Alfa has no AAA filter: AAA runs every rule and keeps only WCAG-mapped findings.
    const include = level.alfa === "aa" ? Rules.aaFilter : () => true;
    const result = await Audit.run(alfaPage, { rules: { include } });

    const findings: RawFinding[] = [];
    let passes = 0;
    // outcomes iterate as [ruleUri, Sequence<Outcome>] pairs; a flat filter matches nothing.
    for (const [ruleUri, outcomes] of result.outcomes as Iterable<[string, Iterable<AnyOutcome>]>) {
      for (const o of outcomes) {
        if (isPassed(o)) passes++;
        const f = toFinding(String(ruleUri), o, level);
        if (f) findings.push(f);
      }
    }
    return { findings, passes };
  } catch (err) {
    return { findings: [], passes: 0, error: clip((err as Error)?.message ?? err, 500) };
  }
}
