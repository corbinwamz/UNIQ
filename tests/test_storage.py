import csv
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.models import EXPORT_COLUMNS
from app.storage import RunStore, StorageError, export_csv, new_run
from test_pipeline import new_record


def complete_run():
    run = new_run([new_record()])
    run["records"][0]["result"] = dict(zip(EXPORT_COLUMNS, ("NEW-42", "Custom Quote", "P2", "No — standard policy", "quote, math", 'Hi Alex,\nA "quoted" reply.\nThe UNIQ Supply Team')))
    return run


class StorageTests(unittest.TestCase):
    def test_atomic_save_reload_list_and_latest(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RunStore(directory)
            run = complete_run()
            store.save(run)
            self.assertEqual(store.latest(), run)
            self.assertEqual(store.load(run["run_id"]), run)
            self.assertEqual(store.list_runs()[0]["completed"], 1)
            self.assertFalse(list(Path(directory).glob("*.tmp")))

    def test_failed_atomic_write_preserves_previous_record(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RunStore(directory)
            run = complete_run()
            store.save(run)
            old = store.load(run["run_id"])
            run["records"][0]["result"]["draft_reply"] = "Replacement"
            with patch("app.storage.os.replace", side_effect=OSError("disk failure")), self.assertRaises(OSError):
                store.save(run)
            self.assertEqual(store.load(run["run_id"]), old)

    def test_invalid_run_id_and_corrupt_latest(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RunStore(directory)
            with self.assertRaises(StorageError):
                store.load("../../.env")
            (Path(directory) / "latest.json").write_text("broken", encoding="utf-8")
            with self.assertRaises(StorageError):
                store.latest()

    def test_export_exact_columns_multiline_and_latest_edit(self):
        run = complete_run()
        run["records"][0]["result"]["draft_reply"] = "Edited, résumé\nSecond line"
        stream = io.StringIO(export_csv(run).decode("utf-8-sig"))
        reader = csv.DictReader(stream)
        self.assertEqual(tuple(reader.fieldnames), EXPORT_COLUMNS)
        self.assertEqual(list(reader)[0]["draft_reply"], "Edited, résumé\nSecond line")

    def test_incomplete_export_blocked_and_formulas_escaped(self):
        with self.assertRaises(StorageError):
            export_csv(new_run([new_record()]))
        run = complete_run()
        run["records"][0]["result"]["draft_reply"] = "=DANGEROUS()"
        row = next(csv.DictReader(io.StringIO(export_csv(run).decode("utf-8-sig"))))
        self.assertEqual(row["draft_reply"], "'=DANGEROUS()")


if __name__ == "__main__":
    unittest.main()
