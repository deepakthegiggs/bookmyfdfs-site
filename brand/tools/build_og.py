"""Builds the OG template + a filled example with the brand mark (B) from brand/logo/*.svg.
Run after build_logos.py: python3 brand/tools/build_og.py  (then rasterise og-render.html)."""
import re, pathlib
L = pathlib.Path(__file__).resolve().parents[1] / "logo"
word = (L / "wordmark-fdfs.path.txt").read_text().strip().split("\n", 1)[1].strip()
tag = (L / "tagline.path.txt").read_text().strip().split("\n", 1)[1].strip()
FONT = ('<style>@font-face{font-family:"Bricolage Grotesque";src:url(/assets/fonts/bricolage-latin.woff2);font-weight:600 800}'
        '@font-face{font-family:"Google Sans";src:url(/assets/fonts/google-sans-latin.woff2);font-weight:400 700}'
        '@font-face{font-family:"Google Sans";src:url(/assets/fonts/google-sans-rupee.woff2);unicode-range:U+20B9;font-weight:400 700}'
        'body{margin:0}</style>')


def og(mark):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630" width="1200" height="630">
<!-- FDFS OG image template (1200x630). Replace the {{{{…}}}} fields at build time, then rasterise
     to PNG with headless Chrome (see og-render-*.html). Logo and tagline are paths; text is Bricolage Grotesque + Google Sans.
     Keep the title to 2 lines (about 28 characters each). -->
<defs><linearGradient id="fade" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#F7C46E" stop-opacity=".30"/><stop offset="1" stop-color="#F7C46E" stop-opacity="0"/></linearGradient>
<style>.t{{font-family:"Bricolage Grotesque",Arial,sans-serif;font-weight:700;letter-spacing:-0.02em}}.b{{font-family:"Google Sans",Arial,sans-serif;font-weight:500}}</style></defs>
<rect width="1200" height="630" fill="#0E0C1D"/>
<path d="M600 -20 L1010 630 H190 Z" fill="url(#fade)"/>
<g transform="translate(64 52) scale(1.5)">{mark}</g>
<g transform="translate(176 72) scale(1.2)" fill="#F5EFE3"><path d="{word}"/></g>
<g transform="translate(178 126) scale(1.8)" fill="#C9C1D8"><path d="{tag}"/></g>
<text x="72" y="300" class="t" font-size="84" fill="#F5EFE3">{{{{title_line_1}}}}</text>
<text x="72" y="396" class="t" font-size="84" fill="#F7C46E">{{{{title_line_2}}}}</text>
<text x="72" y="468" class="b" font-size="32" fill="#C9C1D8">{{{{subtitle}}}}</text>
<path d="M0 560 Q600 540 1200 560 V630 H0 Z" fill="#F5EFE3"/>
<text x="72" y="606" class="b" font-size="26" fill="#17142B">bookmyfdfs.in · {{{{checked}}}} · Independent</text>
</svg>
'''


mark = re.search(r"<title>FDFS</title>(.*)</svg>", (L / "fdfs-mark-dark.svg").read_text(), re.S).group(1)
t = og(mark)
(L / "og-template.svg").write_text(t)
ex = (t.replace("{{title_line_1}}", "Movie ticket offers,").replace("{{title_line_2}}", "checked today.")
       .replace("{{subtitle}}", "7 movie offers from official terms. Caps ₹200–₹750.")
       .replace("{{checked}}", "Checked 25 Nov 2026, 11:30"))
(L / "og-example-offers.svg").write_text(ex)
(L / "og-render.html").write_text("<!doctype html><meta charset=utf-8>" + FONT + "<body>" + ex)
