from __future__ import annotations

from typing import Any


def extract_added_lines(patch: str) -> list[tuple[int | None, str]]:
    result: list[tuple[int | None, str]] = []
    new_line: int | None = None
    for line in patch.splitlines():
        if line.startswith("@@"):
            marker = line.split("+", 1)[1].split(" ", 1)[0]
            try:
                new_line = int(marker.split(",", 1)[0])
            except ValueError:
                new_line = None
            continue
        if line.startswith("+") and not line.startswith("+++"):
            result.append((new_line, line[1:]))
            if new_line is not None:
                new_line += 1
        elif not line.startswith("-") and new_line is not None:
            new_line += 1
    return result


def diff_hunks_by_file(files: list[Any]) -> dict[str, list[tuple[int, int]]]:
    result: dict[str, list[tuple[int, int]]] = {}
    for changed in files:
        hunks: list[tuple[int, int]] = []
        for line in changed.patch.splitlines():
            if not line.startswith("@@") or "+" not in line:
                continue
            marker = line.split("+", 1)[1].split(" ", 1)[0]
            try:
                start_text, length_text = (marker.split(",", 1) + ["1"])[:2]
                start = int(start_text)
                length = int(length_text)
            except ValueError:
                continue
            hunks.append((start, max(start, start + max(1, length) - 1)))
        if hunks:
            result[changed.filename] = hunks
    return result


def source_snippet_loader_for_files(files: list[Any]):
    lines_by_file: dict[str, dict[int, str]] = {}
    for changed in files:
        line_map: dict[int, str] = {}
        for line_no, text in extract_added_lines(changed.patch):
            if line_no is not None:
                line_map[int(line_no)] = text
        lines_by_file[changed.filename] = line_map

    def load(file_path: str, line_no: int, window: int = 5) -> str:
        line_map = lines_by_file.get(file_path) or {}
        if not line_map:
            return ""
        start = max(1, int(line_no) - int(window))
        end = int(line_no) + int(window)
        return "\n".join(line_map[index] for index in range(start, end + 1) if index in line_map)

    return load


def build_diff_slices(files: list[Any], max_added_lines_per_slice: int = 800) -> list[dict[str, Any]]:
    slices: list[dict[str, Any]] = []
    for changed in files:
        added = extract_added_lines(changed.patch)
        if len(added) <= max_added_lines_per_slice:
            slices.append(
                {
                    "file_path": changed.filename,
                    "slice_index": 0,
                    "line_start": added[0][0] if added else None,
                    "line_end": added[-1][0] if added else None,
                    "added_lines": len(added),
                    "reason": "single_slice",
                }
            )
            continue
        for index, start in enumerate(range(0, len(added), max_added_lines_per_slice)):
            chunk = added[start : start + max_added_lines_per_slice]
            slices.append(
                {
                    "file_path": changed.filename,
                    "slice_index": index,
                    "line_start": chunk[0][0] if chunk else None,
                    "line_end": chunk[-1][0] if chunk else None,
                    "added_lines": len(chunk),
                    "reason": "large_diff_split",
                }
            )
    return slices
