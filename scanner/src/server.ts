/*
 * wa-a11y
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * This file is part of wa-a11y.
 * Copyright (C) 2026 Kevin Miller (rockypod)
 * Modifications must retain this wa-a11y notice and document all changes
 * pursuant to AGPLv3 Section 5 and Section 7.
 */

// No shell, no child_process, no DB; reachable only from web on the internal network.
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { getLevel, LEVELS, type LevelSpec } from "./levels.js";
import { closeBrowser, PROFILES, type ProfileName, scan, type ScanRequest, toolVersions } from "./scan.js";
import type { EngineName } from "./types.js";

const MAX_BODY = 16 * 1024;
const ENGINES: readonly EngineName[] = ["axe", "alfa", "accessibility-insights-fastpass"];
const DEFAULT_ENGINES: EngineName[] = ["axe", "alfa"];

class BadRequest extends Error {}

function send(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(body));
}

async function readJson(req: IncomingMessage): Promise<unknown> {
  let size = 0;
  const chunks: Buffer[] = [];
  for await (const chunk of req) {
    size += (chunk as Buffer).length;
    if (size > MAX_BODY) throw new BadRequest("body too large");
    chunks.push(chunk as Buffer);
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new BadRequest("body is not valid JSON");
  }
}

function parseUrl(v: unknown): string {
  if (typeof v !== "string") throw new BadRequest("url must be a string");
  let parsed: URL;
  try {
    parsed = new URL(v);
  } catch {
    throw new BadRequest("url is not a valid URL");
  }
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") throw new BadRequest("url must be http(s)");
  return parsed.href;
}

function parseLevel(v: unknown): { level: string; spec: LevelSpec } {
  const spec = typeof v === "string" ? getLevel(v) : undefined;
  if (!spec) throw new BadRequest(`level must be one of ${Object.keys(LEVELS).join(", ")}`);
  return { level: v as string, spec };
}

function parseSubset<T extends string>(v: unknown, allowed: readonly T[], fallback: T[], name: string): T[] {
  const list = v ?? fallback;
  const ok = Array.isArray(list) && list.length > 0 && list.every((x) => allowed.includes(x as T));
  if (!ok) throw new BadRequest(`${name} must be a non-empty subset of ${allowed.join(", ")}`);
  return [...new Set(list as T[])];
}

// Privacy: no scan without explicit consent and an authorizing user.
function parseAuthorization(v: unknown): { privacy_consent: true; authorized_by: string } {
  const a = (typeof v === "object" && v !== null ? v : {}) as Record<string, unknown>;
  const user = typeof a.authorized_by === "string" ? a.authorized_by.trim() : "";
  if (a.privacy_consent !== true || !user)
    throw new BadRequest("authorization required: privacy_consent must be true and authorized_by set");
  return { privacy_consent: true, authorized_by: user.slice(0, 320) };
}

export function parseScanRequest(body: unknown): ScanRequest {
  if (typeof body !== "object" || body === null) throw new BadRequest("body must be a JSON object");
  const b = body as Record<string, unknown>;
  const authorization = parseAuthorization(b.authorization);
  return {
    url: parseUrl(b.url),
    ...parseLevel(b.level),
    engines: parseSubset(b.engines, ENGINES, DEFAULT_ENGINES, "engines"),
    profiles: parseSubset(b.profiles, Object.keys(PROFILES) as ProfileName[], ["desktop"], "profiles"),
    authorization,
  };
}

// One scan at a time: concurrent scans exhaust Chromium memory.
let chain: Promise<unknown> = Promise.resolve();
function serialised<T>(fn: () => Promise<T>): Promise<T> {
  const next = chain.then(fn, fn);
  chain = next.catch(() => {});
  return next;
}

async function handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
  try {
    if (req.method === "GET" && req.url === "/health") {
      return send(res, 200, { ok: true, service: "scanner", versions: toolVersions() });
    }
    if (req.method === "POST" && req.url === "/scan") {
      const scanReq = parseScanRequest(await readJson(req));
      return send(res, 200, await serialised(() => scan(scanReq)));
    }
    return send(res, 404, { ok: false, error: "not found" });
  } catch (err) {
    if (err instanceof BadRequest) return send(res, 400, { ok: false, error: err.message });
    return send(res, 500, { ok: false, error: "internal error" });
  }
}

export const server = createServer(handle);

if (import.meta.url === `file://${process.argv[1]}`) {
  const port = Number(process.env.PORT ?? 3001);
  server.listen(port, () => console.log(`scanner listening on :${port}`));
  for (const sig of ["SIGTERM", "SIGINT"] as const)
    process.on(sig, () => {
      server.close();
      void closeBrowser().finally(() => process.exit(0));
    });
}
