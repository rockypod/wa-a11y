/*
 * wa-a11y
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * This file is part of wa-a11y.
 * Copyright (C) 2026 Kevin Miller (rockypod)
 * Modifications must retain this wa-a11y notice and document all changes
 * pursuant to AGPLv3 Section 5 and Section 7.
 */

import { EVIDENCE_LIMITS, type FindingEngine, type Outcome, type RawFinding } from "./types.js";
import { isWcag22, levelOf, type WcagLevel } from "./wcag.js";

export const clip = (s: unknown, n: number): string => String(s ?? "").replace(/\s+/g, " ").trim().slice(0, n);

export function mapSc(sc: readonly string[]): { sc: string[]; wcagLevel: WcagLevel | null } {
  const mapped = [...new Set(sc.filter(isWcag22))].sort();
  return { sc: mapped, wcagLevel: levelOf(mapped) };
}

export interface AutomatedInput {
  engine: FindingEngine;
  outcome: Outcome;
  ruleId: unknown;
  sc: readonly string[];
  selector: unknown;
  html: unknown;
  message: unknown;
  impact: string | null;
  helpUrl: unknown;
}

export function automatedFinding(i: AutomatedInput): RawFinding {
  return {
    source: "automated",
    engine: i.engine,
    outcome: i.outcome,
    ruleId: clip(i.ruleId, EVIDENCE_LIMITS.ruleId),
    ...mapSc(i.sc),
    selector: clip(i.selector, EVIDENCE_LIMITS.selector),
    html: clip(i.html, EVIDENCE_LIMITS.html),
    message: clip(i.message, EVIDENCE_LIMITS.message),
    impact: i.impact,
    helpUrl: clip(i.helpUrl, EVIDENCE_LIMITS.helpUrl),
  };
}
