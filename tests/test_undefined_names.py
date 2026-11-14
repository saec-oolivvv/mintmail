"""Garde-fou sans PySide6 : aucun nom utilisé sans être défini ni importé (un import oublié ne se voit sinon qu'avec le vrai Qt)."""
import ast
import builtins
import glob
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _undefined(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    known = set(dir(builtins)) | {"__file__", "__name__"}
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            known.update((a.asname or a.name).split(".")[0] for a in n.names)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            known.add(n.name)
        elif isinstance(n, ast.arg):
            known.add(n.arg)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            known.add(n.id)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            known.add(n.name)
    return sorted({"%s:%d %s" % (os.path.basename(path), n.lineno, n.id) for n in ast.walk(tree)
                   if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in known})


def test_no_undefined_names_in_the_package():
    bad = []
    for path in glob.glob(os.path.join(ROOT, "mintmail", "**", "*.py"), recursive=True):
        bad += _undefined(path)
    assert not bad, bad
