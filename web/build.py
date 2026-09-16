"""Copy the Qt-free half of `app/` into `web/py/` for the browser build.

The web preview runs the REAL detection code under Pyodide (CPython compiled to
WebAssembly): `MockProvider` generates the markets, `ArbitrageEngine` derives the
opportunities, `calculations` does the maths. Only the UI is rewritten in
HTML/JS, because PySide6 cannot run in a browser.

This script never modifies `app/` - it only reads from it. `web/py/` is generated
output, committed so GitHub Pages can serve it. Re-run after changing any module
listed in `tests/test_no_qt_imports.py`:

    python web/build.py

Refuses to run if that test fails, since a Qt import anywhere in the copied set
would break the browser build in a confusing way.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
OUT = Path(__file__).resolve().parent / "py"

sys.path.insert(0, str(ROOT))
from tests.test_no_qt_imports import PURE_PACKAGES, PURE_SERVICES  # noqa: E402


def sources() -> list[Path]:
    """Every file to copy, as paths relative to the repo root."""
    paths = [APP / "__init__.py"]
    for package in PURE_PACKAGES:
        paths.append(APP / package / "__init__.py")
        paths.extend(sorted(p for p in (APP / package).glob("*.py")
                            if p.name != "__init__.py"))
    paths.append(APP / "services" / "__init__.py")
    paths.extend(APP / "services" / f"{name}.py" for name in PURE_SERVICES)
    return [p for p in paths if p.exists()]


def check_boundary() -> bool:
    """Run the Qt-boundary test; a leak makes the browser build fail obscurely."""
    result = subprocess.run([sys.executable, str(ROOT / "tests" / "test_no_qt_imports.py")],
                            capture_output=True, text=True)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode == 0


def main() -> int:
    if not check_boundary():
        print("\nAborted - fix the Qt import above before rebuilding the web bundle.")
        return 1

    if OUT.exists():
        shutil.rmtree(OUT)

    files = sources()
    manifest = []
    for path in files:
        relative = path.relative_to(ROOT)          # e.g. app/utils/calculations.py
        target = OUT / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        manifest.append(relative.as_posix())

    # Hand-written glue that belongs to the web build, not copied from app/.
    glue = Path(__file__).resolve().parent / "webapp.py"
    if glue.exists():
        shutil.copy2(glue, OUT / "webapp.py")
        manifest.append("webapp.py")

    (OUT / "manifest.json").write_text(
        json.dumps({"files": manifest}, indent=2) + "\n", encoding="utf-8")

    total = sum((OUT / f).stat().st_size for f in manifest)
    print(f"\nCopied {len(manifest)} modules -> web/py/  ({total / 1024:.0f} KB)")
    for name in manifest:
        print(f"  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
