"""26 Nov: an offer whose quote is several verbatim spans (engine model.pieces) must build, not crash the publish."""
import json, sys, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gen"))
import fdfs_site as g  # noqa: E402


class QuoteSpans(unittest.TestCase):
    def test_quote_for_joins_spans(self):
        from types import SimpleNamespace
        o = SimpleNamespace()
        o.quotes = {"value": ["Buy 1 ticket and get 1 free", "up to Rs. 200"]}
        self.assertEqual(g.quote_for(o), "Buy 1 ticket and get 1 free … up to Rs. 200")
        o.quotes = {"value": [], "kind": "Buy one get one"}
        self.assertEqual(g.quote_for(o), "Buy one get one")

    def test_build_with_list_quotes(self):
        data = json.loads((ROOT / "data/offers.json").read_text())
        for o in data["offers"]:
            for k, v in list(o["quotes"].items()):
                if isinstance(v, str) and len(v) > 12:
                    o["quotes"][k] = [v[: len(v) // 2], v[len(v) // 2:]]
        with tempfile.TemporaryDirectory() as t:
            src = Path(t) / "offers.json"; src.write_text(json.dumps(data))
            state = Path(t) / "state.json"; state.write_text((ROOT / "data/build-state.json").read_text())
            out = Path(t) / "out"
            g.build(src, ROOT / "data/history", out, state, ROOT / "data/site.json", ROOT, snapshot=False, render_og=False)
            html = (out / "index.html").read_text()
            self.assertNotIn("['", html.split("<script")[0])


if __name__ == "__main__":
    unittest.main()


class VariantNames(unittest.TestCase):
    def test_issuer_overlap_is_dropped(self):
        self.assertEqual(g.clean_variant("IDFC FIRST", "FIRST Classic"), "Classic")
        self.assertEqual(g.clean_variant("HSBC", "Premier"), "Premier")
        self.assertEqual(g.clean_variant("HSBC", "HSBC Premier"), "Premier")
        self.assertEqual(g.clean_variant("IDFC FIRST", "FIRST"), "FIRST")       # never empties a name
