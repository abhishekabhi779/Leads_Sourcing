"""
Semantic search setup — builds the industry_embeddings lookup table.

Design: leads only carry ~85 distinct (naics_sector, industry) categories, so
per-row vectors are pure duplication — and HNSW recall collapses when millions
of rows share a handful of identical vectors (nearest-neighbour walks get stuck
inside one duplicate cluster and never reach the true best match).

Instead we embed each category's search phrases (label + curated keywords,
one short vector per phrase, ~900 rows total) into a tiny table. Search =
exact cosine scan with a per-category MAX (milliseconds, no vector index),
then a plain indexed lookup on leads by (naics_sector, industry).

Safe to re-run: the table is derived data and is rebuilt from scratch.

Usage: python setup_embeddings.py
"""
import psycopg2
from pgvector.psycopg2 import register_vector
from sentence_transformers import SentenceTransformer
from config import PG_CONFIG
from industry_search_texts import INDUSTRY_KEYWORDS, iter_search_phrases

MODEL_NAME = "all-MiniLM-L6-v2"  # 384 dims, 80 MB, runs on CPU — must match app.py
DIMS = 384

def main():
    print("Loading embedding model (downloads ~80 MB on first run)...")
    model = SentenceTransformer(MODEL_NAME)
    print(f"Model loaded: {MODEL_NAME}")

    conn = psycopg2.connect(**PG_CONFIG)
    conn.autocommit = True
    register_vector(conn)
    cur = conn.cursor()

    cur.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 1. All categories that actually exist in the data
    cur.execute("""
        SELECT DISTINCT naics_sector, industry
        FROM leads
        WHERE naics_sector IS NOT NULL AND industry IS NOT NULL
        ORDER BY naics_sector, industry
    """)
    pairs = cur.fetchall()
    print(f"Distinct (sector, industry) categories: {len(pairs)}")

    # 2. One row per search phrase (label + each keyword) per category —
    #    an industry's match score is the MAX over its phrases, so short
    #    phrases stay sharp instead of being averaged into one muddy vector.
    missing = sorted({i for _, i in pairs if i not in INDUSTRY_KEYWORDS})
    if missing:
        print(f"WARNING — no keywords defined for: {missing} (embedding bare label only)")

    rows = [
        (sector, industry, phrase)
        for sector, industry in pairs
        for phrase in iter_search_phrases(sector, industry)
    ]
    print(f"Embedding {len(rows)} search phrases...")
    embeddings = model.encode(
        [phrase for _, _, phrase in rows],
        show_progress_bar=True, normalize_embeddings=True,
    )

    # 3. Rebuild the lookup table
    cur.execute("DROP TABLE IF EXISTS industry_embeddings")
    cur.execute(f"""
        CREATE TABLE industry_embeddings (
            id           serial PRIMARY KEY,
            naics_sector text NOT NULL,
            industry     text NOT NULL,
            search_text  text NOT NULL,
            embedding    vector({DIMS}) NOT NULL,
            UNIQUE (naics_sector, industry, search_text)
        )
    """)
    for (sector, industry, phrase), emb in zip(rows, embeddings):
        cur.execute("""
            INSERT INTO industry_embeddings (naics_sector, industry, search_text, embedding)
            VALUES (%s, %s, %s, %s)
        """, (sector, industry, phrase, emb.tolist()))
    print(f"industry_embeddings rebuilt: {len(rows)} phrases across {len(pairs)} categories")

    # 4. Index so industry-based lead lookups are fast without a state filter
    #    (with a state filter the existing (borrower_state, industry) index wins)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_leads_industry ON leads (industry)")
    print("idx_leads_industry ensured on leads")

    # 5. The old per-row embedding column + HNSW index are obsolete (~3 GB).
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'leads' AND column_name = 'embedding'
    """)
    if cur.fetchone():
        print(
            "\nNOTE: the legacy per-row embeddings on leads are no longer used.\n"
            "Reclaim ~3 GB whenever you like with:\n"
            "  DROP INDEX IF EXISTS idx_embedding_hnsw;\n"
            "  ALTER TABLE leads DROP COLUMN embedding;\n"
            "  VACUUM FULL leads;  -- optional, locks the table while it rewrites"
        )

    cur.close()
    conn.close()
    print("\nDone — semantic search is ready.")

if __name__ == "__main__":
    main()
