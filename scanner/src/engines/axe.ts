/*
 * wa-a11y
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * This file is part of wa-a11y.
 * Copyright (C) 2026 Kevin Miller (rockypod)
 * Modifications must retain this wa-a11y notice and document all changes
 * pursuant to AGPLv3 Section 5 and Section 7.
 */

import { AxeBuilder } from "@axe-core/playwright";
import type { Page } from "playwright";
import type { LevelSpec } from "../levels.js";
import { automatedFinding, clip, mapSc } from "../finding.js";
import type { EngineRun, RawFinding } from "../types.js";
import { withinLevel } from "../wcag.js";

const MAX_NODES_PER_RULE = 50;

function scFromTags(tags: string[]): string[] {
  const out = new Set<string>();
  for (const t of tags) {
    const m = /^wcag(\d)(\d)(\d+)$/.exec(t);
    if (m) out.add(`${m[1]}.${m[2]}.${m[3]}`);
  }
  return [...out].sort();
}

interface AxeResult {
  id: string;
  impact?: string | null;
  help: string;
  helpUrl: string;
  tags: string[];
  nodes: { html: string; target: unknown[]; failureSummary?: string }[];
}

function toFindings(results: AxeResult[], outcome: RawFinding["outcome"], level: LevelSpec): RawFinding[] {
  const out: RawFinding[] = [];
  for (const r of results) {
    const sc = scFromTags(r.tags);
    if (!withinLevel(mapSc(sc).wcagLevel, level.maxLevel)) continue;
    for (const n of r.nodes.slice(0, MAX_NODES_PER_RULE)) {
      out.push(
        automatedFinding({
          engine: "axe",
          outcome,
          ruleId: r.id,
          sc,
          selector: n.target.map(String).join(" "),
          html: n.html,
          message: n.failureSummary || r.help,
          impact: r.impact ?? null,
          helpUrl: r.helpUrl,
        }),
      );
    }
  }
  return out;
}

export async function runAxe(page: Page, level: LevelSpec): Promise<EngineRun> {
  try {
    const res = await new AxeBuilder({ page }).withTags(level.axeTags).analyze();
    return {
      findings: [
        ...toFindings(res.violations as AxeResult[], "fail", level),
        ...toFindings(res.incomplete as AxeResult[], "cantTell", level),
      ],
      passes: res.passes.length,
    };
  } catch (err) {
    return { findings: [], passes: 0, error: clip((err as Error)?.message ?? err, 500) };
  }
}
