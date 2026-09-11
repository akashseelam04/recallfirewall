# Task gateway — first AC-07 implementation

The gateway owns Hotdata CLI access and selects a fixed database from a trusted
startup binding. An expiring bearer capability authenticates one task. The
stored binding contains only its SHA-256 digest; generate capabilities with
`secrets.token_urlsafe(32)` and deliver each only to its assigned worker.

Exposed routes:

- `POST /v1/tasks/{task_id}/consumption`, with only `{"ingredient_id":"ING-041"}`.
- `GET /v1/tasks/{task_id}/receipts/{receipt_id}` for that task's gateway receipts.
- `POST /v1/tasks/{task_id}/mcp` for stateless MCP initialize/discovery and the
  `consumption` / `get_receipt` tools, with the same task capability.

Use `Authorization: Bearer <task capability>` and `Content-Type: application/json`.
No database/SQL/proxy/admin interface is exposed. Unknown operation arguments, query parameters, scope-selection headers,
duplicate JSON keys and duplicate authorization headers are rejected. Normal
proxy/MCP headers are ignored and grant no authority. No incoming headers are forwarded to Hotdata. The CLI
receives the workspace and database from the server binding as separate argv
entries. Ingredient IDs have a narrow grammar because CLI parameter binding
has not been demonstrated. This read lists fixture consumption records; it is
not the completed-event validation or facility-reconciliation contract.

Install `gateway/requirements.txt` in Python 3.12; the trusted gateway host also
needs authenticated Hotdata CLI 0.33.0. The existing project venv has these
Python versions. Run `python -m probes.setup_demo` to create the private
`.demo/session.json` configuration. The startup factory validates that its
binding and journal paths remain inside `.demo`, then run:

```sh
.venv/bin/uvicorn gateway.app:from_config --factory --host 127.0.0.1 --port 8787
```

Bindings must be created by the trusted provisioner, never by agent input.
Each includes task, incident, facility, scope revision, input epoch, workspace,
database, catalog, source manifest hash, token hash and expiry (Unix seconds).
Role defaults to `facility_investigator`; committed knowledge revision defaults
to zero for the existing probe. Bindings are immutable. Restarting with the
same configuration neither rebinds tasks nor clears persisted revocations.
The current factory does not provision or seal a database. No binding file or
capability is committed by the live probe.

Executed checks:

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m probes.gateway_isolation
```

Unit tests use explicitly marked mocks and cannot satisfy sponsor gates. The
live probe uses real Hotdata through HTTP requests to the in-process ASGI app,
checks both facility results, observes overlapping caller intervals, and tests
32 override attempts. It writes a credential-free report under `probes/results`.
The report records actual SQL, task/workspace/database IDs, native query run IDs,
gateway receipt IDs, result hashes and decimal strings.

## Persistent control state

`gateway/store.py` journals task bindings, incident input state, active tasks and
receipts. SQLite holds control state and copies of sponsor receipts; Hotdata
still performs the analysis. The live probe reopens the journal, reads the actual
Hotdata rows/native query ID, and checks stale-query and revoked-receipt denial.
A unit test also reads a persisted receipt from a separate Python process.

Trusted application code calls `register`, `revoke`, `invalidate_inputs` and
`publish_inputs`; none is an agent HTTP endpoint. Changing incident inputs marks
them `DIRTY` and advances the epoch. Publication is conditional on that epoch.
Replacing one facility's active task leaves other facility tasks untouched.

Before a query, obsolete/unpublished tasks receive HTTP 409. At receipt insertion,
freshness is rechecked in the same SQLite transaction: late results are retained
with `status=STALE` and `admission_status=STALE`. Receipt reads also return
`current_status` so a previously current result is visibly historical after an
update. Revoked/expired credentials cannot retrieve receipts or receive a result
from a query started before revocation. These checks do not authorize a plan or
substitute for the future transactional approval/action guard.

## Remaining before acceptance

- Deploy and test workers without the gateway's credentials, session file, home,
  filesystem or shell access. An in-process HTTP client does not prove this.
- Provision a fresh database per logical task and enforce immutable inputs.
  A local CSV hash is an input manifest, not a verified vendor snapshot.
- Force pagination, retain complete native receipts, and prove stable retrieval.
- Add request/concurrency budgets and durable failed-call receipts. Direct
  `create_app` without a store uses a temporary in-memory journal for probes/tests;
  the service factory uses the private demo session's persistent journal.
- Wire actual source deduplication, conflicts and approval invalidation into
  input acceptance. The current epoch API assumes a trusted caller has accepted
  new input; it does not implement the complete ingestion/approval transaction.
- Cloud MCP calls and a fixed Cloud branching procedure have now executed
  successfully through an explicitly approved tunnel. See the recorded
  `rocketride_gateway.json` and `rocketride_dispatch_positive.json` receipts.
  The LLM investigator remains incomplete after returning tool failures.

Every current result is `INCOMPLETE`, with `coverage.complete=false` and no
claimed vendor snapshot. Delivery metadata is separate. Existing input import
precision is unproven; decimal-string output cannot repair lossy ingestion.
RocketRide orchestration, Cognee/HydraDB claim validation, Rote replay, and
operational approvals are not implemented by this gateway.
