# Scoring rule v1, addendum 2: a persistence reference baseline

Status: PRE-REGISTRATION DRAFT, written 2026-10-25, after `mdo-front-2026-10-25` was issued and before its resolution map (2026-11-01) exists. It takes effect when the owner approves this file's sha256 in writing. Author: Claude (program owner by delegation). Linear: ARG-1431.

Rule v1 (`MDO-FRONT-PUBLIC-SCORING-RULE-v1.md`, sha256 `49f3dffb…9dbb`) scores G only against climatology. Climatology gives every cell the same probability, so it is easy to improve on. The obvious harder question is whether G does better than "the front moves where it moved last week". This addendum fixes that baseline, its scores and a secondary test **before the outcomes it will be tested on are known.**

## 1. What changes, and what does not
- **Unchanged:**
  - G is the primary model;
  - the event, cells, horizon and scores in rule v1 §1 to §3;
  - the rule v1 §4 success test against climatology and its method in addendum 1 (sha256 `c5949b41…a943`);
  - the counted-week definition in rule v1 §2.
- **Added:**
  - a reference baseline, PERS (§2), scored every week beside G;
  - a secondary test of G against PERS (§4);
  - a publication route (§5).
- **Not a new version.** PERS is a reference baseline, not a change to G's features, model form, cells or event (rule v1 §2). The rule v1 week count does not restart. Addendum 1 is the precedent for a non-restarting addendum.
- **The secondary result never replaces or qualifies the rule v1 verdict.** It is reported beside it.

## 2. The baseline (PERS), fully specified
For a forecast issued on DSM map day d0, with cells taken from that forecast's `cells`:

1. **Last week's state.** A cell is in state **gain** if its Russian gain between the map on or before d0 − 7 days and the d0 map is at least `GAIN_FLOOR` (0.05 km²). Otherwise it is in state **no_gain**. The gain is computed with `mdo_front_forecast.cell_gains`, the function the resolution uses.
2. **Historical rates.** Use the 52 weekly windows w = 1 … 52 before d0, with anchors chosen nearest-day-on-or-before:
   - a2 = map(d0 − 7(w+1)), a1 = map(d0 − 7w), a0 = map(d0 − 7(w−1));
   - skip a window if any two of its anchors coincide.
   - Within each window, take the contact cells on the a1 map (frontage ≥ 1 km, the forecast's own rule). Classify each cell by its gain from a2 to a1, then count whether it gained at least `GAIN_FLOOR` from a1 to a0.
   - The **gain** rate is k_gain / n_gain. The **no_gain** rate pools every other cell, whether or not a neighbour gained: k_no_gain / n_no_gain.
   - The last window ends exactly on d0. No map after d0 is read.
3. **Prediction.** Each cell gets the rate for its state. There are exactly two probability values per week.

**Scores**, against the same outcome labels as `mdo_front_forecast.do_resolve`:
- Brier, log loss (clipped to [1e-6, 1 − 1e-6]) and AUC, as in rule v1 §3. AUC treats tied probabilities as scikit-learn's `roc_auc_score` does: each tied positive-negative pair counts one half.
- **Top-10 hits are scored as expected hits under uniformly random tie-breaking,** because PERS has only two values and many cells tie at tenth place. Count the positives strictly above the tenth-place value. Add the positives tied at that value, times the open top-10 slots, divided by the number of tied cells. This is new; G's top-10 rule is unchanged.

**Reference implementation:** `etl/ace/mdo_front_persistence.py` (`issue`, `resolve`, `verdict`).

**Known-answer requirement:** this implementation, and any later one, must reproduce the PERS column of the §6 table exactly from the cycle's daily DSM maps.

**Recompute rule.** PERS reads no map after d0, so `resolve` always recomputes it from the maps. It refuses if a sealed file fails its own `persistence_sha256`, or differs from the recomputed calibration and cells. The scores are always those of the recomputed baseline.

## 3. Sealing and timing
- **Sealing.** Each week, PERS is computed after the v1 forecast is issued, and its file `<forecast_id>.persistence.json` is committed write-once. PERS uses only maps on or before d0, so it can be computed any time before resolution. It is sealed anyway, so that nobody can say it was tuned after the outcome.
- **What the file records:**
  - `persistence_sha256`, over the forecast id and hash, `baseline`, `method_ref`, the dates, the calibration and the cells;
  - outside the hash, for information: `resolution_map_available_at_issue`, `computed_utc`.
- **Seal check, in code.** `resolve` finds the commit that first added the file (`git log --diff-filter=A`, as rule v1 `confirm` does) and records it. `sealed_before_resolution` is true only if that commit is before 03:00 UTC on the resolution map date and the file records `resolution_map_available_at_issue: false`.
- **Resolution.** `resolve` writes `<forecast_id>.persistence-resolution.json` write-once.
- **The seal never decides whether a week counts** (§4). It shows that the baseline was fixed before the outcome; the recompute rule (§2) shows that it was not changed.
- **10-25.** `mdo-front-2026-10-25.persistence.json` was first added in commit `c2de9ee025a472cd3499c162f99a90f3537132b5` (2026-10-25T21:07:56Z), pushed to `origin/claude/ARG-1431-persistence-baseline-addendum-2`. **This PR is merged with a merge commit, never squash or rebase,** so that commit stays in main's history as the file's first-added commit:
  - persistence_sha256 `bd2d81fc1121405b324c40b60cd859549c87fa16522b43fd187f552413ece354`;
  - file sha256 `08ea451c5110a0de206f696e8fe0ed022f3219fafa195f0a75d35b99ef98de76`;
  - 52 windows; gain rate 0.5278 (256 of 485); no_gain rate 0.0246 (210 of 8,529); 5 of 177 cells in state gain;
  - computed with the 2026-11-01 map absent.
- **When the series starts, and why it cannot restart.** The series starts with the 10-25 week (`FIRST_ISSUE`). The method is fixed by `calibration()` and `predict()` in the reference implementation, and it was committed before the 10-25 outcome existed, so approval timing does not move the start.
- **A method change needs a new owner-approved addendum.** That addendum starts a separate series. The weeks before the change keep their persistence resolutions, and they are reported beside any later verdict, never deleted or replaced. This addendum's series and verdict stand as written.

## 4. Secondary test (decided now, applied later)
- **Weeks:** the first 8 forecasts issued on or after **2026-10-25** (`FIRST_ISSUE`) that count under rule v1. **The weeks 10-02, 10-11 and 10-18 are excluded**, because the baseline was chosen after their outcomes were known (§6).
- **No week is left out.** The list is built from the rule v1 resolutions, not from the persistence files. Every such week is included whether or not its seal check passed. If a week has no persistence resolution, the verdict refuses until one is written. The number of sealed weeks is published with the verdict.
- **Per-week statistic:** d_w = PERS Brier − G Brier, as recorded.
- **Bootstrap:** the method of addendum 1 §1 exactly (seed 20261012, 2,000 replicates of 8 week indices, `numpy.percentile` at 2.5 and 97.5).
- **Verdict wording:**
  - "skill over persistence demonstrated (addendum 2, secondary)" if mean(d) > 0 and the lower bound is > 0;
  - otherwise "no demonstrated skill over persistence (addendum 2, secondary)".
  - Either result is published in the same place and format.
- **Earliest verdict:** the 8th qualifying week is issued 2026-12-13 and resolves on the 2026-12-20 map, if no week is missed. The rule v1 verdict comes earlier, on the 2026-12-06 map.
- **Before 8 weeks:** "N persistence weeks; not evidence of skill".

## 5. Publication
- **Not published:** per-cell PERS values. They amount to last week's gain map, which public cards withhold (`PUBLIC-POSTING-GUARDRAILS.md` §2).
- **Published once implemented,** per resolved week: `forecast_id`, `persistence_sha256`, and the PERS Brier, log loss, AUC and expected top-10 hits. They go in a new receipts file, `baselines.csv`, never in `scores.csv`. `scores.csv` stays G-only with its header unchanged (owner ruling 2026-10-13), because every scored model there must be in the reveal, and PERS is not part of the sealed forecast.
- **The card gains one fixed-template sentence:** "Same-as-last-week baseline: Brier <x>." It goes through the existing banned-content filter.
- **Implementation is a separate change, in this order:**
  1. receipts `check_integrity.py` **and** the Battle-DB mirror `etl/ace/mdo_front_receipts.py`, in the same change, with tests. The 2026-10-25 NO-GO came from the mirror lagging behind the receipts check;
  2. a `mdo_front_shadow_report` row generator for `baselines.csv`;
  3. the card sentence and its guardrail tests;
  4. runbook steps (issue: after step 7; resolve: after step 3).
- **Until then, PERS stays internal.** Nothing about PERS is posted.

## 6. Computed after the outcomes (2026-10-25; not counted)
Before writing this addendum, Claude tried four "same as last week" variants on the three resolved weeks, with `etl/ace/mdo_front_persistence_posthoc.py` (sha256 `182abdac…f078`, frozen as run apart from one docstring line). Its output is `mdo-front-persistence-posthoc-2026-10-25.json` (sha256 `8cac1447…e1c3`). Every number below comes from that file:
- **PERS_HARD:** probability 1 if the cell gained last week, else 0;
- **PERS (§2):** the calibrated two-state version;
- **PERS_NBR:** PERS with a third state, "only a neighbour gained";
- **PERS_RANK:** a ranking only, by own 1-week gain, then own 4-week gain, then neighbours' gain.

These numbers were seen before the baseline was chosen. That is why §4 excludes these weeks.

| Week | Status | Positives | G Brier | M Brier | Climatology | PERS_HARD | **PERS** | PERS_NBR | G AUC | PERS AUC | PERS_RANK AUC | G top-10 | PERS top-10 (expected) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10-02 | research | 4 | 0.0214 | 0.0179 | 0.0239 | 0.0284 | **0.0186** | 0.0202 | 0.916 | 0.741 | 0.718 | 2 | 2.06 |
| 10-11 | counted | 6 | 0.0233 | 0.0232 | 0.0338 | 0.0398 | **0.0295** | 0.0310 | 0.954 | 0.658 | 0.804 | 4 | 2.12 |
| 10-18 | counted | 5 | 0.0165 | 0.0162 | 0.0287 | 0.0395 | **0.0231** | 0.0230 | 0.963 | 0.785 | 0.880 | 4 | 3.02 |

Exact PERS Brier values: 0.01864189549495063, 0.029517504062614653, 0.02309298009786585.

- **In 10-02, PERS had a lower Brier than G** (0.0186 against 0.0214), and M was lower than both.
- **In the two counted weeks,** G's Brier was lower than every variant. Its AUC was also higher than every variant's: PERS_HARD ranks cells exactly as PERS does, so it has the same AUC, and PERS_NBR's AUC was 0.727, 0.640 and 0.870.
- About half of the positive cells had no gain the week before (2 of 4, 4 of 6, 2 of 5).

## 7. Why this baseline
- **PERS_HARD is a straw man.** Its Brier was worse than climatology in all three weeks.
- **PERS is the strongest simple probabilistic version.** Its Brier was lowest among the variants in 2 of 3 weeks. In 10-18 it was within 0.0001 of the best (PERS_NBR).
- **It needs no fitting beyond two counts.**
- **PERS_RANK cannot be scored by Brier.**
- The advance lane's PERS (`MDO-FRONT-ADVANCE-SCORING-RULE-v1.md`) is a point mass on a different target, and that lane is unchanged.
- **Choosing the strongest candidate is deliberate.** A secondary test against a weak baseline would say little.

## 8. Limits
- PERS has two values per week, so its AUC and top-10 measure a coarse ranking.
- The calibration window spans 52 weeks of a changing front. The rates move slowly, and they are recorded every week.
- Eight weeks is a small, autocorrelated sample. The test is a minimum, not a guarantee of power.
- Same source limits as rule v1 §6.
