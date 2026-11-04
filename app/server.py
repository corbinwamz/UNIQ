"""Local review server: persistent runs, asynchronous processing, safe exports."""

import argparse
from copy import deepcopy
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Lock, Thread
from urllib.parse import urlsplit

from .ai_client import AIError, OpenAIClient
from .config import INBOX_PATH, MAX_IMPORT_BYTES, ORDERS_PATH, RUNS_DIR, SCENARIO_DATE, STATIC_DIR, ai_settings
from .data_loader import DataValidationError, build_inbox, parse_inbox, parse_orders, read_source
from .models import Email, InboxRecord, Order, OrderCandidate, OrderContext
from .pipeline import Pipeline
from .pricing import RuleInputError
from .storage import RunStore, StorageError, export_csv, new_run, now


class ConflictError(ValueError):
    pass


def source_record(entry):
    context = entry["order_context"]
    return InboxRecord(Email(**entry["email"]), OrderContext(
        tuple(OrderCandidate(Order(**candidate["order"]), candidate["score"], tuple(candidate["reasons"])) for candidate in context["candidates"]),
        context["suggested_order_id"], context["explanation"],
    ))


class InboxServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, records, orders, store, client_factory=None):
        super().__init__(address, InboxHandler)
        self.orders, self.store = orders, store
        self.lock = Lock()
        self.client_factory = client_factory or OpenAIClient
        self.job = {"busy": False, "current": None, "completed": 0, "total": 0, "message": "Ready."}
        self.run = store.latest() or new_run(records)
        store.save(self.run)

    def commit(self, candidate):
        candidate["updated_at"] = now()
        self.store.save(candidate)
        self.run = candidate

    def require_idle(self):
        if self.job["busy"]:
            raise ConflictError("Wait for processing to finish before changing runs or saving edits.")

    def start_processing(self, email_id=None):
        client = self.client_factory()
        client.require_configuration()
        with self.lock:
            self.require_idle()
            if email_id is not None and not any(record["email"]["email_id"] == email_id for record in self.run["records"]):
                raise DataValidationError("Email ID not found in this run.")
            targets = [deepcopy(record) for record in self.run["records"] if record["email"]["email_id"] == email_id or (email_id is None and record["result"] is None)]
            self.job = {"busy": bool(targets), "current": None, "completed": 0, "total": len(targets), "message": "Processing." if targets else "All emails already have results."}
        if targets:
            Thread(target=self._process, args=(targets, client), daemon=True).start()

    def _process(self, targets, client):
        pipeline = Pipeline(client)
        try:
            for target in targets:
                email_id = target["email"]["email_id"]
                with self.lock:
                    self.job["current"] = email_id
                result, error = None, None
                try:
                    result = pipeline.process(source_record(target))
                except (AIError, RuleInputError, DataValidationError) as exc:
                    error = str(exc)
                except Exception:
                    error = "Processing failed unexpectedly; review this email and retry. No previous result was replaced."
                with self.lock:
                    candidate = deepcopy(self.run)
                    entry = next(record for record in candidate["records"] if record["email"]["email_id"] == email_id)
                    if result is not None:
                        entry.update(result=result, reviewed=False, error=None, revision=entry["revision"] + 1)
                    else:
                        entry["error"] = error
                    self.commit(candidate)
                    self.job["completed"] += 1
        except OSError:
            with self.lock:
                self.job["message"] = "Saving failed. Processing stopped; previous saved results are preserved. Check disk access."
        except Exception:
            with self.lock:
                self.job["message"] = "Processing stopped unexpectedly; saved work is preserved. Reload and inspect the run."
        finally:
            with self.lock:
                self.job["busy"] = False
                self.job["current"] = None
                if self.job["completed"] == self.job["total"]:
                    self.job["message"] = "Processing finished. Review results and any per-email errors."


class InboxHandler(BaseHTTPRequestHandler):
    def _send(self, status, body, content_type="application/json; charset=utf-8", filename=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def _snapshot(self):
        with self.server.lock:
            data = deepcopy(self.server.run)
            data.update(scenario_date=SCENARIO_DATE.isoformat(), stage="AI drafting and human review", job=deepcopy(self.server.job))
        settings = ai_settings()
        data["ai_configured"] = bool(settings["OPENAI_API_KEY"] and settings["OPENAI_MODEL"])
        return data

    def do_GET(self):
        path = urlsplit(self.path).path
        try:
            if path == "/api/health":
                self._send(HTTPStatus.OK, {"status": "ok", "step": 5})
            elif path == "/api/inbox":
                self._send(HTTPStatus.OK, self._snapshot())
            elif path == "/api/runs":
                with self.server.lock:
                    runs = self.server.store.list_runs()
                self._send(HTTPStatus.OK, {"runs": runs})
            elif path == "/api/export":
                with self.server.lock:
                    self.server.require_idle()
                    content = export_csv(self.server.run)
                self._send(HTTPStatus.OK, content, "text/csv; charset=utf-8", "uniq-results.csv")
            else:
                assets = {"/": ("index.html", "text/html"), "/styles.css": ("styles.css", "text/css"), "/app.js": ("app.js", "text/javascript")}
                if path not in assets:
                    self._send(HTTPStatus.NOT_FOUND, {"error": "Not found."})
                    return
                filename, content_type = assets[path]
                self._send(HTTPStatus.OK, (STATIC_DIR / filename).read_bytes(), content_type + "; charset=utf-8")
        except (StorageError, ConflictError) as exc:
            self._send(HTTPStatus.CONFLICT, {"error": str(exc)})
        except OSError:
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Local files could not be read; check disk access."})

    def do_POST(self):
        path = urlsplit(self.path).path
        if path not in ("/api/import", "/api/process", "/api/review", "/api/open-run", "/api/check-ai"):
            self._send(HTTPStatus.NOT_FOUND, {"error": "Not found."})
            return
        try:
            if self.headers.get_content_type() != "application/json":
                self._send(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "Use application/json."})
                return
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_IMPORT_BYTES:
                self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "Request must be between 1 byte and 2 MiB."})
                return
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise DataValidationError("Request must be a JSON object.")
            if path == "/api/check-ai":
                self._send(HTTPStatus.OK, self.server.client_factory().smoke_test())
                return
            if path == "/api/process":
                email_id = payload.get("email_id")
                if email_id is not None and not isinstance(email_id, str):
                    raise DataValidationError("email_id must be a string.")
                self.server.start_processing(email_id)
            else:
                with self.server.lock:
                    self.server.require_idle()
                    if path == "/api/import":
                        if not isinstance(payload.get("inbox_csv"), str):
                            raise DataValidationError("Request must contain an inbox_csv string.")
                        records = build_inbox(parse_inbox(payload["inbox_csv"]), self.server.orders)
                        candidate = new_run(records)
                    elif path == "/api/open-run":
                        candidate = self.server.store.load(payload.get("run_id"))
                    else:
                        candidate = deepcopy(self.server.run)
                        entry = next((record for record in candidate["records"] if record["email"]["email_id"] == payload.get("email_id")), None)
                        if not entry or entry["result"] is None:
                            raise DataValidationError("A processed email is required before saving a review.")
                        if type(payload.get("revision")) is not int or payload["revision"] != entry["revision"]:
                            raise ConflictError("This draft changed since it was opened. Reload before saving.")
                        if not isinstance(payload.get("draft_reply"), str) or not payload["draft_reply"].strip() or len(payload["draft_reply"]) > 18000:
                            raise DataValidationError("Draft must contain 1-18,000 characters.")
                        if type(payload.get("reviewed")) is not bool:
                            raise DataValidationError("reviewed must be a boolean.")
                        if not entry["result"]["decisions"]["triage"]["reply_allowed"] and payload["draft_reply"] != entry["result"]["draft_reply"]:
                            raise DataValidationError("No-reply cases cannot be changed into outgoing drafts.")
                        entry["result"]["draft_reply"] = payload["draft_reply"].strip()
                        entry["reviewed"] = payload["reviewed"]
                        entry["revision"] += 1
                    self.server.commit(candidate)
            self._send(HTTPStatus.ACCEPTED if path == "/api/process" else HTTPStatus.OK, self._snapshot())
        except (DataValidationError, RuleInputError) as exc:
            self._send(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except (StorageError, ConflictError) as exc:
            self._send(HTTPStatus.CONFLICT, {"error": str(exc)})
        except AIError as exc:
            self._send(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
        except (ValueError, UnicodeError, TypeError):
            self._send(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON, encoding, or request fields."})
        except OSError:
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Local data could not be saved. Previous work has not been replaced in memory."})


def create_server(port=8765, *, store_dir=RUNS_DIR, client_factory=None):
    orders = parse_orders(read_source(ORDERS_PATH))
    records = build_inbox(parse_inbox(read_source(INBOX_PATH)), orders)
    return InboxServer(("127.0.0.1", port), records, orders, RunStore(store_dir), client_factory)


def main():
    parser = argparse.ArgumentParser(description="UNIQ local inbox review tool")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        server = create_server(args.port)
    except (DataValidationError, StorageError, OSError, OverflowError) as exc:
        parser.exit(1, f"Startup failed: {exc}\n")
    print(f"UNIQ inbox: http://127.0.0.1:{server.server_port} (AI drafts and local review)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
