"""`ventureos-worker`: reads chat turns from Kafka and runs them (Research, GTM, PM).

Run 1 or more next to `ventureos-api` when KAFKA_BOOTSTRAP_SERVERS is set. Workers share the
consumer group, so Kafka spreads the partitions between them. A turn's offset is committed
only after the turn finishes. A failed turn is recorded in its chat and committed, so a bad
input never loops; a message that is not a valid turn goes to the dead-letter topic.
"""

import json
import signal
import threading
import uuid
from typing import Any, Callable

from research.contracts import JsonObject
from research.logs import logger, setup_logging

from .jobqueue import DEAD_LETTER_TOPIC, GROUP, TOPIC, ensure_topics, kafka_settings

REQUIRED = ("job_id", "chat_id", "kind")


def parse_turn(value: bytes | None) -> JsonObject:
    """A valid turn has UUID job and chat IDs and a known kind; anything else is rejected."""
    turn = json.loads(value or b"")
    if not isinstance(turn, dict) or any(not turn.get(key) for key in REQUIRED):
        raise ValueError("not a chat turn")
    if turn["kind"] not in ("message", "decision"):
        raise ValueError("unknown turn kind")
    for key in ("job_id", "chat_id"):
        turn[key] = str(uuid.UUID(str(turn[key])))  # raises ValueError for anything else
    return turn


def consume(consumer: Any, handle: Callable[[JsonObject], str], dead_letter: Any,
            stop: threading.Event, *, poll_seconds: float = 1.0,
            dead_letter_topic: str = DEAD_LETTER_TOPIC) -> int:
    """Poll until stop is set. Returns how many turns ran (for tests)."""
    handled = 0
    while not stop.is_set():
        message = consumer.poll(poll_seconds)
        if message is None:
            continue
        if message.error():
            logger.warning("Kafka error: %s", message.error())
            continue
        try:
            turn = parse_turn(message.value())
        except ValueError as error:
            logger.warning("dead-lettered a message at offset %s: %s", message.offset(), error)
            dead_letter.produce(dead_letter_topic, key=message.key(), value=message.value())
            dead_letter.flush(10)
        else:
            status = handle(turn)
            handled += 1
            logger.info("turn %s finished status=%s", turn["job_id"], status)
        consumer.commit(message=message, asynchronous=False)
    return handled


def main() -> None:
    from .api import build_service  # the same agents, stores, and checks as the API

    setup_logging()
    service = build_service(require_queue=True)
    import confluent_kafka

    ensure_topics()
    consumer = confluent_kafka.Consumer({
        **kafka_settings(), "group.id": GROUP, "enable.auto.commit": False,
        "auto.offset.reset": "earliest",
        "max.poll.interval.ms": 900000,  # a full turn takes about 3 minutes
    })
    dead_letter = confluent_kafka.Producer(kafka_settings())
    consumer.subscribe([TOPIC])
    stop = threading.Event()
    for name in ("SIGINT", "SIGTERM"):
        signal.signal(getattr(signal, name), lambda *_: stop.set())
    print(f"VentureOS worker is running: reading {TOPIC} as {GROUP}", flush=True)
    try:
        consume(consumer, service.run, dead_letter, stop)
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
