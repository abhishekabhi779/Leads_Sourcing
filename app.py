"""
SBA Business Search — Flask API
Run: python app.py
"""
import time
import requests
from flask import Flask, request, jsonify, render_template, Response
import pymysql
from config import MYSQL_CONFIG, FLASK_HOST, FLASK_PORT, FLASK_DEBUG, GOOGLE_PLACES_API_KEY
from scraper import scrape_contact

app = Flask(__name__)

def get_db():
    return pymysql.connect(**MYSQL_CONFIG, cursorclass=pymysql.cursors.DictCursor)

# ── Pages ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

# ── Filter dropdowns ──────────────────────────────────────────────────────────

@app.route("/api/industries")
def api_industries():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT industry AS name, COUNT(*) AS count
        FROM leads
        WHERE industry IS NOT NULL AND industry != ''
        GROUP BY industry
        ORDER BY industry
    """)
    rows = cur.fetchall()
    cur.close(); conn.close()
    return jsonify(rows)

@app.route("/api/states")
def api_states():
    conn = get_db()
    cur = conn.cursor()
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
    cur = conn.cursor()

    clauses, params = [], []

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
        clauses.append("borrower_city LIKE %s")
        params.append(f"%{city}%")

    name = request.args.get("name", "").strip()
    if name:
        clauses.append("borrower_name LIKE %s")
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
    rows = cur.fetchall()

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

# ── Enrichment (Google Places API) ───────────────────────────────────────────

def places_lookup(business_name, city, state):
    """
    Two-step Google Places lookup:
      1. Text Search  → find the place_id using name + location
      2. Place Details → pull website + phone from that place_id

    Using city+state in the query significantly improves match accuracy
    vs. just sending the business name alone.
    """
    # Step 1 — Text Search
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

    # Step 2 — Place Details (only fetch the fields we need → cheaper API call)
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

        # Step 1 — Google Places
        try:
            places = places_lookup(name, city, state)
        except Exception:
            places = {"website": None, "phone": None, "maps_url": None, "match_name": None}

        time.sleep(0.3)

        # Step 2 — Website scraper (only if Places found a website)
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
    """
    Takes the already-enriched list from the frontend and streams it
    back as a downloadable CSV file.
    """
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
            # Wrap any value containing a comma or quote in double-quotes
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
