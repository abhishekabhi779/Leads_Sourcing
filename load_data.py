"""
SBA Business Search — Data Loader (ETL)
Loads SBA PPP CSV files into PostgreSQL with NAICS-based industry classification.
Only stores columns needed for business lead generation.
Usage: python load_data.py
"""
import csv, sys, time, os
import psycopg2
from psycopg2.extras import execute_values
from config import PG_CONFIG, CSV_FILES, CSV_ENCODING

# 2-digit NAICS prefix → broad sector (parent of industry)
NAICS_SECTOR_MAP = {
    "11": "Agriculture & Farming",
    "21": "Mining & Energy",
    "22": "Utilities",
    "23": "Construction",
    "31": "Manufacturing",
    "32": "Manufacturing",
    "33": "Manufacturing",
    "42": "Wholesale Trade",
    "44": "Retail Trade",
    "45": "Retail Trade",
    "48": "Transportation & Warehousing",
    "49": "Transportation & Warehousing",
    "51": "Technology, Media & Telecom",
    "52": "Finance & Insurance",
    "53": "Real Estate & Rental",
    "54": "Professional Services",
    "56": "Administrative & Support Services",
    "61": "Education",
    "62": "Healthcare & Social Services",
    "71": "Entertainment & Recreation",
    "72": "Food Service & Hospitality",
    "81": "Personal & Repair Services",
    "92": "Government & Public Administration",
}

# Only the columns we actually need — everything else is dropped at load time
COLUMN_MAP = {
    "LoanNumber":             "loan_number",
    "BorrowerName":           "borrower_name",
    "BorrowerAddress":        "borrower_address",
    "BorrowerCity":           "borrower_city",
    "BorrowerState":          "borrower_state",
    "BorrowerZip":            "borrower_zip",
    "NAICSCode":              "naics_code",
    "BusinessType":           "business_type",
    "FranchiseName":          "franchise_name",
    "LoanStatus":             "loan_status",
    "JobsReported":           "jobs_reported",
    "CurrentApprovalAmount":  "current_approval_amount",
    "DateApproved":           "date_approved",
}

# NAICS prefix → human-friendly industry name (most specific first)
NAICS_MAP = [
    ("7224", "Bars & Drinking Places"),
    ("7222", "Fast Food & Limited-Service Restaurants"),
    ("7221", "Full-Service Restaurants"),
    ("722",  "Restaurants & Food Services"),
    ("721",  "Hotels & Accommodation"),
    ("72",   "Food Service & Hospitality"),
    ("713",  "Amusement & Recreation"),
    ("712",  "Museums & Cultural Institutions"),
    ("711",  "Performing Arts"),
    ("71",   "Entertainment & Recreation"),
    ("623",  "Nursing & Residential Care"),
    ("622",  "Hospitals"),
    ("621",  "Outpatient & Medical Clinics"),
    ("62",   "Healthcare & Social Services"),
    ("611",  "Schools & Education"),
    ("61",   "Education"),
    ("562",  "Waste Management"),
    ("561",  "Business Support Services"),
    ("56",   "Administrative & Support Services"),
    ("541",  "Professional & Technical Services"),
    ("54",   "Professional Services"),
    ("532",  "Equipment Rental"),
    ("531",  "Real Estate"),
    ("53",   "Real Estate & Rental"),
    ("524",  "Insurance"),
    ("522",  "Banks, Credit Unions & Lenders"),
    # 521 is central banks — real banks are 5221; rows here are misreported NAICS
    ("521",  "Central Banking & Monetary Authorities"),
    ("52",   "Finance & Insurance"),
    ("519",  "Web & Internet Publishing"),
    ("518",  "Data Processing & Hosting"),
    ("517",  "Telecommunications"),
    ("515",  "Broadcasting"),
    ("512",  "Film & Music"),
    ("511",  "Publishing"),
    ("51",   "Technology, Media & Telecom"),
    ("493",  "Warehousing & Storage"),
    ("492",  "Couriers & Delivery"),
    ("484",  "Trucking"),
    ("483",  "Water Transportation"),
    ("482",  "Rail Transportation"),
    ("481",  "Air Transportation"),
    ("48",   "Transportation"),
    ("49",   "Transportation & Warehousing"),
    ("457",  "Gas Stations"),
    ("456",  "Health & Personal Care Retail"),
    ("455",  "General Merchandise & Department Stores"),
    ("454",  "Online & Nonstore Retail"),
    ("453",  "Miscellaneous Retail"),
    ("451",  "Sporting Goods, Books & Hobby Stores"),
    ("448",  "Clothing & Accessories"),
    ("447",  "Gas Stations"),
    ("446",  "Pharmacies & Drug Stores"),
    ("445",  "Grocery & Food Stores"),
    ("444",  "Home Improvement & Hardware"),
    ("443",  "Electronics & Appliance Stores"),
    ("442",  "Furniture & Home Furnishings"),
    ("441",  "Auto Dealers & Parts"),
    ("44",   "Retail Trade"),
    ("45",   "Retail Trade"),
    ("424",  "Non-Durable Goods Wholesale"),
    ("423",  "Durable Goods Wholesale"),
    ("42",   "Wholesale Trade"),
    ("339",  "Miscellaneous Manufacturing"),
    ("337",  "Furniture Manufacturing"),
    ("336",  "Transportation Equipment Manufacturing"),
    ("334",  "Electronics Manufacturing"),
    ("333",  "Machinery Manufacturing"),
    ("332",  "Metal Products Manufacturing"),
    ("331",  "Primary Metal Manufacturing"),
    ("326",  "Plastics Manufacturing"),
    ("325",  "Chemical Manufacturing"),
    ("323",  "Printing & Publishing"),
    ("321",  "Wood Products Manufacturing"),
    ("315",  "Apparel Manufacturing"),
    ("311",  "Food & Beverage Manufacturing"),
    ("31",   "Manufacturing"),
    ("32",   "Manufacturing"),
    ("33",   "Manufacturing"),
    ("238",  "Specialty Trade Contractors"),
    ("237",  "Civil & Heavy Construction"),
    ("236",  "Building Construction"),
    ("23",   "Construction"),
    ("22",   "Utilities"),
    ("213",  "Oil & Gas Support Services"),
    ("212",  "Mining"),
    ("211",  "Oil & Gas Extraction"),
    ("21",   "Mining & Energy"),
    ("115",  "Agricultural Support Services"),
    ("114",  "Fishing & Hunting"),
    ("113",  "Forestry & Logging"),
    ("112",  "Animal Production & Ranching"),
    ("111",  "Crop Farming"),
    ("11",   "Agriculture & Farming"),
    ("812",  "Personal Care Services"),
    ("811",  "Repair & Maintenance"),
    ("81",   "Personal & Repair Services"),
    ("92",   "Government & Public Administration"),
]

def naics_to_industry(code):
    if not code:
        return "Other / Unknown"
    code = str(code).strip()
    for prefix, name in NAICS_MAP:
        if code.startswith(prefix):
            return name
    return "Other / Unknown"

def naics_to_sector(code):
    if not code:
        return "Other / Unknown"
    return NAICS_SECTOR_MAP.get(str(code).strip()[:2], "Other / Unknown")

def safe_dec(v):
    if not v or not v.strip(): return None
    try: return float(v.strip().replace(",", ""))
    except: return None

def safe_int(v):
    if not v or not v.strip(): return None
    try: return int(float(v.strip().replace(",", "")))
    except: return None

def ensure_db(cfg):
    """Create the sba_leads database if it doesn't exist."""
    admin_cfg = {**cfg, "dbname": "postgres"}
    conn = psycopg2.connect(**admin_cfg)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (cfg["dbname"],))
    if not cur.fetchone():
        cur.execute(f'CREATE DATABASE {cfg["dbname"]}')
        print(f"  Created database: {cfg['dbname']}")
    else:
        print(f"  Database '{cfg['dbname']}' already exists")
    cur.close()
    conn.close()

def create_table(cursor):
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS leads (
        id                      SERIAL PRIMARY KEY,
        loan_number             VARCHAR(20) UNIQUE,
        borrower_name           VARCHAR(255),
        borrower_address        VARCHAR(255),
        borrower_city           VARCHAR(100),
        borrower_state          VARCHAR(5),
        borrower_zip            VARCHAR(20),
        naics_code              VARCHAR(10),
        naics_sector            VARCHAR(100),
        industry                VARCHAR(100),
        business_type           VARCHAR(100),
        franchise_name          VARCHAR(255),
        loan_status             VARCHAR(50),
        jobs_reported           INT,
        current_approval_amount NUMERIC(15,2),
        date_approved           VARCHAR(20),
        source_file             VARCHAR(255)
    )
    """)

    # Add industry column if upgrading from old schema
    try:
        cursor.execute("ALTER TABLE leads ADD COLUMN industry VARCHAR(100)")
        print("  Migrated: added 'industry' column")
    except psycopg2.errors.DuplicateColumn:
        pass

    print("  Table ready")

def create_indexes(cursor):
    indexes = [
        # Composite indexes — most useful for "restaurants in NY" style queries
        ("idx_state_industry",  "borrower_state, industry"),
        ("idx_state_city",      "borrower_state, borrower_city"),
        ("idx_naics_sector",    "naics_sector"),
        ("idx_sector_state",    "naics_sector, borrower_state"),
        # Single-column indexes
        ("idx_naics",          "naics_code"),
        ("idx_bname",          "borrower_name"),
        ("idx_loan_status",    "loan_status"),
        ("idx_jobs",           "jobs_reported"),
        ("idx_amount",         "current_approval_amount"),
    ]
    for name, cols in indexes:
        cursor.execute(f"CREATE INDEX IF NOT EXISTS {name} ON leads ({cols})")

    # Full-text search index on business name
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ft_name ON leads "
        "USING gin(to_tsvector('english', coalesce(borrower_name, '')))"
    )
    print("  Indexes ready")

def load_csv(cursor, filepath, batch_size=5000):
    filename = os.path.basename(filepath)
    print(f"\nLoading: {filename}")

    with open(filepath, "r", encoding=CSV_ENCODING) as f:
        reader = csv.DictReader(f)
        csv_to_db = {c: COLUMN_MAP[c] for c in reader.fieldnames if c in COLUMN_MAP}
        db_cols = list(csv_to_db.values()) + ["naics_sector", "industry", "source_file"]
        sql = (
            f"INSERT INTO leads ({', '.join(db_cols)}) VALUES %s "
            "ON CONFLICT (loan_number) DO NOTHING"
        )
        # Fallback single-row SQL for error recovery
        single_sql = (
            f"INSERT INTO leads ({', '.join(db_cols)}) "
            f"VALUES ({', '.join(['%s'] * len(db_cols))}) "
            "ON CONFLICT (loan_number) DO NOTHING"
        )

        batch, total, skipped, t0 = [], 0, 0, time.time()

        for row in reader:
            vals = []
            naics_raw = row.get("NAICSCode", "").strip()

            for csv_col, db_col in csv_to_db.items():
                raw = row.get(csv_col, "").strip()
                if db_col == "jobs_reported":
                    vals.append(safe_int(raw))
                elif db_col == "current_approval_amount":
                    vals.append(safe_dec(raw))
                else:
                    vals.append(raw if raw else None)

            vals.append(naics_to_sector(naics_raw))
            vals.append(naics_to_industry(naics_raw))
            vals.append(filename)
            batch.append(tuple(vals))
            total += 1

            if len(batch) >= batch_size:
                try:
                    execute_values(cursor, sql, batch)
                except Exception:
                    for r in batch:
                        try: cursor.execute(single_sql, r)
                        except: skipped += 1
                batch = []
                elapsed = time.time() - t0
                print(f"   ... {total:,} rows ({total/elapsed:,.0f}/sec)", end="\r")

        if batch:
            try:
                execute_values(cursor, sql, batch)
            except Exception:
                for r in batch:
                    try: cursor.execute(single_sql, r)
                    except: skipped += 1

    elapsed = time.time() - t0
    print(f"\n   Done: {total:,} rows in {elapsed:.1f}s  ({total/elapsed:,.0f} rows/sec)")
    if skipped:
        print(f"   Skipped (errors): {skipped:,}")
    return total

def main():
    print("=" * 60)
    print("  SBA Business Search — Data Loader")
    print("=" * 60)

    print("\nEnsuring database exists...")
    ensure_db(PG_CONFIG)

    print("Connecting to sba_leads...")
    conn = psycopg2.connect(**PG_CONFIG)
    conn.autocommit = True
    cur = conn.cursor()

    create_table(cur)

    for fp in CSV_FILES:
        if not os.path.exists(fp):
            print(f"\nFile not found — skipping: {fp}")
            continue
        load_csv(cur, fp)

    print("\nBuilding indexes...")
    create_indexes(cur)

    cur.execute("SELECT COUNT(*) FROM leads")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT borrower_state) FROM leads WHERE borrower_state IS NOT NULL")
    states = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT industry) FROM leads WHERE industry IS NOT NULL")
    industries = cur.fetchone()[0]

    print(f"\n{'=' * 60}")
    print(f"  LOAD COMPLETE")
    print(f"  Total rows  : {total:,}")
    print(f"  States      : {states}")
    print(f"  Industries  : {industries}")
    print(f"{'=' * 60}")
    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
