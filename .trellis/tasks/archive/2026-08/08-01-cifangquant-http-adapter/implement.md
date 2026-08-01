# Implementation checklist

1. Add `httpx` to the pipeline dependency baseline and refresh its lockfile.
2. Implement injectable Cifang client with endpoint construction, redacted
   auth, timeout, retry/error mapping, and <=50 symbol chunking.
3. Implement list/historical response mappers and domain validation fixtures.
4. Replace the placeholder adapter with the existing evidence-tuple adapter;
   keep default settings disabled and preserve public compatibility.
5. Add focused MockTransport/fake-clock tests, including secret non-leakage and
   nullable fields.
6. Run focused tests, Ruff, architecture check, and inspect the final diff.

No commit, push, Dagster wiring, migration, or real smoke test belongs to this
task.
