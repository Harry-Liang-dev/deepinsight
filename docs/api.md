# API

## Memory service boundary

Phase One implements the application service contract but does not add HTTP
routes in the Memory task.

`MemoryService.write(MemoryWriteRequest) -> MemoryWriteResult` accepts one
validated L0–L4 item. A source reference and creator are mandatory. The result
contains the stable Memory ID plus opaque namespace/vector identifiers for
operational traceability; no FAISS object is returned.

`MemoryService.search(MemorySearchRequest) -> MemorySearchResponse` performs
semantic retrieval across requested levels and then applies exact namespace,
optional asset, minimum-importance, expiry, and `top_k` filters. Each result
contains:

- Memory ID, level, namespace key, optional asset, type, and text
- cosine similarity score and effective timestamp
- importance score and creator
- the stored `SourceReference`

`time_decay_days` is accepted and validated, but it does not alter ranking
until MASTER_SPEC defines a decay formula. The service never generates a
source or excerpt reference.
