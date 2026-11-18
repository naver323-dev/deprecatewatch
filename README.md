# DeprecateWatch

A static, machine-readable archive of **end-of-life (EOL) and deprecation dates** for SDKs, runtimes,
frameworks, databases, operating systems, server applications and managed cloud services.

Live site: https://deprecatewatch.pages.dev

The snapshot in this repository holds 489 products and 9,418 release cycles. Every date is copied from an
upstream source — nothing is estimated, interpolated or hand-edited. `data/eol_normalized.json` carries the
snapshot date (`as_of`), and every page repeats it.

## What is in the site

| Path | Contents |
|---|---|
| `/` | EOL dates in the next 90 days, AWS Lambda runtime deprecations, recent vendor announcements, FAQ |
| `/product/{slug}.html` | 489 product pages: every tracked cycle with release date, active-support end, EOL date, latest release and status |
| `/category/{category}.html` | Products grouped by type |
| `/eol/{YYYY-MM}.html` | Every cycle whose EOL date falls in that month |
| `/calendar.html` | The next 365 days of deadlines |
| `/announcements.html` | Dated deprecation/retirement notes from Google Cloud, Azure, AWS and GitHub feeds |
| `/api/eol.json` | Full dataset (`application/json`) |
| `/api/products.json`, `/api/upcoming.json`, `/api/announcements.json` | Smaller feeds |
| `/llms.txt` | Plain-text site map for language models |
| `/feed.xml`, `/sitemap.xml`, `/robots.txt` | RSS, sitemap, crawler rules (AI crawlers allowed) |

Everything is static HTML: the tables render without JavaScript. The only script is the Google Analytics 4 tag.

## Pipeline

```bash
python3 scripts/fetch.py        # download every source into data/raw/ (cached; REFRESH=1 to refetch)
python3 scripts/normalize.py    # data/raw/ -> data/eol_normalized.json
python3 scripts/build_site.py   # data/eol_normalized.json -> site/
python3 scripts/check_site.py   # verification; exits 1 on any failure
```

`python3 scripts/build_all.py` runs the four steps in order. No third-party Python packages are required —
everything is the standard library, and no API key is used anywhere.

### Sources

- **endoflife.date API v1** — cycle, active-support and EOL dates for 489 products. MIT licensed, © endoflife.date contributors.
- **AWS Lambda runtimes documentation** — published runtime deprecation dates.
- **Google Cloud release notes feed**, **Azure service updates feed**, **AWS What's New**, **GitHub release feeds** — dated deprecation and breaking-change notes.

Each product page and announcement links back to the source it was read from.

### Status rules

| Status | Meaning |
|---|---|
| `supported` | published EOL date is in the future and active support has not ended |
| `security-only` | active support has ended, EOL date still ahead |
| `eol` | end of life: the published EOL date has passed, **or** the upstream marks the cycle end of life without a date |
| `eol` + `eol_date_published: false` (`eol-no-date`) | marked end of life, but the upstream publishes no date for it — shown as “End of life (date not published)”, counted in `counts.eol_without_date` |
| `no-eol-date` | the upstream publishes no EOL date and does not mark the cycle end of life — no date is invented |

Status is computed from the snapshot date only, so the same build always yields the same statuses.
`counts.eol_cycles` is the total of `eol_with_date` + `eol_without_date`; quote the split, not the total alone,
when saying how many cycles are past their EOL date.

## Automation

`.github/workflows/update.yml` runs weekly, Mondays 21:00 UTC (Tuesdays 06:00 Asia/Seoul): fetch → normalize → build → check,
then commits the refreshed snapshot. Cloudflare Pages deploys the `site/` directory from `main`.

`sitemap.xml` `lastmod` and JSON-LD `dateModified` are **not** the build date: `data/site_state.json` keeps a
fingerprint of the data each page renders, and a page's date only moves when that fingerprint changes. The state
file is committed with the snapshot so the dates survive between weekly runs.

## Editing

- Site copy, layout and JSON-LD: `scripts/build_site.py`.
- Category labels and CSS: `scripts/build_site.py` (`CATEGORY_LABEL`, `CSS`).
- GA4 measurement ID, base URL, contact: `data/site_config.json`.

If you change the schema, bump `schema_version` in `scripts/normalize.py` and update `/llms.txt` in
`scripts/build_site.py` together — the API contract is described there.

## Licence and attribution

The build scripts are MIT licensed (see `LICENSE`). EOL and support data come from endoflife.date
(MIT, © endoflife.date contributors) and from vendor documentation and release feeds, which remain the property
of their vendors and are quoted with a link to the original. DeprecateWatch is not affiliated with any vendor.
