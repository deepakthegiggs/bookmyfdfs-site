#!/usr/bin/env python3
"""Write worker.js from worker.tmpl.js and the constants in gen/fdfs_mcp.py (tool list, wording, version), so the
hosted server and the downloadable one can't drift. Run after changing either: python3 gen/mcp-worker/build.py
tests/test_mcp_worker.py fails if worker.js is out of date."""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import fdfs_mcp as m  # noqa: E402


def constants() -> dict:
    return {"VERSION": m.VERSION, "FEED": m.FEED, "PROTOCOLS": list(m.PROTOCOLS), "CACHE_SECONDS": m.CACHE_SECONDS,
            "STALE_DAYS": m.STALE_DAYS, "DAYS": list(m.DAYS), "DAY_WORDS": m.DAY_WORDS, "APPS": m.APPS,
            "APP_WORDS": m.APP_WORDS, "NOTE": m.NOTE, "TOOLS": m.TOOLS, "NETWORKS": m.NETWORKS, "RANK": m.RANK,
            "HINTS": m.HINTS, "STOP": sorted(m._STOP), "DAY_NAMES": m.DAY_NAMES}


def render() -> str:
    tmpl = (HERE / "worker.tmpl.js").read_text(encoding="utf-8")
    return tmpl.replace("__CONSTANTS__", json.dumps(constants(), ensure_ascii=False, indent=2), 1)


if __name__ == "__main__":
    (HERE / "worker.js").write_text(render(), encoding="utf-8")
    print("wrote", HERE / "worker.js")
