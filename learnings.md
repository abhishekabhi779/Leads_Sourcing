# Learnings

## Database
- Migrated from MySQL to PostgreSQL 18 (port 5432)
- MySQL uses `pymysql`, PostgreSQL uses `psycopg2` (install as `psycopg2-binary`)
- MySQL `MYSQL_CONFIG` uses key `database`, PostgreSQL `PG_CONFIG` uses key `dbname`
- MySQL `AUTO_INCREMENT` → PostgreSQL `SERIAL` (auto-incrementing integer)
- MySQL `DECIMAL` → PostgreSQL `NUMERIC` (same precision, different name)
- MySQL `INSERT IGNORE` → PostgreSQL `INSERT ... ON CONFLICT (unique_col) DO NOTHING`
- MySQL `CREATE DATABASE IF NOT EXISTS` doesn't exist in PG — check `pg_database` table first, then `CREATE DATABASE`
- MySQL `CREATE INDEX IF NOT EXISTS` not supported pre-8.0 — PostgreSQL supports it natively
- `FULLTEXT` index in MySQL → `GIN` index with `to_tsvector()` in PostgreSQL
- PostgreSQL `LIKE` is case-sensitive by default; use `ILIKE` for case-insensitive search

## Performance
- `psycopg2.extras.execute_values()` is much faster than `cursor.executemany()` for bulk inserts — sends many rows in a single round-trip
- `psycopg2.extras.RealDictCursor` returns rows as dicts (like `pymysql.cursors.DictCursor`)
- For DDL statements (CREATE TABLE, CREATE INDEX), PostgreSQL requires `conn.autocommit = True`

## NAICS Code Hierarchy
- NAICS codes are 6 digits; each prefix level is a broader category (33xxxx = Manufacturing sector)
- Bug: filtering `WHERE industry = 'Manufacturing'` missed sub-categories like "Primary Metal Manufacturing"
- Fix: two-column approach — `naics_sector` (2-digit parent, e.g. "Manufacturing") + `industry` (specific, e.g. "Primary Metal Manufacturing")
- `naics_sector` derived at load time via `LEFT(naics_code, 2)` dict lookup — O(1), no prefix scan needed
- SQL backfill with `CASE LEFT(naics_code, 2) WHEN '33' THEN 'Manufacturing' ...` backfilled 1.87M rows in seconds
- Filter by sector in UI → user sees broad categories; search results show the specific industry label

## Semantic Search / pgvector
- pgvector extension adds a `vector` column type and ANN (approximate nearest-neighbour) indexes to PostgreSQL
- Install on Windows: download pre-compiled zip from andreiramani/pgvector_pgsql_windows, copy DLL + SQL files into PG lib/share dirs (requires admin)
- Enable per database: `CREATE EXTENSION IF NOT EXISTS vector`
- Python client: `pip install pgvector` — must call `register_vector(conn)` on each connection before using vector columns
- HNSW index (`USING hnsw`) is fast at query time; IVFFlat is faster to build but slower to query — use HNSW for read-heavy workloads
- Embedding strategy: embed unique (sector, industry) pairs (~85 rows) rather than all 1.87M leads — same category always gets the same vector, backfill is near-instant
- Model: `all-MiniLM-L6-v2` via sentence-transformers — 384 dims, ~80 MB, runs on CPU, good balance of speed and quality
- Cosine similarity query: `ORDER BY embedding <=> %s::vector` (lower = more similar); `1 - (embedding <=> vector)` = similarity score 0–1
- Normalize embeddings at encode time (`normalize_embeddings=True`) so cosine and dot-product give the same ranking


