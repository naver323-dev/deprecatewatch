#!/usr/bin/env python3
"""endoflife.date API(무료·키 불필요)에서 제품 목록과 제품별 사이클을 수집한다.

- 원본 응답은 data/raw/endoflife/<slug>.json 에 그대로 보관한다(가공 전 원문).
- 이미 받아둔 파일이 있으면 REFRESH=1 일 때만 다시 받는다.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "https://endoflife.date/api"
UA = "DeprecateWatch/1.0 (static EOL tracker; +https://deprecatewatch.pages.dev)"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw", "endoflife")
REFRESH = os.environ.get("REFRESH") == "1"


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_product(slug):
    path = os.path.join(RAW, slug + ".json")
    if os.path.exists(path) and not REFRESH:
        return slug, "cached", None
    try:
        cycles = get_json(f"{BASE}/{slug}.json")
        if not isinstance(cycles, list):
            return slug, "bad", "not a list"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cycles, f, ensure_ascii=False)
        return slug, "ok", None
    except urllib.error.HTTPError as e:
        return slug, "http_%d" % e.code, str(e)
    except Exception as e:  # noqa: BLE001 - 수집 실패는 다음 실행에서 재시도
        return slug, "error", str(e)


def main():
    os.makedirs(RAW, exist_ok=True)
    if REFRESH or not os.path.exists(os.path.join(ROOT, "data", "all_products.json")):
        products = get_json(f"{BASE}/all.json")
        with open(os.path.join(ROOT, "data", "all_products.json"), "w", encoding="utf-8") as f:
            json.dump(products, f, ensure_ascii=False)
    else:
        products = json.load(open(os.path.join(ROOT, "data", "all_products.json"), encoding="utf-8"))
    print(f"products: {len(products)}")

    results = {}
    started = time.time()
    with ThreadPoolExecutor(max_workers=4) as pool:
        for slug, status, err in pool.map(fetch_product, products):
            results.setdefault(status, []).append(slug)
            if err and status not in ("cached",):
                print(f"  {slug}: {status} {err[:80]}", file=sys.stderr)
    print("fetched in %.1fs" % (time.time() - started))
    for k, v in sorted(results.items()):
        print(f"  {k}: {len(v)}")
    if results.get("error") or results.get("bad"):
        sys.exit(1)


if __name__ == "__main__":
    main()
