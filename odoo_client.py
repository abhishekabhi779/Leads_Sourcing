"""
Odoo CRM integration — pushes enriched leads into a local Odoo instance.

Uses Odoo's external XML-RPC API (stdlib only, no new dependencies):
  /xmlrpc/2/common  -> authenticate once, get a user id
  /xmlrpc/2/object  -> execute_kw(model, method, args) for everything else

Idempotency: every lead is pushed through crm.lead.load() with an external id
derived from its SBA loan number ("sba_import.lead_<loan_number>").
Pushing the same business twice UPDATES the existing record instead of
creating a duplicate — same mechanism Odoo's CSV import uses.
"""
import time
import xmlrpc.client
from config import ODOO_CONFIG

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}

# Column order for crm.lead.load() — "id" is the external id (dedup key)
LOAD_FIELDS = [
    "id", "name", "partner_name", "contact_name", "email_from", "phone",
    "website", "street", "city", "zip", "state_id", "country_id",
    "expected_revenue", "tag_ids", "description", "type",
]


def _connect():
    """Authenticate and return (uid, object_proxy)."""
    url = ODOO_CONFIG["url"]
    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    uid = common.authenticate(
        ODOO_CONFIG["db"], ODOO_CONFIG["username"], ODOO_CONFIG["api_key"], {})
    if not uid:
        raise RuntimeError("Odoo authentication failed — check ODOO_CONFIG in config.py")
    return uid, xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")


def _execute(uid, models, model, method, *args, **kwargs):
    return models.execute_kw(
        ODOO_CONFIG["db"], uid, ODOO_CONFIG["api_key"],
        model, method, list(args), kwargs)


def _external_id(row):
    """Stable dedup key per business: prefer the loan number (unique in SBA data)."""
    loan_no = str(row.get("loan_number") or "").strip()
    if loan_no:
        return f"sba_import.lead_{loan_no}"
    slug = "".join(c if c.isalnum() else "_"
                   for c in f"{row.get('borrower_name','')}_{row.get('borrower_zip','')}")
    return f"sba_import.lead_{slug.lower()}"


def _to_load_row(row):
    """Map one enriched SBA row (api_enrich output shape) to crm.lead columns."""
    amount = row.get("current_approval_amount") or 0
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        amount = 0.0
    desc = (
        f"SBA PPP loan data<br/>"
        f"Loan #: {row.get('loan_number') or 'n/a'} | "
        f"NAICS: {row.get('naics_code') or 'n/a'} | "
        f"Industry: {row.get('industry') or 'n/a'}<br/>"
        f"Jobs reported: {row.get('jobs_reported') or 'n/a'} | "
        f"Loan status: {row.get('loan_status') or 'n/a'} | "
        f"Amount: ${amount:,.0f}<br/>"
        f"Maps: {row.get('maps_url') or 'n/a'} | "
        f"Matched name: {row.get('match_name') or 'n/a'} | "
        f"Scrape source: {row.get('scrape_source') or 'n/a'}"
    )
    return {
        "id":               _external_id(row),
        "name":             f"SBA - {row.get('borrower_name', '')}",
        "partner_name":     row.get("borrower_name") or "",
        "contact_name":     row.get("contact_name") or "",
        "email_from":       row.get("email") or "",
        "phone":            row.get("phone") or row.get("phone_scraped") or "",
        "website":          row.get("website") or "",
        "street":           row.get("borrower_address") or "",
        "city":             row.get("borrower_city") or "",
        "zip":              row.get("borrower_zip") or "",
        "state_id":         STATE_NAMES.get(row.get("borrower_state") or "", ""),
        "country_id":       "United States",
        "expected_revenue": f"{amount:.2f}",
        "tag_ids":          (row.get("industry") or "").replace(",", " -"),
        "description":      desc,
        "type":             "lead",
    }


def _ensure_tags(uid, models, tag_names):
    """crm.lead.load() matches tags by name but won't create them — do it here."""
    wanted = sorted({t for t in tag_names if t})
    if not wanted:
        return
    existing = _execute(uid, models, "crm.tag", "search_read",
                        [("name", "in", wanted)], fields=["name"])
    have = {t["name"] for t in existing}
    for name in wanted:
        if name not in have:
            _execute(uid, models, "crm.tag", "create", {"name": name})


def push_leads(rows):
    """
    Push enriched SBA rows into Odoo CRM. Returns
    {created, updated, total, messages} — messages only on field errors.
    """
    uid, models = _connect()

    load_rows = [_to_load_row(r) for r in rows]
    _ensure_tags(uid, models, [r["tag_ids"] for r in load_rows])

    data = [[r[f] for f in LOAD_FIELDS] for r in load_rows]
    names = [r["id"].split(".", 1)[1] for r in load_rows]

    # Serialization conflicts (Odoo background jobs touching the same leads)
    # surface as load() messages instead of raising, so Odoo's built-in
    # request retry never kicks in — retry here instead.
    for attempt in range(3):
        # Which external ids already exist? (created vs updated in the response)
        existing = _execute(uid, models, "ir.model.data", "search_read",
                            [("module", "=", "sba_import"), ("name", "in", names)],
                            fields=["name"])
        existing_names = {e["name"] for e in existing}
        updated = sum(1 for n in names if n in existing_names)

        res = _execute(uid, models, "crm.lead", "load", LOAD_FIELDS, data)
        messages = [m.get("message", "") for m in res.get("messages", [])]
        if not any("serialize" in m for m in messages):
            break
        time.sleep(1 + attempt)

    n_loaded = len(res.get("ids") or [])
    return {
        "created":  max(n_loaded - updated, 0),
        "updated":  updated if n_loaded else 0,
        "total":    n_loaded,
        "messages": messages,
    }
