# Recall Firewall

A hackathon prototype for investigating uncertain material links, querying scoped
facility records, and verifying protective actions in a fictional warehouse.

The read-only UI replays **executed sponsor receipts**. Its animated chapters make
no live calls and cannot approve holds, change shipments, or invoke sponsor APIs.
It combines recorded executions; it does not pretend to be one live run.

## Run the UI

No credentials, npm install, or build step is needed:

```sh
python3 -m http.server 8791 --bind 127.0.0.1 --directory demo
```

Open **http://127.0.0.1:8791/**. Click **Next step** to move through the story.
Open `/presentation.html` for the presentation; arrow keys navigate chapters.
The [video walkthrough](demo/VIDEO_WALKTHROUGH.md) provides a two-minute script.
`vercel.json` deploys only `demo/`, even though this repository includes the full
backend, integrations, tests and fixtures.

## Five sponsor contributions

| Sponsor | Executed contribution | Evidence |
|---|---|---|
| Cognee | Ingested a fictional planning note and extracted three proposed lot links. | `probes/results/graph_bridge.json` |
| HydraDB | Stored source-linked proposals and recovered them from a separate reader process. | Same graph receipt; source pointers and native request IDs. |
| Hotdata | Queried two facility databases through a task-bound gateway. | `probes/results/rocketride_dispatch_positive.json` |
| RocketRide | Ran a reviewed procedure in Cloud: read PLANT-A, inspect proposals, conditionally query PLANT-B, verify receipts. | Positive dispatch plus the no-records branch in `rocketride_dispatch.json`. |
| Rote | Captured a query and dependent receipt read-back; replayed on three facility/ingredient combinations. | `probes/results/rote_facility.json` |

The working investigation recording uses **deterministic Cloud orchestration**.
The replacement LLM key passed a separate model check. The attempted LLM-led
investigation returned tool errors and no analytical receipts; it is not used as
evidence of a successful investigation.

A separate local simulator test executed an approved protective hold, read back
the persisted state, and verified that departure returned 409. Its receipt is
`probes/results/warehouse_http.json`. The UI presents that recorded result.

## Project layout

- `demo/`: static replay UI, animated navigation, presentation, screenshots.
- `gateway/`: FastAPI boundary, Hotdata adapter, Cognee/HydraDB adapters,
  provenance contracts, task journal, and shipment simulator.
- `orchestrator/`: RocketRide Cloud pipelines, model setup, deterministic decision
  procedure, and the documented SDK dependency remediation.
- `probes/`: integration checks, fictional fixtures, Rote Play, replay builder,
  Snyk runner, and saved execution receipts.
- `tests/`: local correctness tests; sponsor mocks are labeled and do not count
  as executed integration evidence.

Secrets, private task capabilities, internal working notes and development
history are excluded from the public submission.

## Backend checks

Use Python 3.12 and a current Node.js runtime:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r gateway/requirements.txt
npm --prefix orchestrator ci --ignore-scripts
.venv/bin/python -m unittest discover -s tests -v
```

Live probes also require sponsor accounts, authenticated Hotdata CLI, Rote CLI,
and facility database bindings. Copy `.env.example` to `.env` and supply your own
credentials. The fixture database IDs belong to the recorded demo; configure
your own before running against a different workspace.

`probes.setup_demo` creates expiring private task capabilities; `gateway.demo`
starts the local gateway. Cloud runners require an explicitly provisioned HTTPS
gateway origin. Agents receive scoped task capabilities, never Hotdata workspace
credentials. The simulator action console is separate from the read-only replay.

## Security verification

The final recorded Snyk checks passed with no ignored findings:

- npm: **37 dependencies**, no vulnerable paths.
- Python: **17 dependencies**, no vulnerable paths.
- Snyk Code: gateway source, **zero findings**.
- Snyk Code: read-only UI source, **zero findings**.

See `probes/results/security_summary.json` and the individual JSON reports.
Run `.venv/bin/python -m probes.scan_security` with your Snyk token to repeat.

The vulnerable `adm-zip` dependency was removed from the local RocketRide runtime
bundle. Cloud SDK APIs remain intact; the unused CLI was omitted and ZIP creation
uses `fflate`. [Remediation and rebuild instructions](orchestrator/vendor/README.md)
include upstream provenance. The startup-path source finding was fixed rather
than ignored.

## Honest limits

Source passages establish proposals, not completed material events. Existing
vendor fixtures do not establish immutable snapshots or complete incident
coverage. Empty results do not establish safety. The recorded protective hold
does not establish global containment or real warehouse execution.

No production readiness, regulatory certification, automatic claim promotion,
fresh-snapshot acceptance, or measured speedup is claimed. Some legacy probes
record narrower experiments; use the named receipts above for demo claims.
