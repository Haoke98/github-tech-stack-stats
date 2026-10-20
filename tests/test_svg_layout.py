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
import time
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


class TimestampFooterTest(unittest.TestCase):
    """The card must state when its data was collected, as a dim watermark."""

    ISO_UTC = "2026-07-08T09:44:40.554584+00:00"

    def setUp(self):
        self.mod = load_module()
        self.languages = [("Python", 1000), ("Jupyter Notebook", 500)]

    def render(self, **kw):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "card.svg")
            with contextlib.redirect_stderr(io.StringIO()):
                self.mod.generate_svg(self.languages, "u", "merko", out, top_n=2, **kw)
            with open(out, encoding="utf-8") as f:
                return f.read()

    def height(self, svg):
        return int(re.search(r'<svg width="\d+" height="(\d+)"', svg).group(1))

    def test_footer_contains_collection_time(self):
        svg = self.render(collected_at=self.ISO_UTC)
        self.assertIn("Data collected ", svg)
        self.assertIn(f"<title>Data collected {self.ISO_UTC}</title>", svg)

    def test_footer_is_dimmed_and_centered(self):
        svg = self.render(collected_at=self.ISO_UTC)
        footer = re.search(r'<text x="([\d.]+)" y="([\d.]+)"[^>]*opacity="([\d.]+)">'
                           r'<title>Data collected', svg)
        self.assertIsNotNone(footer, "footer element not found")
        card_w = int(re.search(r'<svg width="(\d+)"', svg).group(1))
        self.assertAlmostEqual(float(footer.group(1)), card_w / 2, delta=0.6)
        self.assertLessEqual(float(footer.group(3)), 0.5, "watermark must be dim")

    def test_footer_sits_below_the_last_row(self):
        svg = self.render(collected_at=self.ISO_UTC)
        footer_y = float(re.search(r'<text x="[\d.]+" y="([\d.]+)"[^>]*opacity="[\d.]+">'
                                   r'<title>', svg).group(1))
        row_ys = [float(y) for y in re.findall(r'<text x="16" y="([\d.]+)"', svg)]
        self.assertGreater(footer_y, max(row_ys))
        self.assertLess(footer_y, self.height(svg))

    def test_no_timestamp_removes_footer_and_its_band(self):
        with_ts = self.render(collected_at=self.ISO_UTC)
        without = self.render(collected_at=self.ISO_UTC, show_timestamp=False)
        self.assertNotIn("Data collected", without)
        self.assertEqual(self.height(with_ts) - self.height(without),
                         self.mod.FOOTER_HEIGHT)

    def test_missing_timestamp_falls_back_to_no_footer(self):
        svg = self.render(collected_at=None)
        self.assertNotIn("Data collected", svg)

    def test_zone_is_written_explicitly(self):
        old = os.environ.get("TZ")
        try:
            os.environ["TZ"] = "Asia/Shanghai"
            time.tzset()
            pretty, iso = self.mod.format_collected_at(self.ISO_UTC)
        finally:
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
            time.tzset()
        self.assertEqual(pretty, "2026-07-08 17:44 UTC+08")
        self.assertEqual(iso, self.ISO_UTC)

    def test_naive_timestamp_is_read_as_utc(self):
        pretty, iso = self.mod.format_collected_at("2026-07-08T09:44:40")
        self.assertRegex(pretty, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC[+-]\d{2}(:\d{2})?$")
        self.assertIn("+00:00", iso)

    def test_garbage_timestamp_does_not_crash(self):
        pretty, iso = self.mod.format_collected_at("not-a-date")
        self.assertEqual(pretty, "not-a-date")


if __name__ == "__main__":
    unittest.main(verbosity=2)
