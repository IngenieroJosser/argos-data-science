# M5.41 dtype-safe explainability fix

This project snapshot contains the repair for the Pandas 3.x `LossySetitemError`
raised by local sensitivity in notebook 41.

Run order after applying this snapshot:

1. Keep the successful notebook 40 outputs.
2. Restart the Jupyter kernel.
3. Run `41_explainability.ipynb` from the first cell.
4. Confirm `implementation: m5-41-permutation-local-sensitivity-v2`.
5. Continue to 42 only if notebook 41 finishes with PASS.

See `docs/decisions/M5_41_DTYPE_SAFE_LOCAL_SENSITIVITY_2026-09-23.md`.
