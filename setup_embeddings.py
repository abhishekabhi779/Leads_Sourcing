"""
Phase 2: Semantic search setup.
- Adds embedding column to leads table (384-dim vectors via all-MiniLM-L6-v2)
- Creates HNSW index for fast approximate nearest-neighbour search
- Embeds every unique (naics_sector, industry) combination (~100 rows)
- Backfills embedding on each lead row by joining to its sector+industry pair

Strategy: embed unique categories first, then batch-update leads.
This is fast (~100 embed calls instead of 1.87M) and produces consistent
vectors for the same industry regardless of which row you hit.

Usage: python setup_embeddings.py
"""
import psycopg2
import psycopg2.extras
from pgvector.psycopg2 import register_vector
from sentence_transformers import SentenceTransformer
from config import PG_CONFIG

MODEL_NAME = "all-MiniLM-L6-v2"  # 384 dims, 80 MB, runs on CPU
DIMS = 384

def main():
    print("Loading embedding model (downloads ~80 MB on first run)...")
    model = SentenceTransformer(MODEL_NAME)
    print(f"Model loaded: {MODEL_NAME}")

    conn = psycopg2.connect(**PG_CONFIG)
    conn.autocommit = True
    register_vector(conn)
    cur = conn.cursor()

    # 1. Enable extension (idempotent)
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. Add embedding column to leads if missing
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'leads' AND column_name = 'embedding'
    """)
    if not cur.fetchone():
        cur.execute(f"ALTER TABLE leads ADD COLUMN embedding vector({DIMS})")
        print(f"Added embedding vector({DIMS}) column to leads")
    else:
        print("embedding column already exists")

    # 3. Create HNSW index for fast ANN search (cosine similarity)
    cur.execute("""
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'leads' AND indexname = 'idx_embedding_hnsw'
    """)
    if not cur.fetchone():
        print("Creating HNSW index (this runs in the background)...")
        cur.execute("""
            CREATE INDEX idx_embedding_hnsw ON leads
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
        """)
        print("HNSW index created")
    else:
        print("HNSW index already exists")

    # 4. Get all unique (naics_sector, industry) pairs
    cur.execute("""
        SELECT DISTINCT naics_sector, industry
        FROM leads
        WHERE naics_sector IS NOT NULL AND industry IS NOT NULL
        ORDER BY naics_sector, industry
    """)
    pairs = cur.fetchall()
    print(f"\nUnique sector+industry pairs to embed: {len(pairs)}")

    # 5. Generate embeddings for each unique pair
    # Text format: "sector: Food Service & Hospitality | industry: Full-Service Restaurants"
    texts = [
        f"sector: {sector} | industry: {industry}"
        for sector, industry in pairs
    ]
    embeddings = model.encode(texts, show_progress_bar=True, normalize_embeddings=True)

    # 6. Backfill leads — update each (sector, industry) combo in one UPDATE
    print("\nBackfilling embeddings on leads table...")
    updated_total = 0
    for (sector, industry), embedding in zip(pairs, embeddings):
        cur.execute("""
            UPDATE leads
            SET embedding = %s
            WHERE naics_sector = %s AND industry = %s AND embedding IS NULL
        """, (embedding.tolist(), sector, industry))
        updated_total += cur.rowcount

    print(f"Backfilled {updated_total:,} rows")

    # 7. Quick stats
    cur.execute("SELECT COUNT(*) FROM leads WHERE embedding IS NOT NULL")
    filled = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM leads")
    total = cur.fetchone()[0]
    print(f"Coverage: {filled:,} / {total:,} rows have embeddings ({filled/total*100:.1f}%)")

    cur.close()
    conn.close()
    print("\nDone — semantic search is ready.")

if __name__ == "__main__":
    main()
