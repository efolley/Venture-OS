import logging
import tempfile
import unittest
from pathlib import Path

from ventureos.research import logs
from ventureos.research.logs import logged, logged_debug, logger, log_progress, setup_logging
from ventureos.research.providers import GeminiModel, TavilySearch


class LoggedDecoratorTests(unittest.TestCase):
    def test_logs_start_and_completion(self) -> None:
        @logged
        def work() -> int:
            return 7

        with self.assertLogs(logger, level="INFO") as captured:
            self.assertEqual(work(), 7)
        text = "\n".join(captured.output)
        self.assertIn("started", text)
        self.assertIn("completed duration_ms=", text)

    def test_logs_failure_and_reraises(self) -> None:
        @logged
        def broken() -> None:
            raise ValueError("boom")

        with self.assertLogs(logger, level="WARNING") as captured:
            with self.assertRaises(ValueError):
                broken()
        self.assertIn("ValueError: boom", captured.output[0])

    def test_debug_helpers_hidden_at_info(self) -> None:
        @logged_debug
        def helper() -> int:
            return 1

        previous = logger.level
        logger.setLevel(logging.INFO)
        try:
            with self.assertNoLogs(logger, level="INFO"):
                helper()
        finally:
            logger.setLevel(previous)

    def test_no_secrets_or_payloads_in_logs(self) -> None:
        secret = "SECRET-KEY-123"
        with self.assertLogs(logger, level="DEBUG") as captured:
            log_progress("searching", {"prompt": "private prompt"}, {"text": "page text"}, "success")
            try:
                TavilySearch(api_key=secret).search("")  # fails offline or via HTTP; must not leak key
            except Exception:
                pass
            try:
                GeminiModel(api_key=secret, model=" ").json("system text", "prompt text")
            except Exception:
                pass
        text = "\n".join(captured.output)
        for forbidden in (secret, "private prompt", "page text", "system text", "prompt text"):
            self.assertNotIn(forbidden, text)


class SetupLoggingTests(unittest.TestCase):
    def test_setup_is_idempotent_and_writes_file(self) -> None:
        existing = [h for h in logger.handlers if getattr(h, "_ventureos", False)]
        for handler in existing:
            logger.removeHandler(handler)
        before = list(logger.handlers)
        with tempfile.TemporaryDirectory() as directory:
            try:
                setup_logging("INFO", directory)
                setup_logging("INFO", directory)
                added = [h for h in logger.handlers if h not in before]
                self.assertEqual(len(added), 2)  # stream + file, not duplicated
                logger.info("hello file")
                for handler in added:
                    handler.flush()
                self.assertIn("hello file", (Path(directory) / "research.log").read_text())
            finally:
                for handler in [h for h in logger.handlers if h not in before]:
                    logger.removeHandler(handler)
                    handler.close()
                for handler in existing:
                    logger.addHandler(handler)
                logger.propagate = not existing


if __name__ == "__main__":
    unittest.main()
