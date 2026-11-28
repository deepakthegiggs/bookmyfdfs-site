"""Pre-launch ban list (decision 111): words and links for the unannounced product that must not appear on the
site, in its feeds, or in this public source before launch. Stored base64-encoded so this repo never spells them
out; decoded at import. To inspect: python3 -c "import prelaunch; print(prelaunch.TERMS)" (from gen/).
"""
import base64
import re

_ENCODED = "dFwubWUvCnRcLm1lXGIKdGVsZWdyYW0KZmRmcyA/bm93CmZkZnNub3dib3Q="
TERMS = base64.b64decode(_ENCODED).decode().split("\n")
PATTERN = "|".join(TERMS)
RX = re.compile(PATTERN, re.I)
