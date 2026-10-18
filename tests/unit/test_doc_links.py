"""Every relative link in the repository's markdown must resolve.

A package rename once left README linking to files that no longer existed,
and nothing caught it. This lists the git-tracked docs and checks each relative
inline or reference-style link against the filesystem.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Generated run reports under results/ are tracked but are not docs we maintain.
SKIP_TOP_LEVEL = {"results"}
# Only used when git is unavailable: never walk into dependencies or caches.
FALLBACK_SKIP_DIRS = {".git", ".venv", "node_modules", "results", "artifacts", "dist"}

_FENCE = re.compile(r"^(```|~~~).*?^\1", re.MULTILINE | re.DOTALL)
_CODE_SPAN = re.compile(r"`[^`\n]*`")
_INLINE = re.compile(r"\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_REFERENCE = re.compile(r"^\s{0,3}\[(?!\^)[^\]]+\]:\s*<?(\S+?)>?(?:\s+.*)?$", re.MULTILINE)


def _markdown_files() -> list[Path]:
    try:
        listed = subprocess.run(
            ["git", "ls-files", "-z", "--", "*.md"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        ).stdout.decode("utf-8")
        paths = [REPO_ROOT / name for name in listed.split("\0") if name]
    except (OSError, subprocess.CalledProcessError):
        paths = [
            path
            for path in REPO_ROOT.rglob("*.md")
            if not set(path.relative_to(REPO_ROOT).parts[:-1]) & FALLBACK_SKIP_DIRS
        ]
    return sorted(
        path
        for path in paths
        if path.relative_to(REPO_ROOT).parts[0] not in SKIP_TOP_LEVEL and path.is_file()
    )


def _relative_targets(text: str) -> list[str]:
    text = _CODE_SPAN.sub("", _FENCE.sub("", text))
    targets = _INLINE.findall(text) + _REFERENCE.findall(text)
    relative = []
    for target in targets:
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith(("#", "//")):
            continue  # URL, mailto:, or an in-page anchor
        path = target.split("#", 1)[0].split("?", 1)[0]
        if path:
            relative.append(path)
    return relative


def test_there_are_markdown_files_to_check() -> None:
    assert (REPO_ROOT / "README.md") in _markdown_files()


@pytest.mark.parametrize("doc", _markdown_files(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_relative_links_resolve(doc: Path) -> None:
    broken = [
        target
        for target in _relative_targets(doc.read_text(encoding="utf-8"))
        # A leading "/" is repository-root-relative, as GitHub renders it.
        if not (
            (REPO_ROOT / target.lstrip("/")) if target.startswith("/") else (doc.parent / target)
        ).exists()
    ]
    assert not broken, f"{doc.relative_to(REPO_ROOT)} links to missing files: {broken}"
