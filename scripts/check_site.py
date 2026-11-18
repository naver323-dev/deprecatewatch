#!/usr/bin/env python3
"""생성된 사이트(site/)와 데이터(data/eol_normalized.json)를 검증한다.

검사 항목
  데이터   : 스키마 필수 필드, 날짜 형식, 상태값, 상태-날짜 일치, 중복 슬러그
  HTML     : title/description/canonical, 금칙어, 내부 링크 해석, 외부 스크립트 제한
  구조화데이터: JSON-LD 파싱, @context, FAQ 문항이 화면 본문에 실제로 존재하는지
  자산     : llms.txt·robots.txt·sitemap.xml·api/*.json 내용과 실제 파일 일치
실패가 있으면 exit 1 (배포 중단용).
"""
import html
import json
import os
import re
import sys
from datetime import date
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")
DATA = os.path.join(ROOT, "data")
CONFIG = json.load(open(os.path.join(DATA, "site_config.json"), encoding="utf-8"))
BASE = CONFIG["base_url"].rstrip("/")
DOC = json.load(open(os.path.join(DATA, "eol_normalized.json"), encoding="utf-8"))
AS_OF = DOC["as_of"]
TODAY = date.fromisoformat(AS_OF)

def load_private_tokens():
    """비공개 식별자 목록은 저장소에 두지 않는다.
    로컬(data/forbidden_private.txt, .gitignore)이나 환경변수 FORBIDDEN_EXTRA(쉼표 구분)에서 읽는다."""
    tokens = []
    path = os.path.join(DATA, "forbidden_private.txt")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#"):
                tokens.append(line)
    for extra in (os.environ.get("FORBIDDEN_EXTRA") or "").split(","):
        if extra.strip():
            tokens.append(extra.strip())
    return tokens


# 저장소에 남겨도 되는 일반 규칙 + (선택) 비공개 목록
FORBIDDEN = ["@gmail.com", "@naver.com", "@nate.com", "@kakao.com"] + load_private_tokens()
PLACEHOLDER_TOKENS = ["G-XXXXXXXXXX", "TODO:", "lorem ipsum", "example.com"]

checks = 0
failures = []


def ok(cond, label, detail=""):
    global checks
    checks += 1
    if not cond:
        failures.append(f"{label}{(' — ' + detail) if detail else ''}")


def text_of(path):
    raw = open(path, encoding="utf-8").read()
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t))


def html_files():
    for d, _, files in os.walk(SITE):
        for f in files:
            if f.endswith(".html"):
                yield os.path.join(d, f)


def url_to_path(url):
    """clean URL(/product/nodejs) -> 실제 파일(site/product/nodejs.html)"""
    p = urlparse(url).path
    if p.endswith("/"):
        p += "index.html"
    target = os.path.join(SITE, p.lstrip("/"))
    if not os.path.exists(target) and not p.endswith(".html"):
        target += ".html"
    return target


# ------------------------------------------------------------------ data
def check_data():
    ok(DOC["schema_version"], "data: schema_version present")
    ok(DOC["as_of"] == TODAY.isoformat(), "data: as_of equals today's snapshot date")
    ok(len(DOC["products"]) > 400, "data: product count > 400", str(len(DOC["products"])))
    slugs = set()
    statuses = {"supported", "security-only", "eol", "no-eol-date", "unknown"}
    for p in DOC["products"]:
        ok(p["slug"] not in slugs, f"data: duplicate slug {p['slug']}")
        slugs.add(p["slug"])
        ok(bool(p["cycles"]), f"data: {p['slug']} has cycles")
        for c in p["cycles"]:
            ok(c["eol_status"] in statuses, f"data: {p['slug']} status value {c['eol_status']}")
            if c.get("eol"):
                ok(re.fullmatch(r"\d{4}-\d{2}-\d{2}", c["eol"]) is not None, f"data: {p['slug']} eol format {c['eol']}")
                # 상태는 날짜 비교로만 결정돼야 한다
                expect_eol = date.fromisoformat(c["eol"]) <= TODAY
                ok((c["eol_status"] == "eol") == expect_eol,
                   f"data: {p['slug']} {c['cycle']} status/date mismatch",
                   f"eol={c['eol']} status={c['eol_status']}")
                ok(c.get("days_left") == (date.fromisoformat(c["eol"]) - TODAY).days,
                   f"data: {p['slug']} {c['cycle']} days_left mismatch")
            else:
                ok(c["eol_status"] in ("no-eol-date", "eol", "unknown"),
                   f"data: {p['slug']} {c['cycle']} status without eol date", c["eol_status"])
    total = sum(len(p["cycles"]) for p in DOC["products"])
    ok(DOC["counts"]["cycles"] == total, "data: cycle count matches sum")
    ok(DOC["counts"]["products"] == len(DOC["products"]), "data: product count matches list")
    ok(DOC["counts"]["upcoming_eol_365d"] == len(DOC["upcoming"]), "data: upcoming count matches list")
    # P0-1: eol 대표 숫자는 ‘종료일이 지난’ 것과 ‘종료일 미공개’로 나눠야 한다
    eol_cycles = [c for p in DOC["products"] for c in p["cycles"] if c["eol_status"] == "eol"]
    ok(DOC["counts"]["eol_cycles"] == len(eol_cycles), "data: eol_cycles matches list")
    ok(DOC["counts"].get("eol_with_date") is not None and DOC["counts"].get("eol_without_date") is not None,
       "data: counts.eol_with_date / eol_without_date present")
    ok(DOC["counts"].get("eol_with_date", -1) + DOC["counts"].get("eol_without_date", -1) == len(eol_cycles),
       "data: eol_with_date + eol_without_date == eol_cycles")
    ok(DOC["counts"].get("eol_with_date") == sum(1 for c in eol_cycles if c.get("eol")),
       "data: eol_with_date == cycles with a published date")
    ok(DOC["counts"].get("eol_without_date") == sum(1 for c in eol_cycles if not c.get("eol")),
       "data: eol_without_date == cycles without a published date")
    ok(all(c.get("eol_date_published") == bool(c.get("eol")) for p in DOC["products"] for c in p["cycles"]),
       "data: eol_date_published matches eol field")
    ok("eol-no-date" in DOC["definitions"], "data: definitions has eol-no-date")
    ok("eol" in DOC["definitions"] and "no-eol-date" in DOC["definitions"], "data: status definitions present")
    ok(all(0 <= u["days_left"] <= 365 for u in DOC["upcoming"]), "data: upcoming window is 0..365 days")
    for a in DOC["announcements"]:
        ok(re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.get("date") or "") is not None, "data: announcement date ISO", a.get("title", "")[:40])
        ok(a.get("url", "").startswith("https://"), "data: announcement url https", a.get("title", "")[:40])
    for r in DOC["lambda_runtimes"]:
        ok(bool(r.get("deprecation_date")), "data: lambda runtime has deprecation date", r["name"])


# ------------------------------------------------------------------ html
def check_html():
    pages = list(html_files())
    ok(len(pages) > 500, "html: page count > 500", str(len(pages)))
    titles = set()
    for path in pages:
        raw = open(path, encoding="utf-8").read()
        rel = "/" + os.path.relpath(path, SITE).replace("\\", "/")
        ok("<title>" in raw, f"{rel}: has title")
        m = re.search(r"<title>(.*?)</title>", raw, re.S)
        if m:
            title = html.unescape(m.group(1)).strip()
            ok(len(title) > 12, f"{rel}: title long enough", title)
            ok(title not in titles or rel == "/404.html", f"{rel}: duplicate title", title)
            titles.add(title)
        d = re.search(r'<meta name="description" content="([^"]*)"', raw)
        ok(bool(d) and len(html.unescape(d.group(1))) > 40, f"{rel}: meta description present")
        c = re.search(r'<link rel="canonical" href="([^"]+)"', raw)
        ok(bool(c) and c.group(1).startswith(BASE), f"{rel}: canonical under base url")
        if c:
            expected = rel[:-5] if rel.endswith(".html") and rel != "/index.html" else ("/" if rel == "/index.html" else rel)
            ok(urlparse(c.group(1)).path == expected, f"{rel}: canonical path matches file", c.group(1))
        body = text_of(path)
        for word in FORBIDDEN:
            ok(word.lower() not in raw.lower(), f"{rel}: forbidden token '{word}'")
        for token in PLACEHOLDER_TOKENS:
            ok(token.lower() not in raw.lower(), f"{rel}: placeholder '{token}'")
        ok("<html lang=" in raw and 'lang="en"' in raw, f"{rel}: html lang set")
        # 외부 스크립트는 GA4 태그만 허용
        for src in re.findall(r'<script[^>]+src="([^"]+)"', raw):
            host = urlparse(src).netloc
            ok(host in ("www.googletagmanager.com",), f"{rel}: external script host {host}")
        ok("adsbygoogle" not in raw and "googlesyndication" not in raw, f"{rel}: no ad tags")
        # 내부 링크
        for href in re.findall(r'href="(/[^"#?]*)"', raw):
            ok(not href.endswith(".html") or href == "/404.html", f"{rel}: internal link uses clean URL", href)
            if href.startswith("/api/") or href.endswith((".xml", ".json", ".txt", ".css")):
                target = os.path.join(SITE, href.lstrip("/"))
                ok(os.path.exists(target), f"{rel}: link target exists", href)
            else:
                target = url_to_path(BASE + href)
                ok(os.path.exists(target), f"{rel}: link target exists", href)


def check_product_pages():
    for p in DOC["products"]:
        path = os.path.join(SITE, "product", p["slug"] + ".html")
        ok(os.path.exists(path), f"product: page for {p['slug']}")
        if not os.path.exists(path):
            continue
        body = text_of(path)
        ok(p["name"] in body, f"product {p['slug']}: name shown")
        cycles = p["cycles"][:60]
        for c in cycles[:60]:
            if c.get("eol"):
                ok(c["eol"] in body, f"product {p['slug']}: EOL {c['eol']} shown for cycle {c['cycle']}")
        if p["cycles"][0].get("eol"):
            ok(p["cycles"][0]["eol"] in body, f"product {p['slug']}: current EOL in direct answer")
        # P0-1: eol인데 날짜가 없으면 ‘date not published’로 표기
        undated_eol = [c for c in cycles if c["eol_status"] == "eol" and not c.get("eol")]
        if undated_eol:
            ok("date not published" in body, f"product {p['slug']}: eol without date labelled")
        # P1-1: meta description은 마침표로 끝나는 문장이어야 한다(붙여 쓴 비문 금지)
        raw = open(path, encoding="utf-8").read()
        d = re.search(r'<meta name="description" content="([^"]*)"', raw)
        if d:
            desc = html.unescape(d.group(1)).strip()
            ok(desc.endswith((".", "!", "?")), f"product {p['slug']}: description ends with punctuation", desc[-60:])
            ok(") the " not in desc and ") the next" not in desc,
               f"product {p['slug']}: no glued clause after parenthesis", desc[-80:])
            ok("  " not in desc, f"product {p['slug']}: no double space in description")
            ok(desc.count(".") >= 1, f"product {p['slug']}: description has sentences", desc[-60:])


def check_jsonld():
    pages = 0
    for path in html_files():
        raw = open(path, encoding="utf-8").read()
        blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', raw, re.S)
        if not blocks:
            continue
        pages += 1
        rel = "/" + os.path.relpath(path, SITE).replace("\\", "/")
        body = text_of(path)
        for b in blocks:
            try:
                obj = json.loads(b)
            except json.JSONDecodeError as ex:
                ok(False, f"{rel}: JSON-LD parses", str(ex))
                continue
            ok(obj.get("@context") == "https://schema.org", f"{rel}: JSON-LD @context")
            for node in (obj.get("@graph") or [obj]):
                if node.get("@type") == "FAQPage":
                    qs = node.get("mainEntity") or []
                    ok(len(qs) >= 2, f"{rel}: FAQ has >=2 questions")
                    for q in qs:
                        ok(q["name"] in body, f"{rel}: FAQ question visible on page", q["name"][:50])
                        ok(q["acceptedAnswer"]["text"] in body, f"{rel}: FAQ answer visible on page", q["name"][:50])
                if node.get("@type") == "Dataset":
                    ok(node.get("dateModified") == AS_OF, f"{rel}: Dataset dateModified = as_of")
                    ok(node.get("distribution"), f"{rel}: Dataset distribution listed")
    ok(pages > 500, "jsonld: most pages carry structured data", str(pages))


def check_assets():
    llms = open(os.path.join(SITE, "llms.txt"), encoding="utf-8").read()
    ok(llms.startswith("# DeprecateWatch"), "llms.txt: heading")
    ok(AS_OF in llms, "llms.txt: carries as_of")
    for path in ("/api/eol.json", "/api/products.json", "/api/upcoming.json", "/api/announcements.json",
                 "/product/{slug}", "/llms.txt"):
        ok(path in llms, f"llms.txt: mentions {path}")

    robots = open(os.path.join(SITE, "robots.txt"), encoding="utf-8").read()
    for bot in ("GPTBot", "ClaudeBot", "PerplexityBot", "Google-Extended", "CCBot", "OAI-SearchBot"):
        ok(f"User-agent: {bot}" in robots, f"robots.txt: allows {bot}")
    ok("Sitemap: " + BASE + "/sitemap.xml" in robots, "robots.txt: sitemap line")

    sm = open(os.path.join(SITE, "sitemap.xml"), encoding="utf-8").read()
    urls = re.findall(r"<loc>([^<]+)</loc>", sm)
    ok(len(urls) >= 520, "sitemap: url count", str(len(urls)))
    ok(len(urls) == len(set(urls)), "sitemap: no duplicate urls")
    for u in urls:
        ok(u.startswith(BASE + "/"), "sitemap: url under base", u[:60])
        ok(os.path.exists(url_to_path(u)), "sitemap: target file exists", u)
    for p in DOC["products"]:
        ok(f"{BASE}/product/{p['slug']}" in urls, f"sitemap: has {p['slug']}")

    for name in ("eol.json", "products.json", "upcoming.json", "announcements.json"):
        path = os.path.join(SITE, "api", name)
        ok(os.path.exists(path), f"api: {name} exists")
        doc = json.load(open(path, encoding="utf-8"))
        ok(doc.get("as_of") == AS_OF, f"api {name}: as_of")
        for word in FORBIDDEN:
            ok(word.lower() not in json.dumps(doc, ensure_ascii=False).lower(), f"api {name}: forbidden '{word}'")
    eol = json.load(open(os.path.join(SITE, "api", "eol.json"), encoding="utf-8"))
    ok(len(eol["products"]) == len(DOC["products"]), "api eol.json: all products")
    prods = json.load(open(os.path.join(SITE, "api", "products.json"), encoding="utf-8"))
    ok(prods["count"] == len(DOC["products"]), "api products.json: count")
    up = json.load(open(os.path.join(SITE, "api", "upcoming.json"), encoding="utf-8"))
    ok(up["count"] == len(DOC["upcoming"]), "api upcoming.json: count")
    ann = json.load(open(os.path.join(SITE, "api", "announcements.json"), encoding="utf-8"))
    ok(ann["count"] == len(DOC["announcements"]), "api announcements.json: count")

    css = os.path.join(SITE, "assets", "style.css")
    ok(os.path.exists(css) and os.path.getsize(css) > 1000, "assets: style.css")


def check_home_numbers():
    body = text_of(os.path.join(SITE, "index.html"))
    for n in (len(DOC["products"]), DOC["counts"]["cycles"],
              DOC["counts"].get("eol_with_date", DOC["counts"]["eol_cycles"]),
              DOC["counts"].get("eol_without_date", 0),
              DOC["counts"]["upcoming_eol_365d"]):
        ok(f"{n:,}" in body or str(n) in body, f"home: shows {n:,}")
    # 대표 숫자를 ‘모두 종료일이 지난 것’처럼 말하지 않는다(P0-1)
    ok("past their published EOL date" in body, "home: dated EOL wording")
    ok(f"{DOC['counts']['eol_cycles']:,}</strong><span>cycles past" not in body,
       "home: no single EOL count labelled as past their date")


def check_lastmod():
    """P1-2: lastmod·dateModified는 빌드일 고정이 아니라 페이지별 실제 변경일이어야 한다."""
    sm = open(os.path.join(SITE, "sitemap.xml"), encoding="utf-8").read()
    lastmods = re.findall(r"<lastmod>([^<]+)</lastmod>", sm)
    ok(len(lastmods) > 500, "sitemap: lastmod on every url", str(len(lastmods)))
    ok(all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", v or "") for v in lastmods), "sitemap: lastmod is an ISO date")
    ok(all(v <= TODAY.isoformat() for v in lastmods), "sitemap: lastmod is never in the future")
    ok(os.path.exists(os.path.join(ROOT, "data", "site_state.json")), "state: data/site_state.json written")
    state = json.load(open(os.path.join(ROOT, "data", "site_state.json"), encoding="utf-8"))
    ok(len(state.get("pages", {})) > 500, "state: page fingerprints recorded", str(len(state.get("pages", {}))))
    probe = open(os.path.join(SITE, "product", "nodejs.html"), encoding="utf-8").read()
    ok('"dateModified":"' + state["pages"]["/product/nodejs"]["lastmod"] in probe.replace(" ", ""),
       "product nodejs: JSON-LD dateModified uses page lastmod")


def check_api_metadata():
    """P1-3: 모든 API에 출처·라이선스·인용 문구가 있다."""
    for name in ("eol.json", "products.json", "upcoming.json", "announcements.json"):
        doc = json.load(open(os.path.join(SITE, "api", name), encoding="utf-8"))
        ok("MIT" in json.dumps(doc.get("license", "")), f"api {name}: license")
        ok("DeprecateWatch" in doc.get("attribution", ""), f"api {name}: attribution")
        ok(bool(doc.get("sources")), f"api {name}: sources")
        ok(doc.get("as_of") == DOC["as_of"], f"api {name}: as_of")


def check_ga():
    ga = CONFIG.get("ga_id")
    if not ga:
        print("note: GA4 measurement ID not configured — skipping GA checks")
        return
    home = open(os.path.join(SITE, "index.html"), encoding="utf-8").read()
    ok(f"googletagmanager.com/gtag/js?id={ga}" in home, "ga: tag in home")
    ok(ga in open(os.path.join(SITE, "privacy.html"), encoding="utf-8").read(), "ga: disclosed in privacy page")
    for path in html_files():
        raw = open(path, encoding="utf-8").read()
        ok(ga in raw, f"ga: tag on {os.path.relpath(path, SITE)}")


def main():
    check_data()
    check_html()
    check_product_pages()
    check_jsonld()
    check_assets()
    check_home_numbers()
    check_lastmod()
    check_api_metadata()
    check_ga()
    print(f"checks run: {checks}")
    if failures:
        print(f"FAILED {len(failures)}")
        for f in failures[:40]:
            print("  -", f)
        sys.exit(1)
    print("PASS — all checks green")


if __name__ == "__main__":
    main()
