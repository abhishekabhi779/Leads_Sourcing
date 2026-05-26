# SBA Lead Sourcing Machine

A full lead generation pipeline built on **SBA PPP loan public data**. Search 1M+ small businesses by industry and location, then automatically find their website, email address, phone number, and contact name — ready for outreach.

**Built for:** Targeted B2B outreach (loan sales, services, etc.)
**Next phase:** Automated email campaigns using the enriched contact data.

---

## What Problem This Solves

Cold outreach is only effective when you know *who* you're calling and *what* they do. The SBA released PPP loan data for every small business that applied — that's 1M+ businesses with their name, address, industry, and size. This project turns that raw government data into actionable sales leads with real contact info.

---

## The Full Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│                        SBA PPP CSV Files                    │
│              (~900MB, 1M+ businesses, public data)          │
└────────────────────────┬────────────────────────────────────┘
                         │  load_data.py (one-time ETL)
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                      MySQL Database                         │
│   13 columns only — name, address, city, state, zip,       │
│   NAICS code, industry (classified), jobs, loan amount      │
└────────────────────────┬────────────────────────────────────┘
                         │  app.py (Flask API)
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                     Search UI (Browser)                     │
│   Filter by: Industry + State + City + Business Name        │
│   Results: paginated list of matching businesses            │
└────────────────────────┬────────────────────────────────────┘
                         │  Select up to 10 → click Enrich
                         ▼
┌──────────────────────────────────────┐
│       Step 1: Google Places API      │
│  Query: "Business Name  City  State" │
│  Returns: Website URL + Phone        │
└──────────────┬───────────────────────┘
               │  website URL found
               ▼
┌──────────────────────────────────────┐
│       Step 2: Website Scraper        │
│  Visits the website, looks for:      │
│  • Schema.org JSON-LD data           │
│  • Footer mailto: / tel: links       │
│  • /contact and /about pages         │
│  • Regex fallback on full page       │
│  Returns: Email + Phone + Owner Name │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│         Enriched CSV Export          │
│  Business Name, Address, Industry,   │
│  Website, Email, Phone, Owner Name   │
└──────────────────────────────────────┘
```

---

## How Each Part Works

### 1. Data Loading (`load_data.py`)

The SBA publishes PPP loan data as CSV files (~450MB each). This script:

- Reads each CSV row by row (streaming — never loads whole file into memory)
- **Drops 35+ columns** that aren't useful for lead generation (lender details, financial breakdowns, government codes)
- **Classifies each business** using its NAICS code → maps it to a human-friendly industry name

**What is a NAICS code?**
Every business in the US is assigned a 6-digit industry code called a NAICS code. For example:
- `722110` = Full-Service Restaurants
- `448110` = Men's Clothing Stores
- `621111` = Offices of Physicians

The scraper maps these to ~80 friendly categories like "Restaurants & Food Services", "Healthcare", "Construction", etc. This happens at **load time** (not query time) so searches stay fast.

- Inserts rows with `INSERT IGNORE` — safe to re-run, duplicates are skipped automatically
- **Composite indexes** on `(state, industry)` and `(state, city)` mean searches across millions of rows return in milliseconds

**Run once. Data stays in MySQL permanently.**

---

### 2. Search API (`app.py`)

A Flask web server with four endpoints:

| Endpoint | What it does |
|---|---|
| `GET /` | Serves the search UI |
| `GET /api/industries` | Returns all ~80 industry categories with counts |
| `GET /api/states` | Returns all 50+ state codes |
| `GET /api/search` | Filtered, paginated business search |
| `POST /api/enrich` | Runs enrichment pipeline on up to 10 businesses |
| `POST /api/export-csv` | Downloads enriched results as a CSV file |

The search query builds a `WHERE` clause dynamically based on what filters the user applies — always filtering on indexed columns so the database never does a full table scan.

---

### 3. Search UI (`templates/index.html`)

A simple single-page app. No frameworks — plain HTML, CSS, and JavaScript.

**Flow:**
1. Page loads → fetches industries and states from API → populates dropdowns
2. User picks Industry + State (+ optional City / Business Name) → hits Search
3. Results render in a table, 50 per page with pagination
4. User checks up to 10 rows → purple toolbar appears
5. Click **"Find Contacts & Export CSV"** → enrichment pipeline runs

---

### 4. Google Places Lookup

For each selected business, the app makes **two API calls** to Google Maps:

**Call 1 — Text Search**
```
GET https://maps.googleapis.com/maps/api/place/textsearch/json
    ?query=Joe's Pizza Brooklyn NY
```
Why include city + state? Sending just the business name would return the most popular result globally. Including location pins it to the right neighborhood — this is called **geo-disambiguation**.

Returns: a `place_id` (Google's unique identifier for that location)

**Call 2 — Place Details**
```
GET https://maps.googleapis.com/maps/api/place/details/json
    ?place_id=ChIJ...
    &fields=website,formatted_phone_number
```
The `fields` parameter is important — we only request what we need. The Places API charges per field, so fetching only `website` and `formatted_phone_number` keeps costs low.

Returns: website URL and phone number

---

### 5. Website Contact Scraper (`scraper.py`)

Once we have the website URL, the scraper visits it and hunts for contact info. It tries four strategies in order from most reliable to least:

**Strategy 1 — Schema.org JSON-LD**

Many modern websites embed machine-readable structured data in their HTML `<head>`:
```html
<script type="application/ld+json">
{
  "@type": "LocalBusiness",
  "telephone": "(555) 123-4567",
  "email": "owner@joespizza.com"
}
</script>
```
This is the most reliable source because the business put it there intentionally for search engines. The scraper parses this JSON directly.

**Strategy 2 — Footer links**

Browsers turn emails and phones into clickable links:
```html
<a href="mailto:owner@joespizza.com">Email us</a>
<a href="tel:+15551234567">Call us</a>
```
The scraper targets the `<footer>` element specifically — this scopes the search so it doesn't accidentally pick up emails from blog posts, navigation, or ads elsewhere on the page.

**Strategy 3 — Contact / About page**

If the homepage footer didn't have enough, the scraper looks for links like `/contact`, `/contact-us`, `/about` and visits that page. Contact pages have the highest density of useful info.

**Strategy 4 — Regex fallback**

Last resort. Scans the full visible text of the page for email and phone patterns:
- Email: `something@domain.com`
- Phone: `(555) 555-5555`, `555-555-5555`, `555.555.5555`

Generic emails like `info@`, `noreply@`, `support@`, `admin@` are filtered out — they're not useful for targeted outreach.

**Polite scraping** — the scraper waits 0.3–0.5 seconds between requests so it doesn't hammer servers or get IP-blocked.

---

## Output CSV Columns

| Column | Source | Use |
|---|---|---|
| Business Name | SBA database | Who you're calling |
| Address / City / State / ZIP | SBA database | Mailing, geo-targeting |
| Industry | Classified from NAICS | Know what they do |
| NAICS Code | SBA database | More specific industry |
| Jobs Reported | SBA database | Business size signal |
| Loan Amount ($) | SBA database | Another size signal |
| Loan Status | SBA database | Active vs paid off |
| Website | Google Places | Verify they're active |
| Phone (Google) | Google Places | Backup phone |
| **Email (Scraped)** | Website scraper | Primary outreach channel |
| **Phone (Scraped)** | Website scraper | Primary call channel |
| **Contact Name** | Website / Schema.org | Personalized outreach |
| Scrape Source | Website scraper | Audit trail |
| Google Maps URL | Google Places | Manual verification |
| Matched Name on Maps | Google Places | Accuracy check |
| Website Found? | Computed | Filter in Excel |

---

## Setup

### Prerequisites
- Python 3.8+
- MySQL 8.0+
- SBA PPP CSV files — free download from [data.sba.gov](https://data.sba.gov/dataset/ppp-foia)
- Google Places API key — from [Google Cloud Console](https://console.cloud.google.com/)

### Install

```bash
pip install flask pymysql requests beautifulsoup4
```

### Configure

```bash
cp config.example.py config.py
# Edit config.py:
#   - Set your MySQL password
#   - Set paths to your CSV files
#   - Set your Google Places API key
```

### Load data (one-time, ~15-20 min)

```bash
python load_data.py
```

Re-run safe — duplicates are automatically skipped.

### Run

```bash
python app.py
# Open http://127.0.0.1:5000
```

---

## Project Structure

```
SBA/
├── app.py              # Flask API — search, enrich, export endpoints
├── load_data.py        # ETL pipeline — CSV → MySQL with NAICS classification
├── scraper.py          # Website contact scraper — email, phone, owner name
├── config.py           # Your credentials (gitignored — never committed)
├── config.example.py   # Template — copy this to config.py
├── templates/
│   └── index.html      # Search + enrichment UI (plain HTML/JS, no framework)
├── static/
│   ├── style.css
│   └── app.js
├── .gitignore          # Excludes config.py, CSVs, pycache
└── README.md
```

---

## Key Engineering Concepts (Interview Reference)

| Concept | Where it appears in this project |
|---|---|
| **ETL pipeline** | `load_data.py` — Extract (CSV), Transform (classify NAICS, drop columns), Load (MySQL) |
| **Idempotent operations** | `INSERT IGNORE` — re-running load never creates duplicates |
| **Derived columns** | `industry` computed at load time from `naics_code`, stored for fast filtering |
| **Composite indexes** | `(state, industry)` — one index serves "restaurants in NY" better than two separate indexes |
| **Column pruning** | Kept 13 of 50+ CSV columns — smaller DB, faster inserts, less I/O |
| **API chaining** | Places Text Search → place_id → Place Details (2 calls, 1 result) |
| **Field masking** | Places Details `?fields=website,phone` — only pay for what you need |
| **Scraping priority order** | Schema.org → footer links → contact page → regex — most reliable first |
| **Geo-disambiguation** | Appending city + state to Places query to get the right local business |
| **Rate limiting** | `time.sleep()` between requests — avoid IP blocks and API quota errors |
| **Secret management** | API key in gitignored `config.py` — never touches version control |
| **Pagination** | `LIMIT + OFFSET` — never load all results at once |
| **Streaming CSV** | Flask `Response(generate())` — streams rows instead of building full string in memory |

---

## Roadmap

- [ ] Hunter.io integration — find emails by domain when scraping fails
- [ ] Automated email campaign integration (SendGrid / Mailgun)
- [ ] De-duplicate chains and franchises
- [ ] Add `date_approved` filter — target recently approved businesses
- [ ] Batch queue — process hundreds overnight with progress tracking
