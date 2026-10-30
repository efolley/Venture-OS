# Storage

Postgres only by default, scale with optional adapters (planned). Files use local disk. The current scaffold has no storage drivers or adapter configuration.

| Interface | Lite default | Scale adapter |
| --- | --- | --- |
| Queue (planned) | PostgreSQL (SKIP LOCKED) (planned) | Kafka (planned) |
| VectorStore (planned) | pgvector (planned) | Chroma (planned) |
| BlobStore (planned) | Local disk (planned) | S3 (planned) |
| Cache (planned) | In-process (planned) | Redis (planned) |

Adapter switching is (planned): no config key or environment variable exists in the current code.

Durable resume, checkpoints, controlled replay, task leases, and action deduplication are (planned) harness responsibilities backed by PostgreSQL; SKIP LOCKED only provides task claiming. Replay must not repeat external side effects. Local disk requires persistent storage; pgvector shares the PostgreSQL deployment.
