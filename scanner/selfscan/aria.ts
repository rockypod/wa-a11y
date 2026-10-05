/*
 * wa-a11y
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * This file is part of wa-a11y.
 * Copyright (C) 2026 Kevin Miller (rockypod)
 * Modifications must retain this wa-a11y notice and document all changes
 * pursuant to AGPLv3 Section 5 and Section 7.
 */

import { chromium, type CDPSession, type Page } from "playwright";
import { BASE, PAGES, PUBLIC, load, signIn } from "./shared.js";

const ROUTES = PAGES.filter((p) => !p.startsWith("CLOSED:"));
const WIDTHS = [1280, 320];
const BROKEN = process.env.ARIA_BROKEN_FIXTURE === "1";
const SKIP_LINK = "Skip to main content";

interface Problem { where: string; what: string }
const problems: Problem[] = [];
let checks = 0;
const bad = (where: string, what: string): void => {
  if (!problems.some((x) => x.where === where && x.what === what)) problems.push({ where, what });
};

const freshUrl = (path: string): string =>
  path === "LOGIN-ERROR" ? "/login"
  : path === "EXPORT-SHOW" || path === "EXPORT-ERROR" ? "/scans/5/export"
  : path === "FORM-ERROR" ? "/"
  : path === "ASSESSMENT-ERROR" ? "/scans/2/assessment"
  : path;

async function axNamedControls(p: Page, cdp: CDPSession): Promise<Map<string, string[]>> {
  const { nodes } = await cdp.send("Accessibility.getFullAXTree");
  const out = new Map<string, string[]>();
  for (const n of nodes) {
    const role = n.role?.value;
    if (!role || n.name?.value === undefined) continue;
    if (!["textbox", "button", "checkbox", "radio", "combobox", "listbox", "switch"].includes(role)) continue;
    const list = out.get(role) ?? [];
    list.push(n.name.value ?? "");
    out.set(role, list);
  }
  return out;
}

async function checkState(p: Page, cdp: CDPSession, where: string): Promise<void> {
  // WCAG 2.2 SC 2.4.2: the title names the page and ends with the site name.
  const title = await p.title();
  checks++;
  if (!title.trim() || !title.endsWith("WA-A11y")) bad(where, `document title "${title}" is empty or does not end with the site name (2.4.2)`);
  else if (title.trim() === "WA-A11y") bad(where, `document title "${title}" has no page-specific part (2.4.2)`);

  // WCAG 2.2 SC 1.3.1/2.4.1. ariaSnapshot indents nested landmarks: match at any indentation.
  const yaml = await p.ariaSnapshot();
  for (const [landmark, label] of [
    ["banner", ""], ["main", ""], ["contentinfo", ""],
    ["navigation", "Main"], ["navigation", "Account"], ["navigation", "Breadcrumb"], ["navigation", "Footer"],
  ] as const) {
    checks++;
    const re = label ? new RegExp(`^\\s*- ${landmark} "${label}":`, "m") : new RegExp(`^\\s*- ${landmark}:`, "m");
    if (!re.test(yaml)) bad(where, `landmark ${landmark}${label ? ` "${label}"` : ""} missing from the accessibility tree (ariaSnapshot)`);
  }
  // WCAG 2.2 SC 1.3.1/2.4.1/4.1.2: no two landmarks share a role and name.
  const seen = new Map<string, number>();
  for (const m of yaml.matchAll(/^\s*- (banner|main|contentinfo|navigation|complementary|region|search|form)(?: "([^"]*)")?:/gm)) {
    const key = m[2] === undefined ? m[1] : `${m[1]} "${m[2]}"`;
    seen.set(key, (seen.get(key) ?? 0) + 1);
  }
  for (const [key, n] of seen) {
    checks++;
    if (n > 1) bad(where, `${n} landmarks share the same role and name: ${key} (landmark names must be unique)`);
  }

  // WCAG 2.2 SC 1.3.1/2.4.6: exactly one level-1 heading.
  const h1s = yaml.match(/heading "[^"]*" \[level=1\]/g) ?? [];
  checks += 2;
  if (h1s.length !== 1) bad(where, `expected exactly 1 level-1 heading, found ${h1s.length}`);

  // WCAG 2.2 SC 4.1.2: every form control has an accessible name.
  for (const [role, names] of await axNamedControls(p, cdp)) {
    for (const name of names) {
      checks++;
      if (!name.trim()) bad(where, `form control with role ${role} has no accessible name (4.1.2, exposed-to-AT via CDP tree)`);
    }
  }

  // WCAG 2.2 SC 1.3.1/4.1.2. p.evaluate still works with page JS disabled (CDP).
  const labelless = await p.evaluate(() => {
    const out: string[] = [];
    for (const el of document.querySelectorAll<HTMLInputElement>("input, textarea, select")) {
      const type = el.getAttribute("type") ?? "text";
      if (["hidden", "submit", "button", "reset"].includes(type)) continue;
      const labelled = document.querySelector(`label[for="${el.id}"]`) ?? el.closest("label");
      const aria = el.getAttribute("aria-label") ?? el.getAttribute("aria-labelledby");
      if (!labelled && !aria) out.push(`#${el.id || el.name || "(no id)"} (${type})`);
    }
    return out;
  });
  checks++;
  if (labelless.length) bad(where, `form fields with no programmatic label: ${labelless.join(", ")} (1.3.1/4.1.2)`);
}

// WCAG 2.2 SC 2.4.1/2.4.3: skip link, then header controls in DOM order, then breadcrumbs.
async function checkFocusOrder(p: Page, path: string, where: string): Promise<void> {
  await p.goto(BASE + freshUrl(path));
  const domNav = await p.evaluate(() =>
    [...document.querySelectorAll<HTMLElement>("header nav a, header nav button")].map((a) => a.textContent?.trim() ?? ""));
  const domCrumbs = await p.evaluate(() =>
    [...document.querySelectorAll<HTMLAnchorElement>('nav[aria-label="Breadcrumb"] a')].map((a) => a.textContent?.trim() ?? ""));
  const stops: { text: string; inNav: boolean }[] = [];
  for (let i = 0; i < 24; i++) {
    await p.keyboard.press("Tab");
    const stop = await p.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return null;
      return { text: el.textContent?.trim() ?? el.id, inNav: !!el.closest("header nav") };
    });
    if (stop === null) break;
    stops.push(stop);
  }
  checks++;
  if (stops[0]?.text !== SKIP_LINK) {
    bad(where, `first Tab stop is "${stops[0]?.text ?? "(none)"}", expected the skip link "${SKIP_LINK}" (2.4.1)`);
  }
  const navStops = stops.filter((s) => s.inNav).map((s) => s.text);
  checks++;
  if (JSON.stringify(navStops) !== JSON.stringify(domNav)) {
    bad(where, `header nav focus order does not match DOM order (2.4.3): focused ${JSON.stringify(navStops)}, DOM ${JSON.stringify(domNav)}`);
  }
  const expected = [SKIP_LINK, ...domNav, ...domCrumbs];
  const actual = stops.slice(0, expected.length).map((s) => s.text);
  checks++;
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    bad(where, `focus order is not skip link → header → breadcrumbs (2.4.3): focused ${JSON.stringify(actual)}, expected ${JSON.stringify(expected)}`);
  }
}

const browser = await chromium.launch();
try {
  for (const width of WIDTHS) {
    const ctx = await browser.newContext({ viewport: { width, height: 900 }, javaScriptEnabled: false });
    const p = await ctx.newPage();
    const cdp = await ctx.newCDPSession(p);
    for (const path of ROUTES) {
      const where = `${path} [no-JS/${width}px]`;
      try {
        if (!PUBLIC.has(path)) await signIn(p);
        await load(p, path);
        await checkState(p, cdp, where);
        await checkFocusOrder(p, path, where);
      } catch (err) {
        bad(where, `could not check: ${(err as Error).message.slice(0, 160)}`);
      }
    }
    await ctx.close();
  }

  if (BROKEN) {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const p = await ctx.newPage();
    const cdp = await ctx.newCDPSession(p);
    await p.goto(BASE + "/login");
    await p.evaluate(() => {
      document.querySelector('label[for="email"]')?.remove();
      document.querySelector('label[for="password"]')?.remove();
    });
    const before = problems.length;
    await checkState(p, cdp, "BROKEN:label-removed [no-JS/1280px]");
    await ctx.close();
    if (problems.length === before) {
      console.error("aria: broken fixture produced NO failures — the suite is not catching missing labels");
      process.exit(1);
    }
    console.log("aria: broken fixture correctly failed:");
    for (const { where, what } of problems.slice(before)) console.log(`  ${where}: ${what}`);
    process.exit(1); // always exit 1: the failure is the proof
  }
} finally {
  await browser.close();
}

const grouped = new Map<string, string[]>();
for (const { where, what } of problems) grouped.set(what, [...(grouped.get(what) ?? []), where]);
for (const [what, wheres] of grouped) console.log(`FAIL ×${wheres.length}  ${what}\n        e.g. ${wheres[0]}`);
console.log(`aria: ${checks} exposure checks across ${ROUTES.length} routes × ${WIDTHS.length} widths, ${problems.length} failures — results are "exposed to assistive technology", not a screen-reader pass`);
process.exit(problems.length ? 1 : 0);