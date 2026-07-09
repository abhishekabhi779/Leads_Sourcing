# SBA Lead Sourcing Machine

A full business intelligence pipeline built on **SBA PPP public loan data** — 1.87M small businesses searchable by industry, location, or plain-English description, with automated contact enrichment.

---

## What It Does

The SBA released PPP loan records for every small business that applied — names, addresses, industries, employee counts, loan amounts. This project turns that raw government dataset into an intelligent, enrichable lead database.

- **Filter search** — sector → industry cascade, state, city, business name
- **AI semantic search** — type "metal fabrication shops" and find them even if the NAICS label says "Metal Products Manufacturing"
- **Contact enrichment** — select any businesses → Google Places finds their website and phone → scraper extracts email, owner name, and direct contact
- **CSV export** — enriched rows ready for outreach

---

## The Full Pipeline

```
┌──────────────────────────────────────────────────┐
│              SBA PPP CSV Files                   │
│        (~900MB, 1.87M businesses, public)        │
└─────────────────────┬────────────────────────────┘
                      │  load_data.py (one-time ETL)
                      ▼
┌──────────────────────────────────────────────────┐
│           PostgreSQL 18 + pgvector               │
│  13 columns: name, address, city, state, zip,    │
│  NAICS code, naics_sector, industry, jobs,       │
│  loan amount, embedding vector(384)              │
└─────────────────────┬────────────────────────────┘
                      │  app.py (Flask API)
                      ▼
┌──────────────────────────────────────────────────┐
│                Search UI                         │
│  Filter Search (sector → industry cascade)       │
│  AI Semantic Search (vector similarity)          │
└─────────────────────┬────────────────────────────┘
                      │  Select up to 10 → Enrich
                      ▼
┌─────────────────────────────────┐
│      Step 1: Google Places      │
│  Returns: website + phone       │
└───────────────┬─────────────────┘
                │
                ▼
┌─────────────────────────────────┐
│      Step 2: Website Scraper    │
│  Returns: email, owner name,    │
│  direct phone                   │
└───────────────┬─────────────────┘
                │
                ▼
┌─────────────────────────────────┐
│         CSV Export              │
└─────────────────────────────────┘
```

---

## How Each Part Works

### 1. Data Loading (`load_data.py`)

Reads SBA CSV files row by row (streaming — never loads the full file into memory), drops 35+ irrelevant columns, and classifies each business at load time using its NAICS code.

**Two-level industry classification:**

Every US business has a 6-digit NAICS code. The loader maps these to two human-readable columns:

| Column | Example | Purpose |
|---|---|---|
| `naics_sector` | Manufacturing | Broad filter (20 sectors) |
| `industry` | Primary Metal Manufacturing | Specific label shown in results |

This matters: a simple `WHERE industry = 'Manufacturing'` would miss all the sub-categories. Storing the 2-digit parent sector separately fixes this — filtering by sector correctly returns every manufacturing sub-type.

Inserts use `ON CONFLICT (loan_number) DO NOTHING` — safe to re-run, no duplicates.

---

### 2. Semantic Search Layer

Search queries and curated industry search phrases are converted to 384-dimensional vectors using [`all-MiniLM-L6-v2`](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) — a local embedding model that runs entirely on CPU.

```
"plumbers"  →  [0.67, -0.12, 0.23, ...]  (384 numbers)
"plumbers" (a phrase of Specialty Trade Contractors)  →  cosine ≈ 1.0  (hit!)
"wineries" (a phrase of Food & Beverage Manufacturing)  →  cosine ≈ 0.1 (far away)
```

Each of the 85 industry categories is represented by **many short phrase vectors** (its label plus curated keywords from `industry_search_texts.py`, ~670 rows total in the `industry_embeddings` table). A query scores each industry by its **best-matching phrase**, keeping single-word queries sharp instead of diluting them against long descriptions.

Search runs in two stages: (1) exact cosine scan over the ~670 phrase vectors picks up to 4 industries above a similarity threshold — no ANN index, so recall is exact and off-topic queries return "no match" instead of garbage; (2) leads for those industries are fetched through ordinary B-tree indexes (state filter included), biggest employers first.

> Why not embed all 1.87M rows? They'd only carry 85 distinct vectors, and HNSW recall collapses on mass-duplicated vectors — searches got stuck inside one duplicate cluster ("banks" returned wineries) and state filters starved to zero rows.

---

### 3. Search API (`app.py`)

Flask with direct `psycopg2` connections (no ORM).

| Endpoint | What it does |
|---|---|
| `GET /api/sectors` | 20 broad sectors with counts |
| `GET /api/industries?sector=` | Industries filtered to a sector (cascade) |
| `GET /api/states` | All state codes |
| `GET /api/search` | Filtered, paginated results (sector, industry, state, city, name) |
| `GET /api/semantic-search` | Two-stage semantic search — `?q=metal+fabrication&state=TX` |
| `POST /api/enrich` | Enrichment pipeline — up to 10 businesses per batch |
| `POST /api/export-csv` | Streams enriched rows as a downloadable CSV |

---

### 4. Google Places Lookup

Two API calls per business:

**Call 1 — Text Search** (`"Business Name City State"`)
Returns a `place_id`. Including city + state is critical for geo-disambiguation — without it you get the most famous result globally, not the local one.

**Call 2 — Place Details** (`?fields=website,formatted_phone_number`)
The `fields` param matters — the Places API bills per field requested.

---

### 5. Website Scraper (`scraper.py`)

Visits the website and tries four strategies in priority order:

1. **Schema.org JSON-LD** — structured data businesses embed for search engines. Most reliable.
2. **Footer `mailto:` / `tel:` links** — scoped to `<footer>` to avoid picking up emails from blog posts or ads.
3. **Contact / About page** — follows `/contact`, `/about`, `/contact-us` links.
4. **Regex fallback** — scans full page text for email and phone patterns.

Generic emails (`info@`, `noreply@`, `support@`) are filtered out — not useful for targeted outreach.

---

## Setup

### Prerequisites

- Python 3.10+
- PostgreSQL 18 (port 5432)
- pgvector 0.8.2 for PG18 — see `install_pgvector_admin.ps1`
- SBA PPP CSV files — free from [data.sba.gov](https://data.sba.gov/dataset/ppp-foia)
- Google Places API key — from [Google Cloud Console](https://console.cloud.google.com/)

### Install dependencies

```bash
pip install flask psycopg2-binary requests beautifulsoup4 pgvector sentence-transformers
```

### Configure

```bash
copy config.example.py config.py
# Set your PostgreSQL password, CSV paths, and Google Places API key
```

### One-time setup

```bash
# 1. Load CSV data into PostgreSQL (~15–20 min for 900MB)
python load_data.py

# 2. Add naics_sector column and backfill
python migrate_naics_sector.py

# 3. Build the industry_embeddings phrase table (re-run after editing industry_search_texts.py)
python setup_embeddings.py
```

All three scripts are safe to re-run.

### Run

```bash
python app.py
# → http://127.0.0.1:5000
```

---

## Project Structure

```
SBA/
├── app.py                    # Flask API — all endpoints
├── load_data.py              # ETL — CSV → PostgreSQL + NAICS classification
├── scraper.py                # Website contact scraper
├── migrate_naics_sector.py   # One-time: adds naics_sector column
├── setup_embeddings.py       # Builds industry_embeddings phrase table (pgvector)
├── industry_search_texts.py  # Curated search phrases per industry — the search "vocabulary"
├── install_pgvector_admin.ps1  # Admin: installs pgvector into PG18 on Windows
├── config.py                 # Credentials (gitignored)
├── config.example.py         # Template
├── templates/
│   └── index.html            # Search UI — filter mode + AI semantic search
└── learnings.md              # Notes from the build
```

---

## Roadmap

- [ ] Contact enrichment via Hunter.io when scraping fails
- [ ] Batch overnight enrichment queue with progress tracking
- [ ] Claude API integration — natural language → structured query parser
- [ ] Additional public datasets (SEC EDGAR, USASpending.gov, building permits)
- [ ] De-duplicate franchise chains
