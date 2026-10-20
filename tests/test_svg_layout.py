#!/usr/bin/env python3
"""SVG layout tests: labels must never collide with the bar track.

Run:  python3 -m unittest discover -s tests -v
"""
import contextlib
import importlib.util
import io
import os
import re
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "generate-lang-stats.py")


def load_module():
    spec = importlib.util.spec_from_file_location("lang_stats_svg", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SvgLayoutTest(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

    def test_long_label_gets_a_wider_column(self):
        labels = ["Python", "Jupyter Notebook", "JavaScript"]
        card_w, label_w, bar_x, bar_w = self.mod.svg_layout(labels)
        longest = self.mod.text_width("Jupyter Notebook", self.mod.LABEL_FONT)
        self.assertGreaterEqual(label_w, longest)
        self.assertGreaterEqual(bar_x, self.mod.PADDING_X + label_w)
        self.assertGreaterEqual(bar_w, self.mod.MIN_BAR_WIDTH)
        # label column + bar + value column + both paddings == card width
        self.assertEqual(
            self.mod.PADDING_X + label_w + self.mod.LABEL_GAP + bar_w
            + self.mod.RIGHT_RESERVE + self.mod.PADDING_X,
            card_w)

    def test_short_labels_keep_the_default_width(self):
        card_w, label_w, _, _ = self.mod.svg_layout(["Go", "C", "Rust"])
        self.assertEqual(card_w, self.mod.MIN_CARD_WIDTH)
        self.assertEqual(label_w, self.mod.LABEL_MIN)

    def test_overlong_label_is_ellipsised_within_the_cap(self):
        raw = "Visual Basic .NET Framework Extended Edition"
        label = self.mod.fit_label(raw)
        self.assertLessEqual(self.mod.text_width(label, self.mod.LABEL_FONT),
                             self.mod.LABEL_MAX)
        self.assertTrue(label.endswith(self.mod.ELLIPSIS))
        self.assertTrue(raw.startswith(label[:-1].rstrip()))

    def test_value_column_never_sits_on_the_track(self):
        card_w, _, bar_x, bar_w = self.mod.svg_layout(["Jupyter Notebook"])
        track_end = bar_x + bar_w
        value_w = self.mod.text_width("100.0%  999.9 MB", self.mod.VALUE_FONT)
        self.assertLessEqual(value_w, self.mod.RIGHT_RESERVE)
        self.assertLessEqual(track_end, card_w - self.mod.PADDING_X - value_w + 1)

    def test_generated_svg_rows_do_not_overlap(self):
        languages = [("Python", 185_600_000), ("Jupyter Notebook", 12_880_000),
                     ("Visual Basic .NET Framework Extended Edition", 1_000)]
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "card.svg")
            with contextlib.redirect_stderr(io.StringIO()):
                self.mod.generate_svg(languages, "u", "merko", out, top_n=3)
            with open(out, encoding="utf-8") as f:
                svg = f.read()

        card_w = int(re.search(r'<svg width="(\d+)"', svg).group(1))
        entries = re.findall(r'<text x="(\d+)" y="(\d+)" [^>]*>([^<]*)</text>', svg)
        label_texts = [t for x, y, t in entries
                       if int(x) == self.mod.PADDING_X
                       and int(y) >= self.mod.HEADER_HEIGHT]
        rects = [(int(x), int(w)) for x, w in re.findall(
            r'<rect x="(\d+)" y="\d+" width="(\d+)" height="10"', svg)]
        tracks = [x for x, w in rects if w >= self.mod.MIN_BAR_WIDTH]

        self.assertEqual(len(label_texts), 3)
        self.assertTrue(tracks, "expected a bar track per row")
        leftmost_track = min(tracks)
        for label in label_texts:
            self.assertLessEqual(
                self.mod.PADDING_X + self.mod.text_width(label, self.mod.LABEL_FONT),
                leftmost_track,
                f"label {label!r} would run into the bar track")
        for x, w in rects:
            self.assertLessEqual(x + w, card_w - self.mod.PADDING_X,
                                 "a bar must stay inside the card")

    def test_escaped_label_is_still_escaped(self):
        languages = [("C++", 1000)]
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "card.svg")
            with contextlib.redirect_stderr(io.StringIO()):
                self.mod.generate_svg(languages, "u", "merko", out, top_n=1)
            with open(out, encoding="utf-8") as f:
                self.assertIn("C++", f.read())


if __name__ == "__main__":
    unittest.main(verbosity=2)
