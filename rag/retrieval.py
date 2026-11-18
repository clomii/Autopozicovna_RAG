"""Sparse BM25, exact cosine search, and weighted reciprocal rank fusion."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import isfinite, log1p, sqrt
import re
import unicodedata

from rag.ollama import ModelError

TOKEN = re.compile(r"[a-z]+[0-9]*|[0-9]+")
IDENTIFIER = re.compile(r"[a-z0-9_]+")
STOP = set("""
a aj ale aby ako ake aky aka akom akej akeho akych akej akym akej akymi aky
alebo ani ano bez bol bola bolo byt budem bude ci co cez da dame do este
hodina ho i ich iba iba je jeho jej jemu jej kde ked kedy komu ktore
ktory ktora ktorej ktoreho ktorym ktorych kolko kolky kolka len ma mam
mame mate medzi mi mohol moze mozno mozeme musi na nad nam nas nasa nase
nech nie no o od ono po pod podla potom pre preco pri prosim sa si som
ste su svoj ta tak take taky tiez tie to tom toho tej teda ten tato tam
tu tvoj tvoja u uz v vam vas vase vo vy z za zo ze
""".split())
QUERY_INSTRUCTION = "Given a car rental question, retrieve passages that contain information needed to answer it."
SEMANTIC_MIN = 0.50
RRF_K = 20


def fold(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold())
                   if not unicodedata.combining(c))


def terms(text):
    # Split camel-case identifiers; prefixes are a cheap aid for Slovak inflection.
    text = re.sub(r"(?<=[a-zá-ž0-9])(?=[A-Z])", " ", text)
    result = []
    for term in TOKEN.findall(fold(text)):
        if term in STOP or len(term) < 2 and not term.isdigit():
            continue
        result.append(term)
        if len(term) >= 5 and term.isalpha():
            result.append("~" + term[:5])
    return result


def unit(vector):
    try:
        if not isinstance(vector, list) or not vector or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v) for v in vector
        ):
            raise ValueError
        norm = sqrt(sum(v * v for v in vector))
        if not norm or not isfinite(norm):
            raise ValueError
        return [v / norm for v in vector]
    except (TypeError, ValueError, OverflowError) as exc:
        raise ModelError("Ollama vrátila neplatný vektor.") from exc


@dataclass(frozen=True)
class Hit:
    chunk: object
    rank_score: float
    bm25: float
    cosine: float | None


class Retriever:
    def __init__(self, chunks, vectors=None):
        self.chunks = chunks
        self.vectors = vectors
        self.terms = [Counter(terms(c.index_text)) for c in chunks]
        self.lengths = [sum(x.values()) for x in self.terms]
        self.avg = (sum(self.lengths) / max(1, len(chunks))) or 1
        df = Counter(word for doc in self.terms for word in doc)
        self.idf = {w: log1p((len(chunks) - n + 0.5) / (n + 0.5)) for w, n in df.items()}

    def search(self, question, k=5, scope="all", query_vector=None, preferred=()):
        q = set(terms(question))
        candidates = [i for i, c in enumerate(self.chunks) if scope == "all" or c.kind == scope]
        ids = set(IDENTIFIER.findall(fold(question)))
        scores, semantic, exact = {}, {}, set()
        for i in candidates:
            c, tf = self.chunks[i], self.terms[i]
            length = 1.2 * (0.25 + 0.75 * self.lengths[i] / self.avg)
            scores[i] = sum(self.idf[w] * (tf[w] * 2.2) / (tf[w] + length)
                            for w in sorted(q & tf.keys()))
            if c.anchor and ("_" in c.anchor or re.search(r"[a-z][A-Z]", c.anchor)) and fold(c.anchor) in ids:
                exact.add(i)
            if query_vector is not None and self.vectors is not None:
                semantic[i] = sum(a * b for a, b in zip(query_vector, self.vectors[i]))
        sparse = sorted((i for i in candidates if scores[i] > 0.0), key=lambda i: (-scores[i], i))
        dense = sorted((i for i in candidates if semantic.get(i, -1) >= SEMANTIC_MIN),
                       key=lambda i: (-semantic[i], i))
        ranks = {}
        for ranking, weight in ((sparse, 1.0), (dense, 1.0)):
            for j, i in enumerate(ranking, 1):
                ranks[i] = ranks.get(i, 0.0) + weight / (RRF_K + j)
        for i in exact:
            ranks[i] = ranks.get(i, 0.0) + 0.12
        for i in candidates:
            if self.chunks[i].anchor in preferred:
                ranks[i] = ranks.get(i, 0.0) + 0.20
        unique = set()
        hits = []
        for i in sorted(ranks, key=lambda i: (-ranks[i], -scores[i], i)):
            if self.chunks[i].group in unique:
                continue
            unique.add(self.chunks[i].group)
            hits.append(Hit(self.chunks[i], ranks[i], scores[i], semantic.get(i)))
            if len(hits) >= k:
                break
        return hits
