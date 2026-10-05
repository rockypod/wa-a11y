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

const { themes } = JSON.parse(readFileSync(new URL("../tokens.json", import.meta.url), "utf8"));
const block = (name) =>
  Object.entries(themes[name]).map(([k, v]) => `  --${k}: ${v};`).join("\n");

const scss = `// GENERATED from tokens.json by scripts/tokens.mjs — do not edit.
// Light is the default; dark follows the device unless the user chose a theme; the user's
// explicit choice (data-theme on <html>) always wins. Extra contrast also follows prefers-contrast.
$wa-light: (${Object.entries(themes.light).map(([k, v]) => `"${k}": ${v}`).join(", ")});

:root, :root[data-theme="light"] {
${block("light")}
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme]) {
${block("dark").replace(/^/gm, "  ")}
    color-scheme: dark;
  }
}
:root[data-theme="dark"] {
${block("dark")}
  color-scheme: dark;
}
@media (prefers-contrast: more) {
  :root:not([data-theme]) {
${block("contrast").replace(/^/gm, "  ")}
    color-scheme: light;
  }
}
:root[data-theme="contrast"] {
${block("contrast")}
  color-scheme: light;
}
`;
writeFileSync(new URL("../scss/_tokens.generated.scss", import.meta.url), scss);
console.log("wrote scss/_tokens.generated.scss");
