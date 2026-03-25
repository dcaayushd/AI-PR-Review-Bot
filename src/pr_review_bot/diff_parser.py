from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field

from .domain import DiffChunk
from .utils import language_for_path, normalize_path


DIFF_HEADER_RE = re.compile(r"^diff --git a/(.+) b/(.+)$")
HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass(slots=True)
class DiffLine:
    kind: str
    text: str
    old_line: int | None = None
    new_line: int | None = None


@dataclass(slots=True)
class DiffHunk:
    header: str
    lines: list[DiffLine] = field(default_factory=list)
    added_lines: set[int] = field(default_factory=set)


@dataclass(slots=True)
class FilePatch:
    path: str
    old_path: str
    metadata: list[str] = field(default_factory=list)
    hunks: list[DiffHunk] = field(default_factory=list)
    is_binary: bool = False
    is_deleted: bool = False
    language: str = "text"

    @property
    def added_lines(self) -> set[int]:
        lines: set[int] = set()
        for hunk in self.hunks:
            lines.update(hunk.added_lines)
        return lines


def parse_unified_diff(diff_text: str) -> list[FilePatch]:
    patches: list[FilePatch] = []
    current_patch: FilePatch | None = None
    current_hunk: DiffHunk | None = None
    old_line = 0
    new_line = 0

    for raw_line in diff_text.splitlines():
        diff_match = DIFF_HEADER_RE.match(raw_line)
        if diff_match:
            current_patch = FilePatch(
                path=normalize_path(diff_match.group(2)),
                old_path=normalize_path(diff_match.group(1)),
            )
            current_patch.language = language_for_path(current_patch.path)
            patches.append(current_patch)
            current_hunk = None
            old_line = 0
            new_line = 0
            continue

        if current_patch is None:
            continue

        if raw_line.startswith("Binary files ") or raw_line == "GIT binary patch":
            current_patch.is_binary = True
            current_patch.metadata.append(raw_line)
            continue

        if raw_line.startswith("deleted file mode "):
            current_patch.is_deleted = True
            current_patch.metadata.append(raw_line)
            continue

        if raw_line.startswith("rename from "):
            current_patch.old_path = normalize_path(raw_line.removeprefix("rename from "))
            current_patch.metadata.append(raw_line)
            continue

        if raw_line.startswith("rename to "):
            current_patch.path = normalize_path(raw_line.removeprefix("rename to "))
            current_patch.language = language_for_path(current_patch.path)
            current_patch.metadata.append(raw_line)
            continue

        hunk_match = HUNK_HEADER_RE.match(raw_line)
        if hunk_match:
            old_line = int(hunk_match.group(1))
            new_line = int(hunk_match.group(3))
            current_hunk = DiffHunk(header=raw_line)
            current_patch.hunks.append(current_hunk)
            continue

        if current_hunk is None:
            current_patch.metadata.append(raw_line)
            continue

        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            current_hunk.lines.append(DiffLine(kind="add", text=raw_line, new_line=new_line))
            current_hunk.added_lines.add(new_line)
            new_line += 1
            continue

        if raw_line.startswith("-") and not raw_line.startswith("---"):
            current_hunk.lines.append(DiffLine(kind="delete", text=raw_line, old_line=old_line))
            old_line += 1
            continue

        if raw_line.startswith(" "):
            current_hunk.lines.append(
                DiffLine(kind="context", text=raw_line, old_line=old_line, new_line=new_line)
            )
            old_line += 1
            new_line += 1
            continue

        current_hunk.lines.append(DiffLine(kind="meta", text=raw_line))

    return patches


def should_ignore(path: str, ignore_patterns: list[str]) -> bool:
    normalized = normalize_path(path)
    for pattern in ignore_patterns:
        if fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(normalized.lstrip("./"), pattern):
            return True
    return False


def filter_reviewable_patches(
    patches: list[FilePatch],
    ignore_patterns: list[str],
) -> tuple[list[FilePatch], list[str]]:
    reviewable: list[FilePatch] = []
    skipped: list[str] = []
    for patch in patches:
        if should_ignore(patch.path, ignore_patterns):
            skipped.append(f"{patch.path} (ignored)")
            continue
        if patch.is_binary:
            skipped.append(f"{patch.path} (binary)")
            continue
        reviewable.append(patch)
    return reviewable, skipped


def _render_hunk(path: str, language: str, metadata: list[str], hunk: DiffHunk) -> str:
    lines = [f"FILE: {path}", f"LANGUAGE: {language}"]
    if metadata:
        lines.append("FILE_METADATA:")
        lines.extend(metadata)
    lines.append("ANNOTATED_DIFF:")
    lines.append(hunk.header)
    for line in hunk.lines:
        if line.kind == "add":
            lines.append(f"R{line.new_line:>6} | {line.text}")
        elif line.kind == "delete":
            lines.append(f"L{line.old_line:>6} | {line.text}")
        elif line.kind == "context":
            lines.append(f"R{line.new_line:>6} | {line.text}")
        else:
            lines.append(f"       | {line.text}")
    return "\n".join(lines)


def build_review_chunks(
    patches: list[FilePatch],
    *,
    max_chunk_chars: int,
    max_chunks: int,
) -> tuple[list[DiffChunk], int]:
    sections: list[tuple[str, str]] = []
    for patch in patches:
        metadata = list(dict.fromkeys(patch.metadata))
        if not patch.hunks and metadata:
            section_text = "\n".join(
                [
                    f"FILE: {patch.path}",
                    f"LANGUAGE: {patch.language}",
                    "FILE_METADATA:",
                    *metadata,
                ]
            )
            sections.append((patch.path, section_text))
            continue
        for hunk in patch.hunks:
            sections.append((patch.path, _render_hunk(patch.path, patch.language, metadata, hunk)))

    chunks: list[DiffChunk] = []
    current_sections: list[str] = []
    current_files: list[str] = []
    current_size = 0
    omitted_sections = 0

    for path, section in sections:
        section_size = len(section) + 2
        if current_sections and current_size + section_size > max_chunk_chars:
            chunk_id = len(chunks) + 1
            chunks.append(DiffChunk(chunk_id=chunk_id, text="\n\n".join(current_sections), files=current_files))
            current_sections = []
            current_files = []
            current_size = 0
        if len(chunks) >= max_chunks:
            omitted_sections += 1
            continue
        current_sections.append(section)
        if path not in current_files:
            current_files.append(path)
        current_size += section_size

    if current_sections and len(chunks) < max_chunks:
        chunk_id = len(chunks) + 1
        chunks.append(DiffChunk(chunk_id=chunk_id, text="\n\n".join(current_sections), files=current_files))

    return chunks, omitted_sections


def build_changed_line_map(patches: list[FilePatch]) -> dict[str, set[int]]:
    mapping: dict[str, set[int]] = {}
    for patch in patches:
        mapping.setdefault(patch.path, set()).update(patch.added_lines)
    return mapping

