"""Offline checks for the public append-only record; Python standard library only.

Run `python3 check_integrity.py --base <commit>` before publishing. Without
--base, schema, reveal hashes and approved rule pins are still checked, but
append-only history cannot be checked. This verifies commitments, not outcomes
or independence of the confirmer, and does not recompute scientific scores.
"""
import argparse
import csv
from datetime import date, datetime, timedelta
import hashlib
import io
import json
import math
from pathlib import Path
import re
import subprocess

from verify import forecast_hash


RULE_PINS = {
    "SCORING-RULE-v1.md": "49f3dffb2d502a04a6297bb5a1bfcf98cd29199d8f1f8790be6b7d775e119dbb",
    "SCORING-RULE-v1-ADDENDUM-1.md": "c5949b414c08934d709b28621f67b640ed7782a4e088a784eca9692cd1e0a943",
    "SCORING-RULE-v1-ADDENDUM-2.md": "da72220ed16aa238e8649663ee4247178f612ab6398a02cbf2d52baec45553fa",
    "advance/SCORING-RULE-ADVANCE-v1.md": "2e78412f4176f1f7defcfc4b198b8c9e8d93559daf3886d89f42cc8d4404e320",
}
RECEIPT_COLUMNS = "forecast_id,forecast_sha256,issued_for_map_date,resolves_on_map_date,{counted},hash_published_utc,status"
SCORE_COLUMNS = {
    "": "forecast_id,counted_under_rule_v1,cells,cells_with_gain,model,brier,log_loss,auc,top10_hits,climatology_brier",
    "advance/": "forecast_id,counted_under_advance_rule_v1,cells,model,crps_km2,mae_log1p_median",
}
# Addendum 2 section 5: one PERS reference-baseline row per resolved week, beside (never in) scores.csv. Per-cell PERS
# values are never published, so the table has no per-cell column and reveals are unchanged.
BASELINE_COLUMNS = ("forecast_id,counted_under_rule_v1,baseline,persistence_sha256,cells,cells_with_gain,brier,log_loss,"
                    "auc,top10_expected_hits")
BASELINES = ("PERS",)
BASELINES_FIRST_ISSUE = date(2026, 10, 25)  # addendum 2 FIRST_ISSUE: earlier weeks never get a baselines row
TABLES = ("receipts.csv", "scores.csv", "advance/receipts.csv", "advance/scores.csv", "baselines.csv")
HEX_SHA = re.compile(r"[0-9a-f]{64}\Z")
# A forecast may gain later status lines (pending -> confirmed -> resolved/missed); the newest line wins, the first
# line is the commitment and every commitment field stays identical. Mirrors the ARGUS app's receipts parser.
STATUS_RANK = {"pending": 0, "confirmed": 1, "resolved": 2, "missed": 2}
COMMITMENT_FIELDS = ("forecast_sha256", "issued_for_map_date", "resolves_on_map_date", "hash_published_utc")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def regular_file(root, filename):
    path = root / filename
    current = root
    for part in Path(filename).parts:
        current = current / part
        require(not current.is_symlink(), f"{filename}: symlinks cannot store published records")
    require(path.is_file(), f"{filename}: published record deleted or replaced")
    return path


def read_rows(root, filename, columns):
    raw = regular_file(root, filename).read_bytes()
    require(raw.endswith(b"\n"), f"{filename}: must end in a newline before appending")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8"), newline=""), strict=True)
    require(reader.fieldnames == columns.split(","), f"{filename}: unexpected CSV header")
    rows = list(reader)
    for row in rows:
        require(None not in row and None not in row.values(), f"{filename}: wrong column count")
        require(all(value.strip() for key, value in row.items() if key != "auc"),
                f"{filename}: empty required field")
    return rows


def status_kind(status):
    head = status.split(";")[0].strip().lower()
    return head if head in STATUS_RANK else "other"


def is_revealed(status):
    return any(segment.strip().lower() == "revealed" for segment in status.split(";"))


def counted(value):
    require(value == "yes" or value == "no" or value.startswith(("yes (", "no (")),
            "counted field must explicitly start with yes or no")
    return value.startswith("yes")


def number(value, label, minimum=0, maximum=None, integer=False):
    n = int(value) if integer else float(value)
    require(math.isfinite(n) and n >= minimum and (maximum is None or n <= maximum),
            f"{label}: out-of-range or non-finite value")
    return n


def reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"reveal JSON: duplicate key {key}")
        result[key] = value
    return result


def finite_tree(value):
    if isinstance(value, dict):
        for item in value.values():
            finite_tree(item)
    elif isinstance(value, list):
        for item in value:
            finite_tree(item)
    elif isinstance(value, float):
        require(math.isfinite(value), "reveal: non-finite number")


def check_advance_cell(cell, fid):
    require(isinstance(cell, dict) and set(cell) == {"AB", "A", "CLIM", "PERS"},
            f"{fid}: advance cell must contain sealed AB/A/CLIM/PERS")
    for model in ("AB", "A", "CLIM"):
        fields = {"q", "p_gain", "mean_km2"} if model == "A" else {"q"}
        require(isinstance(cell[model], dict) and set(cell[model]) == fields,
                f"{fid}/{model}: unexpected advance fields")
        q = cell[model]["q"]
        require(isinstance(q, list) and len(q) == 19, f"{fid}/{model}: expected 19 quantiles")
        for value in q:
            require(isinstance(value, (int, float)) and not isinstance(value, bool),
                    f"{fid}/{model}: quantile must be numeric")
            number(value, f"{fid}/{model}: quantile")
        require(q == sorted(q), f"{fid}/{model}: quantiles must be nondecreasing")
    for model, field, maximum in (("A", "p_gain", 1), ("A", "mean_km2", None), ("PERS", "value", None)):
        if model == "PERS":
            require(isinstance(cell[model], dict) and set(cell[model]) == {"value"}, f"{fid}/PERS: unexpected fields")
        value = cell[model][field]
        require(isinstance(value, (int, float)) and not isinstance(value, bool), f"{fid}/{field}: value must be numeric")
        number(value, f"{fid}/{field}", maximum=maximum)


def check_lane(root, prefix):
    count_column = "counted_under_advance_rule_v1" if prefix else "counted_under_rule_v1"
    receipts = read_rows(root, prefix + "receipts.csv", RECEIPT_COLUMNS.format(counted=count_column))
    by_id = {}
    latest = {}
    for row in receipts:
        fid = row["forecast_id"]
        if fid in by_id:
            first, previous = by_id[fid], latest[fid]
            require(all(row[key] == first[key] for key in COMMITMENT_FIELDS + (count_column,)),
                    f"{prefix}receipts.csv: duplicate forecast {fid} changes its commitment")
            old_kind, new_kind = status_kind(previous["status"]), status_kind(row["status"])
            require(old_kind != "other" and new_kind != "other" and STATUS_RANK[new_kind] > STATUS_RANK[old_kind],
                    f"{prefix}receipts.csv: duplicate forecast {fid} without a status progression")
            latest[fid] = row
            continue
        require(HEX_SHA.fullmatch(row["forecast_sha256"]), f"{fid}: invalid sha256")
        issue, resolution = (date.fromisoformat(row[key]) for key in ("issued_for_map_date", "resolves_on_map_date"))
        require(resolution - issue == timedelta(days=7), f"{fid}: resolution must be seven days after issue")
        require(re.fullmatch(r"[A-Za-z0-9_-]+", fid), f"{fid}: unsafe forecast identifier")
        published = datetime.fromisoformat(row["hash_published_utc"].replace("Z", "+00:00"))
        require(published.date() >= issue, f"{fid}: publication predates issue")
        is_counted = counted(row[count_column])
        if prefix and is_counted:
            require(issue >= date(2026, 10, 25), f"{fid}: advance counting begins 2026-10-25")
        by_id[fid] = row
        latest[fid] = row

    reveals = {}
    reveal_dir = root / (prefix + "reveals")
    require(not reveal_dir.is_symlink(), f"{prefix}reveals: symlinks cannot store published records")
    for entry in reveal_dir.rglob("*"):
        require(not entry.is_symlink(), f"{entry.name}: symlinks cannot store published records")
        require(entry.parent == reveal_dir and entry.is_file(),
                f"{entry.name}: JSON must be published in the flat reveal directory")
    for path in sorted(reveal_dir.glob("*.json")):
        regular_file(root, path.relative_to(root))
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys)
        require(set(data) == {"forecast_id", "issued_for_map_date", "resolves_on_map_date", "cells"},
                f"{path.name}: reveal must contain exactly the four published keys")
        fid = data["forecast_id"]
        require(fid in by_id and path.stem == fid, f"{path.name}: missing matching receipt")
        row = by_id[fid]
        require(all(data[key] == row[key] for key in ("issued_for_map_date", "resolves_on_map_date")),
                f"{fid}: reveal dates differ from receipt")
        require(isinstance(data["cells"], dict) and data["cells"], f"{fid}: cells must be a nonempty object")
        finite_tree(data["cells"])
        if not prefix:
            for cell in data["cells"].values():
                require(isinstance(cell, dict) and {"G", "M"} <= set(cell), f"{fid}: missing G/M probabilities")
                for model, probability in cell.items():
                    require(isinstance(probability, (int, float)) and not isinstance(probability, bool),
                            f"{fid}/{model}: probability must be numeric")
                    number(probability, f"{fid}/{model}", maximum=1)
        else:
            for cell in data["cells"].values():
                check_advance_cell(cell, fid)
        require(forecast_hash(data) == row["forecast_sha256"], f"{fid}: reveal hash differs from commitment")
        reveals[fid] = data

    for fid, row in latest.items():
        if is_revealed(row["status"]):
            require(fid in reveals, f"{fid}: status says revealed but no reveal is published")

    score_keys = set()
    g_scores = {}
    scores = read_rows(root, prefix + "scores.csv", SCORE_COLUMNS[prefix])
    for row in scores:
        fid, model = row["forecast_id"], row["model"]
        require(fid in by_id, f"{prefix}scores.csv: score has no receipt {fid}")
        require(fid in reveals, f"{fid}: publish a verified reveal before scores")
        if not prefix:
            require(status_kind(latest[fid]["status"]) == "resolved",
                    f"{fid}: scores for an unresolved forecast; append a resolved status line first")
        key = (fid, model)
        require(key not in score_keys, f"{fid}/{model}: duplicate score")
        score_keys.add(key)
        require(counted(row[count_column]) == counted(by_id[fid][count_column]), f"{fid}: inconsistent counted status")
        cells = number(row["cells"], f"{fid}: cells", minimum=1, integer=True)
        require(cells == len(reveals[fid]["cells"]), f"{fid}: score/reveal cell count differs")
        if prefix:
            require(model in {"AB", "A", "CLIM", "PERS", "ZERO"}, f"{fid}: unknown advance model")
            for field in ("crps_km2", "mae_log1p_median"):
                number(row[field], f"{fid}: {field}")
        else:
            require(all(model in cell for cell in reveals[fid]["cells"].values()), f"{fid}: score model absent from reveal")
            positives = number(row["cells_with_gain"], f"{fid}: gains", maximum=cells, integer=True)
            for field in ("brier", "climatology_brier"):
                number(row[field], f"{fid}: {field}", maximum=1)
            number(row["log_loss"], f"{fid}: log_loss")
            if row["auc"]:
                number(row["auc"], f"{fid}: auc", maximum=1)
            number(row["top10_hits"], f"{fid}: top10_hits", maximum=min(10, positives), integer=True)
            if model == "G":
                g_scores[fid] = row

    if not prefix:
        check_baselines(root, by_id, latest, reveals, g_scores)


def check_baselines(root, by_id, latest, reveals, g_scores):
    """baselines.csv (addendum 2 section 5): reference baselines scored beside G, never counted, never in scores.csv."""
    keys = set()
    for row in read_rows(root, "baselines.csv", BASELINE_COLUMNS):
        fid, baseline = row["forecast_id"], row["baseline"]
        require(fid in by_id, f"baselines.csv: baseline has no receipt {fid}")
        require(fid in reveals, f"{fid}: publish a verified reveal before baselines")
        require(status_kind(latest[fid]["status"]) == "resolved",
                f"{fid}: baselines for an unresolved forecast; append a resolved status line first")
        require(fid in g_scores, f"{fid}: publish the G score row before baselines")
        require(baseline in BASELINES, f"{fid}: unknown baseline {baseline}")
        require(HEX_SHA.fullmatch(row["persistence_sha256"]), f"{fid}: invalid persistence_sha256")
        key = (fid, baseline)
        require(key not in keys, f"{fid}/{baseline}: duplicate baseline")
        keys.add(key)
        require(date.fromisoformat(by_id[fid]["issued_for_map_date"]) >= BASELINES_FIRST_ISSUE,
                f"{fid}: baselines begin with the 2026-10-25 issue (addendum 2)")
        require(counted(row["counted_under_rule_v1"]) == counted(by_id[fid]["counted_under_rule_v1"]),
                f"{fid}: inconsistent counted status in baselines")
        cells = number(row["cells"], f"{fid}: baseline cells", minimum=1, integer=True)
        require(cells == len(reveals[fid]["cells"]), f"{fid}: baseline/reveal cell count differs")
        positives = number(row["cells_with_gain"], f"{fid}: baseline gains", maximum=cells, integer=True)
        require(positives == int(g_scores[fid]["cells_with_gain"]), f"{fid}: baseline/G cells_with_gain differs")
        number(row["brier"], f"{fid}: baseline brier", maximum=1)
        number(row["log_loss"], f"{fid}: baseline log_loss")
        if row["auc"]:
            number(row["auc"], f"{fid}: baseline auc", maximum=1)
        number(row["top10_expected_hits"], f"{fid}: top10_expected_hits", maximum=min(10, positives))


def check_history(root, base):
    # Resolve a commit first so --base can never become a Git option or path.
    revision = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "--verify", "--end-of-options", base + "^{commit}"], text=True,
        stderr=subprocess.PIPE,
    ).strip()
    files = subprocess.check_output(["git", "-C", str(root), "ls-tree", "-r", "--name-only", revision], text=True).splitlines()
    for filename in files:
        immutable = filename in RULE_PINS or (filename.startswith(("reveals/", "advance/reveals/")) and filename.endswith(".json"))
        if filename not in TABLES and not immutable:
            continue
        old = subprocess.check_output(["git", "-C", str(root), "show", f"{revision}:{filename}"])
        path = regular_file(root, filename)
        new = path.read_bytes()
        if immutable:
            require(new == old, f"{filename}: published bytes are immutable; publish a new version or erratum")
        else:
            require(new.startswith(old), f"{filename}: existing CSV bytes changed; append only")


def check_integrity(root, base=None):
    root = Path(root)
    for filename, digest in RULE_PINS.items():
        require(hashlib.sha256(regular_file(root, filename).read_bytes()).hexdigest() == digest,
                f"{filename}: approved scoring rule hash changed")
    for prefix in ("", "advance/"):
        check_lane(root, prefix)
    if base:
        check_history(root, base)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="Git base commit for byte-preserving append-only checks")
    args = parser.parse_args()
    try:
        check_integrity(Path(__file__).resolve().parent, args.base)
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError, csv.Error) as exc:
        parser.exit(1, f"Integrity check failed: {exc}\n")
    print("Receipt schemas, reveal hashes and approved scoring-rule pins verified." +
          (" Published history is append-only." if args.base else " Use --base to verify append-only history."))


if __name__ == "__main__":
    main()
