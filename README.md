# SBA Business Search

Search ~1M+ small businesses from SBA PPP loan data by industry and location. Built as a lead generation tool — find businesses by type (e.g. restaurants, construction, healthcare) filtered by state and city.

**Next phase:** Scraper layer to enrich results with business owner names and emails.

---

## What It Does

- Loads SBA PPP public CSV data into a MySQL database
- Classifies every business by industry using NAICS codes (~80 categories)
- Simple web UI: pick industry + state + city → get a list of business names and addresses
- ~1M+ businesses across all 50 states

---

## Tech Stack

| Layer | Technology |
|---|---|
| Database | MySQL |
| Backend | Python / Flask |
| Frontend | Vanilla HTML/CSS/JS |
| ETL | Python (csv, pymysql) |

---

## Project Structure

```
SBA/
├── app.py              # Flask API server
├── load_data.py        # ETL: loads CSV → MySQL with industry classification
├── config.example.py   # Config template (copy to config.py and fill in)
├── templates/
│   └── index.html      # Search UI
├── static/
│   ├── style.css
│   └── app.js
└── .gitignore
```

---

## Setup

### 1. Prerequisites

- Python 3.8+
- MySQL 8.0+
- SBA PPP data CSVs — download free from [SBA FOIA data](https://data.sba.gov/dataset/ppp-foia)

### 2. Install dependencies

```bash
pip install flask pymysql
```

### 3. Configure

```bash
cp config.example.py config.py
# Edit config.py — set your MySQL password and CSV file paths
```

### 4. Load data (one-time, ~15–20 min for 900MB)

```bash
python load_data.py
```

Safe to re-run — duplicate rows are skipped automatically (`INSERT IGNORE` on loan number).

### 5. Run the app

```bash
python app.py
```

Open `http://127.0.0.1:5000`

---

## Database Schema

Only the columns needed for lead generation are stored. ~35 financial/lender columns from the raw CSV are intentionally dropped.

| Column | Type | Purpose |
|---|---|---|
| `loan_number` | VARCHAR UNIQUE | Deduplication key |
| `borrower_name` | VARCHAR | Business name |
| `borrower_address` | VARCHAR | Street address |
| `borrower_city` | VARCHAR | City filter |
| `borrower_state` | VARCHAR | State filter |
| `borrower_zip` | VARCHAR | ZIP code |
| `naics_code` | VARCHAR | Raw NAICS industry code |
| `industry` | VARCHAR | Human-friendly industry name (derived) |
| `business_type` | VARCHAR | LLC, Corporation, Sole Proprietor, etc. |
| `franchise_name` | VARCHAR | Franchise brand if applicable |
| `loan_status` | VARCHAR | Active / Paid in Full / Exemption 4 |
| `jobs_reported` | INT | Employee count (business size signal) |
| `current_approval_amount` | DECIMAL | Loan size (business size signal) |
| `date_approved` | VARCHAR | When loan was approved |

### Key Indexes

| Index | Columns | Why |
|---|---|---|
| `idx_state_industry` | `(borrower_state, industry)` | Powers "restaurants in NY" queries |
| `idx_state_city` | `(borrower_state, borrower_city)` | Powers city-level filters |
| `idx_ft_name` | `borrower_name` (FULLTEXT) | Business name search |

---

## API Endpoints

| Endpoint | Params | Returns |
|---|---|---|
| `GET /api/industries` | — | All industries with counts |
| `GET /api/states` | — | All states |
| `GET /api/search` | `industry`, `state`, `city`, `name`, `page` | Paginated business list |

---

## Key Concepts (for interviews)

| Concept | How it's used here |
|---|---|
| **ETL pipeline** | CSV → classify → MySQL |
| **Idempotent loading** | `INSERT IGNORE` makes re-runs safe |
| **Derived columns** | `industry` computed from `naics_code` at load time, stored for query speed |
| **Composite indexes** | `(state, industry)` faster than two separate indexes for multi-filter queries |
| **Column pruning** | Dropped 35 unused columns — 40% smaller DB, faster inserts |
| **Pagination** | `LIMIT` + `OFFSET` for large result sets |
| **Schema migration** | `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` for safe iterative changes |

---

## Roadmap

- [ ] Scraper layer: given a business name + city, find owner name and email
- [ ] Export filtered results to CSV
- [ ] Add `date_approved` range filter (target recently active businesses)
- [ ] Deduplicate chains/franchises
