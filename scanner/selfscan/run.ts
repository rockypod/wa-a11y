/*
 * wa-a11y
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * This file is part of wa-a11y.
 * Copyright (C) 2026 Kevin Miller (rockypod)
 * Modifications must retain this wa-a11y notice and document all changes
 * pursuant to AGPLv3 Section 5 and Section 7.
 */

import { chromium, type Page } from "playwright";
import { runAlfa } from "../src/engines/alfa.js";
import { runAxe } from "../src/engines/axe.js";
import { runFastpass } from "../src/engines/fastpass.js";
import { getLevel } from "../src/levels.js";
import { BASE, PAGES, PUBLIC, load, signIn } from "./shared.js";
import type { EngineRun } from "../src/types.js";

const spec = getLevel("2.2-AAA")!;
// Local iteration only: never set SELFSCAN_PAGES in scripts/check.
const ONLY = process.env.SELFSCAN_PAGES?.split(",").filter(Boolean);
const FONTS = ["atkinson", "lexend", "opendyslexic", "browser"];
const FAMILY: Record<string, string> = { atkinson: "Atkinson Hyperlegible Next", lexend: "Lexend", opendyslexic: "OpenDyslexic" };
const WIDTHS = [1280, 320];
const SPACINGS = ["standard", "wide"];
const COMBOS = [
  ...FONTS.map((font) => ({ font, theme: "light" })),
  { font: "atkinson", theme: "dark" },
  { font: "atkinson", theme: "contrast" },
];

// WCAG 2.2 SC 1.4.12: text spacing override values.
const TEXT_SPACING = `*{line-height:1.5!important;letter-spacing:.12em!important;word-spacing:.16em!important}p{margin-bottom:2em!important}`;

interface Problem { where: string; what: string }
const problems: Problem[] = [];
const review = new Map<string, number>();

function report(r: EngineRun, where: string, path: string): void {
  if (r.error) problems.push({ where, what: `engine error: ${r.error}` });
  for (const f of r.findings) {
    const key = `${f.engine}:${f.ruleId} (${f.sc.join(",")}) ${path} ${f.selector.slice(0, 60)}`;
    if (f.outcome === "fail") problems.push({ where, what: key });
    else review.set(key, (review.get(key) ?? 0) + 1);
  }
}

async function applyDisplay(p: Page, font: string, theme: string, spacing: string, open: boolean): Promise<void> {
  await p.evaluate(([f, t, s, o]) => {
    const el = document.documentElement;
    if (f !== "atkinson") el.dataset.font = f!;
    el.dataset.theme = t!;
    if (s !== "standard") el.dataset.spacing = s!;
    document.querySelectorAll("details").forEach((d) => (d.open = o === "open"));
  }, [font, theme, spacing, open ? "open" : "closed"]);
  await p.evaluate(() => document.fonts.ready);
}

// WCAG 2.2 SC 2.4.7/2.4.13: every Tab stop has an outline ≥ 2px and is on screen.
async function focusWalk(p: Page): Promise<string[]> {
  const bad: string[] = [];
  for (let i = 0; i < 60; i++) {
    await p.keyboard.press("Tab");
    const info = await p.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return null;
      const cs = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      return {
        id: el.id || el.tagName.toLowerCase() + (el.textContent ? `“${el.textContent.trim().slice(0, 30)}”` : ""),
        outline: cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) >= 2,
        onScreen: r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth,
      };
    });
    if (!info) break;
    if (!info.outline) bad.push(`no visible focus outline on ${info.id}`);
    if (!info.onScreen) bad.push(`focused element off-screen: ${info.id}`);
  }
  return [...new Set(bad)];
}

// WCAG 2.2 SC 1.4.10/1.4.12: no horizontal scroll and no clipped text.
async function layoutChecks(p: Page, width: number): Promise<string[]> {
  return p.evaluate((w) => {
    const out: string[] = [];
    if (document.documentElement.scrollWidth > w + 1) {
      const wide = [...document.querySelectorAll<HTMLElement>("body *")].filter((el) => el.getBoundingClientRect().right > w + 1);
      const leaf = wide.find((el) => !wide.some((o) => o !== el && el.contains(o)));
      const what = leaf ? ` at <${leaf.tagName.toLowerCase()} class="${leaf.className}"> "${(leaf.textContent ?? "").trim().slice(0, 40)}"` : "";
      out.push(`horizontal scroll (${document.documentElement.scrollWidth}px > ${w}px)${what}`);
    }
    for (const el of document.querySelectorAll<HTMLElement>("body *")) {
      const cs = getComputedStyle(el);
      if (/(hidden|clip)/.test(cs.overflow + cs.overflowY) && el.scrollHeight > el.clientHeight + 1 && el.clientHeight > 0)
        out.push(`clipped text in <${el.tagName.toLowerCase()} class="${el.className}"> (scroll ${el.scrollWidth}×${el.scrollHeight} > box ${el.clientWidth}×${el.clientHeight})`);
    }
    return out;
  }, width);
}

const browser = await chromium.launch();
let runs = 0;
for (const { font, theme } of COMBOS)
  for (const spacing of SPACINGS)
    for (const width of WIDTHS)
      for (const path of PAGES) {
        if (ONLY && !ONLY.includes(path)) continue;
        const ctx = await browser.newContext({ viewport: { width, height: 900 } });
        const p = await ctx.newPage();
        if (!PUBLIC.has(path)) await signIn(p);
        const where = `${path} [${font}/${theme}/${spacing}/${width}px]`;
        p.on("console", (m) => {
          if (/Content Security Policy/i.test(m.text())) problems.push({ where, what: `CSP violation: ${m.text().slice(0, 160)}` });
        });
        try {
          await load(p, path);
          // No-JS policy: the server must never ship scripts or inline handlers.
          const html = await p.content();
          if (/<script\b/i.test(html)) problems.push({ where, what: "no-JS: page contains <script>" });
          if (/\son[a-z]+\s*=/i.test(html.replace(/<pre[\s\S]*?<\/pre>/gi, "")))
            problems.push({ where, what: "no-JS: inline on*= event handler" });
          await applyDisplay(p, font, theme, spacing, !path.startsWith("CLOSED:"));
          const family = FAMILY[font];
          if (family && !(await p.evaluate((f) => document.fonts.check(`16px "${f}"`) && [...document.fonts].some((ff) => ff.family.replace(/"/g, "") === f && ff.status === "loaded"), family)))
            problems.push({ where, what: `font did not load: ${family} (results would test a fallback font)` });
          for (const r of [await runAxe(p, spec), await runAlfa(p, spec)]) report(r, where, path);
          for (const what of await layoutChecks(p, width)) problems.push({ where, what: `reflow: ${what}` });
          if (font === "atkinson" && theme === "light") {
            for (const what of await focusWalk(p)) problems.push({ where, what: `focus: ${what}` });
            report(await runFastpass(p, spec), where, path); // after focusWalk, which must start at the top
          }
          // CSP blocks <style> (hash-based style-src), so use adoptedStyleSheets.
          await p.evaluate((css) => {
            const sheet = new CSSStyleSheet();
            sheet.replaceSync(css);
            document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
          }, TEXT_SPACING);
          for (const what of await layoutChecks(p, width)) problems.push({ where, what: `text spacing 1.4.12: ${what}` });
        } catch (err) {
          problems.push({ where, what: `could not check: ${(err as Error).message.slice(0, 200)}` });
        } finally {
          await ctx.close();
        }
        runs++;
      }
// The provenance banner must stay visible when results are printed.
// Printing shows every problem's details, even those closed on screen.
{
  const ctx = await browser.newContext();
  const p = await ctx.newPage();
  await signIn(p);
  for (const path of ["/scans/2", "/scans/5", "/scans/6", "/scans/7"]) {
    if (ONLY && !ONLY.includes(path) && !ONLY.includes(`CLOSED:${path}`)) continue;
    await p.goto(BASE + path);
    await p.evaluate(() => document.querySelectorAll("details").forEach((d) => (d.open = false)));
    await p.emulateMedia({ media: "print" });
    const hiddenDetails = await p.evaluate(() =>
      [...document.querySelectorAll<HTMLElement>(".wa-finding > :not(summary)")].filter(
        (el) => !el.checkVisibility() || el.getBoundingClientRect().height === 0,
      ).length,
    );
    if (hiddenDetails) problems.push({ where: `${path} [print]`, what: `${hiddenDetails} problem detail block(s) hidden in print` });
    const shown = await p.evaluate(() => {
      const el = document.getElementById("provenance");
      if (!el) return false;
      const cs = getComputedStyle(el);
      return cs.display !== "none" && cs.visibility !== "hidden" && el.getBoundingClientRect().height > 0;
    });
    if (!shown) problems.push({ where: `${path} [print]`, what: "provenance banner hidden in print" });
    await p.emulateMedia({ media: "screen" });
    runs++;
  }
  await ctx.close();
}
await browser.close();

const grouped = new Map<string, string[]>();
for (const { where, what } of problems) grouped.set(what, [...(grouped.get(what) ?? []), where]);
for (const [what, wheres] of grouped) console.log(`FAIL ×${wheres.length}  ${what}\n        e.g. ${wheres[0]}`);
for (const [what, n] of review) console.log(`REVIEW ×${n}  ${what}`);
console.log(`selfscan: ${runs} page checks, ${problems.length} failures, ${review.size} items for human review`);
process.exit(problems.length ? 1 : 0);
