"""
SBA Business Search — Flask API
Run: python app.py
"""
import os
import time
from flask import Flask, request, jsonify, render_template, Response
import psycopg2
import psycopg2.extras
from pgvector.psycopg2 import register_vector
from sentence_transformers import SentenceTransformer
from config import PG_CONFIG, FLASK_HOST, FLASK_PORT, FLASK_DEBUG
from scraper import scrape_contact
from website_finder import find_website
from odoo_client import push_leads

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
            loan_number,
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

# An industry only counts as a match above this cosine similarity...
SEMANTIC_MIN_SIMILARITY = 0.50
# ...and within this distance of the best match (so one strong hit doesn't
# drag in loosely related industries).
SEMANTIC_DROPOFF = 0.15
SEMANTIC_MAX_INDUSTRIES = 4

@app.route("/api/semantic-search")
def api_semantic_search():
    """
    Natural language search, two stages:
      1. Embed the query and score every industry by its best-matching search
         phrase (exact cosine scan over ~700 phrase vectors — small enough
         that no ANN index is needed, so recall is exact).
      2. Fetch leads for the matched industries through the ordinary B-tree
         indexes, biggest employers first.
    Never vector-searches the 1.87M lead rows: they only carry ~85 distinct
    category vectors, and HNSW recall collapses on mass-duplicated vectors
    (that's what made "banks" return wineries, and any state filter starve).

    Params:
      q      — free-text query, e.g. "metal fabrication shops"
      state  — optional state filter
      limit  — number of results (default 50, max 200)
    """
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "q parameter required"}), 400

    state = request.args.get("state", "").strip()
    limit = min(int(request.args.get("limit", 50)), 200)

    embedding = get_embed_model().encode(q, normalize_embeddings=True).tolist()

    conn = get_db()
    cur  = get_cursor(conn)

    # Stage 1 — which industries does the query mean?
    cur.execute("""
        SELECT naics_sector, industry,
               MAX(1 - (embedding <=> %s::vector)) AS similarity
        FROM industry_embeddings
        GROUP BY naics_sector, industry
        ORDER BY similarity DESC
        LIMIT 8
    """, [embedding])
    scored = [dict(r) for r in cur.fetchall()]
    for s in scored:
        s["similarity"] = round(float(s["similarity"]), 4)

    best = scored[0]["similarity"] if scored else 0.0
    cutoff = max(SEMANTIC_MIN_SIMILARITY, best - SEMANTIC_DROPOFF)
    matches = [s for s in scored if s["similarity"] >= cutoff][:SEMANTIC_MAX_INDUSTRIES]
    # On ties, put specific industries before sector-level catch-alls
    # (e.g. "banks": Banks, Credit Unions & Lenders before Finance & Insurance)
    matches.sort(key=lambda m: (-m["similarity"], m["industry"] == m["naics_sector"]))

    if not matches:
        cur.close(); conn.close()
        return jsonify({
            "query": q,
            "results": [],
            "count": 0,
            "no_match": True,
            "matched_industries": [],
            "best_guess": scored[0] if scored else None,
        })

    # Stage 2 — pull leads for those industries (industry → sector is 1:1,
    # so filtering on industry alone hits idx_leads_industry, and the
    # (borrower_state, industry) composite when a state is given).
    industries = [m["industry"] for m in matches]
    sim_by_industry = {m["industry"]: m["similarity"] for m in matches}

    rank_case = " ".join(
        f"WHEN industry = %s THEN {i}" for i in range(len(industries))
    )
    state_clause = "AND borrower_state = %s" if state else ""

    params = [tuple(industries)]
    if state:
        params.append(state)
    params += industries + [limit]

    cur.execute(f"""
        SELECT
            loan_number,
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
        WHERE industry IN %s
        {state_clause}
        ORDER BY CASE {rank_case} ELSE {len(industries)} END,
                 jobs_reported DESC NULLS LAST,
                 borrower_name ASC
        LIMIT %s
    """, params)

    rows = [dict(r) for r in cur.fetchall()]
    for row in rows:
        if hasattr(row.get("current_approval_amount"), "is_finite"):
            row["current_approval_amount"] = float(row["current_approval_amount"]) or 0
        row["similarity"] = sim_by_industry.get(row["industry"])

    cur.close(); conn.close()
    return jsonify({
        "query":   q,
        "results": rows,
        "count":   len(rows),
        "matched_industries": matches,
    })

# ── Enrichment (search-based website finder + scraper) ───────────────────────

@app.route("/api/enrich", methods=["POST"])
def api_enrich():
    """
    Full enrichment pipeline per business:
      1. Website finder (DuckDuckGo search + domain guessing, identity-verified)
         → website URL + key-free Google Maps link
      2. Website scraper → email, phone, contact name from footer/contact page
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
            found = find_website(name, city, state)
        except Exception:
            found = {"website": None, "phone": None, "maps_url": None, "match_name": None}

        time.sleep(0.3)

        scraped = {"email": None, "phone_scraped": None, "contact_name": None, "scrape_source": None}
        if found.get("website"):
            try:
                result = scrape_contact(found["website"])
                scraped = {
                    "email":         result.get("email"),
                    "phone_scraped": result.get("phone_scraped"),
                    "contact_name":  result.get("contact_name"),
                    "scrape_source": result.get("source"),
                }
                # The scraped phone is now the primary phone (no Places phone anymore)
                if result.get("phone_scraped") and not found.get("phone"):
                    found["phone"] = result["phone_scraped"]
            except Exception:
                pass

        results.append({**biz, **found, **scraped})

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
        "Website", "Phone", "Email (Scraped)", "Phone (Scraped)",
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

# ── Odoo CRM Export ───────────────────────────────────────────────────────────

@app.route("/api/export-odoo", methods=["POST"])
def api_export_odoo():
    """
    Pushes the already-enriched list from the frontend into Odoo CRM.
    Dedup: each row's loan_number becomes an Odoo external id, so re-sending
    the same businesses updates the existing leads instead of duplicating.
    """
    data = request.get_json()
    rows = data.get("rows", [])
    if not rows:
        return jsonify({"error": "No rows provided"}), 400

    try:
        result = push_leads(rows)
    except Exception as e:
        return jsonify({"error": f"Odoo push failed: {e}"}), 502
    return jsonify(result)

# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", FLASK_PORT))
    print(f"SBA Business Search — http://{FLASK_HOST}:{port}")
    app.run(host=FLASK_HOST, port=port, debug=FLASK_DEBUG)
