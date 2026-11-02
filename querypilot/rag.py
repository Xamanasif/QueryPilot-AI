"""Governed retrieval: BM25 over tenant-scoped chunks of approved document versions."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import asdict, dataclass

from .db import Database

STOPWORDS = frozenset(
    "a an and are as at be by for from has have in is it its of on or that the this to was were will with "
    "any all may shall not if than then thereafter after upon".split()
)
_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS]


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    doc_id: str
    version: int
    status: str
    title: str
    text: str
    score: float
    matched_terms: int

    def to_dict(self) -> dict:
        return asdict(self)


class Retriever:
    """BM25 retrieval. By default only chunks of currently approved versions are searchable."""

    def __init__(self, db: Database, k1: float = 1.5, b: float = 0.75):
        self.db = db
        self.k1 = k1
        self.b = b

    def _load(self, tenant_id: str, statuses: tuple[str, ...]) -> list[dict]:
        marks = ",".join("?" * len(statuses))
        with self.db.connect() as conn:
            rows = conn.execute(
                f"""SELECT c.chunk_id, c.doc_id, c.version, v.status, d.title, c.text
                    FROM chunks c
                    JOIN document_versions v ON v.doc_id = c.doc_id AND v.version = c.version
                    JOIN documents d ON d.doc_id = c.doc_id
                    WHERE c.tenant_id = ? AND d.tenant_id = ? AND v.status IN ({marks})
                    ORDER BY c.chunk_id""",
                (tenant_id, tenant_id, *statuses),
            ).fetchall()
        return [dict(r) for r in rows]

    def search(self, tenant_id: str, query: str, k: int = 4,
               statuses: tuple[str, ...] = ("approved",)) -> list[Hit]:
        terms = list(dict.fromkeys(tokenize(query)))
        docs = self._load(tenant_id, statuses)
        if not terms or not docs:
            return []
        token_lists = [tokenize(d["text"]) for d in docs]
        avg_len = sum(map(len, token_lists)) / len(token_lists)
        df = Counter(t for tokens in token_lists for t in set(tokens))
        n = len(docs)

        hits = []
        for doc, tokens in zip(docs, token_lists):
            tf = Counter(tokens)
            score, matched = 0.0, 0
            for term in terms:
                if term not in tf:
                    continue
                matched += 1
                idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
                freq = tf[term]
                score += idf * freq * (self.k1 + 1) / (
                    freq + self.k1 * (1 - self.b + self.b * len(tokens) / avg_len))
            if matched:
                hits.append(Hit(doc["chunk_id"], doc["doc_id"], doc["version"], doc["status"],
                                doc["title"], doc["text"], round(score, 4), matched))
        hits.sort(key=lambda h: (-h.score, h.chunk_id))
        return hits[:k]
