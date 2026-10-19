"""Mutation coverage using the exact public record bytes in an isolated directory."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from check_integrity import check_integrity, check_history, TABLES
from verify import forecast_hash


SOURCE = Path(__file__).resolve().parents[1]


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ("receipts.csv", "scores.csv", "SCORING-RULE-v1.md", "SCORING-RULE-v1-ADDENDUM-1.md"):
            shutil.copyfile(SOURCE / name, self.root / name)
        for name in ("reveals", "advance"):
            shutil.copytree(SOURCE / name, self.root / name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.git("add", ".")
        self.git("-c", "user.name=Integrity tests", "-c", "user.email=tests@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "exact public baseline")

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args])

    def replace(self, name, old, new):
        path = self.root / name
        data = path.read_bytes()
        self.assertIn(old, data)
        path.write_bytes(data.replace(old, new, 1))

    def append(self, name, row):
        with (self.root / name).open("a", encoding="utf-8", newline="") as stream:
            stream.write(row + "\n")

    def reject(self, message):
        with self.assertRaisesRegex((ValueError, FileNotFoundError), message):
            check_integrity(self.root, "HEAD")

    def reveal(self):
        return self.root / "reveals/mdo-front-2026-10-02.json"

    def test_existing_public_record_and_hash_unchanged(self):
        before = {name: (self.root / name).read_bytes() for name in TABLES}
        check_integrity(self.root, "HEAD")
        self.assertEqual(before, {name: (self.root / name).read_bytes() for name in TABLES})
        self.assertEqual(forecast_hash(json.loads(self.reveal().read_text())),
                         "d4ddcd56f41b97191166ee5b949c346fa716df4d0fca8944e2b1a52c2790821b")

    # Synthetic ids far in the future so the tests never collide with a real, later-published week.
    FUTURE = "mdo-front-2099-01-04"

    def test_append_receipt_allowed(self):
        self.append("receipts.csv", f"{self.FUTURE}," + "a" * 64 + ",2099-01-04,2099-01-11,yes,2099-01-04,pending")
        check_integrity(self.root, "HEAD")

    def test_score_edit_fails_even_when_schema_valid(self):
        self.replace("scores.csv", b"0.021439", b"0.021438")
        self.reject("existing CSV bytes changed")

    def test_receipt_deletion_fails(self):
        path = self.root / "receipts.csv"
        path.write_bytes(path.read_bytes().splitlines(keepends=True)[0])
        self.reject("no receipt|missing matching receipt")

    def test_csv_header_change_fails(self):
        self.replace("scores.csv", b"brier,", b"other,")
        self.reject("unexpected CSV header")

    def test_csv_extra_column_fails(self):
        self.replace("scores.csv", b"0.023933\n", b"0.023933,extra\n")
        self.reject("wrong column count")

    def test_missing_newline_fails(self):
        path = self.root / "advance/receipts.csv"
        path.write_bytes(path.read_bytes().rstrip(b"\n"))
        self.reject("newline")

    def test_duplicate_receipt_fails(self):
        row = (self.root / "receipts.csv").read_text().splitlines()[1]
        self.append("receipts.csv", row)
        self.reject("duplicate forecast")

    def test_status_progression_line_allowed(self):
        self.append("receipts.csv", f"{self.FUTURE}," + "a" * 64 + ",2099-01-04,2099-01-11,yes,2099-01-04,pending")
        self.append("receipts.csv", f"{self.FUTURE}," + "a" * 64 + ",2099-01-04,2099-01-11,yes,2099-01-04,resolved")
        check_integrity(self.root, "HEAD")

    def test_status_line_cannot_change_commitment(self):
        self.append("receipts.csv", f"{self.FUTURE}," + "a" * 64 + ",2099-01-04,2099-01-11,yes,2099-01-04,pending")
        self.append("receipts.csv", f"{self.FUTURE}," + "b" * 64 + ",2099-01-04,2099-01-11,yes,2099-01-04,resolved")
        self.reject("changes its commitment")

    def test_status_line_cannot_change_counted(self):
        self.append("receipts.csv", f"{self.FUTURE}," + "a" * 64 + ",2099-01-04,2099-01-11,yes,2099-01-04,pending")
        self.append("receipts.csv", f"{self.FUTURE}," + "a" * 64 + ",2099-01-04,2099-01-11,no,2099-01-04,resolved")
        self.reject("changes its commitment")

    def test_status_line_cannot_regress(self):
        self.append("receipts.csv", f"{self.FUTURE}," + "a" * 64 + ",2099-01-04,2099-01-11,yes,2099-01-04,resolved")
        self.append("receipts.csv", f"{self.FUTURE}," + "a" * 64 + ",2099-01-04,2099-01-11,yes,2099-01-04,pending")
        self.reject("without a status progression")

    def test_revealed_status_requires_reveal(self):
        self.append("receipts.csv", f"{self.FUTURE}," + "a" * 64 + ",2099-01-04,2099-01-11,yes,2099-01-04,pending")
        self.append("receipts.csv", f"{self.FUTURE}," + "a" * 64 + ",2099-01-04,2099-01-11,yes,2099-01-04,resolved; revealed")
        self.reject("no reveal is published")

    def test_scores_require_resolved_status(self):
        payload = {"forecast_id": self.FUTURE, "issued_for_map_date": "2099-01-04", "resolves_on_map_date": "2099-01-11",
                   "cells": {"c1": {"G": 0.1, "M": 0.2}}}
        digest = forecast_hash(payload)
        (self.root / f"reveals/{self.FUTURE}.json").write_text(json.dumps(payload))
        self.append("receipts.csv", f"{self.FUTURE},{digest},2099-01-04,2099-01-11,yes,2099-01-04,pending")
        self.append("scores.csv", f"{self.FUTURE},yes,1,0,G,0.01,0.02,,0,0.02")
        self.reject("unresolved forecast")
        self.append("receipts.csv", f"{self.FUTURE},{digest},2099-01-04,2099-01-11,yes,2099-01-04,resolved; revealed")
        check_integrity(self.root, "HEAD")

    def test_duplicate_score_fails(self):
        row = (self.root / "scores.csv").read_text().splitlines()[1]
        self.append("scores.csv", row)
        self.reject("duplicate score")

    def test_hash_mismatch_fails(self):
        self.replace("receipts.csv", b"d4ddcd56", b"a4ddcd56")
        self.reject("reveal hash differs")

    def test_rule_edit_fails(self):
        with (self.root / "SCORING-RULE-v1.md").open("ab") as stream:
            stream.write(b"\n")
        self.reject("approved scoring rule hash changed")

    def test_reveal_reformatting_fails_history(self):
        # Semantically equal JSON and identical commitment; original public bytes still immutable.
        path = self.reveal()
        path.write_text(json.dumps(json.loads(path.read_text()), indent=2) + "\n")
        self.reject("published bytes are immutable")

    def test_reveal_deleted_fails_history(self):
        self.reveal().unlink()
        with self.assertRaisesRegex(ValueError, "deleted or replaced"):
            check_history(self.root, "HEAD")

    def test_duplicate_json_key_fails(self):
        self.replace("reveals/mdo-front-2026-10-02.json", b'{\n "cells":', b'{\n "cells": {},\n "cells":')
        self.reject("duplicate key")

    def test_nan_reveal_fails(self):
        self.replace("reveals/mdo-front-2026-10-02.json", b"0.003231", b"NaN")
        self.reject("non-finite")

    def test_out_of_range_probability_fails(self):
        self.replace("reveals/mdo-front-2026-10-02.json", b"0.003231", b"1.003231")
        self.reject("out-of-range")

    def test_nonfinite_score_fails(self):
        self.replace("scores.csv", b"0.021439", b"nan")
        self.reject("non-finite")

    def test_counted_status_mismatch_fails(self):
        self.replace("scores.csv", b"2026-10-02,no", b"2026-10-02,yes")
        self.reject("inconsistent counted")

    def test_score_cell_count_mismatch_fails(self):
        self.replace("scores.csv", b",176,", b",175,")
        self.reject("cell count differs")

    def test_wrong_forecast_horizon_fails(self):
        self.replace("receipts.csv", b",2026-10-18,yes", b",2026-10-19,yes")
        self.reject("seven days")

    def test_advance_counting_before_approved_start_fails(self):
        self.append("advance/receipts.csv", "mdo-front-advance-2026-10-18," + "a" * 64 + ",2026-10-18,2026-10-25,yes,2026-10-18,pending")
        self.reject("advance counting begins")

    def test_scores_cannot_precede_reveal(self):
        self.append("receipts.csv", f"{self.FUTURE}," + "a" * 64 + ",2099-01-04,2099-01-11,yes,2099-01-04,pending")
        self.append("scores.csv", f"{self.FUTURE},yes,176,1,G,0.01,0.02,0.5,1,0.02")
        self.reject("verified reveal before scores")

    def append_advance(self, mutate=None):
        cell = {"AB": {"q": [0.1] * 19}, "A": {"p_gain": 0.5, "mean_km2": 0.1, "q": [0.1] * 19},
                "CLIM": {"q": [0.2] * 19}, "PERS": {"value": 0.2}}
        if mutate:
            mutate(cell)
        fid = "mdo-front-adv-2099-01-04"
        payload = {"forecast_id": fid, "issued_for_map_date": "2099-01-04", "resolves_on_map_date": "2099-01-11", "cells": {"synthetic_cell": cell}}
        self.append("advance/receipts.csv", f"{fid},{forecast_hash(payload)},2099-01-04,2099-01-11,yes,2099-01-04,pending")
        (self.root / f"advance/reveals/{fid}.json").write_text(json.dumps(payload))
        self.append("advance/scores.csv", f"{fid},yes,1,AB,0.1,0.2")

    def test_advance_publication_and_zero_baseline_allowed(self):
        self.append_advance()
        self.append("advance/scores.csv", "mdo-front-adv-2099-01-04,yes,1,ZERO,0.1,0.2")
        check_integrity(self.root, "HEAD")

    def test_advance_wrong_quantile_count_fails(self):
        self.append_advance(lambda cell: cell["AB"]["q"].pop())
        self.reject("19 quantiles")

    def test_advance_quantile_order_fails(self):
        self.append_advance(lambda cell: cell["AB"]["q"].__setitem__(0, 1))
        self.reject("nondecreasing")

    def test_advance_negative_quantile_fails(self):
        self.append_advance(lambda cell: cell["AB"]["q"].__setitem__(0, -1))
        self.reject("out-of-range")

    def test_advance_probability_fails(self):
        self.append_advance(lambda cell: cell["A"].__setitem__("p_gain", 2))
        self.reject("out-of-range")

    def test_advance_extra_unpublished_fields_fail(self):
        self.append_advance(lambda cell: cell.__setitem__("input_polygons", []))
        self.reject("sealed AB/A/CLIM/PERS")

    def test_reveal_and_parent_directory_symlinks_fail(self):
        # New symlinked JSON used to pass once, then fail the next history check.
        data = json.loads(self.reveal().read_text())
        data.update(forecast_id="mdo-front-2099-01-04", issued_for_map_date="2099-01-04", resolves_on_map_date="2099-01-11")
        target = self.root / "candidate.json"
        target.write_text(json.dumps(data))
        self.append("receipts.csv", f"mdo-front-2099-01-04,{forecast_hash(data)},2099-01-04,2099-01-11,yes,2099-01-04,pending")
        link = self.root / "reveals/mdo-front-2099-01-04.json"
        link.symlink_to(target)
        with self.subTest("new reveal file"):
            self.reject("symlink")
        link.unlink()
        target.unlink()
        # Parent symlinks hid Git-level deletions behind identical target bytes.
        copied = self.root / "copied-advance"
        (self.root / "advance").rename(copied)
        (self.root / "advance").symlink_to(copied, target_is_directory=True)
        with self.subTest("protected parent directory"):
            self.reject("symlink")

    def test_nested_reveal_json_fails(self):
        nested = self.root / "reveals/nested"
        nested.mkdir()
        (nested / "unchecked.json").write_text('{"inputs": "not a four-key forecast"}')
        self.reject("flat reveal directory")

    def test_invalid_base_fails_closed(self):
        with self.assertRaises(subprocess.CalledProcessError):
            check_history(self.root, "--not-a-commit")


if __name__ == "__main__":
    unittest.main()
