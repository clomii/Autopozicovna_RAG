"""PDF text, page-preserving chunks, and OWL passages."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote
import hashlib
import re
import xml.etree.ElementTree as ET

from pypdf import PdfReader
from rag.owl import OWL_FILE, extract_owl

WINDOW, OVERLAP = 135, 25


@dataclass(frozen=True)
class Chunk:
    id: str
    kind: str
    file: str
    title: str
    text: str
    page: int | None = None
    anchor: str | None = None

    @property
    def group(self):
        return (self.file, self.page if self.kind == "pdf" else self.anchor)

    @property
    def locator(self):
        return f"str. {self.page}" if self.kind == "pdf" else self.anchor

    @property
    def url(self):
        page = f"#page={self.page}" if self.kind == "pdf" else ""
        return f"/sources/{quote(self.file)}{page}"

    @property
    def index_text(self):
        return f"{self.title}\n{self.text}"


@dataclass(frozen=True)
class Source:
    file: str
    title: str
    kind: str
    pages: int | None
    chunks: int
    url: str


@dataclass(frozen=True)
class Corpus:
    chunks: tuple[Chunk, ...]
    sources: tuple[Source, ...]
    owl_counts: dict[str, int]
    warnings: tuple[str, ...]
    signature: str
    ranges: tuple


def read_pdf(path, number):
    if path.stat().st_size > 50 * 1024 * 1024:
        raise ValueError("PDF presahuje limit 50 MB.")
    reader = PdfReader(path)
    if reader.is_encrypted:
        raise ValueError("PDF je chránené heslom.")
    title = str((reader.metadata or {}).get("/Title") or path.stem).strip()[:160]
    chunks, warnings = [], []
    for page_no, page in enumerate(reader.pages, start=1):
        try:
            lines = (page.extract_text() or "").splitlines()
        except Exception as exc:
            warnings.append(f"{path.name}, str. {page_no}: chyba extrakcie ({type(exc).__name__}).")
            continue
        words = " ".join(
            x.strip() for x in lines if not re.match(
                r"^(MOTOR RENT \||ŠKOLSKÁ SIMULÁCIA \|)", x.strip())
        ).split()
        if not words:
            warnings.append(f"{path.name}, str. {page_no}: chýba textová vrstva; OCR sa nepoužíva.")
            continue
        for seq, start in enumerate(range(0, len(words), WINDOW - OVERLAP), 1):
            part = words[start:start + WINDOW]
            chunks.append(Chunk(f"P{number:02d}-{page_no:02d}-{seq:02d}", "pdf", path.name,
                                title, " ".join(part), page_no))
            if start + WINDOW >= len(words):
                break
    return chunks, Source(path.name, title, "pdf", len(reader.pages), len(chunks),
                          f"/sources/{quote(path.name)}"), warnings


def load_corpus(data: Path) -> Corpus:
    chunks, sources, warnings = [], [], []
    for i, path in enumerate(sorted((data / "pdfs").glob("*.pdf")), 1):
        try:
            result, source, warn = read_pdf(path, i)
            chunks.extend(result)
            sources.append(source)
            warnings.extend(warn)
        except Exception as exc:
            warnings.append(f"{path.name}: súbor sa nepodarilo načítať ({exc}).")
    counts, ranges = {}, ()
    owl_path = data / "ontology" / OWL_FILE
    try:
        records, counts, version, ranges = extract_owl(owl_path)
        chunks.extend(Chunk(f"O{i:03d}", "owl", owl_path.name, title, text, anchor=anchor)
                      for i, (anchor, title, text) in enumerate(records, 1))
        sources.append(Source(owl_path.name, f"Ontológia autopožičovne · {version}", "owl",
                              None, len(records), f"/sources/{quote(owl_path.name)}"))
    except (OSError, ET.ParseError, ValueError) as exc:
        warnings.append(f"{owl_path.name}: {exc}")
    digest = hashlib.sha256()
    for c in chunks:
        digest.update(f"{c.id}\0{c.file}\0{c.locator}\0{c.index_text}\0".encode("utf-8"))
    return Corpus(tuple(chunks), tuple(sources), counts, tuple(warnings), digest.hexdigest(), ranges)
