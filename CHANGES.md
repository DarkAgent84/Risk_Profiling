# Risk profiling accuracy upgrade

Drop each bank folder's contents over the matching folder in the repo
(FEDBANK/ -> FEDBANK/, SBFC/ -> SBFC/), and the root .gitignore over the repo's.

## Measured result (Fedbank, same `python main.py evaluate`)
| | Agreement with legacy SOA Risk Type |
|---|---|
| Original code | 60.5% |
| New code, calibrated | 70.8% (in-sample) |
| New code, held-out 30% of loans (calibrator, excludes "3 MOB" labels) | 73.0% |

Per tier: High precision 78% / recall 79%; Low 75% / 86%; **Medium 39% / 18%** (still weak).
Ceiling check: a gradient-boosting model on the same columns reaches ~81%, so rules still have headroom.

## What changed
- scoring.py: severity is monotonic by bucket/DPD (current < 1-29 < 30-59 < 60-89 < 90+); fixes current loans with a small charge scoring High.
  Adds a bounce-evidence term (collector assigned, charges_2/3/payable). These were the strongest separators of the legacy labels. Duplicate SOA loans dropped. Vectorised. All numbers overridable via `calibrated_params.json`.
- bounce.py: SOA `risk_type` removed from bounce evidence (it was circular against evaluation); "Always Bounced" needs >= 2 receipts.
- matured.py: "still owing" uses overdue_dues, not gross total_dues.
- report.py: unlabeled loans no longer counted as "Low" in accuracy; adds per-tier precision/recall.
- calibrate.py: tunes parameters to the legacy label, 70/30 held-out report. `python calibrate.py --apply` rewrites calibrated_params.json.
- requirements.txt: adds python-dotenv (config.py imports it unconditionally).

## Read before relying on this
1. **The legacy label tracks bounce history, not DPD.** 90% of "Never Bounce" loans are Low and 84% of "Matured" loans are Low, even though most Matured loans are 90+ DPD. Higher agreement therefore means "closer to the bank's old label", not necessarily "better at predicting default". Validate against roll-forward/recovery outcomes if you can.
2. **NPA stays High by policy.** Letting the calibrator demote NPA loans scores 0.6 pt higher but puts 90+ DPD loans in Medium/Low. Use `calibrate.py --allow-npa-downgrade` only if the bank agrees.
3. **SBFC cannot be calibrated.** Its customer file has no Risk Type column (and no charges_2/3). SBFC ships a conservative parameter set that keeps the original bucket-based tiering (1-29 Medium, 30+ High). Supply any labelled outcome and run calibrate.py there.
4. **Fedbank has 768 loans with no label and 1,467 labelled "3 MOB"** (not a tier). `evaluate` counts the latter as mismatches; the calibrator excludes them.
5. **Customer data is committed to a public GitHub repo** (names, mobiles, emails, addresses in data/raw and data/processed, plus SQL dumps). The updated .gitignore only stops future commits. Make the repo private now, then purge history (git filter-repo/BFG) and treat the data as exposed.

## Not changed (found while testing)
- Fedbank dates are ISO, so `format="mixed"` is fine there; SBFC already uses dayfirst=True. My earlier date-parsing concern applies only to db.py.
- Remaining items from the first review (db-score/evaluate filenames, stale load_tables.sql, sql_parser import-time execution, URL building in db.py) are untouched.
