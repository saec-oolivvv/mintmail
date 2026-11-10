#!/usr/bin/env python3
"""Cohérence du numéro de version : VERSION == mintmail/VERSION == première section de CHANGELOG.md, au format X.Y.Z. Code de sortie 1 sinon."""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(p):
    with open(os.path.join(ROOT, p), encoding="utf-8") as f:
        return f.read()


def problems():
    out = []
    a, b = read("VERSION").strip(), read("mintmail/VERSION").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", a):
        out.append("VERSION doit être au format X.Y.Z (lu : %r)" % a)
    if a != b:
        out.append("VERSION (%s) et mintmail/VERSION (%s) diffèrent" % (a, b))
    sections = re.split(r"^## ", read("CHANGELOG.md"), flags=re.M)[1:]
    head, _, body = (sections[0] if sections else "").partition("\n")
    if head.strip() != a:
        out.append("la première section de CHANGELOG.md (%s) doit être %s" % (head.strip() or "absente", a))
    elif not re.search(r"^- .+", body, re.M) or "(à compléter)" in body:
        out.append("la section %s de CHANGELOG.md est vide ou contient « (à compléter) »" % a)
    return out


if __name__ == "__main__":
    errs = problems()
    for e in errs:
        print("✗", e)
    if not errs:
        print("version %s : cohérente" % read("VERSION").strip())
    sys.exit(1 if errs else 0)
