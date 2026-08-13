#!/usr/bin/env python3
"""
Decode Naver 부동산 share links into complexId / articleId / pyeong-type info.

Naver's own listing-detail API (new.land.naver.com/api/articles/<id>) is hard
bot-blocked (429 TOO_MANY_REQUESTS on every attempt, even with fresh cookies
+ Referer - this isn't a rate limit, it's a wall). So this script does NOT
fetch price/floor/dong - it only decodes the IDs embedded in a share link.
Price/floor/etc still has to come from what the user can see on the Naver
page itself, or by cross-referencing complexId against pipeline.py's sources.

Requires: pip install --break-system-packages --user lzstring

Usage:
    python3 decode_naver_links.py "https://naver.me/xxxxx" "https://fin.land.naver.com/map?...&layer=..." ...
    python3 decode_naver_links.py --file links.txt   # one URL per line

Output: one row per unique articleId - complexId, articleId, tradeType,
pyeongTypeNumber. Cross-check complexId against COMPLEX_CACHE /
pipeline.py's resolved codes (NEONET complex_cd, Tencomz aptNo, Hanbang CD
have all matched this same numeric ID in every case seen so far).
"""
import argparse
import json
import re
import subprocess
import sys
import urllib.parse

try:
    from lzstring import LZString
except ImportError:
    print("ERROR: pip install --break-system-packages --user lzstring", file=sys.stderr)
    sys.exit(1)


def resolve_short_link(url):
    """naver.me short links 307-redirect to the real fin.land.naver.com URL."""
    if "naver.me" not in url:
        return url
    r = subprocess.run(
        ["curl", "-s", "-I", "-A", "Mozilla/5.0", url],
        capture_output=True, text=True,
    )
    m = re.search(r"^location:\s*(\S+)", r.stdout, re.IGNORECASE | re.MULTILINE)
    return m.group(1).strip() if m else url


def extract_layer_param(url):
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    layer = qs.get("layer", [None])[0]
    return layer


def decode_link(url):
    full_url = resolve_short_link(url)
    layer = extract_layer_param(full_url)
    if not layer:
        return None
    try:
        decoded = LZString().decompressFromEncodedURIComponent(layer)
        data = json.loads(decoded)
    except Exception as e:
        print(f"WARN: failed to decode layer param from {url}: {e}", file=sys.stderr)
        return None

    result = {"source_url": url, "resolved_url": full_url}
    for entry in data:
        params = entry.get("params", {})
        search = entry.get("searchParams", {})
        if entry.get("id") == "complex_detail":
            result["complexId"] = params.get("complexId")
            result["tab"] = search.get("tab")
            result["articleTradeTypes"] = search.get("articleTradeTypes")
            result["pyeongTypeNumber"] = search.get("transactionPyeongTypeNumber")
        elif entry.get("id") == "article_detail":
            result["articleId"] = params.get("articleId")
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("urls", nargs="*", help="Naver share link(s)")
    ap.add_argument("--file", help="file with one URL per line")
    args = ap.parse_args()

    urls = list(args.urls)
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            urls += [line.strip() for line in f if line.strip()]

    if not urls:
        print("No URLs given. Pass them as args or --file.", file=sys.stderr)
        sys.exit(1)

    results = []
    for url in urls:
        r = decode_link(url)
        if r:
            results.append(r)

    # dedupe by articleId (same listing can be pasted twice)
    seen = {}
    for r in results:
        key = r.get("articleId") or r["source_url"]
        seen[key] = r
    results = list(seen.values())

    print(f"{'articleId':>14}  {'complexId':>10}  {'pyeongType':>10}  {'tradeType':<12}  source")
    for r in results:
        print(f"{r.get('articleId','-'):>14}  {r.get('complexId','-'):>10}  "
              f"{r.get('pyeongTypeNumber','-'):>10}  {r.get('articleTradeTypes','-'):<12}  {r['source_url']}")

    complex_ids = sorted(set(str(r.get("complexId")) for r in results if r.get("complexId")))
    if complex_ids:
        print(f"\ncomplexId(s) seen: {', '.join(complex_ids)}")
        print("Cross-check these against pipeline.py's NEONET complex_cd / Tencomz aptNo / "
              "Hanbang CD for this apartment - they have matched exactly in every case tried so far.")


if __name__ == "__main__":
    main()
