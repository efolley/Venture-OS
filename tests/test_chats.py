"""Chats you can come back to: server-side turns, stored transcripts, Redis, Kafka, the worker.

Offline: provider doubles, in-memory stores, and small fakes of the Redis and Kafka clients.
Set REDIS_TEST_URL, KAFKA_TEST_BOOTSTRAP, or RESEARCH_TEST_DATABASE_URL to also run the
integration tests against real services (use disposable ones).
"""

import json
import os
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from typing import Any

from doubles import FULL_ITEMS, FULL_ROUTES, FakeSearch, WorldModel, page
from gtm.orchestrator import GTMOrchestrator
from pipeline.chats import ChatService
from pipeline.jobqueue import TOPIC, KafkaQueue
from pipeline.sessions import CachedSessionStore, MemorySessionStore, PostgresSessionStore
from pipeline.shortterm import MemoryShortTerm, RedisShortTerm
from pipeline.worker import consume, parse_turn
from pm.agent import PMAgent
from research import MemoryStore, ResearchAgent
from test_gtm import FakeModel
from test_pm import FakeModel as FakePMModel

try:
    from fastapi.testclient import TestClient

    from pipeline.api import create_app
except ImportError:  # the api and test extras are optional
    TestClient = None  # type: ignore[assignment,misc]

AMBIGUOUS = {"official website": [page("https://acmecloud.com/", "Acme Cloud", "Docs tool"),
                                  page("https://acmecloud.io/", "Acme Cloud Hosting", "Hosting")],
             **FULL_ROUTES}
RESOLVE = {"status": "ambiguous", "candidates": [
    {"name": "Acme Cloud", "website": "https://acmecloud.com", "reason": "documents"},
    {"name": "Acme Cloud Hosting", "website": "https://acmecloud.io", "reason": "hosting"}]}


class FailingGTM(GTMOrchestrator):
    def __init__(self) -> None:
        super().__init__(FakeModel())

    def run(self, value: object, *, instructions: str = ""):  # type: ignore[no-untyped-def]
        raise RuntimeError("model unavailable")


class HeldQueue:
    """Keeps turns instead of running them, like Kafka waiting for a worker."""

    def __init__(self) -> None:
        self.turns: list[dict[str, Any]] = []

    def submit(self, turn: dict[str, Any]) -> None:
        self.turns.append(turn)


class BrokenQueue:
    def submit(self, turn: dict[str, Any]) -> None:
        raise RuntimeError("broker down")


@unittest.skipIf(TestClient is None, "install the api and test extras")
class ChatApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.results = Path(self.tmp.name)
        self.sessions = MemorySessionStore()
        self.short_term = MemoryShortTerm()
        self.store = MemoryStore()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def app(self, routes=None, gtm=None, queue=None):  # type: ignore[no-untyped-def]
        agent = ResearchAgent(WorldModel(FULL_ITEMS, resolve=RESOLVE),
                              FakeSearch(routes or FULL_ROUTES), self.store)
        return TestClient(create_app(
            agent, self.store, gtm or GTMOrchestrator(FakeModel()), PMAgent(FakePMModel()),
            run_inline=True, results_dir=self.results, pm_results_dir=self.results / "pm",
            static_dir=None, sessions=self.sessions, short_term=self.short_term, queue=queue))

    def send(self, client, chat_id: str, message: str) -> dict:  # type: ignore[no-untyped-def]
        response = client.post(f"/api/chats/{chat_id}/messages", json={"message": message})
        self.assertEqual(response.status_code, 200, response.text)
        return client.get(f"/api/chat-jobs/{response.json()['job_id']}").json()

    def kinds(self, client, chat_id: str) -> list[str]:  # type: ignore[no-untyped-def]
        return [m["kind"] for m in client.get(f"/api/chats/{chat_id}").json()["messages"]]

    def test_a_message_runs_research_gtm_and_pm_and_keeps_the_transcript(self) -> None:
        client = self.app()
        chat_id = client.post("/api/chats").json()["chat_id"]
        job = self.send(client, chat_id, "acmecloud.com")
        self.assertEqual(job["status"], "done", job)
        phases = [(e["data"]["phase"], e["status"]) for e in job["events"] if e["step"] == "phase"]
        self.assertEqual(phases, [("research", "running"), ("research", "done"), ("gtm", "running"),
                                  ("gtm", "done"), ("pm", "running"), ("pm", "done")])
        view = client.get(f"/api/chats/{chat_id}").json()
        self.assertEqual([m["kind"] for m in view["messages"]],
                         ["text", "step", "pack", "step", "strategy", "step", "pm"])
        user, research_step, pack, _, strategy, _, pm = view["messages"]
        self.assertEqual((user["role"], user["text"]), ("user", "acmecloud.com"))
        self.assertTrue(research_step["payload"]["events"])
        run_id = pack["run_id"]
        self.assertEqual(strategy["payload"]["strategy"]["input_run_id"], run_id)
        self.assertEqual(pm["payload"]["result"]["status"], "hitl_required")
        self.assertEqual(view["chat"]["title"], pack["payload"]["pack"]["company"]["name"])
        self.assertIsNone(view["chat"]["active_job_id"])
        self.assertTrue((self.results / f"{run_id}.json").exists())
        self.assertTrue((self.results / "pm" / f"{run_id}.json").exists())

        decided = client.post(f"/api/chats/{chat_id}/decisions",
                              json={"run_id": run_id, "decision": "proceed"}).json()["job_id"]
        self.assertEqual(client.get(f"/api/chat-jobs/{decided}").json()["status"], "done")
        messages = client.get(f"/api/chats/{chat_id}").json()["messages"]
        self.assertEqual(messages[-3]["text"], "Proceed with gaps")
        self.assertEqual(messages[-1]["payload"]["result"]["status"], "partial")

    def test_a_reopened_chat_continues_where_it_stopped(self) -> None:
        first = self.app(AMBIGUOUS)
        chat_id = first.post("/api/chats").json()["chat_id"]
        self.send(first, chat_id, "Acme Cloud")
        self.assertEqual(self.kinds(first, chat_id), ["text", "step", "clarify"])
        # A new server process on the same stores: the chat is listed and its question is open.
        later = self.app(AMBIGUOUS)
        listed = later.get("/api/chats").json()["chats"]
        self.assertEqual([c["id"] for c in listed], [chat_id])
        self.assertEqual(listed[0]["title"], "Acme Cloud")
        self.assertEqual(later.get(f"/api/chats/{chat_id}").json()["chat"]["pending"], "clarify")
        job = self.send(later, chat_id, "1")
        self.assertEqual(job["status"], "done", job)
        self.assertEqual(self.kinds(later, chat_id)[-5:], ["pack", "step", "strategy", "step", "pm"])

    def test_one_turn_at_a_time_per_chat(self) -> None:
        client = self.app()
        chat_id = client.post("/api/chats").json()["chat_id"]
        self.assertTrue(self.short_term.acquire(chat_id, "another-job"))
        busy = client.post(f"/api/chats/{chat_id}/messages", json={"message": "acmecloud.com"})
        self.assertEqual(busy.status_code, 409)
        self.short_term.release(chat_id, "another-job")
        self.assertEqual(self.send(client, chat_id, "acmecloud.com")["status"], "done")

    def test_a_queued_turn_waits_for_a_worker(self) -> None:
        queue = HeldQueue()
        client = self.app(queue=queue)
        chat_id = client.post("/api/chats").json()["chat_id"]
        job_id = client.post(f"/api/chats/{chat_id}/messages",
                             json={"message": "acmecloud.com"}).json()["job_id"]
        self.assertEqual(client.get(f"/api/chat-jobs/{job_id}").json()["status"], "queued")
        self.assertEqual(client.get(f"/api/chats/{chat_id}").json()["chat"]["active_job_id"], job_id)
        self.assertEqual(queue.turns[0]["text"], "acmecloud.com")
        # The worker side: a separate service on the same stores runs the queued turn.
        worker = ChatService(ResearchAgent(WorldModel(FULL_ITEMS), FakeSearch(FULL_ROUTES), self.store),
                             GTMOrchestrator(FakeModel()), PMAgent(FakePMModel()), self.sessions,
                             self.short_term)
        worker.results.gtm_dir, worker.results.pm_dir = self.results, self.results / "pm"
        self.assertEqual(worker.run(queue.turns[0]), "done")
        job = client.get(f"/api/chat-jobs/{job_id}?after=2").json()
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["next"], 2 + len(job["events"]))
        self.assertIsNone(client.get(f"/api/chats/{chat_id}").json()["chat"]["active_job_id"])

    def test_a_failed_step_is_recorded_and_the_pack_is_kept(self) -> None:
        client = self.app(gtm=FailingGTM())
        chat_id = client.post("/api/chats").json()["chat_id"]
        self.assertEqual(self.send(client, chat_id, "acmecloud.com")["status"], "failed")
        messages = client.get(f"/api/chats/{chat_id}").json()["messages"]
        self.assertEqual([m["kind"] for m in messages], ["text", "step", "pack", "step", "error"])
        self.assertEqual(messages[3]["payload"]["status"], "failed")
        self.assertIn("model unavailable", messages[-1]["text"])
        self.assertTrue(self.short_term.acquire(chat_id, "next"))  # the lock was released

    def test_a_queue_outage_is_reported_and_unlocks_the_chat(self) -> None:
        client = self.app(queue=BrokenQueue())
        chat_id = client.post("/api/chats").json()["chat_id"]
        response = client.post(f"/api/chats/{chat_id}/messages", json={"message": "acmecloud.com"})
        self.assertEqual(response.status_code, 503)
        self.assertTrue(self.short_term.acquire(chat_id, "next"))

    def test_unknown_chats_and_jobs(self) -> None:
        client = self.app()
        self.assertEqual(client.get("/api/chats/not-a-uuid").status_code, 404)
        self.assertEqual(client.get(f"/api/chats/{uuid.uuid4()}").status_code, 404)
        self.assertEqual(client.post(f"/api/chats/{uuid.uuid4()}/messages",
                                     json={"message": "x"}).status_code, 404)
        self.assertEqual(client.get("/api/chat-jobs/nope").status_code, 404)
        health = client.get("/api/health").json()
        self.assertEqual((health["sessions"], health["short_term"], health["queue"]),
                         ("MemorySessionStore", "MemoryShortTerm", "InProcessQueue"))


class FakeRedis:
    """The few Redis commands RedisShortTerm uses, in memory."""

    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.ttls: dict[str, int] = {}

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        if ex:
            self.ttls[key] = ex
        return True

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def delete(self, key: str) -> int:
        return int(self.values.pop(key, None) is not None)

    def eval(self, script: str, keys: int, key: str, owner: str) -> int:
        return self.delete(key) if self.values.get(key) == owner else 0

    def llen(self, key: str) -> int:
        return len(self.values.get(key, []))

    def rpush(self, key: str, value: str) -> None:
        self.values.setdefault(key, []).append(value)

    def expire(self, key: str, seconds: int) -> None:
        self.ttls[key] = seconds

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        items = self.values.get(key, [])
        return items[start:] if end == -1 else items[start:end + 1]


class ShortTermTests(unittest.TestCase):
    def check(self, short_term: Any) -> None:
        chat, owner = str(uuid.uuid4()), "job-1"
        self.assertTrue(short_term.acquire(chat, owner))
        self.assertFalse(short_term.acquire(chat, "job-2"))
        short_term.release(chat, "job-2")  # not the owner: the lock stays
        self.assertFalse(short_term.acquire(chat, "job-2"))
        short_term.release(chat, owner)
        self.assertTrue(short_term.acquire(chat, "job-2"))
        job = str(uuid.uuid4())  # a fresh key, so a real Redis holds no earlier events for it
        short_term.put_job(job, {"status": "running"})
        self.assertEqual(short_term.get_job(job), {"status": "running"})
        for number in range(3):
            short_term.add_event(job, {"n": number})
        self.assertEqual([e["n"] for e in short_term.events(job, 1)], [1, 2])
        short_term.cache_chat(chat, {"chat": {"id": chat}})
        self.assertEqual(short_term.cached_chat(chat), {"chat": {"id": chat}})
        short_term.drop_chat(chat)
        self.assertIsNone(short_term.cached_chat(chat))

    def test_memory(self) -> None:
        self.check(MemoryShortTerm())

    def test_redis_commands(self) -> None:
        fake = FakeRedis()
        self.check(RedisShortTerm(client=fake))
        self.assertTrue(all(ttl > 0 for ttl in fake.ttls.values()))

    def test_memory_entries_expire(self) -> None:
        short_term = MemoryShortTerm(ttl=1)
        short_term.put_job("j", {"status": "done"})
        short_term._values["job:j"] = (time.time() - 1, {"status": "done"})
        self.assertIsNone(short_term.get_job("j"))

    @unittest.skipUnless(os.getenv("REDIS_TEST_URL"), "set REDIS_TEST_URL to a disposable Redis")
    def test_real_redis(self) -> None:
        self.check(RedisShortTerm(os.environ["REDIS_TEST_URL"]))


class CountingStore(MemorySessionStore):
    reads = 0

    def messages(self, chat_id: str):  # type: ignore[no-untyped-def]
        self.reads += 1
        return super().messages(chat_id)


class SessionStoreTests(unittest.TestCase):
    def check(self, store: Any) -> None:
        chat = store.create()
        store.append(chat["id"], "user", "text", "Linear")
        store.append(chat["id"], "assistant", "pack", "Here it is", run_id=str(uuid.uuid4()),
                     payload={"pack": {"status": "complete"}})
        store.update(chat["id"], title="Linear", pending={"kind": "rerun"}, active_job_id="j")
        record = store.get(chat["id"])
        self.assertEqual((record["title"], record["pending"], record["active_job_id"]),
                         ("Linear", {"kind": "rerun"}, "j"))
        messages = store.messages(chat["id"])
        self.assertEqual([(m["seq"], m["kind"]) for m in messages], [(1, "text"), (2, "pack")])
        self.assertEqual(messages[1]["payload"], {"pack": {"status": "complete"}})
        self.assertEqual(store.list(5)[0]["message_count"], 2)
        with self.assertRaises(ValueError):
            store.append(chat["id"], "user", "unknown-kind", "x")
        with self.assertRaises(KeyError):
            store.append(str(uuid.uuid4()), "user", "text", "x")

    def test_memory(self) -> None:
        self.check(MemorySessionStore())

    def test_cache_reads_through_once_and_writes_through(self) -> None:
        backing = CountingStore()
        cached = CachedSessionStore(backing, MemoryShortTerm())
        self.check(cached)
        chat_id = backing.list(1)[0]["id"]
        before = backing.reads
        for _ in range(3):
            self.assertEqual(len(cached.messages(chat_id)), 2)
        self.assertEqual(backing.reads, before)  # served from the cache
        self.assertEqual(cached.get(chat_id)["title"], "Linear")

    @unittest.skipUnless(os.getenv("RESEARCH_TEST_DATABASE_URL"),
                         "set RESEARCH_TEST_DATABASE_URL to a disposable PostgreSQL database")
    def test_postgres(self) -> None:
        store = PostgresSessionStore(os.environ["RESEARCH_TEST_DATABASE_URL"])
        store.migrate()
        store.migrate()  # migrations are idempotent
        self.check(store)


class FakeMessage:
    def __init__(self, value: bytes, offset: int) -> None:
        self._value, self._offset = value, offset

    def error(self) -> None:
        return None

    def value(self) -> bytes:
        return self._value

    def key(self) -> bytes:
        return b"chat"

    def offset(self) -> int:
        return self._offset


class FakeConsumer:
    def __init__(self, values: list[bytes], stop: threading.Event) -> None:
        self.messages = [FakeMessage(v, n) for n, v in enumerate(values)]
        self.stop = stop
        self.committed: list[int] = []

    def poll(self, timeout: float) -> FakeMessage | None:
        if not self.messages:
            self.stop.set()
            return None
        return self.messages.pop(0)

    def commit(self, message: FakeMessage, asynchronous: bool) -> None:
        self.committed.append(message.offset())


class FakeProducer:
    def __init__(self, error: str | None = None) -> None:
        self.sent: list[tuple[str, bytes, bytes]] = []
        self.error = error
        self.callbacks: list[Any] = []

    def produce(self, topic: str, key: bytes, value: bytes, on_delivery: Any = None) -> None:
        self.sent.append((topic, key, value))
        if on_delivery:
            self.callbacks.append(on_delivery)

    def flush(self, timeout: float) -> int:
        for callback in self.callbacks:
            callback(self.error, None)
        self.callbacks = []
        return 0


class KafkaTests(unittest.TestCase):
    def test_turns_are_keyed_by_chat_and_failures_raise(self) -> None:
        producer = FakeProducer()
        KafkaQueue(producer=producer).submit({"job_id": "j", "chat_id": "c", "kind": "message"})
        topic, key, value = producer.sent[0]
        self.assertEqual((topic, key, json.loads(value)["job_id"]), (TOPIC, b"c", "j"))
        with self.assertRaises(RuntimeError):
            KafkaQueue(producer=FakeProducer(error="broker down")).submit(
                {"job_id": "j", "chat_id": "c", "kind": "message"})

    def test_worker_runs_turns_dead_letters_bad_messages_and_commits_each(self) -> None:
        stop = threading.Event()
        job_id, chat_id = str(uuid.uuid4()), str(uuid.uuid4())
        good = json.dumps({"job_id": job_id, "chat_id": chat_id, "kind": "message", "text": "x"}).encode()
        not_ids = json.dumps({"job_id": "j", "chat_id": "c", "kind": "message"}).encode()
        bad = [b"not json", b'{"job_id": "j2"}', not_ids]
        consumer = FakeConsumer([good, *bad], stop)
        dead_letter = FakeProducer()
        handled: list[str] = []
        count = consume(consumer, lambda turn: handled.append(turn["job_id"]) or "done",
                        dead_letter, stop, poll_seconds=0)
        self.assertEqual((count, handled), (1, [job_id]))
        self.assertEqual(consumer.committed, [0, 1, 2, 3])
        self.assertEqual([value for _, _, value in dead_letter.sent], bad)
        for value in (b"[]", json.dumps({"job_id": job_id, "chat_id": chat_id, "kind": "x"}).encode()):
            with self.assertRaises(ValueError):
                parse_turn(value)

    @unittest.skipUnless(os.getenv("KAFKA_TEST_BOOTSTRAP"), "set KAFKA_TEST_BOOTSTRAP to a disposable Kafka")
    def test_real_kafka_round_trip(self) -> None:
        import confluent_kafka

        from pipeline.jobqueue import ensure_topics

        bootstrap = os.environ["KAFKA_TEST_BOOTSTRAP"]
        job_id = str(uuid.uuid4())
        topic = f"ventureos-test-{job_id}"  # never the real topic a worker reads
        ensure_topics(bootstrap, topic=topic)
        KafkaQueue(bootstrap, topic=topic).submit(
            {"job_id": job_id, "chat_id": str(uuid.uuid4()), "kind": "message"})
        consumer = confluent_kafka.Consumer({"bootstrap.servers": bootstrap,
                                             "group.id": f"test-{job_id}",
                                             "auto.offset.reset": "earliest",
                                             "enable.auto.commit": False})
        consumer.subscribe([topic])
        stop, seen = threading.Event(), []

        def handle(turn: dict[str, Any]) -> str:
            seen.append(turn["job_id"])
            if turn["job_id"] == job_id:
                stop.set()
            return "done"

        timer = threading.Timer(30, stop.set)
        timer.start()
        try:
            consume(consumer, handle, confluent_kafka.Producer({"bootstrap.servers": bootstrap}), stop,
                    dead_letter_topic=f"{topic}.dlq")
        finally:
            timer.cancel()
            consumer.close()
            from confluent_kafka.admin import AdminClient

            AdminClient({"bootstrap.servers": bootstrap}).delete_topics([topic, f"{topic}.dlq"])
        self.assertIn(job_id, seen)


if __name__ == "__main__":
    unittest.main()
