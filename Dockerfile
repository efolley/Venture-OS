# 1 image for the API, the worker, and the gateway (docker-compose.yml picks the command).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install '.[research,api,queue]'

RUN useradd --create-home --uid 10001 app && mkdir -p /app/runs /app/logs && chown app /app/runs /app/logs
USER app

EXPOSE 8000 8080
CMD ["ventureos-api"]
