/*
 * wa-a11y
 * SPDX-License-Identifier: AGPL-3.0-or-later
 *
 * This file is part of wa-a11y.
 * Copyright (C) 2026 Kevin Miller (rockypod)
 * Modifications must retain this wa-a11y notice and document all changes
 * pursuant to AGPLv3 Section 5 and Section 7.
 */

import assert from "node:assert/strict";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { after, before, describe, test } from "node:test";
import { EgressDenied, isPublicAddress, resolvePublic, setAllowInternal } from "../src/egress.js";
import { getLevel } from "../src/levels.js";
import { closeBrowser, scan } from "../src/scan.js";

let site: Server;
let internal: Server; // never allowlisted
let sitePort = 0;
let internalPort = 0;
let internalHits = 0;

const html = (body: string) => `<!doctype html><html lang="en"><head><title>t</title></head><body><main>${body}</main></body></html>`;

before(async () => {
  internal = createServer((_q, r) => {
    internalHits++;
    r.writeHead(200, { "content-type": "text/plain" }).end("SECRET internal data");
  });
  await new Promise<void>((r) => internal.listen(0, "127.0.0.1", r));
  internalPort = (internal.address() as AddressInfo).port;

  site = createServer((q, r) => {
    if (q.url === "/redirect") return r.writeHead(302, { location: `http://127.0.0.1:${internalPort}/` }).end();
    if (q.url === "/subresources")
      return r.writeHead(200, { "content-type": "text/html" }).end(html(
        `<h1>x</h1><img alt="a" src="http://127.0.0.1:${internalPort}/plain.png"><img alt="b" src="https://127.0.0.1:${internalPort}/tls.png">`));
    r.writeHead(200, { "content-type": "text/html" }).end(html("<h1>ok</h1>"));
  });
  await new Promise<void>((r) => site.listen(0, "127.0.0.1", r));
  sitePort = (site.address() as AddressInfo).port;
  setAllowInternal([`127.0.0.1:${sitePort}`]);
});
after(async () => {
  site.close();
  internal.close();
  await closeBrowser();
});

const run = (url: string) => scan({ url, level: "2.2-AA", spec: getLevel("2.2-AA")!, engines: ["axe"], profiles: ["desktop"], authorization: { privacy_consent: true, authorized_by: "tester@example.com" } });

describe("isPublicAddress", () => {
  for (const ip of ["127.0.0.1", "10.1.2.3", "172.20.0.5", "192.168.8.129", "169.254.169.254", "100.93.208.5",
    "0.0.0.0", "::1", "fe80::1", "fd7a:115c:a1e0::1", "::ffff:10.0.0.1", "::ffff:127.0.0.1", "not-an-ip",
    // hex-notation IPv4-mapped; NAT64 / 6to4 / Teredo wrapping internal IPv4
    "::ffff:7f00:1", "::ffff:a00:1", "0:0:0:0:0:ffff:c0a8:801", "64:ff9b::a00:1", "64:ff9b::7f00:1",
    "64:ff9b:1::a9fe:a9fe", "2002:a00:1::1", "2002:7f00:1::", "2001:0:4136:e378:8000:63bf:3fff:fdd2"])
    test(`blocks ${ip}`, () => assert.equal(isPublicAddress(ip), false));
  for (const ip of ["1.1.1.1", "8.8.8.8", "2606:4700:4700::1111", "::ffff:8.8.8.8", "::ffff:808:808", "64:ff9b::808:808"])
    test(`allows ${ip}`, () => assert.equal(isPublicAddress(ip), true));
});

describe("egress guard", () => {
  test("internal target is refused before any request", async () => {
    const before = internalHits;
    const r = await run(`http://127.0.0.1:${internalPort}/`);
    assert.equal(r.status, "error");
    assert.match(r.error ?? "", /target not allowed: .*non-public/);
    assert.equal(internalHits, before);
  });

  test("hostname resolving to loopback (localhost) is refused", async () => {
    const r = await run(`http://localhost:${internalPort}/`);
    assert.equal(r.status, "error");
    assert.match(r.error ?? "", /target not allowed/);
  });

  test("redirect from an allowed page to an internal address is blocked", async () => {
    const before = internalHits;
    const r = await run(`http://127.0.0.1:${sitePort}/redirect`);
    assert.equal(r.status, "error");
    assert.match(r.error ?? "", /redirected to an address that is not allowed/);
    assert.ok(r.blockedRequests.some((b) => b.includes(`127.0.0.1:${internalPort}`)), JSON.stringify(r.blockedRequests));
    assert.equal(internalHits, before, "internal service was reached via redirect");
  });

  test("internal subresources (http and https/CONNECT) are blocked; page still scanned", async () => {
    const before = internalHits;
    const r = await run(`http://127.0.0.1:${sitePort}/subresources`);
    assert.equal(r.status, "done", r.error);
    const log = JSON.stringify(r.blockedRequests);
    assert.ok(r.blockedRequests.some((b) => b.startsWith("GET ") && b.includes("plain.png")), log);
    assert.ok(r.blockedRequests.some((b) => b.startsWith(`CONNECT 127.0.0.1:${internalPort}`)), log);
    assert.equal(internalHits, before, "internal service was reached via subresource");
  });

  test("allowlisted host works and records nothing blocked", async () => {
    const r = await run(`http://127.0.0.1:${sitePort}/`);
    assert.equal(r.status, "done", r.error);
    assert.deepEqual(r.blockedRequests, []);
  });
});

describe("opt-in local targets (WA_A11Y_ALLOW_LOCAL_TARGETS)", () => {
  // Same opt-in as web/app/urlguard.py, read at call time — tests flip the env var.
  const saved = process.env.WA_A11Y_ALLOW_LOCAL_TARGETS;
  let localSite: Server;
  let localPort = 0;

  before(async () => {
    localSite = createServer((_q, r) =>
      r.writeHead(200, { "content-type": "text/html" }).end(html("<h1>local</h1>")));
    await new Promise<void>((r) => localSite.listen(0, "127.0.0.1", r));
    localPort = (localSite.address() as AddressInfo).port;
  });
  after(() => {
    if (saved === undefined) delete process.env.WA_A11Y_ALLOW_LOCAL_TARGETS;
    else process.env.WA_A11Y_ALLOW_LOCAL_TARGETS = saved;
    localSite.close();
  });

  test("off: loopback and private addresses stay blocked", () => {
    delete process.env.WA_A11Y_ALLOW_LOCAL_TARGETS;
    for (const ip of ["127.0.0.1", "10.1.2.3", "172.20.0.5", "192.168.1.20", "::1", "fd00::1",
      "::ffff:127.0.0.1"])
      assert.equal(isPublicAddress(ip), false);
  });

  test("on: loopback and private pass; link-local, metadata, CGNAT, multicast never", () => {
    process.env.WA_A11Y_ALLOW_LOCAL_TARGETS = "1";
    for (const ip of ["127.0.0.1", "10.1.2.3", "172.20.0.5", "192.168.1.20", "::1", "fd00::1",
      "::ffff:127.0.0.1"])
      assert.equal(isPublicAddress(ip), true);
    for (const ip of ["169.254.169.254", "fe80::1", "100.93.208.5", "224.0.0.1", "ff02::1", "0.0.0.0"])
      assert.equal(isPublicAddress(ip), false);
  });

  test("on: resolvePublic allows localhost and LAN addresses on any port", async () => {
    process.env.WA_A11Y_ALLOW_LOCAL_TARGETS = "1";
    assert.ok(["127.0.0.1", "::1"].includes(await resolvePublic("localhost", 3000)));
    assert.equal(await resolvePublic("127.0.0.1", 8080), "127.0.0.1");
    assert.equal(await resolvePublic("192.168.1.20", 80), "192.168.1.20");
  });

  test("on: resolvePublic still refuses cloud metadata and link-local", async () => {
    process.env.WA_A11Y_ALLOW_LOCAL_TARGETS = "1";
    await assert.rejects(() => resolvePublic("169.254.169.254", 80), EgressDenied);
    await assert.rejects(() => resolvePublic("fe80::1", 80), EgressDenied);
  });

  test("on: a local page is scanned end to end", async () => {
    process.env.WA_A11Y_ALLOW_LOCAL_TARGETS = "1";
    const r = await run(`http://127.0.0.1:${localPort}/`);
    assert.equal(r.status, "done", r.error);
  });

  test("off again: the same local page is refused", async () => {
    delete process.env.WA_A11Y_ALLOW_LOCAL_TARGETS;
    const r = await run(`http://127.0.0.1:${localPort}/`);
    assert.equal(r.status, "error");
    assert.match(r.error ?? "", /target not allowed/);
  });
});


describe("special-use ranges and self-port guard with the opt-in", () => {
  test("special-use IPv6 ranges are never public (match Python is_global)", () => {
    for (const ip of ["2001:2::1", "2001:10::1", "2001:20::1", "3fff::1", "5f00::1", "2001:0:4136::1"])
      assert.equal(isPublicAddress(ip), false, ip);
  });

  test("the scanner's own API port on loopback is refused even with local targets on", async () => {
    process.env.WA_A11Y_ALLOW_LOCAL_TARGETS = "1";
    try {
      await assert.rejects(resolvePublic("127.0.0.1", 3001), /own scanner service/);
      await assert.rejects(resolvePublic("localhost", 3001), /own scanner service/);
      assert.equal(await resolvePublic("127.0.0.1", 3000), "127.0.0.1");
    } finally {
      delete process.env.WA_A11Y_ALLOW_LOCAL_TARGETS;
    }
  });
});
