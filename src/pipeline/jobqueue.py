"""Where chat turns wait to run: Kafka when KAFKA_BOOTSTRAP_SERVERS is set, else in process.

Kafka keeps the web server free: the API only produces a small turn message (IDs and the user's
text), and `ventureos-worker` processes consume and run it. The chat ID is the message key, so
the turns of 1 chat stay in order on 1 partition. Without Kafka, a thread pool inside the API
runs the turns, which is the zero-setup default.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from research.contracts import JsonObject
from research.logs import logger

TOPIC = os.getenv("KAFKA_TOPIC", "ventureos.chat-jobs")
DEAD_LETTER_TOPIC = f"{TOPIC}.dlq"
GROUP = os.getenv("KAFKA_GROUP", "ventureos-workers")
PARTITIONS = 3


class InProcessQueue:
    """Runs each turn on a thread pool in this process. inline=True runs it at once (tests)."""

    def __init__(self, handler: Callable[[JsonObject], Any], *, workers: int = 4,
                 inline: bool = False) -> None:
        self.handler = handler
        self.inline = inline
        self.pool = None if inline else ThreadPoolExecutor(max_workers=workers,
                                                           thread_name_prefix="chat-turn")

    def submit(self, turn: JsonObject) -> None:
        if self.pool is None:
            self.handler(turn)
            return
        future = self.pool.submit(self.handler, turn)
        future.add_done_callback(
            lambda done: done.exception() and logger.error("chat turn crashed: %s", done.exception()))


def kafka_settings(bootstrap: str | None = None) -> dict[str, str]:
    servers = bootstrap or os.getenv("KAFKA_BOOTSTRAP_SERVERS", "")
    if not servers:
        raise ValueError("Set KAFKA_BOOTSTRAP_SERVERS to use Kafka.")
    return {"bootstrap.servers": servers}


def _kafka() -> Any:
    try:
        import confluent_kafka
    except ImportError as error:
        raise ValueError("confluent-kafka is not installed. Run: pip install -e '.[queue]'") from error
    return confluent_kafka


def ensure_topics(bootstrap: str | None = None, *, admin: Any = None, topic: str = TOPIC) -> None:
    """Create the turn topic and its dead-letter topic if they are missing."""
    kafka = _kafka()
    from confluent_kafka.admin import AdminClient, NewTopic

    client = admin or AdminClient(kafka_settings(bootstrap))
    existing = set(client.list_topics(timeout=10).topics)
    wanted = [NewTopic(name, num_partitions=PARTITIONS if name == topic else 1, replication_factor=1)
              for name in (topic, f"{topic}.dlq") if name not in existing]
    if not wanted:
        return
    for name, future in client.create_topics(wanted).items():
        try:
            future.result(timeout=15)
            logger.info("created Kafka topic %s", name)
        except kafka.KafkaException as error:
            if error.args and error.args[0].code() == kafka.KafkaError.TOPIC_ALREADY_EXISTS:
                continue
            raise


class KafkaQueue:
    """Produces each turn to Kafka and waits for the broker to acknowledge it."""

    def __init__(self, bootstrap: str | None = None, *, producer: Any = None,
                 topic: str = TOPIC) -> None:
        if producer is None:
            kafka = _kafka()
            producer = kafka.Producer({**kafka_settings(bootstrap), "acks": "all",
                                       "enable.idempotence": True})
        self.producer = producer
        self.topic = topic

    def submit(self, turn: JsonObject) -> None:
        errors: list[str] = []

        def delivered(error: Any, _message: Any) -> None:
            if error is not None:
                errors.append(str(error))

        self.producer.produce(self.topic, key=str(turn["chat_id"]).encode(),
                              value=json.dumps(turn).encode(), on_delivery=delivered)
        remaining = self.producer.flush(10)
        if remaining or errors:
            raise RuntimeError(f"Kafka did not accept the turn: {errors[0] if errors else 'timeout'}")
