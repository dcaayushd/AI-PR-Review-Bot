from __future__ import annotations

import glob
from pathlib import Path

from .config import RepositoryContextSettings
from .domain import RepositorySnippet
from .utils import dedupe_preserve_order, normalize_path, truncate_text


def load_repository_snippets(repo_root: Path, settings: RepositoryContextSettings) -> list[RepositorySnippet]:
    if not settings.enabled:
        return []

    candidates: list[str] = []
    for pattern in settings.include:
        matches = glob.glob(str(repo_root / pattern), recursive=True)
        if matches:
            candidates.extend(matches)
        else:
            direct = repo_root / pattern
            if direct.exists():
                candidates.append(str(direct))

    snippets: list[RepositorySnippet] = []
    for candidate in dedupe_preserve_order(candidates):
        if len(snippets) >= settings.max_files:
            break
        path = Path(candidate)
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        relative_path = normalize_path(str(path.relative_to(repo_root)))
        snippets.append(
            RepositorySnippet(
                path=relative_path,
                content=truncate_text(content, settings.max_chars_per_file),
            )
        )
    return snippets

