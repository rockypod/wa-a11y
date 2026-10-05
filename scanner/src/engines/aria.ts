/*
 * wa-a11y
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * This file is part of wa-a11y.
 * Copyright (C) 2026 Kevin Miller (rockypod)
 * Modifications must retain this wa-a11y notice and document all changes
 * pursuant to AGPLv3 Section 5 and Section 7.
 */

// Never return or store the snapshot: only bounded observations leave this module.
// Policy: structural checks are heuristics, so cantTell, never a fail alone.
import type { CDPSession, Page } from "playwright";
import { automatedFinding, clip } from "../finding.js";
import type { EngineRun, Outcome, RawFinding } from "../types.js";

export const ARIA_ENGINE = "aria-tree";
export const NOT_RUN = "aria-tree-not-run";

const TIMEOUT_MS = Number(process.env.SCAN_ARIA_TIMEOUT_MS ?? 15_000);
// Evidence caps.
const MAX_NODES = 20_000;
const MAX_ITEMS = 25;
const NAME_CHARS = 80;

export interface AxNode {
  role: string;
  name?: string;
  level?: number;
  url?: string;
  children?: AxNode[];
}

const CONTROLS = new Set(["textbox", "searchbox", "combobox", "listbox", "checkbox", "radio", "slider", "spinbutton", "switch"]);
const LANDMARKS = new Set(["banner", "navigation", "main", "complementary", "contentinfo", "region", "form", "search"]);
// region and form are landmarks only when named.
const NAMED_ONLY = new Set(["region", "form"]);

const UNDERSTANDING = "https://www.w3.org/WAI/WCAG22/Understanding/";
const HELP: Record<string, string> = {
  "aria-page-title": `${UNDERSTANDING}page-titled.html`,
  "aria-main-landmark": `${UNDERSTANDING}bypass-blocks.html`,
  "aria-h1": `${UNDERSTANDING}info-and-relationships.html`,
  "aria-heading-order": `${UNDERSTANDING}info-and-relationships.html`,
  "aria-control-names": `${UNDERSTANDING}name-role-value.html`,
  "aria-link-names": `${UNDERSTANDING}link-purpose-in-context.html`,
  "aria-button-names": `${UNDERSTANDING}name-role-value.html`,
  "aria-landmark-names": `${UNDERSTANDING}bypass-blocks.html`,
  "aria-tree-partial": `${UNDERSTANDING}info-and-relationships.html`,
};
const SCS: Record<string, string[]> = {
  "aria-page-title": ["2.4.2"],
  "aria-main-landmark": ["1.3.1", "2.4.1"],
  "aria-h1": ["1.3.1", "2.4.6"],
  "aria-heading-order": ["1.3.1"],
  "aria-control-names": ["1.3.1", "4.1.2"],
  "aria-link-names": ["2.4.4", "4.1.2"],
  "aria-button-names": ["4.1.2"],
  "aria-landmark-names": ["1.3.1", "2.4.1"],
  "aria-tree-partial": ["1.3.1"],
};

function obs(ruleId: string, outcome: Outcome, message: string, selector = "", html = ""): RawFinding {
  return automatedFinding({
    engine: ARIA_ENGINE,
    outcome,
    ruleId,
    sc: SCS[ruleId] ?? [],
    selector,
    html,
    message,
    impact: null,
    helpUrl: HELP[ruleId] ?? "",
  });
}

const quoted = (name: string | undefined) => (name ? ` "${clip(name, NAME_CHARS)}"` : "");

interface Seen {
  node: AxNode;
  where: string;
  nth: number;
}

function walk(roots: AxNode[]): { seen: Seen[]; truncated: boolean } {
  const seen: Seen[] = [];
  const counts = new Map<string, number>();
  const stack: { node: AxNode; path: string[] }[] = roots.map((node) => ({ node, path: [] })).reverse();
  while (stack.length) {
    if (seen.length >= MAX_NODES) return { seen, truncated: true };
    const { node, path } = stack.pop()!;
    const nth = (counts.get(node.role) ?? 0) + 1;
    counts.set(node.role, nth);
    seen.push({ node, where: ["page", ...path].join(" › "), nth });
    const inner = LANDMARKS.has(node.role) ? [...path, `${node.role}${quoted(node.name)}`] : path;
    for (const child of [...(node.children ?? [])].reverse()) stack.push({ node: child, path: inner });
  }
  return { seen, truncated: false };
}

const locate = (s: Seen) => `${s.where} › ${s.node.role} ${s.nth}${quoted(s.node.name)}`;
const treeLine = (n: AxNode) =>
  `- ${n.role}${quoted(n.name)}${n.level ? ` [level=${n.level}]` : ""}${n.url ? ` [url=${clip(n.url, 200)}]` : ""}`;

function capped(items: Seen[], ruleId: string, outcome: Outcome, message: (s: Seen) => string): RawFinding[] {
  const more = items.length > MAX_ITEMS ? ` (${MAX_ITEMS} of ${items.length} listed.)` : "";
  return items.slice(0, MAX_ITEMS).map((s, i) => obs(ruleId, outcome, message(s) + (i === 0 ? more : ""), locate(s), treeLine(s.node)));
}

function namesCheck(seen: Seen[], roles: Set<string>, ruleId: string, what: string, problem: (s: Seen) => string): RawFinding[] {
  const all = seen.filter((s) => roles.has(s.node.role));
  if (!all.length) return []; // not applicable, not a pass
  const nameless = all.filter((s) => !s.node.name?.trim());
  if (!nameless.length) return [obs(ruleId, "pass", `All ${all.length} ${what} have an accessible name exposed to assistive technology.`)];
  return capped(nameless, ruleId, "fail", problem);
}

function titleCheck(title: string): RawFinding {
  return title.trim()
    ? obs("aria-page-title", "pass", "The page has a title exposed to assistive technology.")
    : obs("aria-page-title", "fail", "The page has no title, so a screen reader cannot announce which page this is. Add a <title> that names the page and its site.", "page › title");
}

function mainCheck(seen: Seen[]): RawFinding {
  const mains = seen.filter((s) => s.node.role === "main");
  if (mains.length === 1) return obs("aria-main-landmark", "pass", "The page exposes exactly one main landmark.");
  if (!mains.length)
    return obs("aria-main-landmark", "cantTell", "No main landmark is exposed, so screen-reader users cannot jump to the main content. Wrap the main content in <main>, unless a skip link or headings already let people bypass repeated blocks.", "page");
  return obs("aria-main-landmark", "cantTell", `${mains.length} main landmarks are exposed. A page should have one visible <main>; check whether the others should be a different element.`, mains.map(locate).slice(0, 5).join("; "));
}

function headingChecks(seen: Seen[]): RawFinding[] {
  const headings = seen.filter((s) => s.node.role === "heading");
  const level = (s: Seen) => s.node.level ?? 2; // role="heading" without aria-level is level 2
  const out: RawFinding[] = [];
  out.push(
    headings.some((s) => level(s) === 1)
      ? obs("aria-h1", "pass", "The page exposes a level 1 heading.")
      : obs("aria-h1", "cantTell", headings.length
          ? "No level 1 heading is exposed. Screen-reader users often jump to the h1 to find the page's topic; mark the main title up as <h1>."
          : "No headings are exposed, so screen-reader users cannot move through the page by heading. Mark section titles up as <h1>–<h6>.", "page"),
  );
  if (headings.length < 2) return out;
  const skips: Seen[] = [];
  const prev = new Map<Seen, number>();
  headings.forEach((s, i) => {
    const before = i ? level(headings[i - 1]!) : 0;
    if (i && level(s) > before + 1) {
      skips.push(s);
      prev.set(s, before);
    }
  });
  out.push(
    ...(skips.length
      ? capped(skips, "aria-heading-order", "cantTell", (s) => `Heading level ${level(s)} follows level ${prev.get(s)}, skipping a level. Check the outline makes sense to someone moving by heading; use the next level down unless a level is skipped on purpose.`)
      : [obs("aria-heading-order", "pass", `The ${headings.length} exposed headings do not skip levels.`)]),
  );
  return out;
}

function landmarkNamesCheck(seen: Seen[]): RawFinding[] {
  const byRole = new Map<string, Seen[]>();
  for (const s of seen)
    if (LANDMARKS.has(s.node.role) && s.node.role !== "main" && !(NAMED_ONLY.has(s.node.role) && !s.node.name))
      byRole.set(s.node.role, [...(byRole.get(s.node.role) ?? []), s]);
  if (!byRole.size) return [];
  const unclear: Seen[] = [];
  for (const group of byRole.values()) {
    if (group.length < 2) continue;
    const names = group.map((s) => s.node.name?.trim().toLowerCase() ?? "");
    group.forEach((s, i) => {
      if (!names[i] || names.indexOf(names[i]!) !== i || names.lastIndexOf(names[i]!) !== i) unclear.push(s);
    });
  }
  if (!unclear.length) return [obs("aria-landmark-names", "pass", "Repeated landmarks, if any, have distinct names exposed to assistive technology.")];
  return capped(unclear, "aria-landmark-names", "cantTell", (s) => `There is more than one ${s.node.role} landmark and this one has no distinct name, so a screen reader's landmark list cannot tell them apart. Give each one a distinct aria-label or aria-labelledby.`);
}

export function observe(title: string, roots: AxNode[]): RawFinding[] {
  const { seen, truncated } = walk(roots);
  return [
    titleCheck(title),
    mainCheck(seen),
    ...headingChecks(seen),
    ...namesCheck(seen, CONTROLS, "aria-control-names", "form controls", (s) =>
      `This ${s.node.role} has no accessible name, so a screen reader announces only its role. Give it a visible <label for>, or aria-labelledby pointing at visible text.`),
    ...namesCheck(seen, new Set(["link"]), "aria-link-names", "links", () =>
      "This link has no accessible name, so a screen reader cannot say where it goes. Add link text, or alt text on the image inside it."),
    ...namesCheck(seen, new Set(["button"]), "aria-button-names", "buttons", () =>
      "This button has no accessible name, so a screen reader cannot say what it does. Add button text, or an aria-label matching the visible icon's meaning."),
    ...landmarkNamesCheck(seen),
    ...(truncated
      ? [obs("aria-tree-partial", "cantTell", `The page is very large: only the first ${MAX_NODES} accessibility-tree nodes were checked. Check the rest with a screen reader.`)]
      : []),
  ];
}

// Drop text nodes: static page text is never stored (privacy).
function fromSnapshot(v: unknown): AxNode[] {
  if (!Array.isArray(v)) return [];
  const out: AxNode[] = [];
  for (const n of v) {
    if (typeof n !== "object" || n === null || typeof (n as AxNode).role !== "string") continue;
    const r = n as Record<string, unknown>;
    if (r.role === "text") continue;
    out.push({
      role: String(r.role),
      ...(typeof r.name === "string" && r.name ? { name: r.name } : {}),
      ...(typeof r.level === "number" ? { level: r.level } : {}),
      ...(typeof r.url === "string" ? { url: r.url } : {}),
      children: fromSnapshot(r.children),
    });
  }
  return out;
}

interface CdpNode {
  nodeId: string;
  ignored?: boolean;
  role?: { value?: unknown };
  name?: { value?: unknown };
  properties?: { name: string; value?: { value?: unknown } }[];
  childIds?: string[];
}

const CDP_ROLES: Record<string, string> = { textField: "textbox" };
const SKIPPED = new Set(["", "RootWebArea", "StaticText", "InlineTextBox", "generic", "none", "Section", "sectionheader", "sectionfooter"]);

const cdpName = (n: CdpNode) => (typeof n.name?.value === "string" ? n.name.value.trim() : "");

function cdpNode(n: CdpNode, children: AxNode[]): AxNode | null {
  const raw = String(n.role?.value ?? "");
  if (n.ignored || SKIPPED.has(raw)) return null;
  const role = CDP_ROLES[raw] ?? raw;
  const name = cdpName(n);
  if (NAMED_ONLY.has(role) && !name) return null;
  const level = n.properties?.find((p) => p.name === "level")?.value?.value;
  return { role, ...(name ? { name } : {}), ...(typeof level === "number" ? { level } : {}), children };
}

function cdpBuild(byId: Map<string, CdpNode>, id: string, depth: number): AxNode[] {
  const n = byId.get(id);
  if (!n || depth > 500) return [];
  const kids = (n.childIds ?? []).flatMap((c) => cdpBuild(byId, c, depth + 1));
  const node = cdpNode(n, kids);
  return node ? [node] : kids;
}

export function fromCdp(nodes: CdpNode[]): AxNode[] {
  const byId = new Map(nodes.map((n) => [n.nodeId, n]));
  const childIds = new Set(nodes.flatMap((n) => n.childIds ?? []));
  return nodes.filter((n) => !childIds.has(n.nodeId)).flatMap((n) => cdpBuild(byId, n.nodeId, 0));
}

function withTimeout<T>(p: Promise<T>, what: string): Promise<T> {
  let timer: NodeJS.Timeout | undefined;
  const t = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${what} took longer than ${TIMEOUT_MS} ms`)), TIMEOUT_MS);
  });
  return Promise.race([p, t]).finally(() => clearTimeout(timer));
}

async function cdpTree(page: Page): Promise<AxNode[]> {
  let session: CDPSession | undefined;
  try {
    session = await page.context().newCDPSession(page);
    const res = (await withTimeout(session.send("Accessibility.getFullAXTree"), "the accessibility tree")) as { nodes: CdpNode[] };
    return fromCdp(res.nodes ?? []);
  } finally {
    await session?.detach().catch(() => {});
  }
}

export async function readTree(page: Page, sources = { snapshot: true, cdp: true }): Promise<AxNode[]> {
  const why: string[] = [];
  if (sources.snapshot)
    try {
      return fromSnapshot(await page.ariaSnapshotJSON({ timeout: TIMEOUT_MS }));
    } catch (err) {
      why.push(`aria snapshot: ${clip((err as Error)?.message ?? err, 200)}`);
    }
  if (sources.cdp)
    try {
      return await cdpTree(page);
    } catch (err) {
      why.push(`accessibility tree: ${clip((err as Error)?.message ?? err, 200)}`);
    }
  throw new Error(why.join("; ") || "no accessibility-tree source enabled");
}

// An unavailable tree is an explicit "not run", never an empty pass.
export async function runAriaTree(page: Page, sources?: { snapshot: boolean; cdp: boolean }): Promise<EngineRun> {
  try {
    const title = await withTimeout(page.title(), "reading the page title");
    const findings = observe(title, await readTree(page, sources));
    return { findings, passes: findings.filter((f) => f.outcome === "pass").length };
  } catch (err) {
    const why = clip((err as Error)?.message ?? err, 500);
    return {
      findings: [obs(NOT_RUN, "cantTell", `The screen-reader structure check could not run (${why}). Nothing was checked, so nothing here is a pass: check the page with a screen reader.`)],
      passes: 0,
    };
  }
}
