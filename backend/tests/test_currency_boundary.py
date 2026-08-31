"""Enforces, mechanically, that currency conversion stays a presentation-
layer concern: no computation/persistence package may import
`app.services.currency`. This is the automated version of the rule stated
in that module's own docstring — a comment can rot, this test can't.
"""

import ast
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[1] / "app"

FORBIDDEN_MODULE = "app.services.currency"

# Every package whose job is to compute or persist a number — forecasting,
# pricing, optimization, the agent/tool layer, ORM models, and every
# service module except currency.py itself (which is the one legitimate
# definition site).
PACKAGES_THAT_MUST_NOT_IMPORT_CURRENCY = [
    "forecasting",
    "pricing",
    "optimization",
    "agents",
    "tools",
    "models",
]


def _imports_forbidden_module(py_file: Path) -> bool:
    tree = ast.parse(py_file.read_text(), filename=str(py_file))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == FORBIDDEN_MODULE or alias.name.startswith(FORBIDDEN_MODULE + ".") for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.module:
            full_module = node.module
            if full_module == FORBIDDEN_MODULE or full_module.startswith(FORBIDDEN_MODULE + "."):
                return True
    return False


def _python_files_in(package_dir: Path) -> list[Path]:
    return sorted(package_dir.rglob("*.py"))


@pytest.mark.parametrize("package", PACKAGES_THAT_MUST_NOT_IMPORT_CURRENCY)
def test_package_never_imports_currency_module(package: str) -> None:
    package_dir = APP_ROOT / package
    assert package_dir.is_dir(), f"expected app/{package}/ to exist"

    offenders = [f for f in _python_files_in(package_dir) if _imports_forbidden_module(f)]
    assert offenders == [], (
        f"app/{package}/ must never import {FORBIDDEN_MODULE} — currency conversion is a "
        f"presentation-layer concern only. Offending files: {[str(f) for f in offenders]}"
    )


def test_services_package_never_imports_currency_except_currency_itself() -> None:
    services_dir = APP_ROOT / "services"
    offenders = [
        f
        for f in _python_files_in(services_dir)
        if f.name != "currency.py" and _imports_forbidden_module(f)
    ]
    assert offenders == [], (
        f"app/services/ (besides currency.py itself) must never import {FORBIDDEN_MODULE}. "
        f"Offending files: {[str(f) for f in offenders]}"
    )


def test_currency_module_itself_does_not_import_computation_packages() -> None:
    # Guards the other direction too: currency.py should stay a leaf module
    # (only app.config), not reach into anything it's meant to stay decoupled from.
    currency_file = APP_ROOT / "services" / "currency.py"
    tree = ast.parse(currency_file.read_text(), filename=str(currency_file))
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
        elif isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)

    forbidden_prefixes = ("app.forecasting", "app.pricing", "app.optimization", "app.agents", "app.tools")
    offending = [m for m in imported_modules if m.startswith(forbidden_prefixes)]
    assert offending == [], f"app/services/currency.py unexpectedly imports: {offending}"
