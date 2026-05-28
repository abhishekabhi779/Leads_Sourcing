"""
SBA Business Search — Flask API
Run: python app.py
"""
import time
import requests
from flask import Flask, request, jsonify, render_template, Response
import psycopg2
import psycopg2.extras
from pgvector.psycopg2 import register_vector
from sentence_transformers import SentenceTransformer
from config import PG_CONFIG, FLASK_HOST, FLASK_PORT, FLASK_DEBUG, GOOGLE_PLACES_API_KEY
from scraper import scrape_contact

app = Flask(__name__)

# Loaded once at startup — stays in memory for the life of the process
_embed_model = None

def get_embed_model():
    global _embed_model
    if _embed_model is None:
        _embed_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embed_model

def get_db():
    conn = psycopg2.connect(**PG_CONFIG)
    register_vector(conn)
    return conn

def get_cursor(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

# ── Pages ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

# ── Filter dropdowns ──────────────────────────────────────────────────────────

@app.route("/api/industries")
def api_industries():
    conn = get_db()
    cur = get_cursor(conn)
    sector = request.args.get("sector", "").strip()
    if sector:
        cur.execute("""
            SELECT industry AS name, COUNT(*) AS count
            FROM leads
            WHERE industry IS NOT NULL AND industry != ''
              AND naics_sector = %s
            GROUP BY industry
            ORDER BY industry
        """, [sector])
    else:
        cur.execute("""
            SELECT industry AS name, COUNT(*) AS count
            FROM leads
            WHERE industry IS NOT NULL AND industry != ''
            GROUP BY industry
            ORDER BY industry
        """)
    rows = cur.fetchall()
    cur.close(); conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/sectors")
def api_sectors():
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute("""
        SELECT naics_sector AS name, COUNT(*) AS count
        FROM leads
        WHERE naics_sector IS NOT NULL AND naics_sector != ''
        GROUP BY naics_sector
        ORDER BY naics_sector
    """)
    rows = cur.fetchall()
    cur.close(); conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/states")
def api_states():
    conn = get_db()
    cur = get_cursor(conn)
    cur.execute("""
        SELECT DISTINCT borrower_state AS state
        FROM leads
        WHERE borrower_state IS NOT NULL AND borrower_state != ''
        ORDER BY borrower_state
    """)
    rows = [r["state"] for r in cur.fetchall()]
    cur.close(); conn.close()
    return jsonify(rows)

# ── Search ────────────────────────────────────────────────────────────────────

@app.route("/api/search")
def api_search():
    conn = get_db()
    cur = get_cursor(conn)

    clauses, params = [], []

    sector = request.args.get("sector", "").strip()
    if sector:
        clauses.append("naics_sector = %s")
        params.append(sector)

    industry = request.args.get("industry", "").strip()
    if industry:
        clauses.append("industry = %s")
        params.append(industry)

    state = request.args.get("state", "").strip()
    if state:
        clauses.append("borrower_state = %s")
        params.append(state)

    city = request.args.get("city", "").strip()
    if city:
        clauses.append("borrower_city ILIKE %s")
        params.append(f"%{city}%")

    name = request.args.get("name", "").strip()
    if name:
        clauses.append("borrower_name ILIKE %s")
        params.append(f"%{name}%")

    where = " AND ".join(clauses) if clauses else "1=1"

    page     = max(1, int(request.args.get("page", 1)))
    per_page = 50
    offset   = (page - 1) * per_page

    cur.execute(f"SELECT COUNT(*) AS cnt FROM leads WHERE {where}", params)
    total = cur.fetchone()["cnt"]

    cur.execute(f"""
        SELECT
            borrower_name,
            borrower_address,
            borrower_city,
            borrower_state,
            borrower_zip,
            naics_sector,
            industry,
            naics_code,
            business_type,
            jobs_reported,
            current_approval_amount,
            loan_status
        FROM leads
        WHERE {where}
        ORDER BY borrower_name ASC
        LIMIT %s OFFSET %s
    """, params + [per_page, offset])
    rows = [dict(r) for r in cur.fetchall()]

    for row in rows:
        for k, v in row.items():
            if hasattr(v, "is_finite"):
                row[k] = float(v) if v else 0

    cur.close(); conn.close()
    return jsonify({
        "results":     rows,
        "total":       total,
        "page":        page,
        "per_page":    per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
    })

# ── Semantic Search ───────────────────────────────────────────────────────────

@app.route("/api/semantic-search")
def api_semantic_search():
    """
    Natural language search using vector similarity.
    Query is embedded with the same model used at setup time, then compared
    against the stored industry embeddings via cosine distance (HNSW index).

    Params:
      q      — free-text query, e.g. "metal fabrication shops"
      state  — optional state filter (applied after vector search)
      limit  — number of results (default 50, max 200)
    """
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "q parameter required"}), 400

    state  = request.args.get("state", "").strip()
    limit  = min(int(request.args.get("limit", 50)), 200)

    model  = get_embed_model()
    embedding = model.encode(
        f"sector: unknown | industry: {q}",
        normalize_embeddings=True
    ).tolist()

    conn = get_db()
    cur  = get_cursor(conn)

    state_clause = "AND borrower_state = %s" if state else ""
    state_params = [state] if state else []

    cur.execute(f"""
        SELECT
            borrower_name,
            borrower_address,
            borrower_city,
            borrower_state,
            borrower_zip,
            naics_sector,
            industry,
            naics_code,
            business_type,
            jobs_reported,
            current_approval_amount,
            loan_status,
            1 - (embedding <=> %s::vector) AS similarity
        FROM leads
        WHERE embedding IS NOT NULL
        {state_clause}
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """, [embedding] + state_params + [embedding, limit])

    rows = [dict(r) for r in cur.fetchall()]
    for row in rows:
        if hasattr(row.get("current_approval_amount"), "is_finite"):
            row["current_approval_amount"] = float(row["current_approval_amount"]) or 0
        if row.get("similarity") is not None:
            row["similarity"] = round(float(row["similarity"]), 4)

    cur.close(); conn.close()
    return jsonify({
        "query":   q,
        "results": rows,
        "count":   len(rows),
    })

# ── Enrichment (Google Places API) ───────────────────────────────────────────

def places_lookup(business_name, city, state):
    """
    Two-step Google Places lookup:
      1. Text Search  → find the place_id using name + location
      2. Place Details → pull website + phone from that place_id
    """
    query = f"{business_name} {city} {state}"
    search_url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    search_resp = requests.get(search_url, params={
        "query": query,
        "key":   GOOGLE_PLACES_API_KEY,
    }, timeout=10)
    search_data = search_resp.json()

    if search_data.get("status") != "OK" or not search_data.get("results"):
        return {"website": None, "phone": None, "maps_url": None, "match_name": None}

    top = search_data["results"][0]
    place_id   = top["place_id"]
    match_name = top.get("name", "")
    maps_url   = f"https://www.google.com/maps/place/?q=place_id:{place_id}"

    details_url = "https://maps.googleapis.com/maps/api/place/details/json"
    details_resp = requests.get(details_url, params={
        "place_id": place_id,
        "fields":   "website,formatted_phone_number",
        "key":      GOOGLE_PLACES_API_KEY,
    }, timeout=10)
    details = details_resp.json().get("result", {})

    return {
        "website":    details.get("website"),
        "phone":      details.get("formatted_phone_number"),
        "maps_url":   maps_url,
        "match_name": match_name,
    }

@app.route("/api/enrich", methods=["POST"])
def api_enrich():
    """
    Full enrichment pipeline per business:
      1. Google Places → website URL + phone
      2. Website scraper → email, scraped phone, contact name from footer/contact page
    """
    data       = request.get_json()
    businesses = data.get("businesses", [])

    if not businesses:
        return jsonify({"error": "No businesses provided"}), 400
    if len(businesses) > 10:
        return jsonify({"error": "Max 10 businesses per batch"}), 400

    results = []
    for biz in businesses:
        name  = biz.get("borrower_name", "")
        city  = biz.get("borrower_city", "")
        state = biz.get("borrower_state", "")

        try:
            places = places_lookup(name, city, state)
        except Exception:
            places = {"website": None, "phone": None, "maps_url": None, "match_name": None}

        time.sleep(0.3)

        scraped = {"email": None, "phone_scraped": None, "contact_name": None, "scrape_source": None}
        if places.get("website"):
            try:
                result = scrape_contact(places["website"])
                scraped = {
                    "email":         result.get("email"),
                    "phone_scraped": result.get("phone_scraped"),
                    "contact_name":  result.get("contact_name"),
                    "scrape_source": result.get("source"),
                }
            except Exception:
                pass

        results.append({**biz, **places, **scraped})

    return jsonify({"results": results})

# ── CSV Export ────────────────────────────────────────────────────────────────

@app.route("/api/export-csv", methods=["POST"])
def api_export_csv():
    """Takes the already-enriched list from the frontend and streams it as a CSV."""
    data  = request.get_json()
    rows  = data.get("rows", [])

    headers = [
        "Business Name", "Address", "City", "State", "ZIP",
        "Industry", "NAICS Code", "Jobs Reported", "Loan Amount ($)", "Loan Status",
        "Website", "Phone (Google)", "Email (Scraped)", "Phone (Scraped)",
        "Contact Name", "Scrape Source",
        "Google Maps URL", "Matched Name on Maps", "Website Found?",
    ]

    def generate():
        yield ",".join(headers) + "\n"
        for r in rows:
            loan_amt = r.get("current_approval_amount", "") or ""
            if loan_amt:
                try: loan_amt = f"{float(loan_amt):,.0f}"
                except: pass
            website = r.get("website", "") or ""
            vals = [
                r.get("borrower_name", ""),
                r.get("borrower_address", ""),
                r.get("borrower_city", ""),
                r.get("borrower_state", ""),
                r.get("borrower_zip", ""),
                r.get("industry", ""),
                r.get("naics_code", ""),
                str(r.get("jobs_reported", "") or ""),
                str(loan_amt),
                r.get("loan_status", ""),
                website,
                r.get("phone", "") or "",
                r.get("email", "") or "",
                r.get("phone_scraped", "") or "",
                r.get("contact_name", "") or "",
                r.get("scrape_source", "") or "",
                r.get("maps_url", "") or "",
                r.get("match_name", "") or "",
                "Yes" if website else "No",
            ]
            safe = []
            for v in vals:
                v = str(v)
                if "," in v or '"' in v or "\n" in v:
                    v = '"' + v.replace('"', '""') + '"'
                safe.append(v)
            yield ",".join(safe) + "\n"

    return Response(
        generate(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=sba_enriched_leads.csv"},
    )

# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"SBA Business Search — http://{FLASK_HOST}:{FLASK_PORT}")
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)
