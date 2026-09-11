# RocketRide runtime bundle

`rocketride-1.3.0-rf.1.tgz` contains the sponsor's MIT-licensed TypeScript SDK
with a small, reproducible dependency remediation. The Cloud client and its
account/chat/tool APIs are unchanged.

The upstream package includes `adm-zip`, for which Snyk reports
`SNYK-JS-ADMZIP-19276676` with no fixed version. This runtime removes the unused
bundled CLI and its docs-provisioning extraction code, and switches app-pack ZIP
creation to `fflate@0.8.3`. There is no vulnerability ignore or version downgrade.
The bundle does not provide the upstream `rocketride` command-line executable;
our runners use the preserved SDK API.

Rebuild with `python orchestrator/build_runtime.py /path/to/original/rocketride-client.tgz`.
The script checks the upstream version and exact patch sites. Input/output
SHA-256 values are in `provenance.json`. Existing per-file MIT notices remain.

Verification: SDK archive creation was decoded and compared in a round-trip;
a real Cloud pipeline started with this installed package; the npm Snyk scan
reported no vulnerable paths. Source advisory:
https://security.snyk.io/vuln/SNYK-JS-ADMZIP-19276676
