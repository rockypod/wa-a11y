/*
 * wa-a11y
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * This file is part of wa-a11y.
 * Copyright (C) 2026 Kevin Miller (rockypod)
 * Modifications must retain this wa-a11y notice and document all changes
 * pursuant to AGPLv3 Section 5 and Section 7.
 */

// WCAG 2.2 SC 1.4.6 / 1.4.11: text pairs ≥ 7:1 and non-text pairs ≥ 3:1 in every theme
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const { themes, pairs } = JSON.parse(readFileSync(new URL("../tokens.json", import.meta.url), "utf8"));

const lin = (c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const lum = (hex) => {
  const [r, g, b] = [1, 3, 5].map((i) => lin(parseInt(hex.slice(i, i + 2), 16) / 255));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
export const ratio = (a, b) => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

test("contrast formula sanity", () => {
  assert.equal(Math.round(ratio("#000000", "#ffffff")), 21);
  assert.ok(Math.abs(ratio("#767676", "#ffffff") - 4.54) < 0.01);
});

for (const [name, t] of Object.entries(themes)) {
  for (const [kind, min] of [["text", 7], ["nonText", 3]]) {
    for (const [fg, bg] of pairs[kind]) {
      test(`${name}: ${fg} on ${bg} ≥ ${min}:1`, () => {
        assert.ok(t[fg] && t[bg], `missing token ${fg} or ${bg} in ${name}`);
        const r = ratio(t[fg], t[bg]);
        assert.ok(r >= min, `${name}: ${fg} ${t[fg]} on ${bg} ${t[bg]} = ${r.toFixed(2)}:1 < ${min}:1`);
      });
    }
  }
}
