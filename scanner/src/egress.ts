/*
 * wa-a11y
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * This file is part of wa-a11y.
 * Copyright (C) 2026 Kevin Miller (rockypod)
 * Modifications must retain this wa-a11y notice and document all changes
 * pursuant to AGPLv3 Section 5 and Section 7.
 */

import { lookup } from "node:dns/promises";
import { createServer, request as httpRequest, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import { BlockList, connect, isIP, type AddressInfo, type Socket } from "node:net";

const blocked = new BlockList();
for (const [net, prefix] of [
  ["0.0.0.0", 8], ["10.0.0.0", 8], ["100.64.0.0", 10] /* CGNAT, incl. Tailscale */, ["127.0.0.0", 8],
  ["169.254.0.0", 16] /* link-local, cloud metadata */, ["172.16.0.0", 12], ["192.0.0.0", 24],
  ["192.0.2.0", 24], ["192.168.0.0", 16], ["198.18.0.0", 15], ["198.51.100.0", 24],
  ["203.0.113.0", 24], ["224.0.0.0", 4], ["240.0.0.0", 4],
] as const) blocked.addSubnet(net, prefix, "ipv4");
for (const [net, prefix] of [
  ["::", 128], ["::1", 128], ["fc00::", 7] /* ULA, incl. Tailscale */, ["fe80::", 10],
  ["ff00::", 8], ["2001:db8::", 32], ["100::", 64],
  // IANA special-use ranges (match Python's is_global).
  ["2001::", 23], ["3fff::", 20], ["5f00::", 16],
] as const) blocked.addSubnet(net, prefix, "ipv6");

// Opt-in allows loopback/private only; never link-local/metadata, multicast, CGNAT or reserved.
const localOk = new BlockList();
for (const [net, prefix] of [
  ["127.0.0.0", 8], ["10.0.0.0", 8], ["172.16.0.0", 12], ["192.168.0.0", 16],
  ["::1", 128], ["fd00::", 8],
] as const) localOk.addSubnet(net, prefix, net.includes(":") ? "ipv6" : "ipv4");

// Keep in sync with web's urlguard, which reads the same variable.
function allowLocalTargets(): boolean {
  return ["1", "true", "yes", "on"].includes(
    (process.env.WA_A11Y_ALLOW_LOCAL_TARGETS ?? "").trim().toLowerCase(),
  );
}

function hextets(ip: string): number[] | null {
  let addr = ip.split("%")[0]!.toLowerCase();
  const v4tail = /(\d+\.\d+\.\d+\.\d+)$/.exec(addr);
  if (v4tail) {
    const o = v4tail[1]!.split(".").map(Number);
    addr = addr.slice(0, -v4tail[1]!.length) + `${((o[0]! << 8) | o[1]!).toString(16)}:${((o[2]! << 8) | o[3]!).toString(16)}`;
  }
  const [head, tail] = addr.includes("::") ? addr.split("::") : [addr, undefined];
  const h = head ? head.split(":") : [];
  const t = tail !== undefined && tail !== "" ? tail.split(":") : [];
  const fill = tail === undefined ? [] : Array(8 - h.length - t.length).fill("0");
  const parts = [...h, ...fill, ...t];
  return parts.length === 8 ? parts.map((p) => parseInt(p, 16)) : null;
}

const v4 = (a: number, b: number) => `${a >> 8}.${a & 255}.${b >> 8}.${b & 255}`;

function embeddedIPv4(ip: string): string | null {
  const h = hextets(ip);
  if (!h) return null;
  if (h.slice(0, 5).every((x) => x === 0) && h[5] === 0xffff) return v4(h[6]!, h[7]!);
  if (h[0] === 0x64 && h[1] === 0xff9b && h.slice(2, 6).every((x) => x === 0)) return v4(h[6]!, h[7]!);
  if (h[0] === 0x64 && h[1] === 0xff9b && h[2] === 1) return v4(h[6]!, h[7]!);
  if (h[0] === 0x2002) return v4(h[1]!, h[2]!);
  return null;
}

export function isPublicAddress(ip: string): boolean {
  const bare = ip.split("%")[0]!;
  const family = isIP(bare);
  if (family === 0) return false;
  // Judge embedded IPv4 (mapped/NAT64/6to4) as IPv4.
  if (family === 6) {
    const inner = embeddedIPv4(bare);
    if (inner) return isPublicAddress(inner);
  }
  const fam = family === 4 ? ("ipv4" as const) : ("ipv6" as const);
  if (!blocked.check(bare, fam)) return true;
  return allowLocalTargets() && localOk.check(bare, fam);
}

let allowInternal = new Set(
  (process.env.SCANNER_ALLOW_INTERNAL ?? "").split(",").map((s) => s.trim().toLowerCase()).filter(Boolean),
);
// Tests only.
export function setAllowInternal(entries: string[]): void {
  allowInternal = new Set(entries.map((s) => s.toLowerCase()));
}

export class EgressDenied extends Error {}

const selfPorts = new Set<number>([Number(process.env.PORT ?? 3001)]);
function registerSelfPort(port: number): void {
  selfPorts.add(port);
}

function isLoopback(ip: string): boolean {
  const inner = isIP(ip) === 6 ? embeddedIPv4(ip) : null;
  const v = inner ?? ip;
  return v === "::1" || /^127\./.test(v) || v === "0.0.0.0" || v === "::";
}

export const BLOCKED_HEADER = "x-wa-a11y-egress";

// Check every resolved IP and return the checked one to connect to: DNS rebinding.
export async function resolvePublic(host: string, port: number): Promise<string> {
  const bare = host.replace(/^\[|\]$/g, "");
  const literal = isIP(bare) !== 0;
  const addrs = literal ? [bare] : (await lookup(bare, { all: true, verbatim: true })).map((a) => a.address);
  if (addrs.length === 0) throw new EgressDenied(`${host} did not resolve`);
  // Never reach the scanner's own API or proxy on loopback, even with local targets.
  if (selfPorts.has(port) && addrs.some((a) => isLoopback(a)))
    throw new EgressDenied(`${bare}:${port} is wa-a11y's own scanner service`);
  const allowed = allowInternal.has(bare.toLowerCase()) || allowInternal.has(`${bare.toLowerCase()}:${port}`);
  if (!allowed) {
    const bad = addrs.find((a) => !isPublicAddress(a));
    if (bad) throw new EgressDenied(`${bare}:${port} resolves to a non-public address (${bad})`);
  }
  return addrs[0]!;
}

export interface Egress {
  url: string;
  blocked: string[];
  contacted: Set<string>;
  close(): Promise<void>;
}

function deny(log: string[], what: string, err: unknown): string {
  const msg = `${what} — ${err instanceof EgressDenied ? err.message : (err as Error)?.message ?? String(err)}`;
  if (log.length < 100) log.push(msg);
  return msg;
}

const MAX_SOCKETS = 64;
const IDLE_MS = 30_000;
const MAX_UPLOAD = 10 * 1024 * 1024;

export async function startEgress(): Promise<Egress> {
  const log: string[] = [];
  const contacted = new Set<string>();
  const sockets = new Set<Socket>();
  const track = (sock: Socket): void => {
    sockets.add(sock);
    sock.setTimeout(IDLE_MS, () => sock.destroy());
    sock.once("close", () => sockets.delete(sock));
  };

  async function proxyHttp(req: IncomingMessage, res: ServerResponse): Promise<void> {
    try {
      const target = new URL(req.url ?? "");
      if (target.protocol !== "http:") throw new EgressDenied(`unsupported scheme ${target.protocol}`);
      const port = Number(target.port || 80);
      const ip = await resolvePublic(target.hostname, port);
      contacted.add(`${target.hostname}:${port}`);
      if (Number(req.headers["content-length"] ?? 0) > MAX_UPLOAD) throw new EgressDenied("request body too large");
      const upstream = httpRequest(
        { host: ip, port, method: req.method, path: target.pathname + target.search, headers: { ...req.headers, host: target.host } },
        (up) => {
          res.writeHead(up.statusCode ?? 502, up.headers);
          up.pipe(res);
        },
      );
      upstream.on("socket", track);
      upstream.on("error", () => res.destroy());
      let sent = 0;
      req.on("data", (chunk: Buffer) => {
        sent += chunk.length;
        if (sent > MAX_UPLOAD) {
          upstream.destroy();
          req.destroy();
        }
      });
      req.pipe(upstream);
    } catch (err) {
      deny(log, `${req.method} ${req.url}`, err);
      res.writeHead(403, { "content-type": "text/plain", [BLOCKED_HEADER]: "blocked" }).end("blocked by wa-a11y egress policy");
    }
  }

  async function proxyConnect(req: IncomingMessage, client: Socket, head: Buffer): Promise<void> {
    try {
      const m = /^(\[[^\]]+\]|[^:]+):(\d+)$/.exec(req.url ?? "");
      if (!m) throw new EgressDenied(`bad CONNECT target ${req.url}`);
      const port = Number(m[2]);
      const ip = await resolvePublic(m[1]!, port);
      contacted.add(`${m[1]}:${port}`);
      const upstream = connect(port, ip, () => {
        client.write("HTTP/1.1 200 Connection Established\r\n\r\n");
        if (head.length) upstream.write(head);
        upstream.pipe(client);
        client.pipe(upstream);
      });
      track(upstream);
      upstream.on("error", () => client.destroy());
      client.on("error", () => upstream.destroy());
    } catch (err) {
      deny(log, `CONNECT ${req.url}`, err);
      client.end("HTTP/1.1 403 Forbidden\r\n\r\n");
    }
  }

  const server: Server = createServer(proxyHttp);
  server.maxConnections = MAX_SOCKETS;
  server.requestTimeout = 60_000;
  server.headersTimeout = 30_000;
  server.on("connection", track);
  server.on("connect", proxyConnect);

  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  const { port } = server.address() as AddressInfo;
  registerSelfPort(port);
  return {
    url: `http://127.0.0.1:${port}`,
    blocked: log,
    contacted,
    close: () =>
      new Promise((r) => {
        for (const s of sockets) s.destroy();
        server.close(() => r());
      }),
  };
}
