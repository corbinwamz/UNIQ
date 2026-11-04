"""Atomic local run snapshots and exact six-column CSV export."""

import csv
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
import tempfile
from uuid import uuid4

from .models import EXPORT_COLUMNS, jsonable


class StorageError(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def new_run(records):
    return {"version": 1, "run_id": uuid4().hex, "created_at": now(), "updated_at": now(),
            "records": [{**jsonable(record), "result": None, "error": None, "reviewed": False, "revision": 0} for record in records]}


class RunStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, run_id):
        if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
            raise StorageError("Invalid run ID.")
        return self.directory / (run_id + ".json")

    def _atomic(self, path, value):
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.directory, suffix=".tmp", delete=False) as stream:
                temp_path = Path(stream.name)
                json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def save(self, run):
        pointer = self.directory / "latest.json"
        current_id = None
        if pointer.exists():
            try:
                current_id = json.loads(pointer.read_text(encoding="utf-8"))["run_id"]
            except (OSError, ValueError, KeyError, TypeError):
                raise StorageError("Latest-run pointer is invalid; saved work has not been overwritten.") from None
        self._atomic(self._path(run["run_id"]), run)
        # Existing active runs need one atomic replacement, not two. On a new
        # run, pointer failure leaves the old active run intact and a recoverable
        # orphan snapshot, rather than claiming an in-memory commit succeeded.
        if current_id != run["run_id"]:
            self._atomic(pointer, {"run_id": run["run_id"]})

    def load(self, run_id):
        try:
            run = json.loads(self._path(run_id).read_text(encoding="utf-8"))
            if run["version"] != 1 or run["run_id"] != run_id or not isinstance(run["records"], list) or not run["records"]:
                raise ValueError()
            ids = [record["email"]["email_id"] for record in run["records"]]
            if len(set(ids)) != len(ids):
                raise ValueError()
            for record in run["records"]:
                if not isinstance(record["revision"], int) or type(record["reviewed"]) is not bool:
                    raise ValueError()
                if record["result"] is not None and any(not isinstance(record["result"].get(key), str) for key in EXPORT_COLUMNS):
                    raise ValueError()
            return run
        except (OSError, ValueError, KeyError, TypeError):
            raise StorageError("Saved run is missing or invalid; existing files have not been overwritten.") from None

    def latest(self):
        pointer = self.directory / "latest.json"
        if not pointer.exists():
            return None
        try:
            return self.load(json.loads(pointer.read_text(encoding="utf-8"))["run_id"])
        except (OSError, ValueError, KeyError, TypeError):
            raise StorageError("Latest saved run cannot be read. Inspect output/runs before starting a new run.") from None

    def list_runs(self):
        runs = []
        for path in self.directory.glob("*.json"):
            if not re.fullmatch(r"[0-9a-f]{32}", path.stem):
                continue
            run = self.load(path.stem)
            runs.append({"run_id": run["run_id"], "created_at": run["created_at"], "updated_at": run["updated_at"],
                         "count": len(run["records"]), "completed": sum(record["result"] is not None for record in run["records"])})
        return sorted(runs, key=lambda run: run["updated_at"], reverse=True)


def export_csv(run):
    incomplete = [record["email"]["email_id"] for record in run["records"] if record["result"] is None]
    if incomplete:
        raise StorageError(f"Complete all emails before export. Pending/failed: {', '.join(incomplete)}.")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=EXPORT_COLUMNS)
    writer.writeheader()
    for record in run["records"]:
        result = record["result"]
        writer.writerow({key: "'" + result[key] if result[key].lstrip().startswith(("=", "+", "-", "@")) else result[key] for key in EXPORT_COLUMNS})
    return ("\ufeff" + stream.getvalue()).encode("utf-8")
