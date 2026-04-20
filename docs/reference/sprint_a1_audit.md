# Sprint A.1 — Sulfur Accounting Audit Report

Branch: `sprint-a1-sulfur-audit`

## Summary

Sprint A landed the sulfur complex (Amine + SRU + TGT + SUP sale point)
but four inconsistencies slipped through review. The audit traces each to
root cause, fixes the real leak, and adds a test that catches the class
of bug instead of the specific symptom.

| # | Symptom | Root cause | Status |
|---|---------|------------|--------|
| 1 | UI margin $1.26M/d vs reported -$130K/d | UI uses `quick_optimize` path with elevated product prices + $10 crude discount; reported number is `run_optimization` with raw Gulf Coast prices, plus `_build_planning_result` drops ~15 objective line items | documented, not a bug |
| 2 | Crude S input 0.9 LT/D on heavy-sour slate | Two bugs: Caps sheet parser missed `('000)` multiplier for sulfur rows; builder used flat LT/bbl constants independent of assay S | fixed |
| 3 | Mass-balance test passed despite leak | Test balanced the LP's internal H2S inventory (phantom), not crude-assay S | replaced |
| 4 | No sulfur lane in UI | Sprint A did emit the lane; was hidden by "Show Utilities" toggle | toggle on |

## Task 1 — Margin reconciliation

Three distinct numbers all come from the same Pyomo model:

- **$1,263,982/d** — UI path (`RefineryService.quick_optimize`) uses an
  elevated price deck (gasoline=95, diesel/jet=100) and a $10/bbl crude
  discount. This is the number on the home screen.
- **-$130,577/d** — `run_optimization` path pulls prices from Gulf Coast
  `prices.csv` (gasoline=82.08, diesel=92.40, ...) and pipes the solution
  through `_build_planning_result`, which re-computes margin from ~7 cost
  terms — **omitting** coke, BTX, H2, sulfur, coker/vacuum/isom/arom
  opex, and internal utility crediting.
- **+$227,384/d** — same `run_optimization` solve, but read via
  `pyo.value(model.objective)`, which reflects the full objective the
  solver actually optimized.

Not a regression. `_build_planning_result`'s margin drift predates Sprint A.
Tracked separately for Sprint B's "result-consistency" audit.

## Task 2 — Sulfur trace diagnostic

`scripts/diagnostics/sulfur_trace.py`:
- (a) Crude slate + per-crude S input
- (b) CDU outlet cut S (which assay rows were actually read)
- (c) HDT H2S per unit (KHT / DHT / GOHT / Scanfiner / Coker NHT / HCU)
- (d) FCC + Coker H2S
- (e) Terminal sinks (SUP sales, stack, amine slip, product-pool S)
- (f) Residual vs crude input

Before-fix (commit `e5b34c3`, Sprint A head):
```
  S_CRUDE_TOTAL         =    337.159 LT/D
  tracked terminal out  =      0.958 LT/D
  RESIDUAL              =   -336.201 LT/D  (-99.72% of crude S)
```

After-fix (commit `359ba40`):
```
  S_CRUDE_TOTAL         =    337.159 LT/D
  tracked terminal out  =    337.159 LT/D
  RESIDUAL              =     -0.000 LT/D  (-0.00% of crude S)
```

## Task 3 — Caps sheet sulfur rows

See `docs/reference/caps_sulfur_rows.md`. Key finding: row 2 of the Caps
sheet declares `('000)` **once**, applying to every subsequent row — BPD,
TPD, MMSCFD, **and LT/D**. Sprint A read `CAMN=3`, `CSRU=3`, `CTGT=0.2`
as raw LT/D when they were actually thousands-of-LT-per-quarter (i.e.
3000 / 3000 / 200 LT/D daily cap).

## Task 4 — The fix

Two files, two independent bugs.

**`src/eurekan/parsers/gulf_coast.py`** — sulfur rows now route through
the same `× 1000` scaling as every other Caps row:

```python
if is_sulfur and max_val is None:
    capacity = _SULFUR_UNIT_DEFAULTS.get(unit_id, 0.0)
    min_tp = 0.0
else:
    capacity = (max_val * 1000.0) if max_val is not None else 0.0
    min_tp = (min_val * 1000.0) if min_val is not None else 0.0
```

`_SULFUR_UNIT_DEFAULTS = {"amine_1": 3000.0, "sru_1": 3000.0, "tgt_1": 200.0}`
is used only when the Caps cell is blank.

**`src/eurekan/optimization/builder.py`** — H2S generation at every
hydrotreater / cracker / coker now uses **library-weighted per-cut S
coefficients**:

```python
cut_s_lt_per_bbl[cut] = sum_over_crudes(
    weight[c] * vol_yield[c, cut] * cut_api_spg_mass[c, cut] * cut_s_wt[c, cut]
) / total_weight
```

Each sulfur-bearing unit's H2S contribution is
`feed_vol × cut_s_lt_per_bbl[feed_cut] × _HT_S_REMOVAL[unit] × 34/32`
with unit removals:

| Unit | Cut | Removal |
|------|-----|---------|
| KHT | kerosene | 0.92 |
| DHT | diesel | 0.95 |
| GOHT | vgo | 0.92 |
| Scanfiner | heavy_naphtha | 0.95 |
| Coker NHT | coker_naphtha | 0.95 |
| HCU | vgo | 0.97 |
| FCC | vgo | 0.30 (liberation, not removal) |
| Coker | vac_resid | 0.20 (to gas) |

A new **`products_s_lt`** variable absorbs the residual S that stays in
finished liquid/solid products (bulk of crude S for this slate), and a
closure constraint enforces:

```python
crude_s_feed == sulfur_sales + s_to_stack + amine_slip_s + products_s_lt
```

## Task 5 — Integrity test

`tests/integration/test_sulfur_vs_crude_assay.py` recomputes crude S
from assay data using constants that have no coupling to builder
internals (`_BBL_M3`, `_WATER_KG_M3`, `_KG_PER_LT`, API→SPG) and
asserts the LP's terminal-sink sum is within 1% of crude input.

Second test guards against a silent regression to flat coefficients by
requiring `model.sulfur_produced >= 10.0 LT/D` on a heavy-sour slate
(pre-fix: 0.9; post-fix: 14.1).

Both tests pass. All 683 pre-existing tests still pass.

## Task 6 — Frontend verification

Live flow graph emission (verified via `RefineryService.quick_optimize`):

```
amine_1         Amine Unit                  46.769 LT/D
sru_1           SRU                         42.483 LT/D
tgt_1           Tail Gas Treatment           1.314 LT/D
sale_sulfur     Sulfur (SUP)                42.483 LT/D

kht_1         -> amine_1      H2S                 1.22 LT/D
dht_1         -> amine_1      H2S                 7.16 LT/D
fcc_1         -> amine_1      H2S                 6.63 LT/D
amine_1       -> sru_1        Conc. H2S          46.53 LT/D
sru_1         -> sale_sulfur  Elemental S        42.48 LT/D
sru_1         -> tgt_1        Tail Gas            1.31 LT/D
tgt_1         -> amine_1      Recycle H2S         1.18 LT/D
```

`modes.py` now computes H2S edge labels with the same assay-driven
formula the LP uses, so UI numbers reconcile with the solved flow.

Sulfur complex shares the UTILITIES swim lane (`layoutEngine.ts`
line 24, h=100). Visibility gated by the "Show Utilities" toggle
in the flowsheet controls.

## Commits on this branch

| SHA | Subject |
|-----|---------|
| `25854e5` | diag(sulfur): audit scaffolding — trace, caps reference, failing S integrity test |
| `359ba40` | fix(units): assay-driven sulfur accounting + caps sheet x1000 scaling |
| `3f7e272` | fix(flowsheet): H2S edge labels use assay-driven coefficients |

## Acceptance

- [x] Margin number reconciled (documented, see Task 1)
- [x] `sulfur_trace.py` before/after captured
- [x] Caps sheet sulfur rows documented
- [x] Crude S residual < 1%: actual 0.00%
- [x] Crude S throughput order 10² LT/D: 337.16 LT/D
- [x] SUP production scales with S accounting: 14.1 LT/D (3000 LT/D cap non-binding)
- [x] Integrity test passes after fix, failed before
- [x] All 683 existing tests pass
- [x] Sulfur lane emits in live flow graph with correct edge magnitudes
