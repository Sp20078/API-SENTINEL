"""Isolation wall: app.trust_router must not import the scanner module.

The Trust Router is an additive module (API Sentinel Mesh). Its isolation
contract — stdlib + httpx + pydantic + fastapi only, never app.scanner,
app.store, app.models, or app.target_guard — is enforced here by walking
every module in the package with ast and checking absolute and relative
imports.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[1] / "app" / "trust_router"

FORBIDDEN_PREFIXES = (
    "app.scanner",
    "app.store",
    "app.models",
    "app.target_guard",
    "app.openapi_client",
    "app.main",
)
ALLOWED_THIRD_PARTY = {"httpx", "pydantic", "fastapi", "anyio", "typing_extensions"}
STDLIB_ROOTS = set(sys.stdlib_module_names)


def _iter_imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            level = node.level
            if level > 0:
                # relative import: resolve against the package layout
                if level >= 2:
                    yield f"(relative beyond package: {module})", node.lineno
                elif module:
                    yield f"app.trust_router.{module}", node.lineno
                else:
                    yield "app.trust_router", node.lineno
            else:
                yield module, node.lineno


def test_trust_router_imports_stay_inside_the_wall() -> None:
    violations: list[str] = []
    for py_file in sorted(PACKAGE_DIR.rglob("*.py")):
        for module, lineno in _iter_imports(py_file):
            root = module.split(".")[0]
            if module.startswith(FORBIDDEN_PREFIXES):
                violations.append(f"{py_file.name}:{lineno} imports {module}")
                continue
            if root in STDLIB_ROOTS:
                continue  # stdlib is always allowed
            if root in ALLOWED_THIRD_PARTY:
                continue  # declared third-party dependencies
            if module.startswith("app.trust_router"):
                continue  # intra-package imports
            violations.append(f"{py_file.name}:{lineno} imports {module}")
    assert violations == [], "isolation contract breached:\n" + "\n".join(violations)


def test_no_lazy_forbidden_imports_inside_trust_router() -> None:
    """Function-level imports are covered by the same AST walk; this second
    test guards the textual pattern (e.g. importlib usage) explicitly."""
    suspicious: list[str] = []
    for py_file in sorted(PACKAGE_DIR.rglob("*.py")):
        source = py_file.read_text(encoding="utf-8")
        if "importlib" in source or "__import__" in source:
            suspicious.append(py_file.name)
        for forbidden in FORBIDDEN_PREFIXES:
            if forbidden in source.replace('"""', "") and forbidden not in (
                "app.trust_router",
            ):
                # a docstring mention is fine; an import is not — the AST test
                # catches real imports, this catches sneaky string-built ones
                if f'"{forbidden}"' in source or f"'{forbidden}'" in source:
                    suspicious.append(f"{py_file.name} references {forbidden}")
    assert suspicious == [], "suspicious dynamic imports:\n" + "\n".join(suspicious)
