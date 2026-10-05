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
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { type Browser, chromium, type Page } from "playwright";
import { BLOCKED_HEADER, EgressDenied, type Egress, resolvePublic, startEgress } from "./egress.js";
import { runAlfa } from "./engines/alfa.js";
import { ARIA_ENGINE, runAriaTree } from "./engines/aria.js";
import { runAxe } from "./engines/axe.js";
import { FASTPASS_VERSION, runFastpass } from "./engines/fastpass.js";
import type { LevelSpec } from "./levels.js";
import type { EngineName, EngineRun, Finding, FindingEngine, RawFinding } from "./types.js";

// Chromium only: Alfa attaches over CDP. WCAG 2.2 SC 1.4.10: reflow at 320 px.
export const PROFILES = {
  desktop: { viewport: { width: 1280, height: 800 } },
  "mobile-320": { viewport: { width: 320, height: 640 } },
} as const;
export type ProfileName = keyof typeof PROFILES;

const NAV_TIMEOUT_MS = Number(process.env.SCAN_NAV_TIMEOUT_MS ?? 45_000);
const SETTLE_MS = 500;

export interface ScanRequest {
  url: string;
  level: string;
  spec: LevelSpec;
  engines: EngineName[];
  profiles: ProfileName[];
  authorization: { privacy_consent: true; authorized_by: string };
}

export interface ProfileResult {
  profile: ProfileName;
  error?: string;
  engines: Partial<Record<FindingEngine, { passes: number; findings: number; error?: string }>>;
}

export interface ScanResult {
  url: string;
  level: string;
  engines: EngineName[];
  status: "done" | "error"; // "error" if any profile or engine failed: never a silent pass
  error?: string;
  blockedRequests: string[];
  contactedHosts: string[];
  toolVersions: Record<string, string>;
  profiles: ProfileResult[];
  findings: Finding[];
}

const RUNNERS: Record<EngineName, (page: Page, spec: LevelSpec) => Promise<EngineRun>> = {
  axe: runAxe,
  alfa: runAlfa,
  "accessibility-insights-fastpass": runFastpass,
};

let egress: Promise<Egress> | null = null;
let browser: Promise<Browser> | null = null;

function getEgress(): Promise<Egress> {
  egress ??= startEgress();
  return egress;
}

async function getBrowser(): Promise<Browser> {
  browser ??= getEgress().then((e) =>
    chromium.launch({
      // "<-loopback>": Chromium must not bypass the egress proxy for localhost.
      proxy: { server: e.url, bypass: "<-loopback>" },
      // Privacy: no background Chromium traffic (telemetry, updates, pings, Safe Browsing).
      args: [
        "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
        "--disable-quic",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-domain-reliability",
        "--disable-sync",
        "--disable-client-side-phishing-detection",
        "--disable-features=OptimizationHints,MediaRouter,Translate,AutofillServerCommunication,CertificateTransparencyComponentUpdater",
        "--metrics-recording-only",
        "--no-pings",
        "--no-default-browser-check",
        "--no-first-run",
        "--safebrowsing-disable-auto-update",
      ],
    }),
  );
  return browser;
}

export async function closeBrowser(): Promise<void> {
  const b = browser;
  const e = egress;
  browser = null;
  egress = null;
  if (b) await (await b).close().catch(() => {});
  if (e) await (await e).close().catch(() => {});
}

function pkgVersion(name: string): string {
  try {
    const req = createRequire(import.meta.url);
    let dir = dirname(req.resolve(name));
    for (let i = 0; i < 6; i++) {
      try {
        const pkg = JSON.parse(readFileSync(join(dir, "package.json"), "utf8"));
        if (pkg.name === name) return String(pkg.version);
      } catch {
      }
      dir = dirname(dir);
    }
  } catch {
  }
  return "unknown";
}

export function toolVersions(): Record<string, string> {
  return {
    "axe-core": pkgVersion("axe-core"),
    "@siteimprove/alfa-test-utils": pkgVersion("@siteimprove/alfa-test-utils"),
    playwright: pkgVersion("playwright"),
    "wa-a11y-fastpass": FASTPASS_VERSION,
  };
}

const ariaProfile = (profiles: ProfileName[]): ProfileName | undefined =>
  profiles.includes("desktop") ? "desktop" : profiles[0];

async function scanProfile(req: ScanRequest, profile: ProfileName): Promise<{ result: ProfileResult; runs: Partial<Record<FindingEngine, EngineRun>> }> {
  const result: ProfileResult = { profile, engines: {} };
  const runs: Partial<Record<FindingEngine, EngineRun>> = {};
  const context = await (await getBrowser()).newContext({ ...PROFILES[profile], ignoreHTTPSErrors: false });
  try {
    const page = await context.newPage();
    const response = await page.goto(req.url, { waitUntil: "domcontentloaded", timeout: NAV_TIMEOUT_MS });
    if (response?.headers()[BLOCKED_HEADER])
      throw new Error("the page redirected to an address that is not allowed (internal network)");
    await page.waitForLoadState("load", { timeout: NAV_TIMEOUT_MS }).catch(() => {});
    await page.waitForTimeout(SETTLE_MS);
    for (const engine of req.engines) {
      const run = await RUNNERS[engine](page, req.spec);
      runs[engine] = run;
      result.engines[engine] = { passes: run.passes, findings: run.findings.length, ...(run.error ? { error: run.error } : {}) };
    }
    if (profile === ariaProfile(req.profiles)) {
      const run = await runAriaTree(page);
      runs[ARIA_ENGINE] = run;
      result.engines[ARIA_ENGINE] = { passes: run.passes, findings: run.findings.length - run.passes };
    }
  } catch (err) {
    result.error = String((err as Error)?.message ?? err).slice(0, 500);
  } finally {
    await context.close().catch(() => {});
  }
  return { result, runs };
}

type ProfileRuns = { profile: ProfileName; runs: Partial<Record<FindingEngine, EngineRun>> };

function addFinding(seen: Map<string, Finding>, f: RawFinding, profile: ProfileName): void {
  const key = `${f.engine}::${f.outcome}::${f.ruleId}::${f.selector}`;
  const existing = seen.get(key);
  if (!existing) seen.set(key, { ...f, profiles: [profile] });
  else if (!existing.profiles.includes(profile)) existing.profiles.push(profile);
}

function dedup(perProfile: ProfileRuns[]): Finding[] {
  const seen = new Map<string, Finding>();
  for (const { profile, runs } of perProfile)
    for (const f of Object.values(runs).flatMap((r) => r?.findings ?? [])) addFinding(seen, f, profile);
  return [...seen.values()];
}

function errorResult(req: ScanRequest, error: string, blockedRequests: string[]): ScanResult {
  return { url: req.url, level: req.level, engines: req.engines, status: "error", error,
    blockedRequests, contactedHosts: [], toolVersions: toolVersions(), profiles: [], findings: [] };
}

export async function scan(req: ScanRequest): Promise<ScanResult> {
  if (req.authorization?.privacy_consent !== true || !req.authorization.authorized_by?.trim())
    throw new Error("refusing to scan: privacy consent and an authorizing user are required");
  const e = await getEgress();
  e.blocked.length = 0;
  e.contacted.clear();
  const target = new URL(req.url);
  try {
    await resolvePublic(target.hostname, Number(target.port || (target.protocol === "https:" ? 443 : 80)));
  } catch (err) {
    const why = err instanceof EgressDenied ? err.message : `cannot resolve ${target.hostname}`;
    return errorResult(req, `target not allowed: ${why}`, []);
  }
  const perProfile: ProfileRuns[] = [];
  const profiles: ProfileResult[] = [];
  for (const p of req.profiles) {
    const { result, runs } = await scanProfile(req, p);
    profiles.push(result);
    perProfile.push({ profile: p, runs });
  }
  const failures = profiles.flatMap((p) =>
    p.error
      ? [`${p.profile}: page did not load: ${p.error}`]
      : Object.entries(p.engines).flatMap(([e, r]) => (r?.error ? [`${p.profile}/${e}: ${r.error}`] : [])),
  );
  return {
    url: req.url,
    level: req.level,
    engines: req.engines,
    status: failures.length ? "error" : "done",
    ...(failures.length ? { error: failures.join("; ").slice(0, 2000) } : {}),
    blockedRequests: [...e.blocked],
    contactedHosts: [...e.contacted].sort(),
    toolVersions: toolVersions(),
    profiles,
    findings: dedup(perProfile),
  };
}
