"""Builds every logo SVG (brand mark = B "Seat block", owner 25 Nov; A and C in logo/alt/) in brand/logo/ from (a) hand-set geometry on a
64-unit grid and (b) Anek Latin glyph outlines (OFL), so no logo file depends
on a webfont. FDFS = Film · Deals · Friends · Seats (decision 134; supersedes 042).
Run: python3 brand/tools/build_logos.py <Bricolage opsz96 wght750 .ttf> <Google Sans wght500 .ttf>
"""
import math, sys, pathlib
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

OUT = pathlib.Path(__file__).resolve().parents[1] / "logo"
OUT.mkdir(exist_ok=True)
INK, MARIGOLD, CREAM, NIGHT, MARIGOLD_DEEP = "#17142B", "#F2A12E", "#F5EFE3", "#0E0C1D", "#E08A12"
TAGLINE = "FILM · DEALS · FRIENDS · SEATS"


def text_path(font_file, text, cap_px, x0, baseline, tracking_em=0.0):
    """(svg path d, advance width px) for text set at a given cap height."""
    f = TTFont(font_file)
    gs, cmap = f.getGlyphSet(), f.getBestCmap()
    s = cap_px / f["OS/2"].sCapHeight
    pen = SVGPathPen(gs, ntos=lambda v: ("%.2f" % v).rstrip("0").rstrip("."))
    x, upm = x0, f["head"].unitsPerEm
    for i, ch in enumerate(text):
        g = cmap[ord(ch)]
        gs[g].draw(TransformPen(pen, (s, 0, 0, -s, x, baseline)))
        x += gs[g].width * s + (tracking_em * upm * s if i < len(text) - 1 else 0)
    return pen.getCommands(), x - x0


# ---------- A. Row of Four: four seats facing one curved screen ----------
# The band is the screen (the Film). The four seats are you and your Friends,
# on the best Deal, in the Seats you wanted. The row curves the way real rows
# do, so the outer seats sit a little higher.
BAND = "M5 7Q32 9.6 59 7V17Q32 14.4 5 17Z"   # the curved screen, a gentle arc
PITCH, CUSH, BACK = 15.6, 12.4, 7.6
X0 = (64 - (3 * PITCH + CUSH)) / 2
LIFT = (1.6, 0, 0, 1.6)                     # the row curves: outer seats sit higher


def seat(x, y, back=BACK, cush=CUSH, bh=12, ch=6.4, r=2.6):
    """One seat: cushion left edge at x, back top at y."""
    bx = x + (cush - back) / 2
    cr = min(2, ch / 2 - 0.1)
    return (f"M{bx+r:.2f} {y:.2f}h{back-2*r:.2f}a{r} {r} 0 0 1 {r} {r}v{bh+3-r:.2f}h-{back:.2f}v-{bh+3-r:.2f}a{r} {r} 0 0 1 {r}-{r}z"
            f"M{x+cr:.2f} {y+bh:.2f}h{cush-2*cr:.2f}a{cr} {cr} 0 0 1 {cr} {cr}v{ch-2*cr:.2f}a{cr} {cr} 0 0 1-{cr} {cr}"
            f"h-{cush-2*cr:.2f}a{cr} {cr} 0 0 1-{cr}-{cr}v-{ch-2*cr:.2f}a{cr} {cr} 0 0 1 {cr}-{cr}z")


def armchair(x, y, w=12.4, h=17, back_w=7.6, arm_y=7.5, r=2.2):
    """Front view of a cinema seat: a back rising above a wider base with armrests."""
    bx = x + (w - back_w) / 2
    return (f"M{bx+r:.2f} {y:.2f}h{back_w-2*r:.2f}a{r} {r} 0 0 1 {r} {r}V{y+arm_y:.2f}"
            f"H{x+w-r:.2f}a{r} {r} 0 0 1 {r} {r}V{y+h-r:.2f}a{r} {r} 0 0 1-{r} {r}"
            f"H{x+r:.2f}a{r} {r} 0 0 1-{r}-{r}V{y+arm_y+r:.2f}a{r} {r} 0 0 1 {r}-{r}H{bx:.2f}V{y+r:.2f}a{r} {r} 0 0 1 {r}-{r}z")


def seats_d(y0=31, idx=range(4)):
    return "".join(armchair(X0 + i * PITCH, y0 - LIFT[i]) for i in idx)


def mark_a(mode, cls=False):
    """Three seats for the plan, the fourth is yours: the accent."""
    if mode == "mono":
        return f'<path fill="currentColor" d="{BAND}{seats_d()}"/>'
    s, acc = (INK, MARIGOLD_DEEP) if mode == "light" else (CREAM, MARIGOLD)
    return (f'<path fill="{s}" d="{BAND}"/><path fill="{s}" d="{seats_d(idx=range(3))}"/>'
            f'<path fill="{acc}" d="{seats_d(idx=[3])}"/>')


# ---------- B. Seat block: F·D·F·S on a 2x2 grid of seats ----------
def mark_b(mode, display=None):
    cells = [(2, 4, "F"), (34, 4, "D"), (2, 35, "F"), (34, 35, "S")]
    seats, letters = [], []
    for x, y, ch in cells:
        seats.append(seat(x, y, back=24, cush=28, bh=16, ch=8, r=5))
        d, w = text_path(display, ch, 11.5, 0, 0)
        letters.append(f'<path transform="translate({x + 14 - w/2:.2f} {y + 14.2:.2f})" d="{d}"/>')
    if mode == "mono":
        return (f'<defs><mask id="sb-k"><rect width="64" height="64" fill="#fff"/><g fill="#000">{"".join(letters)}</g></mask></defs>'
                f'<path fill="currentColor" mask="url(#sb-k)" d="{"".join(seats)}"/>')
    s, acc, l = (INK, MARIGOLD_DEEP, CREAM) if mode == "light" else (CREAM, MARIGOLD, INK)
    return (f'<path fill="{s}" d="{"".join(seats[:3])}"/><path fill="{acc}" d="{seats[3]}"/>'
            f'<g fill="{l}">{"".join(letters)}</g>')


# ---------- C. Four Beats: four steps, the plan comes together ----------
def mark_c(mode):
    xs = (8.5, 23.5, 38.5, 53.5)
    rings = "".join(f'<circle cx="{x}" cy="32" r="5.6"/>' for x in xs[:3])
    last = f'<circle cx="{xs[3]}" cy="32" r="7.4"/>'
    if mode == "mono":
        return (f'<g fill="none" stroke="currentColor" stroke-width="3.2">{rings}</g>'
                f'<g fill="currentColor">{last}</g>')
    r, l = (INK, MARIGOLD_DEEP) if mode == "light" else (CREAM, MARIGOLD)
    return f'<g fill="none" stroke="{r}" stroke-width="3.2">{rings}</g><g fill="{l}">{last}</g>'


def svg(w, h, body, title):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'role="img" aria-label="{title}"><title>{title}</title>{body}</svg>\n')


def lockup(markbody, mode, display, text):
    word, ww = text_path(display, "FDFS", 32, 78, 36, tracking_em=0.0)
    tag, tw = text_path(text, TAGLINE, 7.2, 79, 55.5, tracking_em=0.08)
    W = math.ceil(78 + max(ww, tw) + 4)
    fg = {"light": INK, "dark": CREAM, "mono": "currentColor"}[mode]
    tagc = {"light": "#4E4864", "dark": "#C9C1D8", "mono": "currentColor"}[mode]
    body = f'{markbody}<path fill="{fg}" d="{word}"/><path fill="{tagc}" d="{tag}"/>'
    return svg(W, 64, body, "FDFS: Film, Deals, Friends, Seats")


def mark_b_parts(display):
    """B as separate parts, so the site can colour it with CSS and animate the seats."""
    cells = [(2, 4, "F"), (34, 4, "D"), (2, 35, "F"), (34, 35, "S")]
    seats, letters = [], []
    for x, y, ch in cells:
        seats.append(seat(x, y, back=24, cush=28, bh=16, ch=8, r=5))
        d, w = text_path(display, ch, 11.5, 0, 0)
        letters.append(f'<path transform="translate({x + 14 - w/2:.2f} {y + 14.2:.2f})" d="{d}"/>')
    return seats, letters


def main(display, text):
    import json
    ALT = OUT / "alt"
    ALT.mkdir(exist_ok=True)
    # The brand mark (owner, 25 Nov): B "Seat block".
    for mode in ("light", "dark", "mono"):
        (OUT / f"fdfs-mark-{mode}.svg").write_text(svg(64, 64, mark_b(mode, display), "FDFS"))
        (OUT / f"fdfs-lockup-{mode}.svg").write_text(lockup(mark_b(mode, display), mode, display, text))
    # Reference only: A and C.
    for name, fn in {"a-row-of-four": lambda m: mark_a(m), "c-four-beats": lambda m: mark_c(m)}.items():
        for mode in ("light", "dark", "mono"):
            (ALT / f"{name}-mark-{mode}.svg").write_text(svg(64, 64, fn(mode), "FDFS"))
            (ALT / f"{name}-lockup-{mode}.svg").write_text(lockup(fn(mode), mode, display, text))
    word, ww = text_path(display, "FDFS", 34, 0, 34, tracking_em=0.0)
    (OUT / "wordmark-fdfs.path.txt").write_text(f"viewBox 0 0 {math.ceil(ww)} 34\n{word}\n")
    tag, tw = text_path(text, TAGLINE, 7.2, 0, 7.2, tracking_em=0.08)
    (OUT / "tagline.path.txt").write_text(f"viewBox 0 0 {math.ceil(tw)} 8\n{tag}\n")
    seats, letters = mark_b_parts(display)
    (OUT / "mark-b.parts.json").write_text(json.dumps({"seats": seats, "letters": letters}))

    # Favicon (B), switching with the OS theme.
    fb = mark_b("light", display).replace(INK, "VAR_S").replace(MARIGOLD_DEEP, "VAR_A").replace(CREAM, "VAR_L")
    fav = ('<style>.s{fill:#17142B}.a{fill:#E08A12}.l{fill:#F5EFE3}'
           '@media (prefers-color-scheme:dark){.s{fill:#F5EFE3}.a{fill:#F2A12E}.l{fill:#17142B}}</style>'
           + fb.replace('fill="VAR_S"', 'class="s"').replace('fill="VAR_A"', 'class="a"').replace('fill="VAR_L"', 'class="l"'))
    (OUT / "favicon.svg").write_text(svg(64, 64, fav, "FDFS"))
    for size, pad in ((180, 26), (192, 28), (512, 84)):
        sc = (size - 2 * pad) / 64
        (OUT / f"app-icon-{size}.svg").write_text(svg(size, size, f'<rect width="{size}" height="{size}" fill="{INK}"/>'
            f'<g transform="translate({pad} {pad}) scale({sc:.4f})">{mark_b("dark", display)}</g>', "FDFS"))

    # A's favicon and icon, for reference.
    fav_seats = "".join(armchair(1 + i * 16, 31 - (1.5 if i == 0 else 0), w=14, h=21, back_w=9, arm_y=9, r=2.6) for i in range(3))
    fav_acc = armchair(1 + 3 * 16, 29.5, w=14, h=21, back_w=9, arm_y=9, r=2.6)
    fava = ('<style>.s{fill:#17142B}.a{fill:#E08A12}'
            '@media (prefers-color-scheme:dark){.s{fill:#F5EFE3}.a{fill:#F2A12E}}</style>'
            '<path class="s" d="M2 5Q32 8.5 62 5V19Q32 15.5 2 19Z"/>'
            f'<path class="s" d="{fav_seats}"/><path class="a" d="{fav_acc}"/>')
    (ALT / "favicon-a.svg").write_text(svg(64, 64, fava, "FDFS"))
    (ALT / "app-icon-180-a.svg").write_text(svg(180, 180, f'<rect width="180" height="180" fill="{INK}"/>'
        f'<g transform="translate(26 22) scale(2)">{mark_a("dark")}</g>', "FDFS"))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
