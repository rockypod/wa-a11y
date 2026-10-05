# Dependency audit allowlist

Any vulnerability ignored in `pip-audit` (`--ignore-vuln`) or `pnpm audit` (`auditConfig.ignoreCves` /
`ignoreGhsas`) must have a row here **before** the ignore is added. Rows past their expiry date must be
re-reviewed or removed; an expired row is treated as a failing check in review.

| ID (CVE / GHSA / PYSEC) | Package | Reason it does not apply / mitigation | Tracking | Expires (YYYY-MM-DD) |
|---|---|---|---|---|
| PYSEC-2026-311 | chromadb 1.5.9 | Chroma server-mode only (HTTP API / RBAC / trust_remote_code); wa-a11y runs Chroma embedded, no server, built-in embedder — enforced by web/tests/test_rag.py | upstream fix pending | 2027-01-01 |
| PYSEC-2026-3813 | chromadb 1.5.9 | Chroma server-mode only (HTTP API / RBAC / trust_remote_code); wa-a11y runs Chroma embedded, no server, built-in embedder — enforced by web/tests/test_rag.py | upstream fix pending | 2027-01-01 |
| PYSEC-2026-3814 | chromadb 1.5.9 | Chroma server-mode only (HTTP API / RBAC / trust_remote_code); wa-a11y runs Chroma embedded, no server, built-in embedder — enforced by web/tests/test_rag.py | upstream fix pending | 2027-01-01 |
| PYSEC-2026-3815 | chromadb 1.5.9 | Chroma server-mode only (HTTP API / RBAC / trust_remote_code); wa-a11y runs Chroma embedded, no server, built-in embedder — enforced by web/tests/test_rag.py | upstream fix pending | 2027-01-01 |
