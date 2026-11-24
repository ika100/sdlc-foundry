# Measurement plan — 211 (AC-211.10)

**Run:** journey 23, the first journey on the first release that carries spec 211.

**Measure:** `cplat platform runs journey measure --steps`, then the sum over the unit sessions per journey step, for the steps journey 23 and journey 22 share.

**Baseline:** journey 22: 18 unit sessions, about 21 M tokens, 9 to 36 model calls each.

**Thresholds** (journey 23 against journey 22, on those per-step sums):

- model calls at least 25 % lower;
- tokens at least 10 % lower;
- escalations, failed verifications and failed test reviews each no more than in journey 22.

**Noise:** run-to-run noise is about 30 %. A token result between -10 % and +10 % is measured on a second journey, and the mean of the two counts.

**Record:** both journey rows and the per-step comparison with journey 22 go in docs/PERFORMANCE.md.
