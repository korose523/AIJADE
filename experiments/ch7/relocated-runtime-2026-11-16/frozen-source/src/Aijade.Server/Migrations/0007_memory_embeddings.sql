-- Semantic memory search: each evidence chunk's embedding and the model that made it (recomputed when the model changes).
-- Plain real[] so any PostgreSQL works; similarity is computed by the server (personal-scale memory).
ALTER TABLE evidence_chunks ADD COLUMN embedding real[];
ALTER TABLE evidence_chunks ADD COLUMN embedding_model text;
