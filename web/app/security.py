# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

# CSP: the inline <style> by SHA-256 hash only, never 'unsafe-inline'; no scripts

from functools import cache

from app.theme import style_hash


@cache
def security_headers() -> list[tuple[bytes, bytes]]:
    csp = "; ".join(
        [
            "default-src 'none'",
            f"style-src {style_hash()}",
            "font-src 'self'",
            "img-src 'self' data:",
            "form-action 'self'",
            "base-uri 'none'",
            "frame-ancestors 'none'",
            "object-src 'none'",
            "script-src 'none'",
        ]
    )
    headers = {
        "content-security-policy": csp,
        "x-content-type-options": "nosniff",
        "referrer-policy": "no-referrer",
        "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        "cross-origin-opener-policy": "same-origin",
        "cross-origin-resource-policy": "same-origin",
        "x-frame-options": "DENY",
    }
    return [(k.encode(), v.encode()) for k, v in headers.items()]


class SecurityHeaders:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                ours = security_headers()
                names = {k for k, _ in ours}
                message["headers"] = [
                    h for h in message.get("headers", []) if h[0].lower() not in names
                ]
                message["headers"] += ours
            await send(message)

        await self.app(scope, receive, send_with_headers)
