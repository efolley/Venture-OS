# Storage

Postgres only by default, scale with optional adapters (planned). Files use local disk. PostgresStore implements shared task persistence; general storage adapters and switching configuration remain planned.

| Interface | Lite default | Scale adapter |
| --- | --- | --- |
| Queue | PostgreSQL (SKIP LOCKED) task store | Kafka (planned) |
| VectorStore (planned) | pgvector (planned) | Chroma (planned) |
| BlobStore (planned) | Local disk (planned) | S3 (planned) |
| Cache (planned) | In-process (planned) | Redis (planned) |

Adapter switching is (planned): no config key or environment variable exists in the current code.

Shared tasks support checkpoints, fenced leases, recovery, and explicit replay into a new task. External action deduplication remains (planned), and external writes are disabled; SKIP LOCKED only provides task claiming. Replay must not repeat external side effects. Local disk requires persistent storage; pgvector shares the PostgreSQL deployment.
