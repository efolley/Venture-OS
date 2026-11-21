# Security policy

## Status

VentureOS is an MVP. It is built to run on your own machine, not as a public service:

- There are no user accounts. The gateway has 1 optional shared API key (`GATEWAY_API_KEY`) and rate limits.
- The API and gateway listen only on `127.0.0.1` by default. Do not expose them to the internet without adding TLS and real authentication in front.
- Known gaps and their fixes are listed in the [technical architecture](docs/architecture/technical-architecture.md#known-gaps-and-the-fix-for-each).

## Data

- **No accounts, analytics, or telemetry.** Chats store what you type. The gateway keeps client IP addresses briefly, for rate limits only.
- **Sent to the model provider** (Anthropic, or Google with a Gemini model): your messages and instructions, plus the research and strategy built from public pages.
- **Sent to Tavily:** search queries, which can reflect your instructions.
- **Kept on your machine or your configured services:** results in `runs/`, chats in PostgreSQL if configured, until you delete them. Redis state expires within 24 hours, Kafka keeps queued turns for its retention period, and logs rotate.
- **Secrets:** API keys belong in `.env`, which git ignores. The app does not intentionally log keys or prompts, but error tracebacks can include content, so check logs before sharing them.

Before entering confidential information, review the [Anthropic](https://www.anthropic.com/legal/privacy) and [Tavily](https://www.tavily.com/privacy) privacy policies.

## Reporting a vulnerability

Please do not post vulnerability details in a public issue. Open an issue titled "Security contact request" with no details, and the maintainer will reply with a private way to send them. Include the steps to reproduce and the affected version or commit when you do.

## Supported versions

Only the latest commit on `dev` and the latest release get fixes.
