# Contributing

This repository is a frozen manuscript-submission snapshot. Corrections that
affect scientific parameters, thresholds, seeds, preprocessing, clustering,
marker definitions, rankings, or consensus construction must not be merged
into the `v1.0.0` record. Open an issue describing such a proposal and its
expected impact instead.

Documentation, portability, and validation improvements are welcome when they
preserve the frozen numerical outputs. Please run:

```bash
python scripts/validation/validate_release.py
python scripts/validation/security_scan.py
```

Do not commit raw datasets, predictions, checkpoints, logs, credentials, or
vendored copies of third-party method implementations.

