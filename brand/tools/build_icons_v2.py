"""Repaints the favicon and app icons in the V2 palette (decision 139) and rasterises the PNGs (needs Chrome).
Run: python3 brand/tools/build_icons_v2.py

build_logos.py draws the geometry (it needs the source .ttf files and fontTools); this only swaps its old
navy/marigold/cream for the V2 logo tokens in tokens.css (--logo-seat / --logo-letter / --logo-accent), so the tab
icon, the home-screen icon and the Organization logo match the header mark. Idempotent."""
import shutil, subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
LOGO = ROOT / "brand/logo"
sys.path.insert(0, str(ROOT / "gen"))
import fdfs_site as g

# favicon: light = ink seats, olive S, ivory letters; dark = #F1F2E8 seats, lime S, night letters
FAV_OLD = ('.s{fill:#17142B}.a{fill:#E08A12}.l{fill:#F5EFE3}'
           '@media (prefers-color-scheme:dark){.s{fill:#F5EFE3}.a{fill:#F2A12E}.l{fill:#17142B}}')
FAV_NEW = ('.s{fill:#203229}.a{fill:#4B6629}.l{fill:#F6F5EE}'
           '@media (prefers-color-scheme:dark){.s{fill:#F1F2E8}.a{fill:#D5F476}.l{fill:#0F1813}}')
# app icons: the dark mark on the ink tile (tile and letters share the ink)
ICON = {"#17142B": "#203229", "#F5EFE3": "#F1F2E8", "#F2A12E": "#D5F476"}


def recolour():
    fav = LOGO / "favicon.svg"
    t = fav.read_text(encoding="utf-8")
    if FAV_OLD in t:
        fav.write_text(t.replace(FAV_OLD, FAV_NEW), encoding="utf-8")
    for size in (180, 192, 512):
        f = LOGO / f"app-icon-{size}.svg"
        t = f.read_text(encoding="utf-8")
        for a, b in ICON.items():
            t = t.replace(a, b)
        f.write_text(t, encoding="utf-8")


def rasterise():
    ch = g.chrome_path()
    if not ch:
        sys.exit("Chrome needed to render the icons")
    for size, dst in ((180, "apple-touch-icon.png"), (192, "app-icon-192.png"), (512, "app-icon-512.png")):
        tmp = Path(tempfile.mkdtemp())
        page = tmp / "i.html"
        page.write_text("<!doctype html><meta charset=utf-8><style>html,body{margin:0;background:#203229}"
                        f"svg{{display:block;width:{size}px;height:{size}px}}</style>"
                        + (LOGO / f"app-icon-{size}.svg").read_text(encoding="utf-8"), encoding="utf-8")
        subprocess.run([ch, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                        f"--user-data-dir={tmp / 'prof'}", "--force-device-scale-factor=1",
                        f"--window-size={size},{size}", f"--screenshot={tmp / 'o.png'}", page.as_uri()],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45)
        if not (tmp / "o.png").exists():
            sys.exit(f"Chrome failed on {dst}")
        shutil.copyfile(tmp / "o.png", LOGO / dst)
        shutil.rmtree(tmp, ignore_errors=True)
        print("wrote brand/logo/" + dst)


if __name__ == "__main__":
    recolour()
    rasterise()
