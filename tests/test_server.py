from contextlib import contextmanager
from http.client import HTTPConnection
import json
import threading
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.server import create_server
from test_data_loader import inbox_csv


@contextmanager
def running_server():
    with tempfile.TemporaryDirectory() as directory:
        server = create_server(0, store_dir=directory)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)


class ServerTests(unittest.TestCase):
    def test_source_inbox_assets_and_health(self):
        with running_server() as base:
            with urlopen(base + "/api/inbox", timeout=5) as response:
                data = json.load(response)
            self.assertEqual(len(data["records"]), 20)
            self.assertEqual(data["scenario_date"], "2027-03-08")
            for path, content_type in (("/", "text/html"), ("/styles.css", "text/css"), ("/app.js", "text/javascript"), ("/api/health", "application/json")):
                with self.subTest(path=path), urlopen(base + path, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.headers.get_content_type(), content_type)
            for path in ("/AGENTS.md", "/.env", "/../orders.csv", "/unknown"):
                with self.subTest(path=path), self.assertRaises(HTTPError) as error:
                    urlopen(base + path, timeout=5)
                self.assertEqual(error.exception.code, 404)

    def test_import_and_failed_import_preserves_previous_inbox(self):
        with running_server() as base:
            def post(data):
                request = Request(base + "/api/import", data=json.dumps(data).encode(), headers={"Content-Type": "application/json"})
                return urlopen(request, timeout=5)

            with post({"inbox_csv": inbox_csv()}) as response:
                imported = json.load(response)
            self.assertEqual([r["email"]["email_id"] for r in imported["records"]], ["NEW-1"])
            for payload in ({"inbox_csv": "wrong header"}, {"inbox_csv": 123}, []):
                with self.subTest(payload=payload), self.assertRaises(HTTPError) as error:
                    post(payload)
                self.assertEqual(error.exception.code, 400)
                self.assertIn("error", json.load(error.exception))
            with urlopen(base + "/api/inbox", timeout=5) as response:
                self.assertEqual(json.load(response)["records"][0]["email"]["email_id"], "NEW-1")

    def test_content_type_and_payload_limit(self):
        with running_server() as base:
            for headers, expected in (({"Content-Type": "text/plain"}, 415), ({"Content-Type": "application/json", "Content-Length": "2097153"}, 413)):
                with self.subTest(expected=expected):
                    # These failures must be decided from headers, before the
                    # body is sent. Avoid a deliberately truncated payload that
                    # can reset a Windows socket when the server closes early.
                    connection = HTTPConnection(base.removeprefix("http://"), timeout=5)
                    try:
                        connection.putrequest("POST", "/api/import")
                        for name, value in headers.items():
                            connection.putheader(name, value)
                        connection.endheaders()
                        response = connection.getresponse()
                        self.assertEqual(response.status, expected)
                        self.assertIn("error", json.loads(response.read()))
                    finally:
                        connection.close()


if __name__ == "__main__":
    unittest.main()
