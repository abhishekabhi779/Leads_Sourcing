# RAG Implementation Plan — SBA Lead Search

Goal: ask questions in plain English ("find HVAC companies in Texas with 10+ employees
that have a website") and get answers grounded in the 1.87M-row `leads` table and,
later, in scraped website content.

The project already has the hard parts of RAG infrastructure: PostgreSQL + pgvector,
an HNSW index, and sentence-transformers embeddings (`all-MiniLM-L6-v2`, 384-dim).
What's missing is the **generation** layer (Claude) and a richer **retrieval corpus**.

---

## Phase 1 — Conversational lead search (agentic retrieval)

The leads data is *structured*, so the highest-accuracy pattern is not chunk-embedding
RAG — it's giving Claude **tools** that query Postgres, and letting it decide which to
call. This is "RAG over SQL" and it works far better than embedding 1.87M rows of
structured fields.

### New endpoint: `POST /api/ask`

Claude (via the official `anthropic` Python SDK, model `claude-opus-4-8`) with three tools:

| Tool | Backed by | Purpose |
|---|---|---|
| `search_leads` | parameterized SQL on `leads` | exact filters: state, city, sector, industry, jobs, loan amount |
| `semantic_industry_search` | existing pgvector HNSW query | fuzzy industry matches ("metal shops" → Fabricated Metal Product Mfg) |
| `aggregate_stats` | `GROUP BY` SQL | counts/sums for "how many…", "which state has the most…" |

### Sketch (uses the SDK tool runner — no manual loop)

```python
# pip install anthropic   |   set ANTHROPIC_API_KEY env var (do NOT commit it)
import anthropic
from anthropic import beta_tool

client = anthropic.Anthropic()

@beta_tool
def search_leads(state: str = "", industry: str = "", city: str = "",
                 min_jobs: int = 0, limit: int = 20) -> str:
    """Search SBA PPP leads with exact filters.

    Args:
        state: 2-letter state code, e.g. TX.
        industry: exact industry name from the taxonomy.
        city: city name substring.
        min_jobs: minimum jobs reported.
        limit: max rows (<=50).
    """
    ...  # parameterized SQL -> JSON string

@beta_tool
def semantic_industry_search(query: str, state: str = "", limit: int = 20) -> str:
    """Find leads whose industry semantically matches a free-text description.

    Args:
        query: e.g. "metal fabrication shops".
        state: optional 2-letter state filter.
        limit: max rows (<=50).
    """
    ...  # reuse the /api/semantic-search pgvector query

SYSTEM = """You are a lead-research assistant for SBA PPP data...
<schema and taxonomy description here — keep byte-stable for prompt caching>"""

def ask(question: str) -> str:
    runner = client.beta.messages.tool_runner(
        model="claude-opus-4-8",
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=[{"type": "text", "text": SYSTEM,
                 "cache_control": {"type": "ephemeral"}}],   # prompt caching
        tools=[search_leads, semantic_industry_search],
        messages=[{"role": "user", "content": question}],
    )
    final = None
    for message in runner:
        final = message
    return next(b.text for b in final.content if b.type == "text")
```

Implementation notes:
- **Decimal handling**: coerce `NUMERIC` → `float()` inside tools before JSON-serializing
  (same as `api_search` does).
- **Prompt caching**: keep `SYSTEM` frozen (no timestamps/interpolation) so every request
  after the first reads the cache (~90% cheaper). Verify with
  `response.usage.cache_read_input_tokens`.
- **Config**: read the key from the `ANTHROPIC_API_KEY` env var (the SDK does this
  automatically) — don't put it in `config.py`.
- **Streaming**: for the UI, swap to `client.messages.stream(...)` per turn and forward
  SSE to the browser once the basic version works.
- **Cost option**: `claude-opus-4-8` is the default; if volume gets high, route simple
  questions to `claude-haiku-4-5` ($1/$5 per MTok) — your call, measure first.

Deliverables: `rag.py` (tools + ask), `/api/ask` route, a chat box in `index.html`.

---

## Phase 2 — True RAG over scraped website content

Once enrichment stores website text, you have *unstructured* data worth embedding.

1. **Persist enrichment results** (currently thrown away after CSV export):
   ```sql
   ALTER TABLE leads ADD COLUMN website TEXT, ADD COLUMN email TEXT,
                     ADD COLUMN phone TEXT, ADD COLUMN enriched_at TIMESTAMPTZ;

   CREATE TABLE lead_documents (
     id           BIGSERIAL PRIMARY KEY,
     loan_number  TEXT REFERENCES leads(loan_number),
     url          TEXT,
     chunk_index  INT,
     content      TEXT,
     embedding    vector(384)
   );
   CREATE INDEX ON lead_documents USING hnsw (embedding vector_cosine_ops);
   ```
2. **Capture page text in `scraper.py`**: it already fetches homepage + contact page —
   keep `soup.get_text()` output, chunk to ~1,000 characters with overlap, embed with
   the same `all-MiniLM-L6-v2` model, insert into `lead_documents`.
3. **New tool for Phase 1's runner**: `get_lead_context(question, loan_number=None)` —
   vector search over `lead_documents`, returns top chunks with their source URLs so
   Claude can cite where a claim came from.

Now questions like "which of these roofing companies mention commercial work?" are
answerable from the businesses' own websites.

---

## Phase 3 — Quality and operations

- **Eval set**: 20–30 real questions with expected answers; re-run after every prompt
  or tool change.
- **Batch enrichment**: when enriching thousands of leads, run the scraper as a
  background job writing to the new columns; the UI then reads from the DB instead of
  scraping live. (If you later want Claude to summarize each business from its website
  text, use the Message Batches API — 50% cheaper.)
- **Embedding upgrade (optional)**: `all-MiniLM-L6-v2` is fast but weak on long
  documents. If Phase 2 retrieval feels off, upgrade to `BAAI/bge-small-en-v1.5`
  (same 384 dims, drop-in) and re-run the backfill.

---

## Suggested order

1. Phase 1 (`/api/ask` with the two existing-data tools) — ~1 session, immediately useful.
2. Persist enrichment to the DB (Phase 2 step 1) — also fixes "re-scraping the same lead".
3. `lead_documents` + chunk embedding + `get_lead_context` tool.
4. Eval set + streaming UI polish.
