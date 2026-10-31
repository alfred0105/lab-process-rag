# Phase 3 Technical Backlog

This backlog preserves unfinished Phase 3 verification without reopening core development automatically. `NON_BLOCKING` items do not prevent Phase 4 work. A real integrity, approval-bypass, wrong scientific handoff, or serious security defect must be classified `BLOCKING_DEFECT` and fixed immediately.

| Existing ID | Original requirement / current state | Evidence already available | Remaining verification | Priority / follow-up | Phase 4 blocked? |
|---|---|---|---|---|---|
| P3-FC-01 | Common artifact integrity contract for tool results; partial `IMPLEMENTED` | Hash/path/symlink checks and material-file manifests have tests; workflow outputs persist typed JSON | Extend common metadata and recovery tests across all simulation and scalar outputs, retry and restart cases | P2 / later hardening | No |
| P3-FC-05 | Durable DAG performance matrix; `IN_PROGRESS` | Real queue-to-worker runs; 20 samples for XRD/AFM/SEM/TEM, warm PHREEQC and multi-node PHREEQC; cache reuse and 2-worker same/different-key cases | Isolate API vs Worker RSS; repeat cold/cache; measure restart/retry latency and 1-vs-2+ worker throughput under controlled load | P2 / performance track | No |
| P3-FC-06 | INT-01..12 and final safety audit; `IN_PROGRESS` | Existing regression suite and latest backend/E2E/CI pass | Complete per-ID executed-test mapping and re-audit migration/backup, units, bounds, lifecycle and approval edges | P1 / before production use | No, unless a blocking defect is found |
| P3-FC-07 | Phase 4 data contract extraction; `IN_PROGRESS`, now carried into P4-001/P4-002 | Approved-observation endpoint preserves topic, experiment, method, step, source, unit, review and replicate lineage | Audit all field definitions and bounds against every supported process family; expand end-to-end unit conversion and process-step matching | P1 / Phase 4 dataset hardening | No |
| P3-FC-08 | Separate software completion from external validation; `REVISED` | Core status now declared separately; historical software-in-progress audit remains preserved | Keep status links synchronized when backlog items close; do not upgrade detailed rows without evidence | P2 / continuous | No |
| Cross-cutting warning cleanup | `IN_PROGRESS` | Current CI passes | Replace deprecated `datetime.utcnow()` usage and update Starlette/httpx / SWIG warning paths as compatible | P3 / maintenance | No |
| Long-duration load and operational recovery | `NOT_STARTED` | Standard durable-workflow regressions pass | Extended queue/load, disk-full, crash/restart, backup restore, and retention/cleanup test matrix | P2 / before wider deployment | No, unless integrity defect |

The historical software audit documents remain unchanged snapshots and must not be bulk-edited to make this backlog appear complete.
