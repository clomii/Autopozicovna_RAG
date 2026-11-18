"""Reproducible RAG evaluation: retrieval first, optional real Ollama generation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import re
from statistics import mean, median

from rag.pipeline import Pipeline
from rag.retrieval import fold

BASE = Path(__file__).resolve().parent


def key(source):
    return source["file"], source["page"] if source["kind"] == "pdf" else source["anchor"]


def rank_metrics(rows):
    positives = [r for r in rows if r["gold"]]
    if not positives:
        return {}
    h1, h5, coverage, recall, precision = [], [], [], [], []
    for row in positives:
        expected = set(map(tuple, row["gold"]))
        ranking = [tuple(x) for x in row["ranked"]]
        relevant = len(set(ranking[:5]) & expected)
        h1.append(bool(set(ranking[:1]) & expected))
        h5.append(bool(relevant))
        coverage.append(expected.issubset(ranking[:5]))
        recall.append(relevant / len(expected))
        precision.append(relevant / 5)
    return {"queries": len(positives), "hit_at_1": mean(h1), "hit_at_5": mean(h5),
            "all_gold_at_5": mean(coverage), "recall_at_5": mean(recall),
            "precision_at_5": mean(precision)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--generate", action="store_true", help="Spusti skutočné generovanie v Ollame.")
    p.add_argument("--lexical", action="store_true", help="Použi iba BM25.")
    p.add_argument("--id", action="append", help="Vyber otázku, napr. --id K01.")
    p.add_argument("--output", type=Path, help="Voliteľný výstup JSON.")
    args = p.parse_args()
    cases = json.loads((BASE / "evaluation" / "questions.json").read_text(encoding="utf-8"))
    if args.id:
        cases = [c for c in cases if c["id"] in args.id]
    if not cases:
        p.error("Nenašli sa vybrané testovacie otázky.")
    pipeline = Pipeline(BASE)
    index = pipeline.build(with_vectors=not args.lexical)
    status = pipeline.status(index)
    if args.generate and not status["generation_ready"]:
        p.error(f"Pre generovanie potrebuješ lokálny {status['chat_model']}.")
    print(f"{status['pdf_count']} PDF / {status['page_count']} strán / "
          f"{status['owl_count']} OWL / {status['chunk_count']} úryvkov", flush=True)

    modes = ["lexical"] + (["hybrid"] if index.dense and not args.lexical else [])
    retrieval, generation = {}, []
    for mode in modes:
        rows = []
        for case in cases:
            hits, actual, note = pipeline.retrieve(index, case["question"], mode)
            if mode == "hybrid" and actual != "hybrid":
                raise RuntimeError(note or "Počas testu nefungovalo hybridné vyhľadávanie.")
            rows.append({"id": case["id"], "gold": case["gold"],
                         "ranked": [h.chunk.group for h in hits],
                         "cosines": [round(h.cosine, 4) if h.cosine is not None else None for h in hits]})
        retrieval[mode] = {"metrics": rank_metrics(rows), "rows": rows}
        print(mode, retrieval[mode]["metrics"], flush=True)
    if args.generate:
        for case in cases:
            response = pipeline.ask(index, case["question"], modes[-1])
            expected = set(map(tuple, case["gold"]))
            cited = {key(s) for s in response["sources"] if s["cited"]}
            facts_ok = all(re.search(pattern, fold(response["answer"])) for pattern in case["match"])
            passed = (response["kind"] == "rag" and facts_ok and expected.issubset(cited)
                      if expected else response["kind"] == "insufficient")
            generation.append({
                **case, "kind": response["kind"], "answer": response["answer"],
                "cited": sorted(cited, key=str), "facts_ok": bool(facts_ok) if expected else None,
                "passed": passed, "ms": response["total_ms"],
                "retrieval_ms": response["retrieval_ms"], "warning": response["warning"],
            })
            print(case["id"], "OK" if passed else "CHECK", response["kind"],
                  f"{response['total_ms']/1000:.2f}s", response["answer"], flush=True)
    positives = [r for r in generation if r["gold"]]
    negatives = [r for r in generation if not r["gold"]]
    report = {
        "environment": {"platform": platform.system() + " " + platform.machine(),
                        "python": platform.python_version(),
                        "ollama": (pipeline.ollama.call("/api/version").get("version")
                                   if status["ollama_online"] else None)},
        "corpus": {k: status[k] for k in ("pdf_count", "page_count", "owl_count", "chunk_count", "owl_counts", "warnings")},
        "models": {"chat": status["chat_model"] if args.generate else None,
                   "embedding": status["embed_model"] if index.dense else None},
        "retrieval": retrieval, "generation": generation,
        "generation_summary": {
            "positive_passed": sum(r["passed"] for r in positives), "positive_total": len(positives),
            "negative_passed": sum(r["passed"] for r in negatives), "negative_total": len(negatives),
            "median_ms": round(median(r["ms"] for r in generation)) if generation else None,
        },
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["generation_summary"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
