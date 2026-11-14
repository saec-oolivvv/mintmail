"""main() ne doit pas masquer un nom global par un import local (UnboundLocalError au lancement, 1.33.0)."""
import ast
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_no_shadowing_imports_in_functions():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mintmail", "entry.py")
    tree = ast.parse(open(path, encoding="utf-8").read())
    top = set()
    for n in tree.body:
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            top |= {(a.asname or a.name).split(".")[0] for a in n.names}
    bad = []
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        used = {x.id for x in ast.walk(fn) if isinstance(x, ast.Name)}
        for n in ast.walk(fn):
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                for a in n.names:
                    nm = (a.asname or a.name).split(".")[0]
                    if nm in top and nm in used:
                        bad.append("%s: import local de %s masque le global" % (fn.name, nm))
    assert not bad, bad


if __name__ == "__main__":
    test_no_shadowing_imports_in_functions()
    print("ok")
