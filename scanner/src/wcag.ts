/*
 * wa-a11y
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * This file is part of wa-a11y.
 * Copyright (C) 2026 Kevin Miller (rockypod)
 * Modifications must retain this wa-a11y notice and document all changes
 * pursuant to AGPLv3 Section 5 and Section 7.
 */

// WCAG 2.2 removed SC 4.1.1 Parsing.
export type WcagLevel = "A" | "AA" | "AAA";

const A = "A", AA = "AA", AAA = "AAA";
const WCAG22: Readonly<Record<string, WcagLevel>> = {
  "1.1.1": A,
  "1.2.1": A, "1.2.2": A, "1.2.3": A, "1.2.4": AA, "1.2.5": AA, "1.2.6": AAA, "1.2.7": AAA, "1.2.8": AAA, "1.2.9": AAA,
  "1.3.1": A, "1.3.2": A, "1.3.3": A, "1.3.4": AA, "1.3.5": AA, "1.3.6": AAA,
  "1.4.1": A, "1.4.2": A, "1.4.3": AA, "1.4.4": AA, "1.4.5": AA, "1.4.6": AAA, "1.4.7": AAA, "1.4.8": AAA,
  "1.4.9": AAA, "1.4.10": AA, "1.4.11": AA, "1.4.12": AA, "1.4.13": AA,
  "2.1.1": A, "2.1.2": A, "2.1.3": AAA, "2.1.4": A,
  "2.2.1": A, "2.2.2": A, "2.2.3": AAA, "2.2.4": AAA, "2.2.5": AAA, "2.2.6": AAA,
  "2.3.1": A, "2.3.2": AAA, "2.3.3": AAA,
  "2.4.1": A, "2.4.2": A, "2.4.3": A, "2.4.4": A, "2.4.5": AA, "2.4.6": AA, "2.4.7": AA, "2.4.8": AAA,
  "2.4.9": AAA, "2.4.10": AAA, "2.4.11": AA, "2.4.12": AAA, "2.4.13": AAA,
  "2.5.1": A, "2.5.2": A, "2.5.3": A, "2.5.4": A, "2.5.5": AAA, "2.5.6": AAA, "2.5.7": AA, "2.5.8": AA,
  "3.1.1": A, "3.1.2": AA, "3.1.3": AAA, "3.1.4": AAA, "3.1.5": AAA, "3.1.6": AAA,
  "3.2.1": A, "3.2.2": A, "3.2.3": AA, "3.2.4": AA, "3.2.5": AAA, "3.2.6": A,
  "3.3.1": A, "3.3.2": A, "3.3.3": AA, "3.3.4": AA, "3.3.5": AAA, "3.3.6": AAA, "3.3.7": A, "3.3.8": AA, "3.3.9": AAA,
  "4.1.2": A, "4.1.3": AA,
};

const RANK: Record<WcagLevel, number> = { A: 1, AA: 2, AAA: 3 };

export function isWcag22(sc: string): boolean {
  return Object.hasOwn(WCAG22, sc);
}

export function levelOf(scs: string[]): WcagLevel | null {
  let best: WcagLevel | null = null;
  for (const sc of scs) {
    const l = WCAG22[sc];
    if (l && (!best || RANK[l] < RANK[best])) best = l;
  }
  return best;
}

export function withinLevel(level: WcagLevel | null, max: WcagLevel): boolean {
  return level !== null && RANK[level] <= RANK[max];
}
