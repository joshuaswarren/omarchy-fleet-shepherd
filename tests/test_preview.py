"""Preview frames must not contain overlapping text boxes.

Vision review of the animated preview found colliding strings; this pins the
collision guards in scripts/make_preview.py structurally, no pixels needed.
"""

import importlib.machinery
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "make_preview.py"


def load_mod():
    spec = importlib.util.spec_from_loader(
        "make_preview",
        importlib.machinery.SourceFileLoader("make_preview", str(SCRIPT)),
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def boxes_for(mod, **spec):
    """Render one frame with text() instrumented, returning text hit-boxes."""
    recorded = []
    real_text = mod.text

    def spy(x, y, s, *a, **k):
        size = k.get("size", 12)
        anchor = k.get("anchor")
        w = mod.est_w(s, size)
        x0 = x - w if anchor == "end" else x
        recorded.append((x0, y - size, x0 + w, y, s))
        return real_text(x, y, s, *a, **k)

    mod.text = spy
    try:
        mod.frame(**spec)
    finally:
        mod.text = real_text
    return recorded


def overlap(a, b):
    ax0, ay0, ax1, ay1, _ = a
    bx0, by0, bx1, by1, _ = b
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


class PreviewOverlapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_mod()
        cls.demo = json.loads((ROOT / "tests" / "fixtures" / "fleet_demo.json").read_text())

    def frames(self):
        conns = self.demo["connectors"]
        return [
            dict(conns=conns, view="overview", cursor=0),
            dict(conns=conns, view="overview", cursor=2),
            dict(conns=conns, view="attention", cursor=0),
            dict(conns=conns, view="agents", cursor=1),
            dict(conns=conns, view="usage", cursor=0),
            dict(conns=conns, view="overview", cursor=0, query="api"),
            dict(conns=conns, view="overview", cursor=0, query="xyzzy"),
        ]

    def test_no_frame_has_overlapping_text_boxes(self):
        for spec in self.frames():
            with self.subTest(**{k: v for k, v in spec.items() if k != "conns"}):
                boxes = boxes_for(self.mod, **spec)
                for i in range(len(boxes)):
                    for j in range(i + 1, len(boxes)):
                        if overlap(boxes[i], boxes[j]):
                            self.fail(
                                f"overlap between {boxes[i][4]!r} and {boxes[j][4]!r} "
                                f"in frame {spec}"
                            )

    def test_all_text_stays_inside_the_panel(self):
        for spec in self.frames():
            boxes = boxes_for(self.mod, **spec)
            for x0, y0, x1, y1, s in boxes:
                self.assertGreaterEqual(x0, 10, f"{s!r} starts left of panel")
                self.assertLessEqual(x1, self.mod.W - 10, f"{s!r} exceeds right edge")
                self.assertGreaterEqual(y0, 10, f"{s!r} above panel top")
                self.assertLessEqual(y1, self.mod.H - 10, f"{s!r} below panel bottom")


if __name__ == "__main__":
    unittest.main()
