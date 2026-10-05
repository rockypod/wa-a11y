/*
 * wa-a11y
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * This file is part of wa-a11y.
 * Copyright (C) 2026 Kevin Miller (rockypod)
 * Modifications must retain this wa-a11y notice and document all changes
 * pursuant to AGPLv3 Section 5 and Section 7.
 */

import { readFileSync, writeFileSync } from "node:fs";
import { transform } from "lightningcss";
import { PurgeCSS } from "purgecss";

const dist = (f) => new URL(`../dist/${f}`, import.meta.url);

// Alfa ignores linked stylesheets, so the purged CSS is inlined into every page.
const [purged] = await new PurgeCSS().purge({
  content: [{ raw: "", extension: "html" }, "../web/app/**/*.py"],
  extractors: [
    {
      extensions: ["py"],
      extractor: (content) => {
        const words = content.match(/[A-Za-z0-9_:-]+/g) ?? [];
        return [...words, ...words.map((w) => w.toLowerCase())];
      },
    },
  ],
  css: [{ raw: readFileSync(dist("wa-a11y.full.css"), "utf8") }],
  safelist: {
    standard: ["html", "body", ":root", "skip-link", /^data-/],
    greedy: [/data-theme/, /data-spacing/, /data-font/, /focus-visible/],
  },
  variables: false,
  keyframes: true,
  fontFace: false,
});

const { code } = transform({
  filename: "wa-a11y.css",
  code: Buffer.from(purged.css),
  minify: true,
});
writeFileSync(dist("wa-a11y.css"), code);
const kb = (n) => `${(n / 1024).toFixed(1)} KiB`;
console.log(`purged ${kb(readFileSync(dist("wa-a11y.full.css")).length)} → ${kb(code.length)} (dist/wa-a11y.css)`);
