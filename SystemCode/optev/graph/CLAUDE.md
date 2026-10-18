# graph

Neo4j schema, loading and retrieval.

**Owner:** P4  ·  **Reads:** `optev/contracts/`  ·  **Spec:** `specs/005-knowledge-graph/`

The graph explains decisions; Postgres is the source of truth for numbers. Retrieval is parameterised Cypher, not generated queries. If a traversal returns nothing, say so — never let the model invent a justification.

Labels, keys and relationships live in `schema.py`; loaders MERGE on those keys and build composite keys only with its helpers. `python -m optev.graph ping|schema|apply-schema|heartbeat|load --sample|clear --sample`. `load.rows()` holds all loading logic; `load()` only sends it.
