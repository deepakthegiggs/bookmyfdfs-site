"""Decision 165 (growth agent, 26 Nov 2026): "New since your last visit" on the home page, from this browser only."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gen"))
sys.path.insert(0, str(ROOT / "tests"))
import fdfs_site as g  # noqa: E402
from test_redesign_r1 import NOW, VERIFIED, Browser, R1  # noqa: E402


class Static(R1):
    def test_home_carries_the_note_and_the_script(self):
        t = (self.site() / "index.html").read_text()
        self.assertIn('<p class="newn" data-new hidden></p>', t)
        self.assertIn(g.NEW_JS, t)

    def test_nothing_leaves_the_browser(self):
        for word in ("fetch", "XMLHttpRequest", "sendBeacon", "cookie", "http"):
            self.assertNotIn(word, g.NEW_JS)


class Visits(Browser):
    def test_first_visit_quiet_second_visit_marks_new(self):
        out = self.site()
        res = self.run_js(out, """load('/?fdfs_now=%d',390,function(f,d,w){var r={first:d.querySelector('[data-new]').hidden,
b1:d.querySelectorAll('.nb').length};var s=JSON.parse(w.localStorage.getItem('fdfs-seen'));r.saved=s.ids.length;
s.ids=s.ids.slice(1);w.localStorage.setItem('fdfs-seen',JSON.stringify(s));
load('/?fdfs_now=%d',390,function(f2,d2){var p=d2.querySelector('[data-new]');r.note=p.hidden?null:txt(p);
r.badges=[].map.call(d2.querySelectorAll('#offers .offer .nb'),function(e){return e.closest('.offer').id});
load('/?fdfs_now=%d',390,function(f3,d3){r.third=d3.querySelectorAll('.nb').length;done(r)})})});""" % (NOW, NOW, NOW),
                          budget=12000)
        self.assertTrue(res["first"])
        self.assertEqual(res["b1"], 0)
        self.assertEqual(res["saved"], len(VERIFIED))
        self.assertEqual(res["note"], "1 new offer since your last visit, marked New")
        self.assertEqual(len(res["badges"]), 1)
        self.assertEqual(res["third"], 0, "seen once, it isn't new again")


if __name__ == "__main__":
    unittest.main()
