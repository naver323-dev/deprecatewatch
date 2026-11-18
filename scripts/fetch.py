#!/usr/bin/env python3
"""DeprecateWatch 수집기 — 모든 외부 소스를 data/raw/ 에 원문 그대로 저장한다.

소스(전부 공개·무료·키 불필요)
  1) endoflife.date API v1  : 제품 489종 · 릴리스 사이클 EOL/지원종료 날짜
  2) AWS Lambda 런타임 지원종료 표 (docs.aws.amazon.com)
  3) Google Cloud 릴리스 노트 Atom 피드 (Deprecated/Change 노트)
  4) AWS What's New RSS (지원종료·폐기 키워드)
  5) GitHub releases.atom (주요 오픈소스 저장소의 deprecation/breaking 변경)

실행: python3 scripts/fetch.py            # 캐시 사용
      REFRESH=1 python3 scripts/fetch.py  # 전부 다시 받기
"""
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
RAW = os.path.join(DATA, "raw")
EOF_RAW = os.path.join(RAW, "endoflife")
FEED_RAW = os.path.join(RAW, "feeds")
UA = "DeprecateWatch/1.0 (EOL tracker; +https://deprecatewatch.pages.dev)"
REFRESH = os.environ.get("REFRESH") == "1"

EOF_API = "https://endoflife.date/api"
GCP_FEED = "https://docs.cloud.google.com/feeds/gcp-release-notes.xml"
AWS_WHATSNEW = "https://aws.amazon.com/about-aws/whats-new/recent/feed/"
AZURE_UPDATES = "https://www.microsoft.com/releasecommunications/api/v2/azure/rss"
AWS_LAMBDA_DOC = "https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html"

GITHUB_REPOS = [
    "nodejs/node",
    "python/cpython",
    "postgres/postgres",
    "django/django",
    "kubernetes/kubernetes",
    "facebook/react",
    "vercel/next.js",
    "microsoft/TypeScript",
    "angular/angular",
    "vuejs/core",
    "spring-projects/spring-boot",
    "laravel/framework",
    "rails/rails",
    "golang/go",
    "dotnet/runtime",
    "rust-lang/rust",
    "elastic/elasticsearch",
    "grafana/grafana",
    "redis/redis",
    "hashicorp/terraform",
]


def get(url, timeout=90):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def get_json(url):
    _, body = get(url)
    return json.loads(body.decode("utf-8"))


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = "wb" if isinstance(data, bytes) else "w"
    with open(path, mode) as f:
        f.write(data)


def fetch_file(url, path, label):
    """URL 하나를 파일로 저장. 캐시가 있으면 건너뛴다."""
    if os.path.exists(path) and not REFRESH:
        return f"{label}: cached"
    try:
        status, body = get(url)
        write(path, body)
        return f"{label}: {status} {len(body)}b"
    except urllib.error.HTTPError as e:
        return f"{label}: HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return f"{label}: {type(e).__name__} {e}"


def fetch_endoflife_product(slug):
    path = os.path.join(EOF_RAW, slug + ".json")
    if os.path.exists(path) and not REFRESH:
        return slug, "cached"
    try:
        cycles = get_json(f"{EOF_API}/{slug}.json")
        if not isinstance(cycles, list):
            return slug, "bad-payload"
        write(path, json.dumps(cycles, ensure_ascii=False))
        return slug, "ok"
    except Exception as e:  # noqa: BLE001
        return slug, f"{type(e).__name__}"


def main():
    os.makedirs(EOF_RAW, exist_ok=True)
    os.makedirs(FEED_RAW, exist_ok=True)
    log = []

    # 1) endoflife.date: 제품 목록(v1: 이름·카테고리·태그 포함)
    log.append(fetch_file(f"{EOF_API}/v1/products", os.path.join(DATA, "products_v1.json"), "endoflife products"))
    products_doc = json.load(open(os.path.join(DATA, "products_v1.json"), encoding="utf-8"))
    slugs = [p["name"] for p in products_doc["result"]]
    log.append(f"endoflife slugs: {len(slugs)}")

    started = time.time()
    statuses = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for slug, status in pool.map(fetch_endoflife_product, slugs):
            statuses.setdefault(status, []).append(slug)
    log.append("endoflife cycles: %s in %.1fs" % ({k: len(v) for k, v in sorted(statuses.items())}, time.time() - started))
    failed = [s for k, v in statuses.items() if k not in ("ok", "cached") for s in v]
    if failed:
        log.append(f"FAILED products ({len(failed)}): {failed[:10]}")

    # 2) 나머지 피드
    log.append(fetch_file(AWS_LAMBDA_DOC, os.path.join(FEED_RAW, "aws-lambda-runtimes.html"), "aws lambda runtimes"))
    log.append(fetch_file(GCP_FEED, os.path.join(FEED_RAW, "gcp-release-notes.xml"), "gcp release notes"))
    log.append(fetch_file(AWS_WHATSNEW, os.path.join(FEED_RAW, "aws-whats-new.xml"), "aws what's new"))
    log.append(fetch_file(AZURE_UPDATES, os.path.join(FEED_RAW, "azure-updates.xml"), "azure updates"))
    for repo in GITHUB_REPOS:
        name = "github-" + repo.replace("/", "-") + ".atom"
        log.append(fetch_file(f"https://github.com/{repo}/releases.atom", os.path.join(FEED_RAW, name), f"github {repo}"))

    print("\n".join(log))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
