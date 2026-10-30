# Optional adapters

All adapters below are (planned). The current preview does not authenticate API requests, call tools, execute code, or connect to external services.

| Adapter | Replaces | When to use |
| --- | --- | --- |
| OIDC (planned) | Built-in API keys / JWT identity path (planned) | Organizational SSO |
| E2B or container sandbox (planned) | No generated-code execution by default | Isolated execution of generated code |
| Kafka (planned) | PostgreSQL Queue implementation (planned) | Independent event consumers and higher transport scale |
| Chroma (planned) | pgvector VectorStore implementation (planned) | Dedicated retrieval infrastructure |
| S3 (planned) | Local disk BlobStore implementation (planned) | Shared artifacts across workers and durable object storage |
| Redis (planned) | In-process Cache implementation (planned) | Shared caching and rate counters |

Adapters preserve interface contracts. Kafka needs explicit acknowledgment, retry, and deduplication behavior. A subprocess with resource limits is not a security sandbox.
