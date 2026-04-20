# Gulf Coast `Caps` sheet — sulfur complex and sour-gas-bearing capacity rows

Source: `data/gulf_coast/Gulf_Coast.xlsx`, sheet **`Caps`**.

## Header / units normalization

The Caps sheet header states its normalization basis **once** on row 2, applying
to every row below:

| r | col A | col B |
| - | ----- | ----- |
| 1 | `*  TABLE` | `CAPS` |
| 2 | `*` | `Process Capacities ('000)` |
| 3 |  | `TEXT \| MIN \| MAX \| REPORT \| ***` |

**Every numeric value in the MIN and MAX columns is multiplied by 1000 to
recover the stated engineering unit.** The engineering unit is embedded
inline in the row's TEXT cell (e.g. `"Naph Hydrotrt   BPD"` → unit is BPD,
stored value 60 means 60,000 BPD).

## Sulfur complex rows (verbatim)

| row | PIMS tag | TEXT cell | MIN | MAX | engineering unit | engineering value |
| --- | -------- | --------- | --- | --- | ---------------- | ----------------- |
| 50  | `CAMN`   | `Amine Unit     LT/D`   | —   | 3   | LT/D H2S inlet   | **3,000 LT/D**     |
| 51  | `CSRU`   | `Sulfur Plt     LT/D`   | —   | 3   | LT/D H2S inlet   | **3,000 LT/D**     |
| 52  | `CTGT`   | `Tail Gas Trt   LT/D`   | —   | 0.2 | LT/D S inlet     | **200 LT/D**       |

## Sour-gas-bearing process capacity rows

These process units liberate H2S from feed-S content, so their capacities
bound upstream S throughput.

| row | PIMS tag | TEXT cell | MIN | MAX | engineering unit | engineering value |
| --- | -------- | --------- | --- | --- | ---------------- | ----------------- |
| 17  | `CNHT`   | `Naph Hydrotrt   BPD`  | —   | 60   | BPD | 60,000 BPD |
| 23  | `CKHT`   | `Kero Hydrotrt   BPD`  | 0   | 30   | BPD | 30,000 BPD |
| 24  | `CHYK`   | `KHTU H2`              | 0   | —    | MMSCFD H2 (inferred) | — |
| 25  | `CDHT`   | `Dist Hydrotrt   BPD`  | 0.5 | 30   | BPD | 500 / 30,000 BPD |
| 26  | `CHYD`   | `DHTU H2`              | 0   | —    | MMSCFD H2 (inferred) | — |
| 27  | `CGHT`   | `GO Hydrotreater BPD`  | —   | 60   | BPD | 60,000 BPD |
| 28  | `CHYV`   | `GO HDT H2, MMSCFD`    | 0   | —    | MMSCFD H2 | 0 lower bound |
| 32  | `CCCU`   | `Cat Cracker     BPD`  | 18  | 60   | BPD | 18,000 / 60,000 BPD |
| 33  | `CCRB`   | `Carbon Burnt    TPD`  | 0   | 1    | TPD coke | 1,000 TPD |
| 34  | `CFGU`   | `FCC Fuel Gas    KSCF` | 0   | —    | KSCF/D fuel gas | 0 lower bound |
| 35  | `CSLU`   | `Slurry Pump Limit BPD`| 0   | —    | BPD | — |
| 36  | `CRSD`   | `FCC Resid Rate  BPD`  | 0   | —    | BPD | — |
| 37  | `CHCU`   | `Hydrocrack Dist BPD`  | 5   | 20   | BPD | 5,000 / 20,000 BPD |
| 38  | `CHYC`   | `HCU Hydrogen, MMSCFD` | 0   | —    | MMSCFD H2 | — |
| 39  | `CDLC`   | `Delayed Coker   BPD`  | 0   | 50   | BPD | 0 / 50,000 BPD |
| 40  | `CDCK`   | `Coke Drum Limit, MTD` | 0   | —    | MTD coke | 0 lower bound |
| 48  | `CGTU`   | `Scanfiner       BPD`  | 5   | 25   | BPD | 5,000 / 25,000 BPD |

## Ambiguity flag

- The header row is the **only** place that declares the `('000)` multiplier.
  There is no per-row footnote, and the unit string embedded in each TEXT
  cell (e.g. `"LT/D"`) does **not** itself carry the multiplier — it is the
  final engineering unit, to be combined with the ×1000 from the header.
- Sprint A incorrectly treated the three sulfur rows (`CAMN`, `CSRU`, `CTGT`)
  as already in engineering units (not `'000`), producing 3 LT/D / 3 LT/D /
  0.2 LT/D instead of 3,000 / 3,000 / 200 LT/D. Sprint A.1 corrects this.
- World-scale SRUs run 500–2,500 LT/D sulfur, so a 3,000 LT/D inlet amine
  + 3,000 LT/D Claus sulfur plant is plausible for a large integrated Gulf
  Coast refinery. A 3 LT/D unit is hobby-scale and would not merit its
  own pump.
