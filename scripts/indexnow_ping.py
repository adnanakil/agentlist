#!/usr/bin/env python3
"""Submit changed texthal.com URLs to IndexNow (Bing/Yandex/etc.).

Google does not support IndexNow (mid-2026) — this feeds Bing's index, which
is what ChatGPT Search retrieves from. Run after content deploys:

    python3 scripts/indexnow_ping.py /guides /guides/wake-windows-by-age
    python3 scripts/indexnow_ping.py --all      # every sitemap URL

Stdlib only; the key is public by design and served at /{key}.txt by the
landing router (routes/landing.py _INDEXNOW_KEY — keep the two in sync).
"""

from __future__ import annotations

import json
import sys
import urllib.request
from xml.etree import ElementTree

HOST = "www.texthal.com"
KEY = "dd76015a8b4f3852832f9d57b2b3523e"
ENDPOINT = "https://api.indexnow.org/indexnow"


def sitemap_urls() -> list[str]:
    with urllib.request.urlopen(f"https://{HOST}/sitemap.xml", timeout=15) as r:
        tree = ElementTree.fromstring(r.read())
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    return [el.text for el in tree.findall(".//s:loc", ns) if el.text]


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    if args == ["--all"]:
        urls = sitemap_urls()
    else:
        urls = [f"https://{HOST}{p if p.startswith('/') else '/' + p}" for p in args]

    payload = json.dumps(
        {
            "host": HOST,
            "key": KEY,
            "keyLocation": f"https://{HOST}/{KEY}.txt",
            "urlList": urls,
        }
    ).encode()
    req = urllib.request.Request(
        ENDPOINT, data=payload, headers={"Content-Type": "application/json; charset=utf-8"}
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        print(f"IndexNow: HTTP {r.status} for {len(urls)} URLs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
