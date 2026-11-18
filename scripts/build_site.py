#!/usr/bin/env python3
"""정규화 데이터(data/eol_normalized.json)로 정적 사이트(site/)를 만든다.

- JavaScript 없이 읽히는 정적 HTML 표 + JSON API + llms.txt (AI 크롤러용)
- 모든 수치는 데이터에서 계산한다(하드코딩 없음)
- 광고·추적은 GA4 하나뿐이며 privacy.html에 명시한다
"""
import html
import hashlib
import json
import os
import re
import shutil
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SITE = os.path.join(ROOT, "site")
KST = timezone(timedelta(hours=9))

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
CATEGORY_ORDER = list(CATEGORY_LABEL)

STATUS_LABEL = {
    "supported": "Supported",
    "security-only": "Security-only",
    "eol": "End of life",
    "no-eol-date": "No EOL date",
    "unknown": "Unknown",
}

CONFIG = json.load(open(os.path.join(DATA, "site_config.json"), encoding="utf-8"))
DOC = json.load(open(os.path.join(DATA, "eol_normalized.json"), encoding="utf-8"))
BASE = CONFIG["base_url"].rstrip("/")
GA = CONFIG.get("ga_id") or ""
AS_OF = DOC["as_of"]
GENERATED = DOC["generated_at"]
TODAY = date.fromisoformat(AS_OF)
PRODUCTS = {p["slug"]: p for p in DOC["products"]}
PRODUCT_LIST = DOC["products"]


# ---------------------------------------------------------------- formatting
def e(text):
    return html.escape(str(text if text is not None else ""), quote=True)


def fmt_date(iso):
    if not iso:
        return "—"
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return e(iso)
    return d.isoformat()


def human(iso_en):
    """2026-11-18 -> 18 November 2026 (화면용)"""
    if not iso_en or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", iso_en):
        return "—"
    d = date.fromisoformat(iso_en)
    return f"{d.day} {d.strftime('%B')} {d.year}"


def days_phrase(n):
    if n is None:
        return ""
    if n == 0:
        return "today"
    if n > 0:
        return f"in {n} day{'s' if n != 1 else ''}"
    return f"{abs(n)} day{'s' if abs(n) != 1 else ''} ago"


def badge(status):
    return f'<span class="badge b-{e(status)}">{e(STATUS_LABEL.get(status, status))}</span>'


# ----------------------------------------------------- last modified (교차검수 P1-2)
# 페이지 본문 전체 대신 그 페이지가 보여 주는 ‘데이터 지문’을 저장하고 비교한다.
# 기준일(as_of)·생성시각처럼 매주 바뀌는 값은 지문에 넣지 않으므로, 재빌드만으로는
# lastmod·dateModified가 갱신되지 않는다(주 1회 재빌드 때 전 페이지가 ‘변경’으로 보이던 문제).
STATE_PATH = os.path.join(DATA, "site_state.json")
try:
    _STATE = json.load(open(STATE_PATH, encoding="utf-8"))
except (OSError, ValueError):
    _STATE = {}
PAGE_STATE = _STATE.get("pages") if isinstance(_STATE.get("pages"), dict) else {}
LAST_MOD = {}


def mod_key(path):
    key = re.sub(r"\.html$", "", path)
    if key.endswith("/index"):
        key = key[: -len("index")]
    return key


def note_mod(path, payload):
    """이 페이지 내용의 마지막 변경일을 정한다(지문이 같으면 이전 날짜 유지)."""
    key = mod_key(path)
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()
    prev = PAGE_STATE.get(key) or {}
    lastmod = prev["lastmod"] if prev.get("hash") == digest and prev.get("lastmod") else AS_OF
    PAGE_STATE[key] = {"hash": digest, "lastmod": lastmod}
    LAST_MOD[key] = lastmod
    return lastmod


def mod_of(path):
    key = mod_key(path)
    return LAST_MOD.get(key) or (PAGE_STATE.get(key) or {}).get("lastmod") or AS_OF


def compute_mod_payloads():
    """모든 페이지의 데이터 지문을 먼저 계산해 둔다(JSON-LD dateModified가 이를 쓴다)."""
    products_sig = {
        p["slug"]: [tuple(str(c.get(k) or "") for k in
                          ("cycle", "release_date", "support_end", "eol", "eol_status", "latest", "lts"))
                    for c in p["cycles"]] for p in PRODUCT_LIST
    }
    note_mod("/", {
        "counts": DOC["counts"],
        "products": {k: v[:3] for k, v in products_sig.items()},
        "upcoming90": [(u["slug"], u["cycle"], u["eol"]) for u in UPCOMING_90],
        "lambda": [(r["identifier"], r.get("deprecation_date"), r["status"]) for r in LAMBDA],
        "ann": [(a["source"], a["date"], a["title"]) for a in ANNOUNCEMENTS[:10]],
    })
    note_mod("/categories.html", {
        "products": {k: (p["name"], p["category"]) for k, p in
                     ((x["slug"], x) for x in PRODUCT_LIST)},
    })
    note_mod("/calendar.html", {"upcoming": [(u["slug"], u["cycle"], u["eol"]) for u in UPCOMING]})
    note_mod("/announcements.html", [(a["source"], a["date"], a["title"], a["url"]) for a in ANNOUNCEMENTS])
    note_mod("/about.html", {"sources": DOC["sources"], "products": len(PRODUCT_LIST)})
    note_mod("/privacy.html", {"page": "privacy"})
    for p in PRODUCT_LIST:
        note_mod(f"/product/{p['slug']}.html", {
            "cycles": products_sig[p["slug"]],
            "active_cycle": p.get("active_cycle"),
            "name": p["name"],
        })
    for cat, items in BY_CAT.items():
        note_mod(f"/category/{cat}.html", [(x["slug"], x["name"], x.get("soonest_eol")) for x in items])
    for month, items in MONTH_INDEX.items():
        note_mod(f"/eol/{month}.html",
                 [(u["slug"], u["cycle"], u["eol"], "past" if u["eol"] <= AS_OF else "upcoming") for u in items])


def save_mod_state():
    os.makedirs(DATA, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({"as_of": AS_OF, "pages": dict(sorted(PAGE_STATE.items()))}, f,
                  ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")


def rel(url):
    """사이트 내부 절대 경로"""
    return f"{BASE}{url}"


def public_urls(text):
    """Cloudflare Pages는 .html 확장자를 308로 clean URL에 넘긴다.
    링크·canonical·JSON-LD의 URL을 실제로 200을 주는 clean URL 형태로 맞춘다."""
    text = re.sub(r'(https://[a-z0-9.-]+\.[a-z]{2,}[^"<\s]*?)\.html(?=["<\s),]|$)', r'\1', text)
    text = re.sub(r'href="(/[^"#]*?)\.html"', r'href="\1"', text)
    text = text.replace('href="/index"', 'href="/"')
    return text


# ---------------------------------------------------------------- layout
NAV = [
    ("/", "Home"),
    ("/categories.html", "Categories"),
    ("/calendar.html", "Calendar"),
    ("/announcements.html", "Announcements"),
    ("/about.html", "Method"),
]


def layout(title, description, path, body, jsonld=None, nav_key="/", wide=False):
    canonical = rel(path)
    nav_html = "".join(
        f'<a href="{href}"{" aria-current=\"page\"" if href == nav_key else ""}>{label}</a>'
        for href, label in NAV
    )
    ld = ""
    if jsonld:
        payload = jsonld if isinstance(jsonld, list) else [jsonld]
        blocks = []
        for obj in payload:
            blocks.append(
                '<script type="application/ld+json">'
                + json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
                + "</script>"
            )
        ld = "\n".join(blocks)
    ga = ""
    if GA:
        ga = f"""
<!-- Google Analytics 4 (aggregate pageviews only) -->
<script async src="https://www.googletagmanager.com/gtag/js?id={e(GA)}"></script>
<script>
window.dataLayer = window.dataLayer || [];
function gtag(){{dataLayer.push(arguments);}}
gtag('js', new Date());
gtag('config', '{e(GA)}', {{anonymize_ip: true}});
</script>"""
    return public_urls(f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(description)}">
<link rel="canonical" href="{e(canonical)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{e(CONFIG['site_name'])}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(description)}">
<meta property="og:url" content="{e(canonical)}">
<meta name="twitter:card" content="summary">
<link rel="stylesheet" href="/assets/style.css">
<link rel="alternate" type="application/json" href="/api/eol.json" title="DeprecateWatch EOL dataset (JSON)">
{ld}{ga}
</head>
<body>
<header class="top">
  <div class="wrap">
    <a class="brand" href="/">Deprecate<span>Watch</span></a>
    <nav>{nav_html}</nav>
  </div>
</header>
<main class="wrap{' wide' if wide else ''}">
{body}
</main>
<footer class="foot">
  <div class="wrap">
    <p><strong>DeprecateWatch</strong> — static end-of-life archive. Data as of <time datetime="{e(AS_OF)}">{e(AS_OF)}</time>.
    EOL and support dates come from the <a href="https://endoflife.date" rel="noopener">endoflife.date</a> API
    (MIT License, © endoflife.date contributors) and from vendor documentation and release feeds linked in each row.
    Not affiliated with any vendor. Always confirm a deadline with the vendor before you plan a migration.</p>
    <p class="small"><a href="/about.html">Method &amp; sources</a> · <a href="/llms.txt">llms.txt</a> ·
    <a href="/api/eol.json">JSON API</a> · <a href="/sitemap.xml">Sitemap</a> · <a href="/privacy.html">Privacy</a></p>
  </div>
</footer>
</body>
</html>
""")


def page(path, content):
    full = os.path.join(SITE, path.lstrip("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)


# ---------------------------------------------------------------- data helpers
def status_counts():
    counts = {"supported": 0, "security-only": 0, "eol": 0, "no-eol-date": 0, "unknown": 0}
    for p in PRODUCT_LIST:
        for c in p["cycles"]:
            counts[c["eol_status"]] = counts.get(c["eol_status"], 0) + 1
    return counts


COUNTS = status_counts()
# eol 상태를 ‘종료일이 있는’ 것과 ‘원문에 종료일이 없는’ 것으로 나눈 수(교차검수 P0-1)
EOL_WITH_DATE = sum(1 for p in PRODUCT_LIST for c in p["cycles"]
                    if c["eol_status"] == "eol" and c.get("eol_date_published"))
EOL_WITHOUT_DATE = COUNTS["eol"] - EOL_WITH_DATE
UPCOMING = DOC["upcoming"]
UPCOMING_90 = [u for u in UPCOMING if u["days_left"] <= 90]
UPCOMING_30 = [u for u in UPCOMING if u["days_left"] <= 30]
LAMBDA = DOC["lambda_runtimes"]
ANNOUNCEMENTS = DOC["announcements"]
BY_CAT = {}
for p in PRODUCT_LIST:
    BY_CAT.setdefault(p["category"], []).append(p)
for cat in BY_CAT:
    BY_CAT[cat].sort(key=lambda p: (p["soonest_eol"]["eol"] if p["soonest_eol"] else "9999-12-31", p["name"]))


# /eol/{YYYY-MM} 페이지에 들어가는 행(지문 계산·페이지 생성 공용)
def _month_rows():
    months = {}
    for u in UPCOMING:
        months.setdefault(u["eol"][:7], []).append(u)
    past = {}
    for p in PRODUCT_LIST:
        for c in p["cycles"]:
            if c.get("eol") and c["eol_status"] == "eol" and c["eol"] >= (TODAY - timedelta(days=365)).isoformat():
                past.setdefault(c["eol"][:7], []).append({"slug": p["slug"], "name": p["name"], "cycle": c["cycle"], "eol": c["eol"]})
    return {m: months.get(m, []) + past.get(m, []) for m in set(list(months) + list(past))}


MONTH_INDEX = _month_rows()


def answer_product(p):
    """제품 페이지 첫 문단 — 데이터로만 만든 직접 답변."""
    cur = p["cycles"][0]
    active = next((c for c in p["cycles"] if c["cycle"] == p["active_cycle"]), None)
    bits = [f"{p['name']} {cur['cycle']} is the current release"]
    if cur.get("release_date"):
        bits.append(f"released {cur['release_date']}")
    if cur["eol_status"] == "eol":
        bits.append(f"and it reached end of life on {cur['eol']}" if cur.get("eol")
                    else "and it is marked end of life with no published date")
    elif cur.get("eol"):
        bits.append(f"with end of life on {cur['eol']}")
    else:
        bits.append("with no end-of-life date published upstream")
    sentence = ", ".join(bits[:3]) + "."
    if len(bits) > 3:
        sentence = f"{bits[0]}, {bits[1]} {bits[2]}, {bits[3]}."
        sentence = sentence.replace(", and ", ", and ")
    # 아래 문장들은 각각 완결된 문장으로 만든다(붙여 쓰면 비문이 된다 — 교차검수 P1-1)
    rest = []
    dated = [c for c in p["cycles"] if c["eol_status"] == "eol" and c.get("eol_date_published")]
    undated = [c for c in p["cycles"] if c["eol_status"] == "eol" and not c.get("eol_date_published")]
    if dated:
        rest.append(f"{len(dated)} of its {p['cycle_count']} tracked cycles have passed their published end-of-life date.")
    if undated:
        rest.append(f"{len(undated)} more are marked end of life by the upstream source with no published date.")
    if active:
        rest.append(
            f"The newest cycle still supported is {active['cycle']}"
            + (f" (latest release {active['latest']})" if active.get("latest") and active["latest"] != active["cycle"] else "")
            + (f", supported until {active['eol']}." if active.get("eol") else ", with no published end-of-life date.")
        )
    if p.get("soonest_eol"):
        s = p["soonest_eol"]
        when = days_phrase(s["days_left"])
        rest.append(f"The next deadline is cycle {s['cycle']} on {s['eol']}" + (f" ({when})." if when else "."))
    return sentence, rest


def cycle_table(p, limit=None):
    rows = []
    cycles = p["cycles"] if not limit else p["cycles"][:limit]
    for c in cycles:
        eol_cell = c.get("eol") or (
            "not announced" if c["eol_status"] == "no-eol-date"
            else "date not published" if c["eol_status"] == "eol"
            else "—")
        rows.append(
            "<tr>"
            f"<td class=\"mono\">{e(c['cycle'])}</td>"
            f"<td>{e(c.get('release_date') or '—')}</td>"
            f"<td>{e(c.get('support_end') or '—')}</td>"
            f"<td><strong>{e(eol_cell)}</strong>"
            + (f"<br><span class=\"small muted\">{e(days_phrase(c.get('days_left')))}</span>" if c.get("days_left") is not None else "")
            + "</td>"
            f"<td class=\"mono small\">{e(c.get('latest') or '—')}</td>"
            f"<td>{badge(c['eol_status'])}{' <span class=\"badge b-lts\">LTS</span>' if c.get('lts') else ''}</td>"
            "</tr>"
        )
    extra = ""
    if limit and len(p["cycles"]) > limit:
        extra = f'<p class="small muted">Showing the {limit} most recent of {len(p["cycles"])} tracked cycles. The full list is in <a href="/api/eol.json">/api/eol.json</a>.</p>'
    return f"""<table class="grid">
<thead><tr><th>Cycle</th><th>Released</th><th>Active support ends</th><th>End of life (EOL)</th><th>Latest</th><th>Status</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>{extra}"""


# ---------------------------------------------------------------- home
def faq_home():
    return [
        ("What is DeprecateWatch?",
         f"DeprecateWatch is a static archive of end-of-life and deprecation dates for {len(PRODUCT_LIST)} SDKs, runtimes, frameworks, databases, operating systems and cloud services. It holds {DOC['counts']['cycles']:,} release cycles and is rebuilt every week, on Tuesdays at 06:00 KST, from upstream sources. The snapshot on this page is dated {AS_OF}."),
        ("Where do the dates come from?",
         "Cycle and support dates come from the endoflife.date API (MIT licensed). AWS Lambda runtime deprecation dates come from the AWS Lambda documentation table. Deprecation announcements come from the Google Cloud release notes feed, the Azure service updates feed, AWS What's New and GitHub release feeds. Every row links to the source it was read from, and no date is estimated or filled in by hand."),
        ("How many tracked versions are already end-of-life?",
         f"As of {AS_OF}, {EOL_WITH_DATE:,} of {DOC['counts']['cycles']:,} tracked release cycles have passed their published end-of-life date, "
         f"and {EOL_WITHOUT_DATE:,} more are marked end of life by the upstream source with no published date. "
         f"{COUNTS['security-only']:,} are past active support but not yet at end of life, and {len(UPCOMING_90):,} reach end of life within the next 90 days."),
        ("What does the Security-only status mean?",
         "Security-only means the cycle is past the end of its active support window but its published end-of-life date has not arrived yet, so the upstream project no longer ships regular updates for it. "
         "End of life means the published EOL date has passed; it also covers cycles the upstream marks end of life without a date, shown as ‘date not published’. "
         "No EOL date means the project has not published an end-of-life date for that cycle and has not marked it end of life in the source data."),
        ("Does DeprecateWatch recommend which version to upgrade to?",
         "No. Each product page shows two facts only: the newest cycle that is still supported for that product, and any replacement the upstream source itself states (for example a recommended model or successor). We do not rank vendors, score alternatives or issue migration advice."),
        ("How fresh is the data and how is it updated?",
         f"The snapshot shown here was generated on {GENERATED} (Asia/Seoul). A scheduled job re-fetches every source weekly (Tuesdays 06:00 KST) and rebuilds these pages, so the as_of date in every table header matches the snapshot you are reading. Machine-readable copies are at /api/eol.json, /api/products.json, /api/upcoming.json and /api/announcements.json."),
    ]


def jsonld_org():
    return {
        "@type": "Organization",
        "@id": rel("/#org"),
        "name": CONFIG["site_name"],
        "url": rel("/"),
        "description": CONFIG["tagline"],
    }


def jsonld_faq(faq, page_url):
    return {
        "@type": "FAQPage",
        "@id": page_url + "#faq",
        "mainEntity": [
            {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq
        ],
    }


def faq_block(faq, title="Questions this page answers"):
    items = "".join(f"<div class=\"qa\"><h3>{e(q)}</h3><p>{e(a)}</p></div>" for q, a in faq)
    return f'<section id="faq"><h2>{e(title)}</h2>{items}</section>'


def build_home():
    rows = "".join(
        f'<tr><td><a href="/product/{e(u["slug"])}.html">{e(u["name"])}</a></td>'
        f'<td class="mono">{e(u["cycle"])}</td><td><strong>{e(u["eol"])}</strong></td>'
        f'<td>{e(days_phrase(u["days_left"]))}</td>'
        f'<td class="mono small">{e(u.get("latest") or "—")}</td>'
        f'<td class="mono small">{e(u.get("active_cycle") or "—")}</td></tr>'
        for u in UPCOMING_90[:40]
    )
    cat_cards = "".join(
        f'<a class="card" href="/category/{e(cat)}.html"><strong>{e(CATEGORY_LABEL.get(cat, cat))}</strong>'
        f'<span class="small muted">{len(BY_CAT.get(cat, []))} products · {sum(1 for p in BY_CAT.get(cat, []) if p.get("soonest_eol") and p["soonest_eol"]["days_left"] <= 90)} ending within 90 days</span></a>'
        for cat in CATEGORY_ORDER if BY_CAT.get(cat)
    )
    lam = "".join(
        f'<tr><td>{e(r["name"])}</td><td class="mono small">{e(r["identifier"])}</td>'
        f'<td><strong>{e(r["deprecation_date"] or "—")}</strong></td>'
        f'<td>{e(days_phrase(r.get("days_left")))}</td>'
        f'<td>{badge("eol" if r["status"] == "deprecated" else "supported")}</td></tr>'
        for r in [r for r in LAMBDA if r.get("days_left") is not None and r["days_left"] >= -120][:8]
    )
    ann = "".join(
        f'<li><span class="src src-{e(a["source"])}">{e(a["source"].upper())}</span> '
        f'<a href="{e(a["url"])}" rel="noopener">{e(a["title"])}</a> '
        f'<span class="small muted">{e(a["date"])}</span></li>'
        for a in ANNOUNCEMENTS[:10]
    )
    faq = faq_home()
    body = f"""
<h1>End-of-life dates for SDKs, cloud runtimes and open-source projects</h1>
<p class="lede">A static, machine-readable archive of deprecation and end-of-life (EOL) dates across
<strong>{len(PRODUCT_LIST)}</strong> products — languages, frameworks, databases, operating systems, server
applications and managed cloud services. Every date is taken from an upstream source and dated; snapshot
<time datetime="{e(AS_OF)}">{e(AS_OF)}</time>.</p>

<div class="stats">
  <div><strong>{len(PRODUCT_LIST)}</strong><span>products tracked</span></div>
  <div><strong>{DOC['counts']['cycles']:,}</strong><span>release cycles</span></div>
  <div><strong>{EOL_WITH_DATE:,}</strong><span>cycles past their published EOL date</span></div>
  <div><strong>{EOL_WITHOUT_DATE:,}</strong><span>marked end of life, no published date</span></div>
  <div><strong>{len(UPCOMING)}</strong><span>EOL dates in the next 365 days</span></div>
  <div><strong>{len(UPCOMING_90)}</strong><span>EOL dates in the next 90 days</span></div>
</div>

<section id="ending-soon">
<h2>Reaching end of life within 90 days</h2>
<p class="small muted">{len(UPCOMING_90)} cycles pass their published EOL date between {e(AS_OF)} and
{e((TODAY + timedelta(days=90)).isoformat())}.{" Showing the first 40." if len(UPCOMING_90) > 40 else ""}</p>
<table class="grid">
<thead><tr><th>Product</th><th>Cycle ending</th><th>EOL date</th><th>When</th><th>Last release of that cycle</th><th>Newest supported cycle</th></tr></thead>
<tbody>{rows}</tbody>
</table>
<p><a href="/calendar.html">See the full month-by-month EOL calendar →</a></p>
</section>

<section id="lambda">
<h2>AWS Lambda runtime deprecations</h2>
<p class="small muted">Deprecation dates published in the AWS Lambda runtimes documentation. AWS blocks new
functions 30 days after deprecation and updates 60 days after.</p>
<table class="grid">
<thead><tr><th>Runtime</th><th>Identifier</th><th>Deprecation date</th><th>When</th><th>Status</th></tr></thead>
<tbody>{lam}</tbody>
</table>
</section>

<section id="announcements">
<h2>Recent deprecation announcements</h2>
<p class="small muted">Deprecation and retirement notes from vendor release feeds, newest first, as quoted from
the source title and summary.</p>
<ul class="feed">{ann}</ul>
<p><a href="/announcements.html">All {len(ANNOUNCEMENTS)} announcements →</a></p>
</section>

<section id="categories">
<h2>Browse by category</h2>
<div class="cards">{cat_cards}</div>
</section>

{faq_block(faq)}

<section id="use">
<h2>Using this data</h2>
<p>The same snapshot is published as JSON, so an assistant or a script can answer "is X end of life, and when"
with a dated value instead of a training-cutoff guess:</p>
<ul>
<li><a href="/api/eol.json"><code>/api/eol.json</code></a> — every product with every tracked cycle, support and EOL dates, status and day counts.</li>
<li><a href="/api/products.json"><code>/api/products.json</code></a> — one row per product with its current cycle and next deadline.</li>
<li><a href="/api/upcoming.json"><code>/api/upcoming.json</code></a> — cycles whose EOL date falls in the next 365 days.</li>
<li><a href="/api/announcements.json"><code>/api/announcements.json</code></a> — vendor deprecation and retirement notes with source links.</li>
<li><a href="/llms.txt"><code>/llms.txt</code></a> — a plain-text map of the site for language models.</li>
</ul>
</section>
"""
    jsonld = {
        "@context": "https://schema.org",
        "@graph": [
            jsonld_org(),
            {
                "@type": "WebSite",
                "@id": rel("/#website"),
                "url": rel("/"),
                "name": CONFIG["site_name"],
                "description": CONFIG["tagline"],
                "publisher": {"@id": rel("/#org")},
                "inLanguage": "en",
            },
            {
                "@type": "Dataset",
                "@id": rel("/#dataset"),
                "name": "DeprecateWatch end-of-life dataset",
                "description": f"End-of-life and support-end dates for {len(PRODUCT_LIST)} software products and cloud runtimes, with {DOC['counts']['cycles']:,} tracked release cycles, rebuilt weekly (Tuesdays 06:00 KST) from upstream sources.",
                "url": rel("/api/eol.json"),
                "sameAs": rel("/"),
                "license": "https://opensource.org/license/mit",
                "creator": {"@id": rel("/#org")},
                "isAccessibleForFree": True,
                "dateModified": mod_of("/"),
                "temporalCoverage": f"1976-01-01/{AS_OF}",
                "keywords": ["end of life", "EOL", "deprecation", "support lifecycle", "SDK", "runtime", "cloud"],
                "variableMeasured": ["end-of-life date", "end of active support date", "latest release"],
                "distribution": [
                    {"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": rel("/api/eol.json")},
                    {"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": rel("/api/products.json")},
                    {"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": rel("/api/upcoming.json")},
                ],
            },
            {
                "@type": "WebPage",
                "@id": rel("/#webpage"),
                "url": rel("/"),
                "name": "DeprecateWatch — end-of-life dates for SDKs, cloud runtimes and open-source projects",
                "isPartOf": {"@id": rel("/#website")},
                "about": {"@id": rel("/#dataset")},
                "dateModified": mod_of("/"),
                "inLanguage": "en",
            },
            jsonld_faq(faq, rel("/")),
        ],
    }
    page("/index.html", layout(
        f"DeprecateWatch — {len(PRODUCT_LIST)} products, EOL dates as of {AS_OF}",
        f"Static archive of end-of-life and deprecation dates for {len(PRODUCT_LIST)} SDKs, runtimes, frameworks, databases, operating systems and cloud services. {len(UPCOMING_90)} reach EOL within 90 days. Data as of {AS_OF}.",
        "/", body, jsonld))


# ---------------------------------------------------------------- product pages
def build_product(p):
    cur = p["cycles"][0]
    sentence, rest = answer_product(p)
    active = next((c for c in p["cycles"] if c["cycle"] == p["active_cycle"]), None)
    category = p["category"] or "other"
    faq = []
    faq.append((f"Is {p['name']} {cur['cycle']} end of life?",
                f"{'Yes' if cur['eol_status'] == 'eol' else 'No'}. {p['name']} {cur['cycle']} "
                + (f"reached end of life on {cur['eol']} ({days_phrase(cur.get('days_left'))})." if cur["eol_status"] == "eol" and cur.get("eol")
                   else f"has an end-of-life date of {cur['eol']} ({days_phrase(cur.get('days_left'))})." if cur.get("eol")
                   else "has no published end-of-life date in the source data.")))
    if active:
        faq.append((f"What is the newest supported version of {p['name']}?",
                    f"{p['name']} {active['cycle']}"
                    + (f" (latest release {active['latest']})" if active.get("latest") else "")
                    + (f", released {active['release_date']}" if active.get("release_date") else "")
                    + (f", with end of life on {active['eol']}" if active.get("eol") else ", with no published end-of-life date")
                    + "."))
    if p["eol_cycle_count"]:
        faq.append((f"How many {p['name']} versions are already end of life?",
                    f"{p['eol_cycle_count']} of the {p['cycle_count']} cycles tracked here have passed their EOL date as of {AS_OF}."))
    if len(faq) < 2:
        faq.append((f"How many {p['name']} cycles does DeprecateWatch track?",
                    f"{p['cycle_count']} release cycles are tracked for {p['name']}, of which {p['eol_cycle_count']} have passed their published end-of-life date as of {AS_OF}."))

    replacement_rows = []
    if active:
        replacement_rows.append(
            f'<li><strong>Newest cycle still supported:</strong> {e(active["cycle"])}'
            + (f' (latest release {e(active["latest"])})' if active.get("latest") and active["latest"] != active["cycle"] else "")
            + (f' — end of life {e(active["eol"])}' if active.get("eol") else " — no published end-of-life date")
            + ".</li>")
    stated = next((c for c in p["cycles"] if c.get("replacement")), None)
    if stated:
        replacement_rows.append(
            f'<li><strong>Replacement stated by the upstream source</strong> for cycle {e(stated["cycle"])}: '
            f'{e(stated["replacement"])}.</li>')
    if not replacement_rows:
        replacement_rows.append("<li>No successor is stated in the upstream data for this product.</li>")

    same_cat = [x for x in BY_CAT.get(category, []) if x["slug"] != p["slug"] and x.get("soonest_eol")][:8]
    related = "".join(
        f'<li><a href="/product/{e(x["slug"])}.html">{e(x["name"])}</a> — '
        f'next EOL {e(x["soonest_eol"]["eol"])} ({e(x["soonest_eol"]["cycle"])})</li>' for x in same_cat
    )
    title = f"{p['name']} end-of-life and support dates (EOL {cur.get('eol') or 'not announced'})"
    desc = f"{sentence} " + " ".join(rest) if rest else sentence
    jsonld = {
        "@context": "https://schema.org",
        "@graph": [
            jsonld_org(),
            {
                "@type": "WebPage",
                "@id": rel(f"/product/{p['slug']}.html") + "#webpage",
                "url": rel(f"/product/{p['slug']}.html"),
                "name": title,
                "description": desc[:300],
                "isPartOf": {"@id": rel("/#website")},
                "dateModified": mod_of(f"/product/{p['slug']}.html"),
                "inLanguage": "en",
                "about": {
                    "@type": "SoftwareApplication",
                    "name": p["name"],
                    "applicationCategory": CATEGORY_LABEL.get(category, category),
                    "softwareVersion": cur["cycle"],
                },
            },
            jsonld_faq(faq, rel(f"/product/{p['slug']}.html")),
        ],
    }
    body = f"""
<nav class="crumbs"><a href="/">Home</a> › <a href="/category/{e(category)}.html">{e(CATEGORY_LABEL.get(category, category))}</a> › {e(p['name'])}</nav>
<h1>{e(p['name'])} — support and end-of-life dates</h1>
<p class="lede">{e(sentence)}</p>
{'<ul class="facts">' + ''.join(f'<li>{e(x)}</li>' for x in rest) + '</ul>' if rest else ''}

<div class="callout">
  <h2>Direct answer</h2>
  <p><strong>{e(p['name'])} {e(cur['cycle'])}</strong>
  {('reached end of life on <strong>' + e(cur['eol']) + '</strong>') if cur['eol_status'] == 'eol' and cur.get('eol')
   else ('has an end-of-life date of <strong>' + e(cur['eol']) + '</strong>') if cur.get('eol')
   else 'has no published end-of-life date'}.
  {'Newest supported cycle: <strong>' + e(active['cycle']) + '</strong>' + (' (latest ' + e(active['latest']) + ')' if active.get('latest') else '') + '.' if active else ''}
  Data as of {e(AS_OF)}.</p>
</div>

<h2>All tracked cycles</h2>
{cycle_table(p, limit=60)}

<h2>Upgrade path stated in the data</h2>
<ul>{''.join(replacement_rows)}</ul>
<p class="small muted">This is not a recommendation from DeprecateWatch. It repeats what the upstream source states,
plus the newest cycle that is still inside its published support window.</p>

<section id="faq"><h2>Questions this page answers</h2>
{''.join(f'<div class="qa"><h3>{e(q)}</h3><p>{e(a)}</p></div>' for q, a in faq)}
</section>

{'<section><h2>Other ' + e(CATEGORY_LABEL.get(category, category)) + ' with upcoming deadlines</h2><ul>' + related + '</ul></section>' if related else ''}

<p class="small muted">Source for the cycle table: <a href="{e(p['source_url'])}" rel="noopener">endoflife.date/{e(p['slug'])}</a>
read through the endoflife.date API on {e(AS_OF)}. Machine-readable copy:
<a href="/api/eol.json">/api/eol.json</a> (product key <code>{e(p['slug'])}</code>).</p>
"""
    page(f"/product/{p['slug']}.html", layout(title, desc, f"/product/{p['slug']}.html", body, jsonld,
                                              nav_key="/categories.html"))


# ---------------------------------------------------------------- category pages
def build_category(cat, items):
    label = CATEGORY_LABEL.get(cat, cat)
    rows = []
    for p in items:
        cur = p["cycles"][0]
        s = p.get("soonest_eol")
        if s:
            soon = f'{e(s["eol"])} <span class="small muted">({e(days_phrase(s["days_left"]))})</span>'
        else:
            soon = "—"
        rows.append(
            f'<tr><td><a href="/product/{e(p["slug"])}.html">{e(p["name"])}</a></td>'
            f'<td class="mono">{e(p["latest_cycle"])}</td>'
            f'<td>{e(cur.get("eol") or "not announced")}</td>'
            f'<td>{badge(cur["eol_status"])}</td>'
            f'<td>{soon}</td>'
            f'<td class="mono small">{e(p["cycle_count"])}</td></tr>')
    upcoming_here = [p for p in items if p.get("soonest_eol") and p["soonest_eol"]["days_left"] <= 90]
    body = f"""
<nav class="crumbs"><a href="/">Home</a> › Categories</nav>
<h1>{e(label)} support and end-of-life dates</h1>
<p class="lede">{len(items)} products in this category. {len(upcoming_here)} have a published end-of-life date within
the next 90 days. Sorted by the soonest upcoming deadline. Data as of <time datetime="{e(AS_OF)}">{e(AS_OF)}</time>.</p>
<table class="grid">
<thead><tr><th>Product</th><th>Current cycle</th><th>Current cycle EOL</th><th>Status</th><th>Next deadline</th><th>Cycles</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
<p class="small muted">Full cycle-level data: <a href="/api/eol.json">/api/eol.json</a>.</p>
"""
    jsonld = {
        "@context": "https://schema.org",
        "@graph": [
            jsonld_org(),
            {
                "@type": "CollectionPage",
                "@id": rel(f"/category/{cat}.html") + "#webpage",
                "url": rel(f"/category/{cat}.html"),
                "name": f"{label} end-of-life dates",
                "isPartOf": {"@id": rel("/#website")},
                "dateModified": mod_of(f"/category/{cat}.html"),
                "inLanguage": "en",
                "mainEntity": {
                    "@type": "ItemList",
                    "numberOfItems": len(items),
                    "itemListElement": [
                        {"@type": "ListItem", "position": i + 1, "name": p["name"],
                         "url": rel(f"/product/{p['slug']}.html")}
                        for i, p in enumerate(items[:50])
                    ],
                },
            },
        ],
    }
    page(f"/category/{cat}.html", layout(
        f"{label} end-of-life dates ({len(items)} products)", 
        f"End-of-life and support-end dates for {len(items)} {label.lower()} products, with the next deadline for each. Data as of {AS_OF}.",
        f"/category/{cat}.html", body, jsonld, nav_key="/categories.html"))


def build_categories_index():
    cards = "".join(
        f'<a class="card" href="/category/{e(cat)}.html"><strong>{e(CATEGORY_LABEL.get(cat, cat))}</strong>'
        f'<span class="small muted">{len(BY_CAT.get(cat, []))} products</span></a>'
        for cat in CATEGORY_ORDER if BY_CAT.get(cat))
    body = f"""
<nav class="crumbs"><a href="/">Home</a> › Categories</nav>
<h1>Browse end-of-life dates by category</h1>
<p class="lede">{len(PRODUCT_LIST)} products across {len([c for c in CATEGORY_ORDER if BY_CAT.get(c)])} categories. Data as of {e(AS_OF)}.</p>
<div class="cards">{cards}</div>
"""
    page("/categories.html", layout("Categories — end-of-life dates by product type",
                                    "Browse tracked products by category: languages, frameworks, databases, operating systems, server applications and managed cloud services.",
                                    "/categories.html", body, {"@context": "https://schema.org", "@graph": [jsonld_org()]},
                                    nav_key="/categories.html"))


# ---------------------------------------------------------------- calendar
def build_calendar():
    months = {}
    for u in UPCOMING:
        months.setdefault(u["eol"][:7], []).append(u)
    past = {}
    for p in PRODUCT_LIST:
        for c in p["cycles"]:
            if c.get("eol") and c["eol_status"] == "eol" and c["eol"] >= (TODAY - timedelta(days=365)).isoformat():
                past.setdefault(c["eol"][:7], []).append({"slug": p["slug"], "name": p["name"], "cycle": c["cycle"], "eol": c["eol"]})

    month_links = []
    for m in sorted(set(list(months) + list(past))):
        n = len(months.get(m, [])) + len(past.get(m, []))
        month_links.append(f'<li><a href="/eol/{m}.html">{m}</a> — {n} end-of-life dates</li>')

    rows = "".join(
        f'<tr><td><a href="/product/{e(u["slug"])}.html">{e(u["name"])}</a></td><td class="mono">{e(u["cycle"])}</td>'
        f'<td><a href="/eol/{e(u["eol"][:7])}.html">{e(u["eol"])}</a></td><td>{e(days_phrase(u["days_left"]))}</td></tr>'
        for u in UPCOMING[:60])
    body = f"""
<nav class="crumbs"><a href="/">Home</a> › Calendar</nav>
<h1>End-of-life calendar</h1>
<p class="lede">{len(UPCOMING)} published end-of-life dates fall in the next 365 days; {len(UPCOMING_90)} of them in the next 90 days.
The list below is the nearest {min(60, len(UPCOMING))}. Data as of <time datetime="{e(AS_OF)}">{e(AS_OF)}</time>.</p>
<table class="grid">
<thead><tr><th>Product</th><th>Cycle</th><th>EOL date</th><th>When</th></tr></thead>
<tbody>{rows}</tbody>
</table>
<h2>Month by month</h2>
<ul class="months">{''.join(month_links)}</ul>
"""
    page("/calendar.html", layout(
        f"End-of-life calendar — {len(UPCOMING)} deadlines in the next year",
        f"Upcoming end-of-life dates for SDKs, runtimes and cloud services, month by month. {len(UPCOMING_90)} deadlines within 90 days. Data as of {AS_OF}.",
        "/calendar.html", body,
        {"@context": "https://schema.org", "@graph": [jsonld_org(), {
            "@type": "WebPage", "@id": rel("/calendar.html#webpage"), "url": rel("/calendar.html"),
            "name": "End-of-life calendar", "isPartOf": {"@id": rel("/#website")},
            "dateModified": mod_of("/calendar.html"), "inLanguage": "en"}]}, nav_key="/calendar.html"))


def build_month(month, upcoming_rows, past_rows):
    rows = "".join(
        f'<tr><td><a href="/product/{e(u["slug"])}.html">{e(u["name"])}</a></td><td class="mono">{e(u["cycle"])}</td>'
        f'<td><strong>{e(u["eol"])}</strong></td><td>{badge("supported" if u["days_left"] > 0 else "eol")}</td></tr>'
        for u in sorted(upcoming_rows, key=lambda x: (x["eol"], x["name"])))
    past = "".join(
        f'<tr><td><a href="/product/{e(u["slug"])}.html">{e(u["name"])}</a></td><td class="mono">{e(u["cycle"])}</td>'
        f'<td>{e(u["eol"])}</td><td>{badge("eol")}</td></tr>'
        for u in sorted(past_rows, key=lambda x: (x["eol"], x["name"])))
    total = len(upcoming_rows) + len(past_rows)
    body = f"""
<nav class="crumbs"><a href="/">Home</a> › <a href="/calendar.html">Calendar</a> › {e(month)}</nav>
<h1>End-of-life dates in {e(month)}</h1>
<p class="lede">{total} tracked release cycles reach their published end-of-life date in {e(month)}. Data as of
<time datetime="{e(AS_OF)}">{e(AS_OF)}</time>.</p>
{'<h2>Upcoming in this month</h2><table class="grid"><thead><tr><th>Product</th><th>Cycle</th><th>EOL date</th><th>Status at ' + e(AS_OF) + '</th></tr></thead><tbody>' + rows + '</tbody></table>' if rows else ''}
{'<h2>Already past EOL in this month</h2><table class="grid"><thead><tr><th>Product</th><th>Cycle</th><th>EOL date</th><th>Status</th></tr></thead><tbody>' + past + '</tbody></table>' if past else ''}
<p><a href="/calendar.html">← Back to the calendar</a></p>
"""
    page(f"/eol/{month}.html", layout(
        f"End-of-life dates in {month} ({total} cycles)",
        f"{total} software release cycles reach end of life in {month}, with product and cycle names. Data as of {AS_OF}.",
        f"/eol/{month}.html", body,
        {"@context": "https://schema.org", "@graph": [jsonld_org(), {
            "@type": "WebPage", "@id": rel(f"/eol/{month}.html#webpage"), "url": rel(f"/eol/{month}.html"),
            "name": f"End-of-life dates in {month}", "isPartOf": {"@id": rel("/#website")},
            "dateModified": mod_of(f"/eol/{month}.html"), "inLanguage": "en"}]}, nav_key="/calendar.html"))


# ---------------------------------------------------------------- announcements
def build_announcements():
    groups = {}
    for a in ANNOUNCEMENTS:
        groups.setdefault(a["date"][:7], []).append(a)
    sections = []
    for m in sorted(groups, reverse=True):
        items = "".join(
            f'<li><span class="src src-{e(a["source"])}">{e(a["source"].upper())}</span> '
            f'<a href="{e(a["url"])}" rel="noopener">{e(a["title"])}</a>'
            f'<div class="small">{e(a["summary"])}</div>'
            f'<div class="small muted">{e(a["date"])} · {e(a["source_label"])}</div></li>'
            for a in groups[m])
        sections.append(f'<h2 id="{m}">{m} ({len(groups[m])})</h2><ul class="feed">{items}</ul>')
    by_src = {}
    for a in ANNOUNCEMENTS:
        by_src[a["source"]] = by_src.get(a["source"], 0) + 1
    body = f"""
<nav class="crumbs"><a href="/">Home</a> › Announcements</nav>
<h1>Deprecation and retirement announcements</h1>
<p class="lede">{len(ANNOUNCEMENTS)} notes from vendor release feeds that announce a deprecation, retirement or
breaking change — Google Cloud release notes ({by_src.get('gcp', 0)}), Azure service updates ({by_src.get('azure', 0)}),
AWS What's New ({by_src.get('aws', 0)}) and GitHub release feeds ({by_src.get('github', 0)}). Newest first.
Snapshot <time datetime="{e(AS_OF)}">{e(AS_OF)}</time>. Summaries are the announcement text taken from the source.</p>
{''.join(sections)}
"""
    page("/announcements.html", layout(
        f"Deprecation announcements — {len(ANNOUNCEMENTS)} vendor notes",
        "Deprecation, retirement and breaking-change announcements collected from Google Cloud, Azure, AWS and GitHub release feeds, with source links.",
        "/announcements.html", body,
        {"@context": "https://schema.org", "@graph": [jsonld_org(), {
            "@type": "WebPage", "@id": rel("/announcements.html#webpage"), "url": rel("/announcements.html"),
            "name": "Deprecation and retirement announcements", "isPartOf": {"@id": rel("/#website")},
            "dateModified": mod_of("/announcements.html"), "inLanguage": "en"}]}, nav_key="/announcements.html"))


# ---------------------------------------------------------------- about / privacy
def build_about():
    src_rows = "".join(
        f'<tr><td>{e(s["name"])}</td><td><a href="{e(s["url"])}" rel="noopener">{e(s["url"])}</a></td>'
        f'<td>{e(s["used_for"])}</td><td>{e(s["license"])}</td></tr>' for s in DOC["sources"])
    body = f"""
<nav class="crumbs"><a href="/">Home</a> › Method</nav>
<h1>Method, sources and limits</h1>
<p class="lede">DeprecateWatch is a static archive. It does not call an API at page load, run a database, or guess a
date. This page explains exactly where each number comes from and what it does not claim.</p>

<h2>Pipeline</h2>
<ol>
<li><strong>Collect.</strong> Every source below is fetched once a week (Tuesdays 06:00 KST) by a scheduled job, without an API key, and the raw response is kept unchanged.</li>
<li><strong>Normalise.</strong> Cycles, support-end and EOL dates are copied into one schema. A status is computed by comparing the source date with the snapshot date: <code>supported</code>, <code>security-only</code>, <code>eol</code>, or <code>no-eol-date</code>.</li>
<li><strong>Publish.</strong> The tables you see, the JSON API and <a href="/llms.txt">llms.txt</a> are generated from that one file, so the HTML, the JSON and the sitemap cannot drift apart.</li>
<li><strong>Verify.</strong> A test suite checks the generated site before it is published: date formats, status/date consistency, JSON schema, duplicate pages, link targets and the FAQ text used in structured data.</li>
</ol>

<h2>Sources</h2>
<table class="grid">
<thead><tr><th>Source</th><th>URL</th><th>Used for</th><th>Terms</th></tr></thead>
<tbody>{src_rows}</tbody>
</table>
<p class="small muted">The endoflife.date API is MIT licensed; its copyright notice is reproduced in the footer of every page.
Vendor documentation and release feeds remain the property of their vendors and are quoted with a link to the original.</p>

<h2>What the statuses mean</h2>
<ul>
<li><strong>Supported</strong> — the published EOL date is in the future and active support has not ended.</li>
<li><strong>Security-only</strong> — active support has ended but the EOL date is still ahead.</li>
<li><strong>End of life</strong> — the published EOL date has passed.</li>
<li><strong>No EOL date</strong> — the upstream project publishes no end-of-life date for that cycle; the site does not invent one.</li>
</ul>

<h2>What this site does not do</h2>
<ul>
<li>It does not estimate or interpolate a date. If a source has no date, the row says so.</li>
<li>It does not rank vendors, score migration paths or recommend a product. The upgrade path shown on a product page is either the newest cycle that is still inside its published support window, or a replacement the upstream source itself states.</li>
<li>It does not claim to be an authoritative record. The vendor is; each row links to the vendor or the upstream dataset.</li>
</ul>

<h2>Snapshot</h2>
<p>Generated <time datetime="{e(GENERATED)}">{e(GENERATED)}</time> (Asia/Seoul) with
{DOC['counts']['products']} products, {DOC['counts']['cycles']:,} cycles, {DOC['counts']['lambda_runtimes']} Lambda runtime entries and
{DOC['counts']['announcements']} announcements.</p>
"""
    page("/about.html", layout("Method and sources — DeprecateWatch",
                               "How DeprecateWatch collects, normalises and verifies end-of-life dates, and what it does not claim.",
                               "/about.html", body,
                               {"@context": "https://schema.org", "@graph": [jsonld_org(), {
                                   "@type": "AboutPage", "@id": rel("/about.html#webpage"), "url": rel("/about.html"),
                                   "name": "Method and sources", "isPartOf": {"@id": rel("/#website")},
                                   "dateModified": mod_of("/about.html")}]}, nav_key="/about.html"))


def build_privacy():
    body = f"""
<nav class="crumbs"><a href="/">Home</a> › Privacy</nav>
<h1>Privacy</h1>
<p class="lede">This site is static. It has no accounts, no forms, no advertising and no third-party scripts other than
the aggregate analytics tag described below.</p>
<h2>Analytics</h2>
<p>Pageviews are counted with Google Analytics 4 (measurement ID <code>{e(GA) if GA else 'not configured'}</code>) with IP
anonymisation enabled. The tag records the page path, referrer, an approximate location derived from the request and
basic device information. It is used only to see which pages are read. No advertising or remarketing data is collected,
and the data is not sold or shared for advertising.</p>
<h2>Cookies</h2>
<p>Google Analytics may set a first-party cookie on this domain to distinguish sessions. No other cookies are set by this site.</p>
<h2>Third parties</h2>
<p>Fonts, stylesheets and scripts are served from this domain, except the Google Analytics tag from googletagmanager.com.
Links to vendor documentation and to endoflife.date leave this site and are governed by those sites' own policies.</p>
<h2>Data requests</h2>
<p>Questions about analytics data or removal requests can be sent to {e(CONFIG['contact'])}.</p>
<p class="small muted">Last updated {e(AS_OF)}.</p>
"""
    page("/privacy.html", layout("Privacy — DeprecateWatch",
                                 "DeprecateWatch privacy note: static site, Google Analytics 4 with IP anonymisation, no advertising.",
                                 "/privacy.html", body,
                                 {"@context": "https://schema.org", "@graph": [jsonld_org(), {
                                     "@type": "WebPage", "@id": rel("/privacy.html#webpage"), "url": rel("/privacy.html"),
                                     "name": "Privacy", "isPartOf": {"@id": rel("/#website")}, "dateModified": mod_of("/privacy.html")}]}))


def build_404():
    body = """
<h1>Page not found</h1>
<p class="lede">That URL is not in this snapshot. Every product page lives at <code>/product/{slug}</code>;
every month at <code>/eol/{YYYY-MM}</code>.</p>
<p><a href="/">Back to the index</a> · <a href="/calendar.html">EOL calendar</a> · <a href="/api/eol.json">JSON API</a></p>
"""
    page("/404.html", layout("Page not found — DeprecateWatch",
                             "That page is not part of the current DeprecateWatch snapshot. Product pages live at /product/{slug} and monthly EOL pages at /eol/{YYYY-MM}.",
                             "/404.html", body))


# ---------------------------------------------------------------- text/API assets
def build_llms():
    cats = ", ".join(f"{CATEGORY_LABEL[c]} ({len(BY_CAT[c])})" for c in CATEGORY_ORDER if BY_CAT.get(c))
    lines = [
        "# DeprecateWatch",
        "",
        f"> End-of-life and deprecation dates for {len(PRODUCT_LIST)} SDKs, runtimes, frameworks, databases, operating systems and managed cloud services, with {DOC['counts']['cycles']:,} tracked release cycles. Static snapshot generated {AS_OF} (Asia/Seoul). Every date is copied from an upstream source; none is estimated.",
        "",
        "DeprecateWatch answers questions of the form \"is <product> <version> end of life, and when\". "
        f"At this snapshot {EOL_WITH_DATE:,} tracked cycles are past their published EOL date, {EOL_WITHOUT_DATE:,} more are marked end of life with no published date, and {len(UPCOMING_90)} reach EOL within 90 days.",
        "",
        "## Machine-readable data",
        "",
        f"- {rel('/api/eol.json')} — full dataset (application/json, ~{DOC['counts']['cycles']:,} cycles). Top-level keys: schema_version, generated_at, as_of, counts, definitions, sources, products[], upcoming[], lambda_runtimes[], announcements[].",
        f"- {rel('/api/products.json')} — one row per product: slug, name, category, latest_cycle, current_eol, current_status, active_cycle, soonest_eol, eol_cycle_count.",
        f"- {rel('/api/upcoming.json')} — cycles with an EOL date in the next 365 days: slug, name, cycle, eol, days_left.",
        f"- {rel('/api/announcements.json')} — vendor deprecation/retirement notes: source, date, title, summary, url.",
        "",
        "## Page patterns",
        "",
        f"- {rel('/')} — index: EOL dates within 90 days, AWS Lambda runtime deprecations, recent announcements, FAQ.",
        f"- {rel('/product/{slug}')} — one page per product: every tracked cycle with release date, active-support end, EOL date, latest release and status, plus the direct answer for the current cycle.",
        f"- {rel('/category/{category}')} — products grouped by type ({cats}).",
        f"- {rel('/eol/{YYYY-MM}')} — every cycle whose EOL date falls in that month (next 12 months).",
        f"- {rel('/calendar.html')} — the next 365 days of deadlines, month by month.",
        f"- {rel('/announcements.html')} — dated deprecation and retirement notes from Google Cloud, Azure, AWS and GitHub release feeds.",
        f"- {rel('/llms.txt')} — this file (plain text site map for language models).",
        f"- {rel('/feed.xml')} — RSS 2.0 of the latest announcements.",
        "",
        "## Definitions",
        "",
        "- supported: published EOL date is in the future and active support has not ended.",
        "- security-only: active support has ended, EOL date still ahead.",
        "- eol: published EOL date has passed.",
        "- no-eol-date: the upstream publishes no EOL date and does not mark the cycle end of life (eol=false); no date is invented.",
        "- eol-no-date: the upstream marks the cycle end of life but publishes no EOL date (eol=true, eolFrom=null). Shown as ‘End of life (date not published)’; counted in counts.eol_without_date, not in counts.eol_with_date.",
        "- days_left: calendar days from as_of to the EOL date (negative = already past).",
        "",
        "## Sources and citation",
        "",
        "- Cycle/support/EOL dates: endoflife.date API v1 (https://endoflife.date/docs/api), MIT licence, © endoflife.date contributors.",
        "- AWS Lambda runtime deprecation dates: https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtimes.html",
        "- Announcements: Google Cloud release notes feed, Azure service updates feed, AWS What's New, GitHub release feeds (each item links to its origin).",
        f"- When citing: \"Source: DeprecateWatch ({rel('/')}), data as of {AS_OF}, upstream endoflife.date\". Always keep the as_of date — this dataset is a dated snapshot, not a live API.",
        "",
        "## Limits",
        "",
        "- Only dates that appear upstream are published. Products whose project has no published EOL date show \"not announced\".",
        "- The site takes no position on which product to choose and does not rank vendors. The upgrade path on a product page is the newest cycle still inside its support window, or a replacement stated by the upstream source.",
        "- Vendor pages are authoritative; each row links to the source it was read from.",
        "",
    ]
    with open(os.path.join(SITE, "llms.txt"), "w", encoding="utf-8") as f:
        f.write(public_urls("\n".join(lines)))


def build_robots():
    ai = ["GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "Claude-Web", "anthropic-ai",
          "PerplexityBot", "Perplexity-User", "Google-Extended", "Applebot-Extended", "CCBot",
          "Bingbot", "Googlebot", "DuckDuckBot", "YandexBot", "Amazonbot", "YouBot", "Meta-ExternalAgent",
          "cohere-ai", "Diffbot"]
    lines = ["# DeprecateWatch — static EOL archive. AI crawlers and assistants may read and quote this site.", ""]
    lines += [f"User-agent: {a}\nAllow: /" for a in ai]
    lines += ["", "User-agent: *", "Allow: /", "", f"Sitemap: {rel('/sitemap.xml')}", ""]
    with open(os.path.join(SITE, "robots.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def build_sitemap(urls):
    """lastmod는 빌드일이 아니라 그 페이지 내용이 마지막으로 바뀐 날짜(site_state.json)를 쓴다."""
    items = "".join(
        f"<url><loc>{e(u)}</loc><lastmod>{e(mod_of(u[len(BASE):] or '/'))}</lastmod></url>" for u in urls)
    xml = f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{items}\n</urlset>\n'
    with open(os.path.join(SITE, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write(public_urls(xml))


def build_feed():
    """RSS 2.0 — 새 지원종료 공지 (구독·재배포용)."""
    items = []
    for a in ANNOUNCEMENTS[:50]:
        items.append(
            "<item>"
            f"<title>{e(a['title'])}</title>"
            f"<link>{e(a['url'])}</link>"
            f"<guid isPermaLink=\"false\">{e(a['source'])}-{e(a['date'])}-{e(abs(hash(a['title'])) % 10**10)}</guid>"
            f"<pubDate>{e(a['date'])}</pubDate>"
            f"<description>{e(a['summary'][:400])}</description>"
            "</item>")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>DeprecateWatch — deprecation announcements</title>
<link>{rel('/announcements.html')}</link>
<description>Deprecation, retirement and breaking-change notes from vendor release feeds.</description>
<language>en</language>
<lastBuildDate>{e(AS_OF)}</lastBuildDate>
{''.join(items)}
</channel></rss>
"""
    with open(os.path.join(SITE, "feed.xml"), "w", encoding="utf-8") as f:
        f.write(public_urls(xml))


def build_api():
    os.makedirs(os.path.join(SITE, "api"), exist_ok=True)
    # 모든 API에 출처·라이선스·인용 문구를 붙인다(교차검수 P1-3: eol.json만 갖고 있었다)
    def api_meta(*source_ids):
        return {
            "license": "MIT — site code and compilation: DeprecateWatch; upstream endoflife.date data: MIT (© endoflife.date contributors)",
            "license_url": "https://opensource.org/license/mit",
            "attribution": f"Source: DeprecateWatch ({rel('/')}), data as of {AS_OF}, upstream endoflife.date. Keep the as_of date when citing — this is a dated snapshot, not a live API.",
            "sources": [s for s in DOC["sources"] if not source_ids or s["id"] in source_ids],
        }

    full = {
        "schema_version": DOC["schema_version"],
        "generated_at": DOC["generated_at"],
        "as_of": DOC["as_of"],
        "timezone": DOC["timezone"],
        "counts": DOC["counts"],
        "definitions": DOC["definitions"],
        "sources": DOC["sources"],
        "license": api_meta()["license"],
        "attribution": api_meta()["attribution"],
        "products": DOC["products"],
        "upcoming": DOC["upcoming"],
        "lambda_runtimes": DOC["lambda_runtimes"],
    }
    products_rows = [{
        "slug": p["slug"], "name": p["name"], "category": p["category"], "aliases": p["aliases"],
        "latest_cycle": p["latest_cycle"], "latest_version": p.get("latest_version"),
        "current_eol": p.get("current_eol"), "current_status": p["current_status"],
        "active_cycle": p.get("active_cycle"), "soonest_eol": p.get("soonest_eol"),
        "cycle_count": p["cycle_count"], "eol_cycle_count": p["eol_cycle_count"],
        "source_url": p["source_url"], "page": rel(f"/product/{p['slug']}.html"),
    } for p in PRODUCT_LIST]
    meta_products = api_meta("endoflife")
    meta_upcoming = api_meta("endoflife")
    meta_ann = api_meta("gcp", "aws", "azure", "github")
    with open(os.path.join(SITE, "api", "eol.json"), "w", encoding="utf-8") as f:
        json.dump(full, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(SITE, "api", "products.json"), "w", encoding="utf-8") as f:
        f.write(public_urls(json.dumps({
            "schema_version": DOC["schema_version"], "as_of": AS_OF,
            "count": len(products_rows), "products": products_rows, **meta_products},
            ensure_ascii=False, separators=(",", ":"))))
    with open(os.path.join(SITE, "api", "upcoming.json"), "w", encoding="utf-8") as f:
        json.dump({"schema_version": DOC["schema_version"], "as_of": AS_OF,
                   "count": len(UPCOMING), "upcoming": UPCOMING, **meta_upcoming}, f,
                  ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(SITE, "api", "announcements.json"), "w", encoding="utf-8") as f:
        json.dump({"schema_version": DOC["schema_version"], "as_of": AS_OF,
                   "count": len(ANNOUNCEMENTS), "announcements": ANNOUNCEMENTS, **meta_ann}, f,
                  ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------- css
CSS = """
:root{--bg:#0f1216;--panel:#161b22;--line:#232a33;--fg:#e6edf3;--muted:#8b949e;--accent:#58c4dd;--ok:#3fb950;--warn:#d29922;--bad:#f85149;--lts:#8957e5}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,"Noto Sans KR",sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:0 20px}
.wrap.wide{max-width:1180px}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
header.top{position:sticky;top:0;background:rgba(15,18,22,.94);border-bottom:1px solid var(--line);backdrop-filter:blur(6px);z-index:5}
header.top .wrap{display:flex;align-items:center;justify-content:space-between;gap:16px;height:58px}
.brand{font-weight:700;font-size:18px;color:var(--fg);letter-spacing:-.2px}
.brand span{color:var(--accent)}
nav a{color:var(--muted);margin-left:16px;font-size:14px}
nav a[aria-current=page]{color:var(--fg);border-bottom:2px solid var(--accent);padding-bottom:2px}
main{padding:32px 0 64px}
h1{font-size:32px;line-height:1.25;margin:0 0 12px;letter-spacing:-.5px}
h2{font-size:21px;margin:40px 0 12px;letter-spacing:-.2px}
h3{font-size:16px;margin:18px 0 6px}
.lede{color:#cbdcf0;font-size:17px;max-width:80ch}
.small{font-size:13px}
.muted{color:var(--muted)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin:24px 0}
.stats div{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}
.stats strong{display:block;font-size:24px;letter-spacing:-.5px}
.stats span{color:var(--muted);font-size:12px;display:block;margin-top:2px}
table.grid{width:100%;border-collapse:collapse;font-size:14px;margin:10px 0 6px;background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}
table.grid th{text-align:left;background:#1b222c;color:#c9d1d9;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em;padding:10px}
table.grid td{padding:9px 10px;border-top:1px solid var(--line);vertical-align:top}
table.grid tr:hover td{background:#1a212a}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.badge{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11px;font-weight:600;letter-spacing:.02em;border:1px solid}
.b-supported{color:var(--ok);border-color:rgba(63,185,80,.4);background:rgba(63,185,80,.1)}
.b-security-only{color:var(--warn);border-color:rgba(210,153,34,.4);background:rgba(210,153,34,.1)}
.b-eol{color:var(--bad);border-color:rgba(248,81,73,.4);background:rgba(248,81,73,.1)}
.b-no-eol-date,.b-unknown{color:var(--muted);border-color:var(--line);background:#1b222c}
.b-lts{color:#d2c4f8;border-color:rgba(137,87,229,.45);background:rgba(137,87,229,.15)}
.callout{background:#12202b;border:1px solid #21445c;border-left:4px solid var(--accent);border-radius:10px;padding:6px 18px;margin:20px 0}
.callout h2{margin:10px 0 6px;font-size:15px;text-transform:uppercase;letter-spacing:.06em;color:var(--accent)}
.facts{margin:8px 0 0;padding-left:20px}
.qa{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:4px 16px;margin:10px 0}
.qa p{margin:6px 0 12px;color:#c9d1d9}
.feed{list-style:none;padding:0;margin:0}
.feed li{padding:12px 0;border-bottom:1px solid var(--line)}
.src{display:inline-block;font-size:10px;font-weight:700;letter-spacing:.06em;padding:1px 6px;border-radius:4px;margin-right:6px;border:1px solid var(--line);color:var(--muted)}
.src-gcp{color:#8ab4f8;border-color:#2c4a7a}.src-azure{color:#7cc4ff;border-color:#2a5a8a}.src-aws{color:#ffb86b;border-color:#7a5220}.src-github{color:#d2c4f8;border-color:#4b3b7a}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.card{display:block;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.card:hover{border-color:var(--accent);text-decoration:none}
.card strong{display:block;margin-bottom:4px}
.crumbs{font-size:13px;color:var(--muted);margin-bottom:10px}
.months{columns:2;list-style:none;padding:0}
.months li{padding:3px 0}
code{background:#1b222c;border:1px solid var(--line);border-radius:5px;padding:1px 6px;font-size:13px}
.foot{border-top:1px solid var(--line);color:var(--muted);font-size:13px;padding:24px 0 40px}
.foot p{max-width:95ch}
@media(max-width:720px){h1{font-size:25px}table.grid{font-size:12.5px}table.grid th,table.grid td{padding:7px 8px}nav a{margin-left:10px;font-size:12.5px}.months{columns:1}}
"""


# ---------------------------------------------------------------- main
def main():
    if os.path.exists(SITE):
        shutil.rmtree(SITE)
    os.makedirs(SITE, exist_ok=True)
    # 먼저 모든 페이지의 데이터 지문을 계산한다(lastmod·dateModified가 여기를 본다)
    compute_mod_payloads()
    with open(os.path.join(SITE, "assets", "style.css") if os.path.isdir(os.path.join(SITE, "assets")) else (os.makedirs(os.path.join(SITE, "assets")) or os.path.join(SITE, "assets", "style.css")), "w") as f:
        f.write(CSS)

    build_home()
    for p in PRODUCT_LIST:
        build_product(p)
    build_categories_index()
    for cat, items in BY_CAT.items():
        build_category(cat, items)
    build_calendar()
    months = {}
    for u in UPCOMING:
        months.setdefault(u["eol"][:7], []).append(u)
    past = {}
    for p in PRODUCT_LIST:
        for c in p["cycles"]:
            if c.get("eol") and c["eol_status"] == "eol" and c["eol"] >= (TODAY - timedelta(days=365)).isoformat():
                past.setdefault(c["eol"][:7], []).append({"slug": p["slug"], "name": p["name"], "cycle": c["cycle"], "eol": c["eol"]})
    for m in sorted(set(list(months) + list(past))):
        build_month(m, months.get(m, []), past.get(m, []))
    build_announcements()
    build_about()
    build_privacy()
    build_404()
    build_llms()
    build_robots()
    build_feed()
    build_api()

    urls = [rel("/"), rel("/categories.html"), rel("/calendar.html"), rel("/announcements.html"),
            rel("/about.html"), rel("/privacy.html")]
    urls += [rel(f"/product/{p['slug']}.html") for p in PRODUCT_LIST]
    urls += [rel(f"/category/{c}.html") for c in BY_CAT]
    urls += [rel(f"/eol/{m}.html") for m in sorted(set(list(months) + list(past)))]
    build_sitemap(urls)
    save_mod_state()

    html_count = sum(1 for _, _, files in os.walk(SITE) for f in files if f.endswith(".html"))
    size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(SITE) for f in fs)
    print(f"built {html_count} HTML pages, sitemap {len(urls)} URLs, total {size/1e6:.1f} MB")
    print(f"GA: {GA or '(not set)'} · as_of {AS_OF} · products {len(PRODUCT_LIST)}")


if __name__ == "__main__":
    main()
