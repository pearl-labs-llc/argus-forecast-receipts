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
        for name in ("receipts.csv", "scores.csv", "baselines.csv", "SCORING-RULE-v1.md", "SCORING-RULE-v1-ADDENDUM-1.md",
                     "SCORING-RULE-v1-ADDENDUM-2.md"):
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

    # ---- baselines.csv (addendum 2 section 5) ----
    PERS_SHA = "b" * 64

    def resolved_week(self, fid=FUTURE, issued="2099-01-04", resolves="2099-01-11", counted="yes", status="resolved; revealed",
                      g_row=True):
        """A synthetic resolved week: receipt, published reveal (two cells), status line and the G score row."""
        payload = {"forecast_id": fid, "issued_for_map_date": issued, "resolves_on_map_date": resolves,
                   "cells": {"c1": {"G": 0.1, "M": 0.2}, "c2": {"G": 0.3, "M": 0.1}}}
        digest = forecast_hash(payload)
        (self.root / f"reveals/{fid}.json").write_text(json.dumps(payload))
        self.append("receipts.csv", f"{fid},{digest},{issued},{resolves},{counted},{issued},pending")
        if status:
            self.append("receipts.csv", f"{fid},{digest},{issued},{resolves},{counted},{issued},{status}")
        if g_row:
            self.append("scores.csv", f"{fid},{counted},2,1,G,0.05,0.2,1.000,1,0.25")
        return fid

    def baseline_row(self, fid=FUTURE, **fields):
        row = {"forecast_id": fid, "counted_under_rule_v1": "yes", "baseline": "PERS", "persistence_sha256": self.PERS_SHA,
               "cells": "2", "cells_with_gain": "1", "brier": "0.120000", "log_loss": "0.400000", "auc": "0.750",
               "top10_expected_hits": "1.000000"}
        row.update(fields)
        return ",".join(row.values())

    def test_baselines_header_is_exact(self):
        self.assertEqual((self.root / "baselines.csv").read_text(),
                         "forecast_id,counted_under_rule_v1,baseline,persistence_sha256,cells,cells_with_gain,brier,log_loss,"
                         "auc,top10_expected_hits\n")
        self.replace("baselines.csv", b"top10_expected_hits", b"top10_hits")
        self.reject("baselines.csv: unexpected CSV header")

    def test_baselines_valid_row_allowed(self):
        self.append("baselines.csv", self.baseline_row(self.resolved_week()))
        check_integrity(self.root, "HEAD")

    def test_baselines_empty_auc_and_fractional_top10_allowed(self):
        self.append("baselines.csv", self.baseline_row(self.resolved_week(), auc="", top10_expected_hits="0.5"))
        check_integrity(self.root, "HEAD")

    def test_baselines_append_only(self):
        self.append("baselines.csv", self.baseline_row(self.resolved_week()))
        self.git("add", ".")
        self.git("-c", "user.name=Integrity tests", "-c", "user.email=tests@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "baseline row")
        check_integrity(self.root, "HEAD")
        self.replace("baselines.csv", b"0.120000", b"0.110000")
        self.reject("baselines.csv: existing CSV bytes changed")

    def test_baselines_unknown_baseline_fails(self):
        self.append("baselines.csv", self.baseline_row(self.resolved_week(), baseline="PERS_HARD"))
        self.reject("unknown baseline PERS_HARD")

    def test_baselines_invalid_persistence_sha_fails(self):
        self.append("baselines.csv", self.baseline_row(self.resolved_week(), persistence_sha256="B" * 64))
        self.reject("invalid persistence_sha256")

    def test_baselines_duplicate_row_fails(self):
        row = self.baseline_row(self.resolved_week())
        self.append("baselines.csv", row)
        self.append("baselines.csv", row.replace("0.120000", "0.130000"))
        self.reject("duplicate baseline")

    def test_baselines_need_a_receipt(self):
        self.append("baselines.csv", self.baseline_row())
        self.reject("baseline has no receipt")

    def test_baselines_need_a_published_reveal(self):
        fid = self.resolved_week(status=None, g_row=False)
        (self.root / f"reveals/{fid}.json").unlink()
        self.append("baselines.csv", self.baseline_row(fid))
        self.reject("verified reveal before baselines")

    def test_baselines_need_a_resolved_status(self):
        self.append("baselines.csv", self.baseline_row(self.resolved_week(status=None, g_row=False)))
        self.reject("baselines for an unresolved forecast")

    def test_baselines_need_the_published_g_row(self):
        self.append("baselines.csv", self.baseline_row(self.resolved_week(g_row=False)))
        self.reject("publish the G score row before baselines")

    def test_baselines_cell_count_must_equal_reveal(self):
        self.append("baselines.csv", self.baseline_row(self.resolved_week(), cells="3"))
        self.reject("baseline/reveal cell count differs")

    def test_baselines_cells_with_gain_must_equal_g_row(self):
        self.append("baselines.csv", self.baseline_row(self.resolved_week(), cells_with_gain="2", top10_expected_hits="1"))
        self.reject("baseline/G cells_with_gain differs")

    def test_baselines_counted_must_match_receipt(self):
        self.append("baselines.csv", self.baseline_row(self.resolved_week(), counted_under_rule_v1="no"))
        self.reject("inconsistent counted status in baselines")

    def test_baselines_counted_must_be_yes_or_no(self):
        self.append("baselines.csv", self.baseline_row(self.resolved_week(), counted_under_rule_v1="reference"))
        self.reject("start with yes or no")

    def test_baselines_before_first_issue_fail(self):
        # The published, resolved, scored 2026-10-18 week: its G row exists, but it predates addendum 2.
        self.append("baselines.csv", self.baseline_row("mdo-front-2026-10-18", cells="177", cells_with_gain="5"))
        self.reject("baselines begin with the 2026-10-25 issue")

    def test_baselines_first_issue_week_allowed(self):
        fid = self.resolved_week("mdo-front-2026-10-25-synthetic", "2026-10-25", "2026-11-01")
        self.append("baselines.csv", self.baseline_row(fid))
        check_integrity(self.root, "HEAD")

    def test_baselines_brier_range(self):
        self.append("baselines.csv", self.baseline_row(self.resolved_week(), brier="1.2"))
        self.reject("baseline brier: out-of-range")

    def test_baselines_log_loss_range(self):
        self.append("baselines.csv", self.baseline_row(self.resolved_week(), log_loss="-0.1"))
        self.reject("baseline log_loss: out-of-range")

    def test_baselines_auc_range(self):
        self.append("baselines.csv", self.baseline_row(self.resolved_week(), auc="1.5"))
        self.reject("baseline auc: out-of-range")

    def test_baselines_top10_at_most_cells_with_gain(self):
        self.append("baselines.csv", self.baseline_row(self.resolved_week(), top10_expected_hits="1.5"))
        self.reject("top10_expected_hits: out-of-range")

    def test_baselines_top10_non_negative_and_finite(self):
        for bad in ("-0.5", "nan"):
            with self.subTest(bad):
                path = self.root / "baselines.csv"
                head = path.read_bytes()
                fid = self.FUTURE if bad == "-0.5" else "mdo-front-2099-01-11"
                self.resolved_week(fid, *(("2099-01-04", "2099-01-11") if bad == "-0.5" else ("2099-01-11", "2099-01-18")))
                path.write_bytes(head)
                self.append("baselines.csv", self.baseline_row(fid, top10_expected_hits=bad))
                self.reject("top10_expected_hits: out-of-range")
                path.write_bytes(head)

    def test_baselines_numbers_must_be_finite(self):
        self.append("baselines.csv", self.baseline_row(self.resolved_week(), brier="nan"))
        self.reject("baseline brier: out-of-range or non-finite")

    def test_baselines_no_per_cell_column(self):
        # Section 5: per-cell PERS values are never published; an extra column is refused.
        self.append("baselines.csv", self.baseline_row(self.resolved_week()) + ",c1=0.5")
        self.reject("baselines.csv: wrong column count")

    def test_pers_is_never_a_scores_row(self):
        # scores.csv stays G-only for PERS: every scored model must be in the reveal, and PERS is not.
        fid = self.resolved_week()
        self.append("scores.csv", f"{fid},yes,2,1,PERS,0.12,0.4,0.750,1,0.25")
        self.reject("score model absent from reveal")

    def test_pers_in_a_reveal_breaks_its_hash(self):
        fid = self.resolved_week()
        path = self.root / f"reveals/{fid}.json"
        data = json.loads(path.read_text())
        data["cells"]["c1"]["PERS"] = 0.5
        path.write_text(json.dumps(data))
        self.reject("reveal hash differs")

    def test_addendum_2_is_pinned(self):
        with (self.root / "SCORING-RULE-v1-ADDENDUM-2.md").open("ab") as stream:
            stream.write(b"\n")
        self.reject("SCORING-RULE-v1-ADDENDUM-2.md: approved scoring rule hash changed")

    def test_baselines_table_deleted_fails(self):
        (self.root / "baselines.csv").unlink()
        self.reject("baselines.csv: published record deleted or replaced")

    def test_invalid_base_fails_closed(self):
        with self.assertRaises(subprocess.CalledProcessError):
            check_history(self.root, "--not-a-commit")


if __name__ == "__main__":
    unittest.main()
