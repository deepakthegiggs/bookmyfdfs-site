"""Renders brand/logo/og-brand.png: the dateless, countless fallback share card (needs Chrome).
Run: python3 brand/tools/build_og_brand.py

Decision 158 (owner, 26 Nov: "nice and clear"): the same card as the per-page ones, drawn by gen/fdfs_site.og_svg on
the V2 ink stage. One idea ("Movie ticket offers"), the name's meaning as the one lime line, and a small mark +
bookmyfdfs.in at the foot. No date, no count, no "checked against the official terms", no "Independent" strip:
those live on the pages."""
import json, shutil, sys, tempfile
from pathlib import Path
from datetime import datetime
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "gen"))
import fdfs_site as g

SPEC = g.og_spec("og-brand", ["Movie ticket offers"], "Film · Deals · Friends · Seats", [])


if __name__ == "__main__":
    site = g.Site(ROOT, json.loads((ROOT / "data/site.json").read_text()), datetime.now(g.IST), [])
    (ROOT / "brand/logo/og-brand.svg").write_text(g.og_svg(site, SPEC), encoding="utf-8")
    tmp = Path(tempfile.mkdtemp())
    if not g.render_og_pngs(ROOT, [SPEC], tmp, site):
        sys.exit("Chrome needed to render the brand card")
    shutil.copyfile(tmp / "og-brand.png", ROOT / "brand/logo/og-brand.png")
    print("wrote brand/logo/og-brand.png")
