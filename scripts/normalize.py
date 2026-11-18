#!/usr/bin/env python3
"""수집한 원문(data/raw)을 표준 스키마 한 파일(data/eol_normalized.json)로 정규화한다.

원칙
  - 날짜·버전은 원문 응답에 있는 값만 쓴다(추정·보간 없음).
  - 상태(status)는 오늘 날짜와 원문 날짜의 비교로만 계산한다.
  - 대체 경로(replacement)는 ① 원문에 명시된 권장 대체 ② 같은 제품의 '현재 지원 중인 최신 사이클'
    두 가지 사실만 쓴다. 임의 추천은 넣지 않는다.
"""
import html
import json
import os
import re
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
RAW = os.path.join(DATA, "raw")
KST = timezone(timedelta(hours=9))

KEYWORDS = re.compile(
    r"deprecat|end[ -]of[ -](support|life)|\bEOL\b|no longer (be )?(supported|available)|"
    r"retire(ment|d)?|sunset|breaking change|drop(ped|s)? support|removed? in",
    re.IGNORECASE,
)

CATEGORY_LABEL = {
    "lang": "Languages & runtimes",
    "framework": "Frameworks & libraries",
    "server-app": "Server applications",
    "app": "Desktop & mobile apps",
    "os": "Operating systems",
    "database": "Databases & datastores",
    "service": "Cloud & managed services",
    "device": "Devices & hardware",
    "standard": "Standards",
}


def read(path, mode="r"):
    with open(path, mode) as f:
        return f.read()


def clean(text):
    text = re.sub(r"<!\[CDATA\[|\]\]>", "", text or "")
    text = html.unescape(text)          # &lt;li&gt; 같은 이스케이프된 태그를 먼저 편다
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_date(value):
    """다양한 표기(ISO, 'Nov 10, 2026')를 date로. 실패하면 None."""
    if not value:
        return None
    value = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return date.fromisoformat(value)
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def cycle_status(cycle, today):
    eol = cycle.get("eol")
    support = cycle.get("support")
    if eol is False:
        return "no-eol-date"
    if eol is True:
        return "eol"
    d = parse_date(eol) if isinstance(eol, str) else None
    if d is None:
        return "unknown"
    if d <= today:
        return "eol"
    sd = parse_date(support) if isinstance(support, str) else None
    if sd and sd <= today:
        return "security-only"
    return "supported"


def normalize_cycle(cycle, today):
    eol = cycle.get("eol")
    support = cycle.get("support")
    eol_date = eol if isinstance(eol, str) else None
    status = cycle_status(cycle, today)
    lts = cycle.get("lts")
    replacement = cycle.get("recommendedReplacement")
    if isinstance(replacement, str) and replacement.strip().upper() in ("N/A", "NONE", ""):
        replacement = None
    out = {
        "cycle": str(cycle.get("cycle")),
        "release_date": cycle.get("releaseDate") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(cycle.get("releaseDate") or "")) else None,
        "support_end": support if isinstance(support, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", support) else None,
        "eol": eol_date,
        "eol_status": status,
        # eol로 표시되어 있지만 원문에 종료일이 없는 사이클(eol: true, eolFrom: null)을 구분한다
        "eol_date_published": bool(eol_date),
        "latest": cycle.get("latest"),
        "latest_release_date": cycle.get("latestReleaseDate") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(cycle.get("latestReleaseDate") or "")) else None,
        "lts": bool(lts) if not isinstance(lts, str) else True,
        "lts_since": lts if isinstance(lts, str) else None,
        "extended_support": cycle.get("extended_support", cycle.get("extendedSupport")) if isinstance(cycle.get("extendedSupport"), (str, bool)) else None,
        "discontinued": cycle.get("discontinued") if isinstance(cycle.get("discontinued"), str) else None,
        "replacement": replacement,
        "release_label": cycle.get("releaseLabel"),
        "link": cycle.get("link"),
        "days_left": None,
    }
    if eol_date:
        out["days_left"] = (date.fromisoformat(eol_date) - today).days
    if not out["release_date"]:
        out.pop("release_date")
    for k in ("support_end", "latest", "latest_release_date", "release_label", "link", "lts_since", "extended_support", "discontinued"):
        if out.get(k) in (None, ""):
            out.pop(k, None)
    return out


def build_products(today):
    meta = json.load(open(os.path.join(DATA, "products_v1.json"), encoding="utf-8"))
    products = []
    for entry in meta["result"]:
        slug = entry["name"]
        path = os.path.join(RAW, "endoflife", slug + ".json")
        if not os.path.exists(path):
            continue
        raw_cycles = json.load(open(path, encoding="utf-8"))
        if not raw_cycles:
            continue
        cycles = [normalize_cycle(c, today) for c in raw_cycles]
        cycles.sort(key=lambda c: (c.get("release_date") or ""), reverse=True)
        current = cycles[0]
        # 현재 지원 중인 최신 사이클(대체 경로 계산용, 원문 날짜 기준)
        supported = [c for c in cycles if c["eol_status"] in ("supported", "security-only")]
        newest_supported = supported[0] if supported else None
        eol_cycles = [c for c in cycles if c["eol_status"] == "eol"]
        soonest = None
        upcoming = [c for c in cycles if c.get("days_left") is not None and c["days_left"] >= 0]
        if upcoming:
            soonest = min(upcoming, key=lambda c: c["days_left"])
        products.append({
            "slug": slug,
            "name": entry.get("label") or slug,
            "aliases": entry.get("aliases") or [],
            "category": entry.get("category"),
            "tags": entry.get("tags") or [],
            "cycle_count": len(cycles),
            "latest_cycle": current["cycle"],
            "latest_version": current.get("latest"),
            "latest_release_date": current.get("latest_release_date"),
            "current_status": current["eol_status"],
            "current_support_end": current.get("support_end"),
            "current_eol": current.get("eol"),
            "soonest_eol": {"cycle": soonest["cycle"], "eol": soonest["eol"], "days_left": soonest["days_left"]} if soonest else None,
            "active_cycle": newest_supported["cycle"] if newest_supported else None,
            "eol_cycle_count": len(eol_cycles),
            "cycles": cycles,
            "source_url": f"https://endoflife.date/{slug}",
        })
    products.sort(key=lambda p: p["name"].lower())
    return products


def build_lambda_runtimes(today):
    path = os.path.join(RAW, "feeds", "aws-lambda-runtimes.html")
    if not os.path.exists(path):
        return []
    raw = read(path)
    tables = re.findall(r"<table.*?</table>", raw, re.S)
    target = None
    for t in tables:
        head = clean(t[:600]).lower()
        if "deprecation date" in head and "identifier" in head:
            target = t
    if not target:
        return []
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", target, re.S)
    out = []
    for r in rows[1:]:
        cells = [clean(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", r, re.S)]
        if len(cells) < 6 or not cells[0]:
            continue
        dep = parse_date(cells[3])
        block_create = parse_date(cells[4])
        block_update = parse_date(cells[5])
        out.append({
            "name": cells[0],
            "identifier": cells[1],
            "os": cells[2],
            "deprecation_date": dep.isoformat() if dep else None,
            "block_create": block_create.isoformat() if block_create else None,
            "block_update": block_update.isoformat() if block_update else None,
            "status": ("deprecated" if dep and dep <= today else "scheduled" if dep else "unknown"),
            "days_left": (dep - today).days if dep else None,
            "source_url": "https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html#runtimes-deprecated",
        })
    out.sort(key=lambda x: x.get("deprecation_date") or "9999")
    return out


def parse_gcp(today):
    path = os.path.join(RAW, "feeds", "gcp-release-notes.xml")
    if not os.path.exists(path):
        return []
    raw = read(path)
    items = []
    for entry in re.findall(r"<entry>(.*?)</entry>", raw, re.S):
        day = clean(re.search(r"<title>(.*?)</title>", entry, re.S).group(1))
        updated = re.search(r"<updated>(.*?)</updated>", entry, re.S)
        link = re.search(r'<link[^>]*href="([^"]+)"', entry)
        content_m = re.search(r"<content[^>]*>(.*?)</content>", entry, re.S)
        if not content_m:
            continue
        content = content_m.group(1)
        iso = updated.group(1)[:10] if updated else None
        # 제품(h2) 단위로 자른 뒤 변경 유형(h3)별 노트로 나눈다
        sections = re.split(r'<h2 class="release-note-product-title">', content)[1:]
        for sec in sections:
            product = clean(sec.split("</h2>")[0])
            body = sec.split("</h2>", 1)[1] if "</h2>" in sec else ""
            notes = re.split(r"<h3[^>]*>", body)
            pending_type = None
            for chunk in notes:
                if not chunk.strip():
                    continue
                kind = clean(chunk.split("</h3>")[0]) if "</h3>" in chunk else ""
                text = clean(chunk.split("</h3>", 1)[1]) if "</h3>" in chunk else clean(chunk)
                if not text:
                    if kind:
                        pending_type = kind
                    continue
                if kind in ("Deprecated", "Change", "Announcement", "Breaking"):
                    if kind == "Deprecated" or KEYWORDS.search(text):
                        items.append({
                            "source": "gcp",
                            "source_label": "Google Cloud release notes",
                            "date": iso,
                            "title": f"{product}: {kind}",
                            "product": product,
                            "kind": kind,
                            "summary": text[:600],
                            "url": (link.group(1) if link else "https://cloud.google.com/release-notes"),
                            "matched": sorted({m.group(0).lower() for m in KEYWORDS.finditer(text)}),
                        })
                pending_type = None
    return items


def parse_aws_whatsnew(today):
    path = os.path.join(RAW, "feeds", "aws-whats-new.xml")
    if not os.path.exists(path):
        return []
    raw = read(path)
    items = []
    for item in re.findall(r"<item>(.*?)</item>", raw, re.S):
        title_m = re.search(r"<title>(.*?)</title>", item, re.S)
        title = clean(title_m.group(1)) if title_m else ""
        desc_m = re.search(r"<description>(.*?)</description>", item, re.S)
        desc = clean(desc_m.group(1)) if desc_m else ""
        link_m = re.search(r"<link>(.*?)</link>", item, re.S)
        pub_m = re.search(r"<pubDate>(.*?)</pubDate>", item, re.S)
        if not KEYWORDS.search(title + " " + desc):
            continue
        pub = None
        if pub_m:
            try:
                pub = datetime.strptime(pub_m.group(1).strip(), "%a, %d %b %Y %H:%M:%S %z").astimezone(KST).date().isoformat()
            except ValueError:
                pub = None
        items.append({
            "source": "aws",
            "source_label": "AWS What's New",
            "date": pub,
            "title": title,
            "product": "AWS",
            "kind": "announcement",
            "summary": desc[:600],
            "url": clean(link_m.group(1)) if link_m else "https://aws.amazon.com/new/",
            "matched": sorted({m.group(0).lower() for m in KEYWORDS.finditer(title + " " + desc)}),
        })
    return items


def parse_github(today):
    items = []
    feed_dir = os.path.join(RAW, "feeds")
    for fn in sorted(os.listdir(feed_dir)):
        if not (fn.startswith("github-") and fn.endswith(".atom")):
            continue
        repo = fn[len("github-"):-len(".atom")].replace("-", "/", 1)
        raw = read(os.path.join(feed_dir, fn))
        for entry in re.findall(r"<entry>(.*?)</entry>", raw, re.S):
            title_m = re.search(r"<title>(.*?)</title>", entry, re.S)
            link_m = re.search(r'<link[^>]*href="([^"]+)"', entry)
            upd_m = re.search(r"<updated>(.*?)</updated>", entry)
            content_m = re.search(r"<content[^>]*>(.*?)</content>", entry, re.S)
            title = clean(title_m.group(1)) if title_m else ""
            content = clean(content_m.group(1)) if content_m else ""
            if not content or len(content) < 80:
                continue
            # 키워드가 포함된 문장만 요약으로 쓴다(원문 문장 그대로, 가공 없음)
            sentences = re.split(r"(?<=[.!?])\s+", content)
            hits = [s for s in sentences if KEYWORDS.search(s) and 40 <= len(s) <= 500]
            if not hits:
                continue
            items.append({
                "source": "github",
                "source_label": f"GitHub releases · {repo}",
                "date": upd_m.group(1)[:10] if upd_m else None,
                "title": f"{repo} {title}".strip(),
                "product": repo,
                "kind": "release",
                "summary": hits[0][:600],
                "url": link_m.group(1) if link_m else f"https://github.com/{repo}/releases",
                "matched": sorted({m.group(0).lower() for m in KEYWORDS.finditer(hits[0])}),
            })
    return items


def parse_azure(today):
    """Azure service updates RSS — retire/deprecat 문구가 있는 항목만."""
    path = os.path.join(RAW, "feeds", "azure-updates.xml")
    if not os.path.exists(path):
        return []
    raw = read(path).lstrip("\ufeff")
    items = []
    for item in re.findall(r"<item>(.*?)</item>", raw, re.S):
        title_m = re.search(r"<title>(.*?)</title>", item, re.S)
        desc_m = re.search(r"<description>(.*?)</description>", item, re.S)
        link_m = re.search(r"<link>(.*?)</link>", item, re.S)
        date_m = re.search(r"<pubDate>(.*?)</pubDate>", item, re.S)
        title = clean(title_m.group(1)) if title_m else ""
        desc = clean(desc_m.group(1)) if desc_m else ""
        if not KEYWORDS.search(title + " " + desc):
            continue
        iso = None
        if date_m:
            for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S GMT", "%Y-%m-%dT%H:%M:%SZ"):
                try:
                    iso = datetime.strptime(date_m.group(1).strip(), fmt).astimezone(KST).date().isoformat()
                    break
                except ValueError:
                    continue
        items.append({
            "source": "azure",
            "source_label": "Azure service updates",
            "date": iso,
            "title": title,
            "product": "Azure",
            "kind": "announcement",
            "summary": desc[:600],
            "url": clean(link_m.group(1)) if link_m else "https://azure.microsoft.com/en-us/updates/",
            "matched": sorted({m.group(0).lower() for m in KEYWORDS.finditer(title + " " + desc)}),
        })
    return items


def main():
    today = datetime.now(KST).date()
    products = build_products(today)
    lambda_runtimes = build_lambda_runtimes(today)
    announcements = parse_gcp(today) + parse_aws_whatsnew(today) + parse_azure(today) + parse_github(today)
    announcements = [a for a in announcements if a.get("date")]
    announcements.sort(key=lambda a: a["date"], reverse=True)
    # 같은 내용이 다른 날짜에 반복되는 경우(릴리스 노트 재게시)를 걸러 낸다
    seen = set()
    uniq = []
    for a in announcements:
        key = (a["source"], a["product"], re.sub(r"\W+", "", a["summary"])[:120])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(a)
    announcements = uniq[:400]

    cycles_total = sum(len(p["cycles"]) for p in products)
    eol_cycles = sum(1 for p in products for c in p["cycles"] if c["eol_status"] == "eol")
    eol_with_date = sum(1 for p in products for c in p["cycles"] if c["eol_status"] == "eol" and c.get("eol_date_published"))
    eol_without_date = eol_cycles - eol_with_date
    upcoming = []
    for p in products:
        for c in p["cycles"]:
            if c.get("days_left") is not None and 0 <= c["days_left"] <= 365:
                upcoming.append({
                    "slug": p["slug"], "name": p["name"], "category": p["category"],
                    "cycle": c["cycle"], "eol": c["eol"], "days_left": c["days_left"],
                    "support_end": c.get("support_end"), "latest": c.get("latest"),
                    "active_cycle": p.get("active_cycle"), "active_version": p.get("latest_version"),
                    "replacement": c.get("replacement"),
                })
    upcoming.sort(key=lambda u: (u["eol"], u["name"]))

    doc = {
        "schema_version": "1.1.0",
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "as_of": today.isoformat(),
        "timezone": "Asia/Seoul",
        "counts": {
            "products": len(products),
            "cycles": cycles_total,
            "eol_cycles": eol_cycles,
            "eol_with_date": eol_with_date,
            "eol_without_date": eol_without_date,
            "upcoming_eol_365d": len(upcoming),
            "lambda_runtimes": len(lambda_runtimes),
            "announcements": len(announcements),
        },
        "definitions": {
            "supported": "EOL date is in the future (and active support has not ended).",
            "security-only": "Active support has ended but the EOL date is still in the future.",
            "eol": "The cycle is end of life: the published EOL date has passed, or the upstream marks it end of life without a date.",
            "eol-with-date": "Status eol and the upstream publishes an EOL date that has passed (counts.eol_with_date).",
            "eol-no-date": "Status eol but the upstream publishes no EOL date for that cycle (eol=true, eolFrom=null in the source). Shown as 'End of life (date not published)'; no date is invented (counts.eol_without_date).",
            "no-eol-date": "The upstream project publishes no EOL date and does not mark the cycle end of life (eol=false in the source).",
        },
        "sources": [
            {"id": "endoflife", "name": "endoflife.date API v1", "url": "https://endoflife.date/docs/api",
             "license": "MIT (endoflife.date contributors)", "used_for": "product cycles, support and EOL dates"},
            {"id": "aws-lambda", "name": "AWS Lambda runtimes (deprecated runtimes table)", "url": "https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html",
             "license": "AWS documentation", "used_for": "Lambda runtime deprecation dates"},
            {"id": "gcp", "name": "Google Cloud release notes feed", "url": "https://cloud.google.com/release-notes",
             "license": "Google Cloud documentation", "used_for": "deprecation notes"},
            {"id": "aws", "name": "AWS What's New feed", "url": "https://aws.amazon.com/new/",
             "license": "AWS", "used_for": "retirement announcements"},
            {"id": "azure", "name": "Azure service updates feed", "url": "https://azure.microsoft.com/en-us/updates/",
             "license": "Microsoft documentation", "used_for": "retirement announcements"},
            {"id": "github", "name": "GitHub releases feeds", "url": "https://github.com",
             "license": "respective projects", "used_for": "breaking changes in release notes"},
        ],
        "products": products,
        "upcoming": upcoming,
        "lambda_runtimes": lambda_runtimes,
        "announcements": announcements,
    }
    out = os.path.join(DATA, "eol_normalized.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    print(json.dumps(doc["counts"], indent=2, ensure_ascii=False))
    print("size: %.1f MB" % (os.path.getsize(out) / 1e6))
    print("upcoming sample:", [ (u["name"], u["cycle"], u["eol"]) for u in upcoming[:5]])
    print("announcement sources:", {s: sum(1 for a in announcements if a["source"] == s) for s in ("gcp", "aws", "azure", "github")})


if __name__ == "__main__":
    main()
