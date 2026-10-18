"""Assert a built wheel ships only the rag_crucible package and one console script.

The package was renamed because a published distribution (crucible-security)
ships a top-level ``crucible/`` and a ``crucible`` entry point, and installing
both overwrote this project's files. Nothing else stops a top-level
``crucible``, ``api`` or any other package from coming back, so CI builds the
wheel and runs this.

Usage: python scripts/check_wheel.py dist/rag_crucible-*.whl
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

EXPECTED_PACKAGE = "rag_crucible"
EXPECTED_SCRIPTS = {"rag-crucible": "rag_crucible.cli:app"}


def _console_scripts(entry_points: str) -> dict[str, str]:
    scripts: dict[str, str] = {}
    section = ""
    for raw in entry_points.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
        elif section == "console_scripts" and "=" in line:
            name, target = line.split("=", 1)
            scripts[name.strip()] = target.strip()
    return scripts


def check(wheel: Path) -> list[str]:
    errors: list[str] = []
    with zipfile.ZipFile(wheel) as archive:
        tops = {name.split("/", 1)[0] for name in archive.namelist()}
        dist_info = sorted(top for top in tops if top.endswith(".dist-info"))
        shipped = sorted(tops - set(dist_info))
        if shipped != [EXPECTED_PACKAGE]:
            errors.append(f"top-level entries are {shipped}, expected only {EXPECTED_PACKAGE!r}")
        if len(dist_info) != 1:
            errors.append(f"expected one .dist-info directory, found {dist_info}")
            return errors
        try:
            entry_points = archive.read(f"{dist_info[0]}/entry_points.txt").decode("utf-8")
        except KeyError:
            errors.append("wheel has no entry_points.txt")
            return errors
    scripts = _console_scripts(entry_points)
    if scripts != EXPECTED_SCRIPTS:
        errors.append(f"console scripts are {scripts}, expected {EXPECTED_SCRIPTS}")
    return errors


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: check_wheel.py WHEEL [WHEEL ...]", file=sys.stderr)
        return 2
    failed = False
    for arg in argv:
        errors = check(Path(arg))
        for error in errors:
            print(f"{arg}: {error}", file=sys.stderr)
        if errors:
            failed = True
        else:
            print(f"{arg}: ok (only {EXPECTED_PACKAGE}/, one entry point)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
