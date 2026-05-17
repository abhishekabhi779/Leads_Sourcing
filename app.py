"""
SBA Business Search — Flask API
Run: python app.py
"""
from flask import Flask, request, jsonify, render_template
import pymysql
from config import MYSQL_CONFIG, FLASK_HOST, FLASK_PORT, FLASK_DEBUG

app = Flask(__name__)

def get_db():
    return pymysql.connect(**MYSQL_CONFIG, cursorclass=pymysql.cursors.DictCursor)

@app.route("/")
def index():
    return render_template("index.html")

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

    page = max(1, int(request.args.get("page", 1)))
    per_page = 50
    offset = (page - 1) * per_page

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
        "results": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
    })

if __name__ == "__main__":
    print(f"SBA Business Search — http://{FLASK_HOST}:{FLASK_PORT}")
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)
