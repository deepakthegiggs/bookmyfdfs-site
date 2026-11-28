"""Decision 167 (growth agent, 26 Nov 2026): feeds that AI assistants and agents can use as they are."""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_redesign_r1 import SPOTTED, R1  # noqa: E402


class Feeds(R1):
    def test_offers_json_has_a_version_a_count_and_each_page(self):
        d = json.loads((self.site() / "offers.json").read_text())
        self.assertIs(type(d["schema_version"]), int)              # the bot reads an int schema_version
        self.assertEqual(d["count"], len(d["offers"]))
        for o in d["offers"]:
            self.assertEqual(o["url"], f"https://bookmyfdfs.in/offer/{o['id']}/")

    def test_llms_full_has_every_checked_offer_and_nothing_spotted(self):
        out = self.site()
        full = (out / "llms-full.txt").read_text()
        ids = [o["id"] for o in json.loads((out / "offers.json").read_text())["offers"]]
        for i in ids:
            self.assertIn(f"- Page: https://bookmyfdfs.in/offer/{i}/", full)
        self.assertEqual(len(re.findall(r"^## ", full, re.M)), len(ids))
        for s in SPOTTED:
            self.assertNotIn(s, full)
        self.assertNotRegex(full.lower(), r"spotted|telegram|t\.me")
        self.assertNotIn("IST IST", full)

    def test_llms_txt_tells_agents_what_is_checked(self):
        t = (self.site() / "llms.txt").read_text()
        self.assertIn("## For AI assistants and agents", t)
        self.assertIn("(https://bookmyfdfs.in/llms-full.txt)", t)
        self.assertIn("don't present it as a confirmed offer", t)


if __name__ == "__main__":
    unittest.main()
