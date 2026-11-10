# Reconciliation Baseline — branch `reconcile`, commit 9775f933

Run from `gusto_pos/backend` with `PYTHONPATH` set to that directory, test DB
reset immediately before via `python tests/reset_test_db.py` (targets
`carevo_test` on `127.0.0.1` only — refuses any other host/db name by its own
guard). Command:

```
python -m pytest --junitxml=docs\reports\baseline_junit.xml
```

Full console output archived at `docs/reports/baseline_junit.xml`.

## Counts

| tests | failures | errors | skipped |
|---|---|---|---|
| 1279 | 0 | 0 | 1 |

Matches the expected `1279 / 0 / 0 / 1` exactly.

## The one skipped test

`tests/test_api_legacy_route_auth.py` —
`test_guarded_route_accepts_staff[GET /api/v1/customers/]`

It is an `xfail` (pytest reports `xfail` as `<skipped type="pytest.xfail">`
in JUnit XML, which is why the raw pytest summary line reads
`1278 passed, 1 xfailed` while the JUnit counts read `tests=1279 skipped=1`
— both describe the same single test).

Reason, verbatim from the JUnit `message` attribute: **"pre-existing:
CustomerResponse requires name/phone_number, model allows null (migration
008)"** — migration 008 made `customers.name` / `customers.phone_number`
nullable (Google-identity customers can have neither), but the
`CustomerResponse` Pydantic schema still requires both, so this one legacy
route's response-model validation is a known, pre-existing mismatch
unrelated to payments/reconciliation.

Status: **DONE**
