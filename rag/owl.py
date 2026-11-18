"""Project OWL/XML extraction; a deliberately small fragment, not an OWL DL reasoner."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import xml.etree.ElementTree as ET

OWL_FILE = "autopozicovna_web_v1_4.owl"
OWL_NS = "http://www.w3.org/2002/07/owl#"
FACETS = {"minInclusive": "≥", "minExclusive": ">", "maxInclusive": "≤", "maxExclusive": "<"}


def tag(node):
    return node.tag.rsplit("}", 1)[-1]


def ident(node):
    value = node.get("IRI") or node.get("abbreviatedIRI") or node.text or ""
    return value.rsplit("#", 1)[-1] if "#" in value else value


def facets(node):
    return [(n.get("facet", "").rsplit("#", 1)[-1], n[0].text)
            for n in node if tag(n) == "FacetRestriction" and len(n) == 1]


def describe(node):
    kind = tag(node)
    if kind == "Class":
        return ident(node)
    if kind in ("ObjectIntersectionOf", "ObjectUnionOf"):
        return (" a " if kind == "ObjectIntersectionOf" else " alebo ").join(map(describe, node))
    if kind in ("ObjectSomeValuesFrom", "ObjectAllValuesFrom") and len(node) == 2:
        q = "aspoň jedna hodnota" if kind == "ObjectSomeValuesFrom" else "všetky hodnoty"
        return f"{q} {ident(node[0])} patria do triedy {describe(node[1])}"
    if kind == "DataAllValuesFrom" and len(node) == 2:
        interval = " a ".join(f"{FACETS.get(op, op)} {n}" for op, n in facets(node[1]))
        return f"všetky hodnoty {ident(node[0])}: {interval or ident(node[1])}"
    if kind == "DataHasValue" and len(node) == 2:
        return f"{ident(node[0])} = {node[1].text}"
    if kind == "DataMinCardinality" and len(node):
        return f"najmenej {node.get('cardinality')} hodnota pre {ident(node[0])}"
    return ""


def in_range(value, restriction):
    if tag(restriction) != "DatatypeRestriction":
        return False
    try:
        n = Decimal(value)
        tests = {"minInclusive": n.__ge__, "minExclusive": n.__gt__,
                 "maxInclusive": n.__le__, "maxExclusive": n.__lt__}
        fs = facets(restriction)
        return n.is_finite() and bool(fs) and all(
            op in tests and tests[op](Decimal(v)) for op, v in fs)
    except (InvalidOperation, TypeError):
        return False


def extract_owl(path: Path):
    if path.stat().st_size > 5 * 1024 * 1024:
        raise ValueError("OWL/XML presahuje limit 5 MB.")
    raw = path.read_bytes()
    if re.search(rb"<!\s*(?:DOCTYPE|ENTITY)", raw, re.I):
        raise ValueError("OWL/XML obsahuje nepodporovanú deklaráciu XML.")
    root = ET.fromstring(raw)
    if root.tag != f"{{{OWL_NS}}}Ontology":
        raise ValueError("Očakáva sa pôvodná ontológia vo formáte OWL/XML.")
    labels, comments, inverse = {}, {}, {}
    entities, parents, direct = (defaultdict(set) for _ in range(3))
    class_notes, prop_notes = defaultdict(list), defaultdict(list)
    objects = defaultdict(lambda: defaultdict(set))
    literals = defaultdict(lambda: defaultdict(set))
    functional_data, rules = set(), []

    for ax in root:
        k = tag(ax)
        p = [n for n in ax if tag(n) != "Annotation"]
        ids = list(map(ident, p))
        if k == "Declaration" and len(p) == 1:
            entities[tag(p[0])].add(ids[0])
        elif k == "AnnotationAssertion" and len(p) == 3 and tag(p[2]) == "Literal":
            if ids[0] in ("rdfs:label", "label"):
                labels[ids[1]] = (p[2].text or "").strip()
            elif ids[0] in ("rdfs:comment", "comment"):
                comments[ids[1]] = (p[2].text or "").strip()
        elif k == "SubClassOf" and len(p) == 2 and tag(p[0]) == "Class":
            if tag(p[1]) == "Class":
                parents[ids[0]].add(ids[1])
            elif desc := describe(p[1]):
                class_notes[ids[0]].append(f"Obmedzenie: {desc}.")
        elif k == "EquivalentClasses" and len(p) == 2:
            named = next((n for n in p if tag(n) == "Class"), None)
            if named is not None:
                rhs = next(n for n in p if n is not named)
                rules.append((ident(named), rhs))
                if desc := describe(rhs):
                    class_notes[ident(named)].append(f"Ekvivalentná definícia: {desc}.")
        elif k == "DisjointClasses" and all(tag(n) == "Class" for n in p):
            for i in ids:
                class_notes[i].append(f"Disjunktné triedy: {', '.join(x for x in ids if x != i)}.")
        elif k == "ClassAssertion" and len(p) == 2 and tag(p[0]) == "Class":
            direct[ids[1]].add(ids[0])
        elif k == "ObjectPropertyAssertion" and len(p) == 3:
            objects[ids[1]][ids[0]].add(ids[2])
        elif k == "DataPropertyAssertion" and len(p) == 3 and tag(p[2]) == "Literal":
            literals[ids[1]][ids[0]].add(p[2].text or "")
        elif k == "InverseObjectProperties" and len(p) == 2:
            a, b = ids
            inverse[a], inverse[b] = b, a
            prop_notes[a].append(f"Inverzná vlastnosť: {b}.")
            prop_notes[b].append(f"Inverzná vlastnosť: {a}.")
        elif k in ("ObjectPropertyDomain", "DataPropertyDomain", "ObjectPropertyRange", "DataPropertyRange") and len(p) == 2:
            prop_notes[ids[0]].append(f"{'Doména' if k.endswith('Domain') else 'Rozsah'}: {ids[1]}.")
        elif k in ("FunctionalObjectProperty", "FunctionalDataProperty") and len(p) == 1:
            prop_notes[ids[0]].append("Funkčná vlastnosť: najviac jedna hodnota na jedinca.")
            if k == "FunctionalDataProperty":
                functional_data.add(ids[0])

    def named_ancestors(classes):
        out, todo = set(classes), list(classes)
        while todo:
            for p in parents[todo.pop()] - out:
                out.add(p)
                todo.append(p)
        return out

    types = {i: named_ancestors(direct[i]) for i in entities["NamedIndividual"]}

    def satisfies(i, node):
        k = tag(node)
        if k == "Class":
            return ident(node) in types[i]
        if k == "ObjectIntersectionOf":
            return bool(len(node)) and all(satisfies(i, n) for n in node)
        if k == "ObjectSomeValuesFrom" and len(node) == 2 and tag(node[1]) == "Class":
            return any(ident(node[1]) in types.get(o, ()) for o in objects[i][ident(node[0])])
        if k == "DataHasValue" and len(node) == 2:
            return (node[1].text or "") in literals[i][ident(node[0])]
        if k == "DataAllValuesFrom" and len(node) == 2:
            prop = ident(node[0])
            v = literals[i][prop]
            # An asserted value of a functional data property exhausts its distinct values.
            return prop in functional_data and len(v) == 1 and in_range(next(iter(v)), node[1])
        return False

    changed = True
    while changed:
        changed = False
        for i in sorted(types):
            for new, rule in rules:
                if new not in types[i] and satisfies(i, rule):
                    types[i].update(named_ancestors({new}))
                    changed = True

    reverse = defaultdict(list)
    for i, props in objects.items():
        for prop, values in props.items():
            for v in values:
                if prop in inverse:
                    reverse[v].append((inverse[prop], i, prop))

    def named(i):
        return f"{i} ({labels[i]})" if i in labels and labels[i] != i else i

    counts = dict(zip(("classes", "objects", "data", "individuals"),
                      (len(entities[k]) for k in ("Class", "ObjectProperty", "DataProperty", "NamedIndividual"))))
    passages = []

    def add(anchor, title, *lines):
        passages.append((anchor, title, " ".join(x for x in lines if x).strip()))

    version = root.get("versionIRI", "").rsplit("/", 1)[-1]
    add("prehľad", "Ontológia autopožičovne",
        f"Ontológia vo formáte OWL/XML, verzia {version}.",
        f"{counts['classes']} tried, {counts['objects']} objektových vlastností, "
        f"{counts['data']} dátové vlastnosti a {counts['individuals']} jedincov.",
        "Hlavné triedy: Auto, Prenajom, Zakaznik, Pobocka. Záznamy a ceny sú fiktívne.")
    for i in sorted(types):
        lines = [f"Jedinec {named(i)}.", comments.get(i, "")]
        if direct[i]:
            lines.append("Explicitná trieda: " + ", ".join(map(named, sorted(direct[i]))) + ".")
        if derived := types[i] - direct[i]:
            lines.append("Odvodené triedy: " + ", ".join(map(named, sorted(derived))) + ".")
        for p, values in sorted(literals[i].items()):
            for v in sorted(values):
                value = (f"{v.replace('.', ',')} EUR/deň" if p == "dennaCena" else
                         f"{v} dní (počet dní: {v})" if p == "pocetDni" else v)
                lines.append(f"{named(p)}: {value}.")
        for p, values in sorted(objects[i].items()):
            for v in sorted(values):
                lines.append(f"{named(p)}: {named(v)}.")
        for p, v, original in sorted(reverse[i]):
            lines.append(f"Inverzia {original}, {p}: {named(v)}.")
        add(i, named(i), *lines)
    for i in sorted(entities["Class"]):
        add(i, named(i), f"Trieda {named(i)}.", comments.get(i, ""),
            f"Nadtriedy: {', '.join(sorted(parents[i]))}." if parents[i] else "", *class_notes[i])
    for kind, label in (("ObjectProperty", "Objektová vlastnosť"), ("DataProperty", "Dátová vlastnosť")):
        for i in sorted(entities[kind]):
            add(i, named(i), f"{label} {named(i)}.", comments.get(i, ""), *prop_notes[i])
    ranges = []
    for target, rule in rules:
        if tag(rule) != "ObjectIntersectionOf":
            continue
        for node in rule:
            if tag(node) == "DataAllValuesFrom" and len(node) == 2:
                prop = ident(node[0])
                if prop in functional_data and tag(node[1]) == "DatatypeRestriction":
                    ranges.append((target, prop, node[1]))
    return passages, counts, version, tuple(ranges)
