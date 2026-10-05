# wa-a11y
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of wa-a11y.
# Copyright (C) 2026 Kevin Miller (rockypod)
# Modifications must retain this wa-a11y notice and document all changes
# pursuant to AGPLv3 Section 5 and Section 7.

# Privacy rule: Chroma telemetry off; embedding model baked in, no runtime download

import logging
import os
from functools import cache
from urllib.parse import urlsplit

import chromadb
from chromadb.config import Settings
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

from app.rag.guidance import GUIDANCE, GUIDANCE_VERSION
from app.store.models import Finding, Outcome, Scan
from app.wcag import SC, sc_label

log = logging.getLogger("wa_a11y.rag")
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
_META = {"hnsw:space": "cosine", "embedding_model": EMBEDDING_MODEL}


def chroma_path() -> str:
    return os.environ.get("WA_A11Y_CHROMA_PATH", "/data/chroma")


@cache
def _client(path: str):
    return chromadb.PersistentClient(
        path=path, settings=Settings(anonymized_telemetry=False, allow_reset=False)
    )


@cache
def _embedder():
    return DefaultEmbeddingFunction()


def collection(name: str):
    return _client(chroma_path()).get_or_create_collection(
        name, embedding_function=_embedder(), metadata=_META
    )


def _doc(f: Finding, scan: Scan) -> str:
    scs = [s for s in (f.sc or "").split(",") if s]
    labels = "; ".join(sc_label(s) for s in scs if s in SC) or "advisory"
    return (
        f"{f.rule_id}: {f.message}\n"
        f"WCAG {labels}. Engine {f.engine.value}. Outcome {f.outcome.value}.\n"
        f"Element {f.selector}\nMarkup {(f.html_snippet or '')[:400]}"
    )


def index_scan(scan: Scan, findings: list[Finding]) -> int:
    col = collection("findings")
    findings = [f for f in findings if f.outcome in (Outcome.FAIL, Outcome.CANT_TELL)]
    level = scan.level.value
    site = urlsplit(scan.url).netloc
    ids, docs, metas = [], [], []
    for f in findings:
        ids.append(f"{f.fingerprint}:{level}")
        docs.append(_doc(f, scan))
        metas.append(
            {
                "site": site,
                "url": scan.url,
                "scan_id": int(scan.id),
                "level": level,
                "engine": f.engine.value,
                "sc": (f.sc or "").split(",")[0],
                "sc_all": f.sc or "",
                "rule_id": f.rule_id,
                "impact": f.impact or "",
                "outcome": f.outcome.value,
                "status": "open",
                "scanned_at": (scan.finished_at or scan.created_at).isoformat(),
            }
        )
    if ids:
        col.upsert(ids=ids, documents=docs, metadatas=metas)
    current = set(ids)
    previous = col.get(
        where={"$and": [{"url": scan.url}, {"level": level}, {"status": "open"}]},
        include=["metadatas"],
    )
    gone = [
        (i, m)
        for i, m in zip(previous["ids"], previous["metadatas"], strict=True)
        if i not in current
    ]
    if gone:
        col.update(
            ids=[i for i, _ in gone],
            metadatas=[{**m, "status": "fixed", "fixed_in_scan": int(scan.id)} for _, m in gone],
        )
    return len(ids)


def forget_scan(scan_id: int) -> int:
    col = collection("findings")
    seen = col.get(where={"scan_id": int(scan_id)})["ids"]
    if seen:
        col.delete(ids=seen)
    marked = col.get(
        where={"fixed_in_scan": int(scan_id)}, include=["documents", "metadatas", "embeddings"]
    )
    if marked["ids"]:
        metas = [
            {**{k: v for k, v in m.items() if k != "fixed_in_scan"}, "status": "open"}
            for m in marked["metadatas"]
        ]
        col.delete(ids=marked["ids"])
        col.add(
            ids=marked["ids"],
            documents=marked["documents"],
            metadatas=metas,
            embeddings=marked["embeddings"],
        )
    return len(seen) + len(marked["ids"])


def seed_guidance() -> int:
    col = collection("guidance")
    ids, docs, metas = [], [], []
    for sc, (name, level) in SC.items():
        ids.append(f"sc-{sc}")
        docs.append(
            f"WCAG 2.2 success criterion {sc} {name} (Level {level}). {GUIDANCE.get(sc, '')}"
        )
        metas.append({"sc": sc, "level": level, "source": "wcag22", "version": GUIDANCE_VERSION})
    for key, (sc, text) in GUIDANCE.get("patterns", {}).items():
        ids.append(f"pattern-{key}")
        docs.append(text)
        metas.append(
            {
                "sc": sc,
                "level": SC.get(sc, ("", ""))[1],
                "source": "wa-a11y-patterns",
                "version": GUIDANCE_VERSION,
            }
        )
    col.upsert(ids=ids, documents=docs, metadatas=metas)
    return len(ids)


def _hits(res) -> list[dict]:
    out = []
    for i, doc, meta, dist in zip(
        res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0], strict=True
    ):
        out.append({"id": i, "text": doc, "metadata": meta, "score": round(1 - dist, 3)})
    return out


def search(name: str, query: str, where: dict | None = None, k: int = 8) -> list[dict]:
    col = collection(name)
    n = col.count()
    if n == 0:
        return []
    return _hits(col.query(query_texts=[query], n_results=min(k, n), where=where or None))


def reindex(engine) -> tuple[int, int]:
    from sqlmodel import Session, select

    from app.store.models import ScanStatus

    client = _client(chroma_path())
    for name in ("findings", "guidance"):
        if name in {c.name for c in client.list_collections()}:
            client.delete_collection(name)
    total = 0
    with Session(engine) as s:
        scans = s.exec(select(Scan).where(Scan.status == ScanStatus.DONE).order_by(Scan.created_at))
        for scan in scans:
            findings = list(s.exec(select(Finding).where(Finding.scan_id == scan.id)))
            total += index_scan(scan, findings)
    return total, seed_guidance()
