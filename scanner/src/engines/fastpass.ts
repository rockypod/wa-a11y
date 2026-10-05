/*
 * wa-a11y
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * This file is part of wa-a11y.
 * Copyright (C) 2026 Kevin Miller (rockypod)
 * Modifications must retain this wa-a11y notice and document all changes
 * pursuant to AGPLv3 Section 5 and Section 7.
 */

import type { Page } from "playwright";
import { automatedFinding, clip, mapSc } from "../finding.js";
import type { LevelSpec } from "../levels.js";
import type { EngineRun, Outcome, RawFinding } from "../types.js";
import { withinLevel } from "../wcag.js";
import { installFastpassHelpers, type PageStop, type PageTarget, type StepResult } from "./fastpass-page.js";

export const FASTPASS_VERSION = "1";

const KEY = "__waA11yFastpass";
const MAX_PRESSES = 200;
const MAX_FRAME_DWELL = 50;
const BUDGET_MS = 20_000;
const MAX_PIXEL_CONFIRMS = 10;
const MAX_PER_RULE = 50;
const MAX_ORDER = 10;
const SHOT = { animations: "disabled", caret: "hide", scale: "css" } as const;

// Policy: fail only on decisive evidence; anything needing judgement is cantTell.
const U = "https://www.w3.org/WAI/WCAG22/Understanding/";
const RULES = {
  reach: { id: "fastpass-keyboard-reachable", sc: ["2.1.1"], impact: "serious", help: `${U}keyboard.html` },
  coverage: { id: "fastpass-tab-coverage", sc: ["2.1.1"], impact: null, help: `${U}keyboard.html` },
  trap: { id: "fastpass-keyboard-trap", sc: ["2.1.2"], impact: "critical", help: `${U}no-keyboard-trap.html` },
  order: { id: "fastpass-focus-order", sc: ["2.4.3"], impact: "moderate", help: `${U}focus-order.html` },
  visible: { id: "fastpass-focus-visible", sc: ["2.4.7"], impact: "serious", help: `${U}focus-visible.html` },
  appearance: { id: "fastpass-focus-appearance", sc: ["2.4.13"], impact: "minor", help: `${U}focus-appearance.html` },
} as const;
type Rule = keyof typeof RULES;

interface Hit {
  rule: Rule;
  outcome: Extract<Outcome, "fail" | "cantTell">;
  at: { selector: string; html: string };
  message: string;
}

interface Walk {
  seq: number[];
  stops: Map<number, PageStop>;
  changed: Map<number, boolean>;
  pairs: [PageStop, PageStop][];
  end: "complete" | "limit" | "trap";
  hits: Hit[];
}

const DOCUMENT = { selector: "html", html: "" };

function call<T>(page: Page, method: string, ...args: unknown[]): Promise<T> {
  return page.evaluate(
    ({ k, m, a }) => (window as unknown as Record<string, Record<string, (...x: unknown[]) => unknown>>)[k]![m]!(...a),
    { k: KEY, m: method, a: args },
  ) as Promise<T>;
}

async function press(page: Page, key: string): Promise<StepResult> {
  await page.keyboard.press(key);
  return call<StepResult>(page, "step", -1);
}

async function leaves(page: Page, loop: Set<number>, key: string, first?: string): Promise<boolean> {
  if (first) await page.keyboard.press(first);
  for (let i = 0; i < loop.size + 2; i++) {
    const { stop } = await press(page, key);
    if (!stop || !loop.has(stop.id)) return true;
  }
  return false;
}

async function trapHit(page: Page, w: Walk, loop: number[]): Promise<Hit> {
  const set = new Set(loop);
  const first = w.stops.get(loop[0]!)!;
  const n = `${loop.length} element${loop.length === 1 ? "" : "s"}`;
  const hit = (outcome: Hit["outcome"], message: string): Hit => ({ rule: "trap", outcome, at: first, message });
  if (await leaves(page, set, "Shift+Tab"))
    return hit("cantTell", `Tab keeps focus cycling through ${n}; Shift+Tab leaves. Check people can move past them.`);
  if (await leaves(page, set, "Tab", "Escape"))
    return hit("cantTell", `Tab keeps focus inside ${n} until Escape is pressed. Check the page tells people how to leave.`);
  if (loop.some((id) => w.stops.get(id)?.inModal))
    return hit("cantTell", `A dialog keeps focus inside ${n}. Check it can be closed from the keyboard.`);
  return hit("fail", `Keyboard trap: Tab, Shift+Tab and Escape cannot move focus away from these ${n}.`);
}

function record(w: Walk, stop: PageStop, prevId: number): void {
  const prev = w.stops.get(prevId);
  if (prev) w.pairs.push([prev, stop]);
  w.seq.push(stop.id);
  w.stops.set(stop.id, stop);
}

type Next = { done: false; prevId: number; sawBody: boolean } | { done: true; loop?: number[] };

function advance(w: Walk, r: StepResult, prevId: number, sawBody: boolean, fromDocStart: boolean): Next {
  if (!r.stop) {
    if (fromDocStart || sawBody || w.seq.length === 0) return { done: true };
    return { done: false, prevId: -1, sawBody: true };
  }
  const at = w.seq.indexOf(r.stop.id);
  if (at === 0 && sawBody) return { done: true };
  if (at >= 0) return { done: true, loop: w.seq.slice(at) };
  record(w, r.stop, prevId);
  return { done: false, prevId: r.stop.id, sawBody };
}

async function tab(page: Page, w: Walk, state: Extract<Next, { done: false }>, fromDocStart: boolean, dwell: number): Promise<[Next, number]> {
  await page.keyboard.press("Tab");
  const r = await call<StepResult>(page, "step", state.prevId);
  if (r.prevChanged !== null) w.changed.set(state.prevId, r.prevChanged);
  if (r.stop?.id !== state.prevId) return [advance(w, r, state.prevId, state.sawBody, fromDocStart), 0];
  // Focus staying on an iframe/custom element is moving inside it, not stuck.
  if (r.stop.frameLike && dwell + 1 < MAX_FRAME_DWELL) return [state, dwell + 1];
  return [{ done: true, loop: [state.prevId] }, 0];
}

async function walk(page: Page, deadline: number): Promise<Walk> {
  const w: Walk = { seq: [], stops: new Map(), changed: new Map(), pairs: [], end: "limit", hits: [] };
  const start = await call<StepResult>(page, "step", -1);
  if (start.stop) record(w, start.stop, -1);
  let state: Next = { done: false, prevId: start.stop?.id ?? -1, sawBody: false };
  let dwell = 0;
  for (let i = 0; i < MAX_PRESSES && Date.now() < deadline && !state.done; i++)
    [state, dwell] = await tab(page, w, state, !start.stop, dwell);
  if (state.done) w.end = state.loop ? "trap" : "complete";
  if (state.done && state.loop) w.hits.push(await trapHit(page, w, state.loop));
  return w;
}

function orderHits(w: Walk): Hit[] {
  const hits: Hit[] = [];
  for (const [prev, next] of w.pairs)
    if (!prev.pinned && !next.pinned && next.bottom < prev.top - 1)
      hits.push({ rule: "order", outcome: "cantTell", at: next,
        message: `Tab moved focus back up the page from ${prev.selector}. Check the focus order follows the reading order.` });
  for (const s of w.stops.values())
    if (s.positiveTabindex)
      hits.push({ rule: "order", outcome: "cantTell", at: s,
        message: "A positive tabindex changes the Tab order. Check the order still makes sense." });
  return hits.slice(0, MAX_ORDER);
}

// Screenshots are compared in memory and never kept.
async function pixelsSame(page: Page, w: Walk, id: number): Promise<boolean | null> {
  const k = w.seq.indexOf(id);
  const [neighbour, key] = k + 1 < w.seq.length ? [w.seq[k + 1], "Shift+Tab"] : [w.seq[k - 1], "Tab"];
  if (neighbour === undefined || !(await call<boolean>(page, "focusNeighbour", neighbour))) return null;
  if ((await press(page, key)).stop?.id !== id) return null;
  const focused = await page.screenshot(SHOT);
  if (!(await call<boolean>(page, "blur"))) return null;
  return focused.equals(await page.screenshot(SHOT));
}

async function visibleHit(page: Page, w: Walk, s: PageStop, confirm: boolean): Promise<Hit> {
  const hit = (outcome: Hit["outcome"], message: string): Hit => ({ rule: "visible", outcome, at: s, message });
  const same = confirm ? await pixelsSame(page, w, s.id) : null;
  if (same === true) return hit("fail", "No visible focus indicator: nothing on the page changes when this element has keyboard focus.");
  if (same === false)
    return hit("cantTell", "The element's own styles do not change with focus, but something on the page does. Check a focus indicator is visible.");
  return hit("cantTell", "The element's styles do not change with focus. Check a focus indicator is visible.");
}

async function focusHits(page: Page, w: Walk): Promise<Hit[]> {
  const hits: Hit[] = [];
  let confirms = 0;
  for (const s of w.stops.values()) {
    if (s.frameLike) continue;
    if (!s.visible)
      hits.push({ rule: "visible", outcome: "cantTell", at: s, message: "The focused element is not visible on screen. Check where focus is shown." });
    else if (w.changed.get(s.id) === false) hits.push(await visibleHit(page, w, s, confirms++ < MAX_PIXEL_CONFIRMS));
    else if (w.changed.get(s.id) && s.outline === "other")
      hits.push({ rule: "appearance", outcome: "cantTell", at: s,
        message: "Check the focus indicator is at least as large as a 2 CSS px outline around the element and has 3:1 contrast with the unfocused state." });
  }
  return hits;
}

function reachHits(targets: PageTarget[], unreached: PageTarget[]): Hit[] {
  const hits: Hit[] = targets.map((t) =>
    t.roleWidget && !t.hasTabindex
      ? { rule: "reach", outcome: "fail", at: t, message: "This element has an interactive role but cannot receive keyboard focus (no tabindex)." }
      : { rule: "reach", outcome: "cantTell", at: t,
          message: t.roleWidget
            ? "This interactive element is taken out of the Tab order (tabindex=\"-1\"). Check it can still be reached and used with the keyboard."
            : "This element reacts to clicks but cannot receive keyboard focus. Check the same action is available from the keyboard." },
  );
  for (const t of unreached)
    hits.push({ rule: "reach", outcome: "cantTell", at: t, message: "Pressing Tab through the whole page never reached this element. Check it can be reached with the keyboard." });
  return hits;
}

function coverageHits(w: Walk): Hit[] {
  if (w.end !== "limit") return [];
  return [{ rule: "coverage", outcome: "cantTell", at: DOCUMENT,
    message: `The Tab walk stopped after ${w.seq.length} stops (scan limit). Check the rest of the page with the keyboard.` }];
}

async function collect(page: Page, deadline: number): Promise<Hit[]> {
  const w = await walk(page, deadline);
  const unreached = w.end === "complete" ? await call<PageTarget[]>(page, "unreached", MAX_PER_RULE) : [];
  const targets = await call<PageTarget[]>(page, "nonFocusable", MAX_PER_RULE);
  return [...w.hits, ...coverageHits(w), ...reachHits(targets, unreached), ...orderHits(w), ...(await focusHits(page, w))];
}

const inLevel = (rule: Rule, level: LevelSpec): boolean => withinLevel(mapSc(RULES[rule].sc).wcagLevel, level.maxLevel);

function toFindings(hits: Hit[], level: LevelSpec): RawFinding[] {
  const perRule = new Map<Rule, number>();
  const out: RawFinding[] = [];
  for (const h of hits) {
    const n = perRule.get(h.rule) ?? 0;
    if (!inLevel(h.rule, level) || n >= MAX_PER_RULE) continue;
    perRule.set(h.rule, n + 1);
    const r = RULES[h.rule];
    out.push(automatedFinding({ engine: "accessibility-insights-fastpass", outcome: h.outcome, ruleId: r.id, sc: r.sc,
      selector: h.at.selector, html: h.at.html, message: h.message, impact: r.impact, helpUrl: r.help }));
  }
  return out;
}

async function restore(page: Page): Promise<void> {
  await page
    .evaluate((k) => {
      (document.activeElement as HTMLElement | null)?.blur?.();
      delete (window as unknown as Record<string, unknown>)[k];
      scrollTo(0, 0);
    }, KEY)
    .catch(() => {});
}

export async function runFastpass(page: Page, level: LevelSpec): Promise<EngineRun> {
  try {
    await page.evaluate(installFastpassHelpers, KEY);
    const findings = toFindings(await collect(page, Date.now() + BUDGET_MS), level);
    const rules = (Object.keys(RULES) as Rule[]).filter((r) => inLevel(r, level));
    const passes = rules.filter((r) => !findings.some((f) => f.ruleId === RULES[r].id)).length;
    return { findings, passes };
  } catch (err) {
    return { findings: [], passes: 0, error: clip((err as Error)?.message ?? err, 500) };
  } finally {
    await restore(page);
  }
}
