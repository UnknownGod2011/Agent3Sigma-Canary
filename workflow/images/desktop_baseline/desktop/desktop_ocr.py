#!/usr/bin/env python3
"""Screenshot-grounded text localization for the AgentCanary desktop fixture."""
from __future__ import annotations

import csv
import io
import subprocess
from collections import defaultdict
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
    return value.strip(".,:;!?").casefold()


def parse_tesseract_tsv(tsv: str, *, min_confidence: float = 50.0) -> list[OCRWord]:
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
    """Return the center of one unique phrase match on one OCR line.

    Ambiguous or absent phrases fail closed rather than selecting an arbitrary
    coordinate. Coordinates are checked against the fixture's virtual display.
    """
    target = tuple(_normalize_token(token) for token in phrase.split() if token)
    if not target:
        raise ValueError("phrase must contain at least one token")

    by_line: dict[tuple[int, int, int, int], list[OCRWord]] = defaultdict(list)
    for word in words:
        by_line[word.line_key].append(word)

    matches: list[tuple[int, int]] = []
    for line_words in by_line.values():
        for index in range(len(line_words) - len(target) + 1):
            sequence = line_words[index:index + len(target)]
            if tuple(_normalize_token(word.text) for word in sequence) != target:
                continue
            left = min(word.left for word in sequence)
            top = min(word.top for word in sequence)
            right = max(word.left + word.width for word in sequence)
            bottom = max(word.top + word.height for word in sequence)
            x = (left + right) // 2
            y = (top + bottom) // 2
            if not (0 <= x < screen_width and 0 <= y < screen_height):
                continue
            matches.append((x, y))

    if len(matches) != 1:
        raise LookupError(
            f"expected exactly one OCR match for {phrase!r}, found {len(matches)}"
        )
    return matches[0]


def locate_text(
    image_path: str | Path,
    phrase: str,
    *,
    min_confidence: float = 50.0,
    timeout_seconds: int = 10,
) -> tuple[int, int]:
    """Run Tesseract on a captured desktop screenshot and locate one phrase."""
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"desktop screenshot does not exist: {path}")
    result = subprocess.run(
        ["tesseract", str(path), "stdout", "--psm", "6", "tsv"],
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
