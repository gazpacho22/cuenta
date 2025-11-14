from __future__ import annotations

import textwrap
from pathlib import Path

_CACHE_ROOT = Path(".pytest_cache") / "generated_features"


def _find_repo_root(start: Path) -> Path:
    """Walk upward from start until a .git directory is found."""

    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return start


def materialize_inline_feature(module_file: str, feature_filename: str, feature_text: str) -> Path:
    """Persist inline Gherkin to a cache file and return its path."""

    module_path = Path(module_file).resolve()
    repo_root = _find_repo_root(module_path)
    rel_parent = module_path.parent.relative_to(repo_root)
    cache_dir = repo_root / _CACHE_ROOT / rel_parent
    cache_dir.mkdir(parents=True, exist_ok=True)

    feature_path = cache_dir / feature_filename
    normalized_text = textwrap.dedent(feature_text).strip() + "\n"
    if not feature_path.exists() or feature_path.read_text(encoding="utf-8") != normalized_text:
        feature_path.write_text(normalized_text, encoding="utf-8")

    return feature_path
