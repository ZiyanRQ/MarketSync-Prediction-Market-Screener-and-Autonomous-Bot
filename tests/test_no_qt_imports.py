"""Guards the Qt boundary that the layering depends on.

`models/`, `providers/`, `utils/` and the four pure services must not import Qt.
That boundary is what keeps the arbitrage maths unit-testable, lets a live
provider slot in without touching the UI, and allows `web/` to run this exact
code in the browser under Pyodide - where Qt cannot load at all.

Adding a PySide6 import to any module listed here silently breaks the web build,
so it is checked rather than left to discipline. Imports are read from the AST,
not matched as text: a docstring mentioning PySide6 is fine, an import is not.

    python tests/test_no_qt_imports.py     # standalone
    pytest tests/                          # or under pytest
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"

#: Packages that must stay free of Qt, in full.
PURE_PACKAGES = ["models", "providers", "utils"]

#: Individual services that must stay free of Qt. The rest (market_data_service,
#: risk_engine, auto_trader) are Qt-bound by design - they own timers and signals.
PURE_SERVICES = [
    "arbitrage_engine",
    "simulation_engine",
    "cache_service",
    "api_usage_tracker",
]

FORBIDDEN = ("PySide6", "PyQt5", "PyQt6", "pyqtgraph")


def pure_modules() -> list[Path]:
    """Every .py file that must remain importable without Qt."""
    paths: list[Path] = []
    for package in PURE_PACKAGES:
        paths.extend(sorted((APP / package).glob("*.py")))
    paths.extend(APP / "services" / f"{name}.py" for name in PURE_SERVICES)
    return paths


def imported_names(path: Path) -> set[str]:
    """Top-level module names imported by `path`, read from its AST."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def offenders() -> list[tuple[Path, str]]:
    """(module, forbidden import) pairs that break the boundary."""
    found = []
    for path in pure_modules():
        for name in sorted(imported_names(path)):
            if name in FORBIDDEN:
                found.append((path, name))
    return found


def test_pure_modules_exist():
    """The list above should not silently rot if a file is renamed."""
    missing = [p for p in pure_modules() if not p.exists()]
    assert not missing, f"listed but missing: {[str(p) for p in missing]}"


def test_pure_modules_import_no_qt():
    found = offenders()
    assert not found, "Qt imported in modules that must stay pure:\n" + "\n".join(
        f"  {p.relative_to(ROOT)} imports {name}" for p, name in found)


def main() -> int:
    missing = [p for p in pure_modules() if not p.exists()]
    for path in missing:
        print(f"MISSING  {path.relative_to(ROOT)}")
    found = offenders()
    for path, name in found:
        print(f"QT LEAK  {path.relative_to(ROOT)} imports {name}")
    if missing or found:
        print(f"\nFAILED - {len(missing)} missing, {len(found)} Qt leak(s).")
        return 1
    print(f"OK - {len(pure_modules())} modules checked, none import Qt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
