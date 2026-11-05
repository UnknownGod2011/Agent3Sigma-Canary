#!/usr/bin/env python3
"""Unit tests for screenshot-grounded desktop text localization."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / "desktop"))
import desktop_ocr  # noqa: E402

TSV = """level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext
5\t1\t1\t1\t1\t1\t68\t156\t67\t12\t96.6\tbaseline
5\t1\t1\t1\t1\t2\t141\t157\t35\t11\t96.6\tnote
5\t1\t1\t1\t2\t1\t345\t363\t29\t10\t96.8\tSave
"""


class DesktopOCRTests(unittest.TestCase):
    def test_phrase_box_uses_union_center(self) -> None:
        words = desktop_ocr.parse_tesseract_tsv(TSV)
        self.assertEqual(desktop_ocr.find_text_box(words, "baseline note"), (122, 162))
        self.assertEqual(desktop_ocr.find_text_box(words, "Save"), (359, 368))

    def test_strips_screenshot_border_bracket_and_keeps_same_row_order(self) -> None:
        words = [
            desktop_ocr.OCRWord("[AgentCanary", 96.6, 67, 146, 109, 15, (1, 1, 1, 1)),
            desktop_ocr.OCRWord("desktop", 96.6, 183, 146, 66, 15, (1, 1, 1, 1)),
            desktop_ocr.OCRWord("baseline", 96.6, 257, 146, 68, 12, (1, 1, 1, 1)),
            desktop_ocr.OCRWord("complete", 96.6, 332, 146, 76, 15, (1, 1, 1, 1)),
        ]
        self.assertEqual(
            desktop_ocr.find_text_box(words, "AgentCanary desktop baseline complete"),
            (237, 153),
        )

    def test_matches_visually_aligned_tokens_across_tesseract_blocks(self) -> None:
        words = desktop_ocr.parse_tesseract_tsv(TSV)
        split = [
            words[0],
            desktop_ocr.OCRWord("note", 96.6, 141, 157, 35, 11, (1, 9, 4, 7)),
        ]
        self.assertEqual(desktop_ocr.find_text_box(split, "baseline note"), (122, 162))

    def test_does_not_join_words_across_visual_rows(self) -> None:
        words = desktop_ocr.parse_tesseract_tsv(TSV)
        split = [
            words[0],
            desktop_ocr.OCRWord("note", 96.6, 141, 200, 35, 11, (1, 1, 1, 1)),
        ]
        with self.assertRaises(LookupError):
            desktop_ocr.find_text_box(split, "baseline note")

    def test_ambiguous_phrase_fails_closed(self) -> None:
        duplicate = TSV.replace(
            "5\t1\t1\t1\t2\t1\t345",
            "5\t1\t1\t1\t1\t3\t220",
        ).replace("29\t10\t96.8\tSave", "29\t10\t96.8\tnote")
        words = desktop_ocr.parse_tesseract_tsv(duplicate)
        with self.assertRaisesRegex(LookupError, "found 2"):
            desktop_ocr.find_text_box(words, "note")

    def test_low_confidence_token_is_ignored(self) -> None:
        low = TSV.replace("96.6\tnote", "20.0\tnote")
        words = desktop_ocr.parse_tesseract_tsv(low)
        with self.assertRaises(LookupError):
            desktop_ocr.find_text_box(words, "baseline note")

    def test_tesseract_invocation_uses_sparse_text_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "screenshot.png"
            path.write_bytes(b"fixture")
            with patch.object(
                desktop_ocr.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0, stdout=TSV, stderr=""),
            ) as run:
                self.assertEqual(desktop_ocr.locate_text(path, "baseline note"), (122, 162))
                self.assertEqual(
                    run.call_args.args[0],
                    ["tesseract", str(path), "stdout", "--psm", "11", "tsv"],
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
