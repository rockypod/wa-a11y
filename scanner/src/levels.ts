/*
 * wa-a11y
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * This file is part of wa-a11y.
 * Copyright (C) 2026 Kevin Miller (rockypod)
 * Modifications must retain this wa-a11y notice and document all changes
 * pursuant to AGPLv3 Section 5 and Section 7.
 */

import { readFileSync } from "node:fs";
import type { WcagLevel } from "./wcag.js";

export interface LevelSpec {
  axeTags: string[];
  alfa: "aa" | "all-wcag";
  maxLevel: WcagLevel;
}

const raw = JSON.parse(readFileSync(new URL("../levels.json", import.meta.url), "utf8")) as Record<string, unknown>;

export const LEVELS: Readonly<Record<string, LevelSpec>> = Object.fromEntries(
  Object.entries(raw).filter(([k]) => !k.startsWith("$")),
) as Record<string, LevelSpec>;

export function getLevel(name: string): LevelSpec | undefined {
  return Object.hasOwn(LEVELS, name) ? LEVELS[name] : undefined;
}
