# ARGUS advance receipts

This is a second public, append-only record next to the weekly gain/no-gain forecast in this repository. It forecasts **how much ground** Russian forces gain in each 20 km front cell over the next 7 days.

## What is forecast
- **Quantity.** km² of Russian territorial gain per cell between two DeepStateMap front-line maps 7 days apart.
- **Cells.** The same cells as that week's main forecast.
- **Output.** The forecast is a full range of 19 quantiles.
- **Primary model.** AB, a hurdle model blended with each cell's recent climatology.
- **Baselines.** Climatology (CLIM) and persistence ("same as last week", PERS) are sealed under the same hash.

## The rule
- **Rule file.** `SCORING-RULE-ADVANCE-v1.md`, sha256 `2e78412f4176f1f7defcfc4b198b8c9e8d93559daf3886d89f42cc8d4404e320`, approved 2026-10-12 before any advance forecast was issued.
- **Score.** Grid CRPS in km².
- **Verdict.** It is given after 26 counted weeks. A skill claim needs AB to beat both climatology and persistence, with a week-blocked bootstrap 95% interval entirely above zero.
- **Counting.** The first counted issue is 2026-10-25. Each week counts only if a confirmer other than the operator confirms it before the outcome map exists.
- **Not evidence of skill yet.** Research model; 2 advance weeks counted; not evidence of skill (mdo-front-adv-2026-10-25 and mdo-front-adv-2026-11-01, scored on the 2026-11-01 and 2026-11-08 maps). The rule's test runs after 26 counted weeks.

## Honest expectation, stated up front
On past weeks, which are exposed history and not blind, AB beat climatology over the full 87-week backtest. Over the 40 weeks of 2026 it did **not** clearly beat climatology. In the current conditions the rule's chance of finding skill is close to zero. Across the full backtest it is about 76%.
- If the 2026 pattern holds, this page will report **no demonstrated skill**, and that result will stay here.
- AB clearly beats "same as last week" in every period tested.

## Layout
- **`receipts.csv`.** Each forecast's hash, published when the forecast is issued.
- **`reveals/`.** Per-cell quantiles, revealed after resolution. Check them with `../verify.py`.
- **`scores.csv`.** Scores, appended after resolution.

As in the rest of this repository, nothing is edited or deleted, and no DeepStateMap data is published here, only hashes, our own forecasts and scores.

Front-line data: DeepStateMap (deepstatemap.live), used with attribution.
