#!/usr/bin/env python3
"""Screenshot-grounded text localization for the AgentCanary desktop fixture."""
from __future__ import annotations

import csv
import io
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OCRWord:
    text: str
    confidence: float
    left: int
    top: int
    width: int
    height: int
    line_key: tuple[int, int, int, int]


def _normalize_token(value: str) -> str:
    return value.strip(".,:;!?[](){}<>").casefold()


def parse_tesseract_tsv(tsv: str, *, min_confidence: float = 35.0) -> list[OCRWord]:
    """Parse word-level TSV rows, discarding empty, malformed, and weak tokens."""
    words: list[OCRWord] = []
    reader = csv.DictReader(io.StringIO(tsv), delimiter="\t")
    required = {
        "page_num", "block_num", "par_num", "line_num", "left", "top",
        "width", "height", "conf", "text",
    }
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError("Tesseract TSV is missing required columns")

    for row in reader:
        text = (row.get("text") or "").strip()
        if not text:
            continue
        try:
            confidence = float(row["conf"])
            left = int(row["left"])
            top = int(row["top"])
            width = int(row["width"])
            height = int(row["height"])
            line_key = tuple(
                int(row[field])
                for field in ("page_num", "block_num", "par_num", "line_num")
            )
        except (KeyError, TypeError, ValueError):
            continue
        if confidence < min_confidence or width <= 0 or height <= 0:
            continue
        words.append(OCRWord(text, confidence, left, top, width, height, line_key))
    return words


def find_text_box(
    words: list[OCRWord], phrase: str, *, screen_width: int = 800, screen_height: int = 600
) -> tuple[int, int]:
    """Return the center of one unique, visually aligned phrase match.

    Tesseract can split adjacent words into different block/line identifiers,
    and word heights can vary enough to reorder same-row tokens by vertical
    center. Cluster by page and vertical overlap first, then match left-to-right
    within each visual row. Ambiguous or absent text fails closed.
    """
    target = tuple(_normalize_token(token) for token in phrase.split() if token)
    if not target:
        raise ValueError("phrase must contain at least one token")

    rows: list[list[OCRWord]] = []
    for word in sorted(
        words,
        key=lambda item: (item.line_key[0], item.top + item.height / 2, item.left),
    ):
        candidates: list[tuple[int, list[OCRWord]]] = []
        for row in rows:
            if row[0].line_key[0] != word.line_key[0]:
                continue
            row_top = max(item.top for item in row)
            row_bottom = min(item.top + item.height for item in row)
            overlap = min(row_bottom, word.top + word.height) - max(row_top, word.top)
            min_height = min([item.height for item in row] + [word.height])
            if overlap >= 0.4 * min_height:
                candidates.append((overlap, row))
        if candidates:
            max(candidates, key=lambda item: item[0])[1].append(word)
        else:
            rows.append([word])

    matches: list[tuple[int, int]] = []
    ordered_for_diagnostics: list[OCRWord] = []
    for row in rows:
        ordered = sorted(row, key=lambda word: word.left)
        ordered_for_diagnostics.extend(ordered)
        for index in range(len(ordered) - len(target) + 1):
            sequence = ordered[index:index + len(target)]
            if tuple(_normalize_token(word.text) for word in sequence) != target:
                continue
            top = max(word.top for word in sequence)
            bottom = min(word.top + word.height for word in sequence)
            min_height = min(word.height for word in sequence)
            if bottom - top < 0.4 * min_height:
                continue
            gaps = [
                right.left - (left.left + left.width)
                for left, right in zip(sequence, sequence[1:])
            ]
            if any(
                gap > 3 * max(left.height, right.height)
                for gap, left, right in zip(gaps, sequence, sequence[1:])
            ):
                continue
            if any(right.left < left.left for left, right in zip(sequence, sequence[1:])):
                continue

            left = min(word.left for word in sequence)
            top = min(word.top for word in sequence)
            right = max(word.left + word.width for word in sequence)
            bottom = max(word.top + word.height for word in sequence)
            x = (left + right) // 2
            y = (top + bottom) // 2
            if 0 <= x < screen_width and 0 <= y < screen_height:
                matches.append((x, y))

    if len(matches) != 1:
        visible = [
            f"{word.text!r}@{word.left},{word.top},{word.width},{word.height}"
            f"/{word.confidence:.0f}"
            for word in ordered_for_diagnostics[:40]
        ]
        raise LookupError(
            f"expected exactly one OCR match for {phrase!r}, found {len(matches)}; "
            f"recognized words: {visible}"
        )
    return matches[0]


def locate_text(
    image_path: str | Path,
    phrase: str,
    *,
    min_confidence: float = 35.0,
    timeout_seconds: int = 10,
) -> tuple[int, int]:
    """Run Tesseract's sparse-text mode on a captured desktop screenshot."""
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"desktop screenshot does not exist: {path}")
    result = subprocess.run(
        ["tesseract", str(path), "stdout", "--psm", "11", "tsv"],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_seconds,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Tesseract failed for desktop screenshot: {detail}")
    return find_text_box(
        parse_tesseract_tsv(result.stdout, min_confidence=min_confidence),
        phrase,
    )
