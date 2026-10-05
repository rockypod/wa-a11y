/*
 * wa-a11y
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * This file is part of wa-a11y.
 * Copyright (C) 2026 Kevin Miller (rockypod)
 * Modifications must retain this wa-a11y notice and document all changes
 * pursuant to AGPLv3 Section 5 and Section 7.
 */

import type { WcagLevel } from "./wcag.js";

export type EngineName = "axe" | "alfa" | "accessibility-insights-fastpass";
export type FindingEngine = EngineName | "aria-tree";

type Source = "automated" | "guided" | "manual";

export type Outcome = "fail" | "cantTell" | "pass" | "notApplicable";

// Evidence caps: never full DOMs or page text.
export const EVIDENCE_LIMITS = { selector: 500, html: 2000, message: 2000, ruleId: 200, helpUrl: 500 } as const;

export interface RawFinding {
  source: Extract<Source, "automated">;
  engine: FindingEngine;
  outcome: Outcome;
  ruleId: string;
  sc: string[];
  wcagLevel: WcagLevel | null;
  selector: string;
  html: string; // untrusted page content: consumers must escape it
  message: string;
  impact: string | null;
  helpUrl: string;
}

export interface Finding extends RawFinding {
  profiles: string[];
}

export interface EngineRun {
  findings: RawFinding[];
  passes: number;
  error?: string;
}
