"""
One-time migration: add naics_sector column and backfill from existing naics_code data.
Safe to re-run — skips if column already exists and data is already populated.
Usage: python migrate_naics_sector.py
"""
import psycopg2
from config import PG_CONFIG

# 2-digit NAICS prefix → broad sector name
SECTOR_CASE = {
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

def build_case_sql():
    whens = "\n        ".join(
        f"WHEN '{prefix}' THEN '{sector}'" for prefix, sector in SECTOR_CASE.items()
    )
    return f"""
        CASE LEFT(naics_code, 2)
        {whens}
        ELSE 'Other / Unknown'
        END
    """

def main():
    conn = psycopg2.connect(**PG_CONFIG)
    conn.autocommit = True
    cur = conn.cursor()

    # 1. Add column if missing
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'leads' AND column_name = 'naics_sector'
    """)
    if not cur.fetchone():
        cur.execute("ALTER TABLE leads ADD COLUMN naics_sector VARCHAR(100)")
        print("Added naics_sector column")
    else:
        print("naics_sector column already exists")

    # 2. Backfill — only rows not yet populated
    cur.execute("SELECT COUNT(*) FROM leads WHERE naics_sector IS NULL")
    to_fill = cur.fetchone()[0]
    print(f"Rows to backfill: {to_fill:,}")

    if to_fill > 0:
        case_sql = build_case_sql()
        cur.execute(f"UPDATE leads SET naics_sector = {case_sql} WHERE naics_sector IS NULL")
        print(f"Backfilled {to_fill:,} rows")

    # 3. Add indexes if missing
    cur.execute("""
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'leads' AND indexname = 'idx_naics_sector'
    """)
    if not cur.fetchone():
        cur.execute("CREATE INDEX idx_naics_sector ON leads (naics_sector)")
        print("Created idx_naics_sector")

    cur.execute("""
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'leads' AND indexname = 'idx_sector_state'
    """)
    if not cur.fetchone():
        cur.execute("CREATE INDEX idx_sector_state ON leads (naics_sector, borrower_state)")
        print("Created idx_sector_state")

    # 4. Report
    cur.execute("""
        SELECT naics_sector, COUNT(*) AS cnt
        FROM leads
        GROUP BY naics_sector
        ORDER BY cnt DESC
    """)
    rows = cur.fetchall()
    print("\nSector breakdown:")
    for sector, cnt in rows:
        print(f"  {sector or 'NULL':<45} {cnt:>10,}")

    cur.close()
    conn.close()
    print("\nDone.")

if __name__ == "__main__":
    main()
