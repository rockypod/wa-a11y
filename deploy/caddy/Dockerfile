# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

FROM docker.io/library/caddy:2.11.6-alpine
COPY deploy/caddy/Caddyfile /etc/caddy/Caddyfile
# Non-root: drop the file capability so caddy runs without NET_BIND_SERVICE
RUN setcap -r /usr/bin/caddy \
 && addgroup -S -g 10002 caddy && adduser -S -D -H -u 10002 -G caddy caddy \
 && chown -R caddy:caddy /data /config
USER caddy
EXPOSE 8080
