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

export const BASE = (process.env.SELFSCAN_URL ?? "http://127.0.0.1:8767").replace(/\/$/, "");
export const PAGES = ["/", "/help", "/about", "/settings", "/settings?saved=1", "/scans/1", "/scans/2", "/scans/3",
  "/scans/4", "/scans/5", "/scans/6", "/scans/7", "/scans/33", "/scans/2/assessment", "ASSESSMENT-ERROR", "CLOSED:/scans/2", "CLOSED:/scans/6", "CLOSED:/scans/7",
  "/scans/5/export", "/privacy", "/accessibility", "/scans", "/scans?page=2", "/scans/2/delete", "EXPORT-SHOW", "EXPORT-ERROR", "FORM-ERROR",
  "/login", "LOGIN-ERROR"];
export const PUBLIC = new Set(["/login", "LOGIN-ERROR"]);

export async function signIn(p: Page): Promise<void> {
  await p.goto(BASE + "/login");
  await p.fill("#email", "selfscan@example.com");
  await p.fill("#password", "selfscan-only-password");
  await Promise.all([p.waitForURL((u) => !u.pathname.endsWith("/login")), p.click("button[type=submit]")]);
}

export async function load(p: Page, path: string): Promise<void> {
  if (path === "LOGIN-ERROR") {
    await p.goto(BASE + "/login");
    await p.fill("#email", "nobody@example.com");
    await p.fill("#password", "not-the-right-password");
    await Promise.all([p.waitForLoadState(), p.click("button[type=submit]")]);
    return;
  }
  if (path === "EXPORT-SHOW" || path === "EXPORT-ERROR") {
    await p.goto(BASE + "/scans/5/export");
    if (path === "EXPORT-SHOW") await p.check("#confirm");
    await Promise.all([p.waitForLoadState(), p.click("button[value=show]")]);
    return;
  }
  if (path === "ASSESSMENT-ERROR") {
    await p.goto(BASE + "/scans/2/assessment");
    await p.fill("#notes-kbd-trap", "Focus stayed in the video player.");
    await Promise.all([p.waitForLoadState(), p.click("#save")]);
    return;
  }
  if (path !== "FORM-ERROR") {
    await p.goto(BASE + path.replace(/^CLOSED:/, ""));
    return;
  }
  await p.goto(BASE + "/");
  await p.fill("#url", "not a web address");
  await p.uncheck("#engines-axe");
  await p.uncheck("#engines-alfa");
  await p.uncheck("#engines-accessibility-insights-fastpass");
  await Promise.all([p.waitForLoadState(), p.click("button[type=submit]")]);
}