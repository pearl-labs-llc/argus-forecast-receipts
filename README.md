# ARGUS forecast receipts

A public, append-only record of ARGUS's weekly forecasts of the Ukraine front line. Each record is committed **before** the outcome is known and scored **after**, under a rule written in advance.

## What is forecast
- **Question.** For each 20 km cell along the front, the probability that Russian forces gain any ground (at least 0.05 km²) in the next 7 days, as shown on the DeepStateMap (DSM) front-line map.
- **Size.** About 176 cells per week.
- **Models.** G (ground state only) is the pre-registered primary model. M (ground state plus event reports) is a secondary model.

## How a week works
1. **Issue.** A forecast is issued from one DSM map date. Its sha256 hash is published in `receipts.csv` as soon as it is issued.
2. **Confirm.** A confirmer other than the operator confirms, before the outcome map exists, that the forecast was committed in time. Today the operator and the confirmer are separate automated agents run by ARGUS. This is separation of duties, not third-party audit.
3. **Reveal and score.** Seven days later, against the next DSM map:
   - the per-cell probabilities are revealed in `reveals/`, so anyone can recompute the hash with `verify.py`;
   - the scores are added to `scores.csv`.
4. **Nothing is edited or deleted.** Misses stay. Missed weeks are recorded as missed.

## The rule
- `SCORING-RULE-v1.md`, sha256 `49f3dffb2d502a04a6297bb5a1bfcf98cd29199d8f1f8790be6b7d775e119dbb`, approved 2026-10-12 before the first counted forecast resolved.
- **Skill claim.** After 8 independently confirmed weeks, ARGUS claims skill for G only if G beats climatology in Brier score with a week-blocked bootstrap 95% interval entirely above zero.
- **Otherwise** this page will say there is no demonstrated skill.

## Advance forecast (second record)
From 2026-10-25 a separate, pre-registered forecast of how much ground (km² per cell) is gained each week runs in `advance/`. It has its own rule (sha256 `2e78412f…e320`) and its own receipts. Its honest expectation is stated up front in `advance/README.md`.

## What this is not
- **Not evidence of skill yet.** 1 week counted; not evidence of skill (mdo-front-2026-10-11, scored on the 2026-10-18 map). The rule's test runs after 8 counted weeks.
  - The first row (2026-10-02) was issued before an independent confirmer existed, so it never counts.
  - Single weeks are not evidence.
- **A research model.** It is not calibrated against any public benchmark and is not an operational product.
- **Inputs are not published.** No DSM or event-report data appear here, only hashes, per-cell probabilities and scores.
- **Disclosure.** The 2026-10-11 hash was first published here on 2026-10-12, one day after issue. Its earlier commitment is a private git commit (2026-10-11T16:21:14Z) and the separate confirmer's record. From now on, each hash is published here when it is issued.

Pearl Labs LLC · ARGUS.

## Verify the public record

Before publishing, run `python3 check_integrity.py --base origin/main` and
`python3 -m unittest discover -s tests -p 'test_*.py'`. These use only Python's
standard library and Git; they do not fetch source data, run models or rescore
forecasts. Fetch `origin/main` first if your checkout is behind.

The integrity check preserves the exact published CSV prefix and reveal bytes,
verifies reveal hashes against receipts, validates table schemas and numeric
ranges, and pins the three approved scoring-rule artifacts, including the
documented editing artifact in rule v1. Corrections belong in a new version or
an erratum; do not rewrite an existing receipt, score, reveal or approved rule.
This validates publication integrity, not the truth of outcomes or the
independence of confirmations.

The `receipt-integrity` pull-request status uses one standard Linux runner with
a two-minute timeout, cancels superseded runs and skips validators for unrelated
paths. There are no scheduled or post-merge runs, dependency installs, database
services or model jobs. Public-repository standard GitHub-hosted runners have no
Actions minute charge. The workflow runs on every PR so requiring this status
does not leave documentation-only PRs waiting on a path-filtered check.

## Errata
- **2026-10-12, `SCORING-RULE-v1.md`.** The file's last two lines (`EOF` and a `cd … shasum` shell command) are an editing artifact from when the file was written. They are not part of the rule.
  - The file is kept byte-for-byte as approved and published, so its sha256 `49f3dffb…9dbb` stays verifiable.
  - The rule is everything above those two lines.
- **2026-10-12, proposed `SCORING-RULE-v1-ADDENDUM-1.md`** (sha256 `c5949b414c08934d709b28621f67b640ed7782a4e088a784eca9692cd1e0a943`).
  - **What it does:** pins the bootstrap method that rule v1 §4 left unspecified: the random generator, the resampling and the percentile method. No decision threshold changes.
  - **Timing:** published before the first counted week resolves on 2026-10-18.
  - **Status:** proposed, pending owner approval.
  - **Approved by the owner on 2026-10-12, before any counted week resolved.** It is in force with rule v1.
