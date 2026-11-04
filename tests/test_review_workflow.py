from contextlib import contextmanager
import csv
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.ai_client import AIError
from app.server import create_server
from test_data_loader import inbox_csv
from test_pipeline import FakeClient


@contextmanager
def review_server(client):
    with tempfile.TemporaryDirectory() as directory:
        server = create_server(0, store_dir=directory, client_factory=lambda: client)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", server
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)


def api(base, path, payload=None):
    request = Request(base + path, data=json.dumps(payload).encode() if payload is not None else None,
                      headers={"Content-Type": "application/json"} if payload is not None else {})
    with urlopen(request, timeout=5) as response:
        return json.load(response)


def finished(base):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        snapshot = api(base, "/api/inbox")
        if not snapshot["job"]["busy"]:
            return snapshot
        time.sleep(.02)
    raise AssertionError("Mock processing did not finish")


class ReviewWorkflowTests(unittest.TestCase):
    def test_import_process_edit_export_failed_retry_and_reload(self):
        client = FakeClient()
        with review_server(client) as (base, server):
            original = api(base, "/api/inbox")["run_id"]
            api(base, "/api/import", {"inbox_csv": inbox_csv()})
            with self.assertRaises(HTTPError) as error:
                api(base, "/api/export")
            self.assertEqual(error.exception.code, 409)
            api(base, "/api/process", {})
            snapshot = finished(base)
            entry = snapshot["records"][0]
            self.assertIsNotNone(entry["result"])
            revision = entry["revision"]
            saved = api(base, "/api/review", {"email_id": "NEW-1", "revision": revision, "draft_reply": "Saved edit, with comma\nThe UNIQ Supply Team", "reviewed": True})
            with self.assertRaises(HTTPError) as error:
                api(base, "/api/review", {"email_id": "NEW-1", "revision": revision, "draft_reply": "Stale edit", "reviewed": False})
            self.assertEqual(error.exception.code, 409)
            with urlopen(base + "/api/export", timeout=5) as response:
                row = next(csv.DictReader(io.StringIO(response.read().decode("utf-8-sig"))))
            self.assertEqual(row["draft_reply"], "Saved edit, with comma\nThe UNIQ Supply Team")
            client.fail = True
            api(base, "/api/process", {"email_id": "NEW-1"})
            failed = finished(base)["records"][0]
            self.assertEqual(failed["result"]["draft_reply"], row["draft_reply"])
            self.assertTrue(failed["reviewed"])
            self.assertIn("timeout", failed["error"])
            self.assertEqual(server.store.latest()["records"][0]["result"]["draft_reply"], row["draft_reply"])
            runs = api(base, "/api/runs")["runs"]
            self.assertEqual(len(runs), 2)
            opened = api(base, "/api/open-run", {"run_id": original})
            self.assertEqual(len(opened["records"]), 20)

    def test_one_failure_does_not_stop_batch(self):
        class PartialFailureClient(FakeClient):
            def complete(self, name, instructions, context, schema):
                if name == "inbox_extraction" and context["record"]["email"]["email_id"] == "FAIL":
                    raise AIError("Mock one-email failure.")
                return super().complete(name, instructions, context, schema)
        with review_server(PartialFailureClient()) as (base, server):
            text = inbox_csv(email_id="FAIL") + inbox_csv(email_id="GOOD").split("\n", 1)[1]
            api(base, "/api/import", {"inbox_csv": text})
            api(base, "/api/process", {})
            snapshot = finished(base)
            self.assertIsNone(snapshot["records"][0]["result"])
            self.assertIn("one-email", snapshot["records"][0]["error"])
            self.assertIsNotNone(snapshot["records"][1]["result"])
            self.assertEqual(snapshot["job"]["completed"], 2)

    def test_no_reply_cannot_be_edited_into_reply(self):
        from test_pipeline import extraction
        client = FakeClient(extraction(category="Spam / Phishing", quantity=None, size_oz=None))
        with review_server(client) as (base, server):
            api(base, "/api/import", {"inbox_csv": inbox_csv()})
            api(base, "/api/process", {})
            entry = finished(base)["records"][0]
            with self.assertRaises(HTTPError) as error:
                api(base, "/api/review", {"email_id": "NEW-1", "revision": entry["revision"], "draft_reply": "Please click the link", "reviewed": True})
            self.assertEqual(error.exception.code, 400)

    def test_missing_configuration_has_clear_setup_error(self):
        from app.ai_client import GeminiClient
        with review_server(GeminiClient({})) as (base, server):
            with self.assertRaises(HTTPError) as error:
                api(base, "/api/process", {})
            self.assertEqual(error.exception.code, 503)
            self.assertIn("GEMINI_API_KEY", json.load(error.exception)["error"])
            self.assertFalse(api(base, "/api/inbox")["job"]["busy"])


if __name__ == "__main__":
    unittest.main()
