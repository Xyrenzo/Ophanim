"""Static guarantees about the code base (AST scans of src/ophanim).

* The independent auditor imports only the standard library and itself.
* Agent-side code (policies, tools) cannot import evaluator or generator code.
* No dynamic code execution anywhere (eval/exec/compile/__import__).
* No use of the `random` module (cross-version reproducibility).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "ophanim"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _files(sub: str) -> list[Path]:
    return sorted((SRC / sub).rglob("*.py")) if (SRC / sub).is_dir() else [SRC / sub]


def test_audit_package_is_independent_of_the_generator():
    stdlib = set(sys.stdlib_module_names) | {"__future__"}
    for path in _files("audit"):
        for name in _imports(path):
            top = name.split(".")[0]
            assert name.startswith("ophanim.audit") or top in stdlib, f"{path.name} imports {name}"


def test_agent_side_code_cannot_import_evaluator_or_generator():
    for sub in ("policies", "env/tools.py", "env/calculator.py", "env/task.py"):
        for path in _files(sub):
            for name in _imports(path):
                assert not name.startswith(("ophanim.evaluator", "ophanim.generator")), f"{path} imports {name}"


def test_no_dynamic_code_execution():
    banned = {"eval", "exec", "compile", "__import__"}
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in banned, f"{path}: call to {node.func.id}"


def test_random_module_is_never_used():
    for path in SRC.rglob("*.py"):
        for name in _imports(path):
            assert name.split(".")[0] != "random", f"{path} imports random"
