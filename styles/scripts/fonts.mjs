/*
 * wa-a11y
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * This file is part of wa-a11y.
 * Copyright (C) 2026 Kevin Miller (rockypod)
 * Modifications must retain this wa-a11y notice and document all changes
 * pursuant to AGPLv3 Section 5 and Section 7.
 */

// OFL-1.1: each font ships with its licence
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";

const FONTS = [
  ["@fontsource-variable/atkinson-hyperlegible-next", "Atkinson Hyperlegible Next", ["wght.css", "wght-italic.css"]],
  ["@fontsource-variable/lexend", "Lexend", ["wght.css"]],
  ["@fontsource/opendyslexic", "OpenDyslexic", ["400.css", "700.css", "400-italic.css", "700-italic.css"]],
];
const SUBSETS = /-latin-(ext-)?(wght|\d{3})-/;

const out = new URL("../dist/fonts/", import.meta.url);
mkdirSync(out, { recursive: true });
const manifest = [];

for (const [pkg, family, cssFiles] of FONTS) {
  const dir = new URL(`../node_modules/${pkg}/`, import.meta.url);
  const short = pkg.split("/").pop();
  copyFileSync(new URL("LICENSE", dir), new URL(`${short}-LICENSE.txt`, out));
  for (const css of cssFiles) {
    const text = readFileSync(new URL(css, dir), "utf8");
    for (const block of text.match(/@font-face\s*{[^}]*}/g) ?? []) {
      const file = /url\(\.\/files\/([^)]+\.woff2)\)/.exec(block)?.[1];
      if (!file || !SUBSETS.test(file)) continue;
      copyFileSync(new URL(`files/${file}`, dir), new URL(file, out));
      manifest.push({
        family,
        file,
        style: /font-style:\s*([^;]+);/.exec(block)?.[1]?.trim() ?? "normal",
        weight: /font-weight:\s*([^;]+);/.exec(block)?.[1]?.trim() ?? "400",
        unicodeRange: /unicode-range:\s*([^;]+);/.exec(block)?.[1]?.trim() ?? "",
      });
    }
  }
}
writeFileSync(new URL("fonts.json", out), JSON.stringify(manifest, null, 2));
console.log(`fonts: ${manifest.length} faces, ${new Set(manifest.map((m) => m.family)).size} families → dist/fonts/`);
