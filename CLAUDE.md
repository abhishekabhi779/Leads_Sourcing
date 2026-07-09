# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install flask psycopg2-binary requests beautifulsoup4 ddgs pgvector sentence-transformers

# One-time data load (~15–20 min for 900MB of CSVs)
python load_data.py

# Build the semantic-search phrase table (re-run after editing industry_search_texts.py)
python setup_embeddings.py

# Run the Flask dev server
python app.py
# → http://127.0.0.1:5000
```

## Setup

`config.py` is gitignored. Copy from the template and fill in PostgreSQL credentials and CSV paths before running anything:

```bash
copy config.example.py config.py
```

CSV files come from [SBA FOIA data](https://data.sba.gov/dataset/ppp-foia) and must be encoded `latin-1`.

## Architecture

**ETL flow**: `load_data.py` reads SBA PPP CSVs → classifies each row's NAICS code against `NAICS_MAP` → inserts into PostgreSQL `sba_leads.leads` table via `INSERT ... ON CONFLICT DO NOTHING` (safe to re-run; `loan_number` is the dedup key).

**API layer** (`app.py`): Flask with direct `psycopg2` connections (no ORM). Endpoints powering the current UI:
- `GET /api/industries` — distinct industries with counts
- `GET /api/states` — distinct state codes
- `GET /api/search` — paginated, filtered results (industry, state, city ILIKE, name ILIKE); 50 rows/page
- `GET /api/semantic-search` — two-stage: exact cosine over `industry_embeddings` phrase vectors picks ≤4 industries (threshold 0.50), then a B-tree lookup on `leads` by industry, biggest employers first
- `POST /api/enrich` — website finder + contact scraper for ≤10 selected businesses
- `POST /api/export-csv` — streams enriched rows as CSV
- `POST /api/export-odoo` — pushes enriched rows into Odoo CRM (`odoo_client.py`)

**Odoo integration** (`odoo_client.py`): XML-RPC push into a local Dockerized Odoo (settings in `ODOO_CONFIG` in `config.py`). Leads go through `crm.lead.load()` with external ids `sba_import.lead_<loan_number>`, so re-pushing the same business updates the existing lead instead of duplicating. Serialization conflicts from Odoo background jobs are retried in the client because `load()` reports them as messages rather than raising.

**Frontend mismatch**: There are two UI versions in conflict.
- `templates/index.html` — simple, self-contained, works with the current API
- `static/app.js` + `static/style.css` — advanced version (dark glassmorphism, charts via Chart.js, multi-select filters, export, lead detail modal) that calls endpoints which **do not yet exist**: `/api/filters`, `/api/stats`, `/api/leads`, `/api/lead/<id>`, `/api/leads/export`

`app.py` currently only serves `index.html` (the simple version). The advanced frontend in `static/` is the intended next phase and requires new backend endpoints to be built.

## Key design decisions

- **Industry classification** happens at load time (`naics_to_industry()` in `load_data.py`), not query time. The result is stored in the `industry` column so queries can filter on a plain string rather than computing NAICS prefix matches per-row.
- **Semantic search never vector-searches the `leads` table.** Leads only carry ~85 distinct categories, and HNSW recall collapses on mass-duplicated vectors (searches got stuck in one duplicate cluster; state filters returned zero rows). Instead, each category is embedded as many short search phrases (label + curated keywords in `industry_search_texts.py`, ~670 rows in `industry_embeddings`) and scored by its best-matching phrase — short phrases keep single-word queries like "plumbers" sharp. To make a query findable, add phrases to `industry_search_texts.py` and re-run `setup_embeddings.py`. The legacy `leads.embedding` column + HNSW index are unused (~3 GB, safe to drop).
- **Composite indexes** `(borrower_state, industry)` and `(borrower_state, borrower_city)` are the primary query accelerators — always filter by state first when adding new queries.
- **Decimal handling**: `psycopg2` returns PostgreSQL `NUMERIC` as Python `Decimal` objects. The `api_search` handler coerces these with `float()` before JSON serialization.
- `load_data.py` drops ~35 financial/lender columns from the raw CSV intentionally — only lead-generation-relevant columns are stored.
