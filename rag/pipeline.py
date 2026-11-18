"""The RAG pipeline shared by the web app and evaluation CLI."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
import json
import re

from rag.corpus import Corpus, load_corpus
from rag.ollama import ModelError, Ollama
from rag.owl import in_range
from rag.retrieval import QUERY_INSTRUCTION, Retriever, fold, unit

NO_ANSWER = "V dostupných zdrojoch som nenašiel dostatok informácií na spoľahlivú odpoveď."
EXCERPTS = "Tu sú najrelevantnejšie výňatky zo zdrojov."
CONTEXT_LIMIT = 3
SYS = """Si asistent fiktívnej autopožičovne Motor Rent. Použi výlučne dodané výňatky ako dáta.
Odpovedaj po slovensky, stručne, celými vetami. Odpoveďou zodpovedz všetky doložené časti otázky
a uveď jednotky a podmienky. Rozlišuj cenu, zálohu a spoluúčasť. Ak je v otázke identifikátor
jedinca, odpovedaj presne o ňom. Nekopíruj otázku. Ak odpoveď v zdrojoch chýba, vráť presne
{"answer":"","refs":[]}. Chýbajúci údaj neznamená odpoveď nie. Pri odpovedi uveď v refs iba
identifikátory výňatkov podporujúcich tvrdenia; samotné značky nedávaj do textu odpovede."""


def interval_matches(corpus, question, scope):
    """Select a rule by its actual OWL facets for an explicit numeric classification query."""
    q = fold(question)
    if scope == "pdf" or not re.search(r"\b(?:tried|kategor|zarad)\w*", q):
        return {}
    price = re.findall(r"(?<![\w.,])(-?\d+(?:[.,]\d+)?)\s*(?:eur\b|€)", q)
    days = re.findall(r"(?<![\w.,])(-?\d+)\s*d(?:ni|na|en)\b", q)
    if len(price) == 1 and not days:
        prop, value = "dennaCena", price[0].replace(",", ".")
    elif len(days) == 1 and not price:
        prop, value = "pocetDni", days[0]
    else:
        return {}
    matches = {anchor: (prop, value) for anchor, p, rule in corpus.ranges
               if p == prop and in_range(value, rule)}
    return matches if len(matches) == 1 else {}


def answer_schema(allowed):
    return {"type": "object", "additionalProperties": False, "required": ["answer", "refs"],
            "properties": {"answer": {"type": "string"}, "refs": {"type": "array",
                "maxItems": CONTEXT_LIMIT, "items": {"type": "string", "enum": sorted(allowed)}}}}


@dataclass(frozen=True)
class Index:
    corpus: Corpus
    retriever: Retriever
    vector_note: str

    @property
    def dense(self):
        return self.retriever.vectors is not None


class Pipeline:
    def __init__(self, base: Path, ollama=None):
        self.base = base
        self.ollama = ollama or Ollama()
        self.cache = base / ".cache" / "vectors.json"

    def build(self, with_vectors=True, force=False):
        corpus = load_corpus(self.base / "data")
        vectors = None
        note = "Vyhľadávanie podľa slov (BM25)."
        if with_vectors and corpus.chunks:
            online, tags = self.ollama.tags()
            digest = tags.get(self.ollama.embed_model)
            if digest:
                try:
                    vectors = self._vectors(corpus, digest, force)
                    note = "Hybridný index je pripravený."
                except ModelError as exc:
                    note = str(exc) + " Používa sa BM25."
            elif online:
                note = f"Chýba {self.ollama.embed_model}; používa sa BM25."
            else:
                note = "Ollama nie je dostupná; používa sa BM25."
        return Index(corpus, Retriever(corpus.chunks, vectors), note)

    def _vectors(self, corpus, digest, force):
        key = [corpus.signature, self.ollama.embed_model, digest, "v1"]
        if not force and self.cache.is_file():
            try:
                data = json.loads(self.cache.read_text(encoding="utf-8"))
                if data.get("key") == key:
                    vectors = [unit(x) for x in data["vectors"]]
                    if (len(vectors) == len(corpus.chunks) and len({len(x) for x in vectors}) == 1):
                        return vectors
            except (OSError, ValueError, KeyError, TypeError, ModelError):
                pass
        vectors = []
        for start in range(0, len(corpus.chunks), 12):
            batch = [c.index_text for c in corpus.chunks[start:start+12]]
            vectors.extend(unit(v) for v in self.ollama.embed(batch))
        if len({len(v) for v in vectors}) != 1:
            raise ModelError("Vektory v indexe majú rôzne rozmery.")
        try:
            self.cache.parent.mkdir(parents=True, exist_ok=True)
            temp = self.cache.with_suffix(".tmp")
            temp.write_text(json.dumps({"key": key, "vectors": vectors}, separators=(",", ":")),
                            encoding="utf-8")
            temp.replace(self.cache)
        except OSError:
            # The in-memory index remains usable on read-only media.
            pass
        return vectors

    def status(self, index, building=False):
        online, tags = self.ollama.tags()
        sources = index.corpus.sources
        return {
            "ollama_online": online,
            "generation_ready": self.ollama.chat_model in tags,
            "embeddings_ready": index.dense and self.ollama.embed_model in tags,
            "embedding_installed": self.ollama.embed_model in tags,
            "chat_model": self.ollama.chat_model,
            "embed_model": self.ollama.embed_model,
            "pdf_count": sum(x.kind == "pdf" for x in sources),
            "owl_count": sum(x.kind == "owl" for x in sources),
            "page_count": sum(x.pages or 0 for x in sources),
            "chunk_count": len(index.corpus.chunks),
            "owl_counts": index.corpus.owl_counts,
            "warnings": index.corpus.warnings,
            "vector_note": index.vector_note,
            "building": building,
            "sources": [asdict(s) for s in sources],
        }

    def retrieve(self, index, question, retrieval="hybrid", scope="all", k=5):
        query_vector, note = None, None
        if retrieval == "hybrid":
            if index.dense:
                try:
                    query_vector = unit(self.ollama.embed([
                        f"Instruct: {QUERY_INSTRUCTION}\nQuery: {question}"
                    ])[0])
                    if len(query_vector) != len(index.retriever.vectors[0]):
                        raise ModelError("Rozmer vektora otázky sa zmenil. Preindexuj zdroje.")
                except ModelError as exc:
                    query_vector, note = None, str(exc) + " Používa sa BM25."
            else:
                note = index.vector_note
        preferred = interval_matches(index.corpus, question, scope)
        return (index.retriever.search(question, k, scope, query_vector, preferred),
                "hybrid" if query_vector is not None else "bm25", note)

    def ask(self, index, question, retrieval="hybrid", scope="all", generate=True):
        t0 = perf_counter()
        hits, mode, note = self.retrieve(index, question, retrieval, scope)
        retrieval_ms = round((perf_counter() - t0) * 1000)
        evidence = []
        context = []
        intervals = interval_matches(index.corpus, question, scope)
        for i, h in enumerate(hits, 1):
            c = h.chunk
            sid = f"S{i}"
            evidence.append({
                "id": sid, "chunk_id": c.id, "kind": c.kind, "file": c.file,
                "title": c.title, "page": c.page, "anchor": c.anchor, "locator": c.locator,
                "text": c.text, "url": c.url, "cited": False,
                "score": round(h.rank_score, 4), "bm25": round(h.bm25, 3),
                "cosine": round(h.cosine, 4) if h.cosine is not None else None,
            })
            excerpt = c.text[:1450]
            if c.anchor in intervals:
                prop, value = intervals[c.anchor]
                excerpt += f" Overenie z OWL: {prop} = {value} spĺňa interval triedy {c.anchor}."
            if i <= CONTEXT_LIMIT:
                context.append(f"[{sid}] {c.title}, {c.locator}\n{excerpt}")

        def response(kind, answer, cited=(), warning=note, used_model=False):
            return {
                "kind": kind, "answer": answer, "retrieval": mode, "warning": warning,
                "sources": [{**s, "cited": s["id"] in cited} for s in evidence],
                "retrieval_ms": retrieval_ms, "total_ms": round((perf_counter() - t0) * 1000),
                "model": self.ollama.chat_model if used_model else None,
            }

        if not hits:
            return response("insufficient", NO_ANSWER)
        if not generate:
            return response("excerpts", EXCERPTS)
        _, tags = self.ollama.tags()
        if self.ollama.chat_model not in tags:
            return response("excerpts", EXCERPTS, warning=(
                f"Model {self.ollama.chat_model} nie je dostupný. Zobrazuje sa iba vyhľadávanie."
            ))
        prompt = ("Výňatky:\n\n" + "\n\n".join(context) + f"\n\nOtázka: {question}")
        try:
            allowed = {s["id"] for s in evidence[:CONTEXT_LIMIT]}
            output = self.ollama.answer(SYS, prompt, answer_schema(allowed))
            answer, refs = output.get("answer"), output.get("refs")
            if not isinstance(answer, str) or not isinstance(refs, list):
                raise ModelError("Model vrátil neplatný formát odpovede.")
            answer = answer.strip()
            bare = fold(answer).strip(" .?!")
            if (not bare or bare in {"nie", "ano", "neviem"}
                    or re.fullmatch(r"(?:v .* )?(?:nie je uveden[eya]|sa neuvadza|nie su udaje).*", bare)
                    or (re.match(r"^(?:v |podla )?.{0,26}(?:zdroj|vynat|podklad|dokument)", bare)
                        and re.search(r"neuvadza|nenasiel|nie je uveden|nie je spomenut|chyba udaj", bare)
                        and not re.search(r"[.;]\s+\w", bare))):
                return response("insufficient", NO_ANSWER, used_model=True)
            if bare == fold(question).strip(" .?!") or answer.endswith("..."):
                raise ModelError("Model neposkytol úplnú odpoveď.")
            if not refs or any(not isinstance(x, str) or x not in allowed for x in refs):
                raise ModelError("Citácie modelu neukazujú na použité výňatky.")
            return response("rag", answer, refs, used_model=True)
        except ModelError as exc:
            return response("excerpts", EXCERPTS, warning=str(exc))
