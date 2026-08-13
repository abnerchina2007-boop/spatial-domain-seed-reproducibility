# Iso-accuracy analysis

Iso-accuracy is implemented in the platform-specific core analyzers referenced
from `scripts/reproducibility/README.md`. It is not a separate algorithm copy.
The primary threshold is `|Δ reference ARI| ≤ 0.02`; 0.01 and 0.03 are frozen
sensitivity thresholds.

