# Phase 6 Early Exit

## Actual sandbox runtime — 2026-11-01

The cached synthetic candidates are now connected to an isolated runtime artifact and the pinned local Qwen3-0.6B decoder. This is a technical runtime check only: the Research API does not pass the sandbox router, no workflow was triggered, no synthetic certificate was promoted, and external scientific validation remains pending.

On the same 30 balanced rows from the existing 384-row frozen synthetic partition, using Qwen revision `c1899de289a04d12100db370d81485cdf75e47ca`, MPS FP16, three warmups, synchronized timings and forward hooks:

| Path | Mean actual layers | p50 | p95 | p50 speedup | Agreement with full-depth | Macro F1 |
|---|---:|---:|---:|---:|---:|---:|
| Full-depth | 28.00 | 85.25 ms | 87.63 ms | 1.00× | reference | A: 0.7990 / C: 0.8283 |
| Candidate A — PABEE | 15.63 | 45.38 ms | 68.34 ms | 1.88× | 96.67% | 0.8283 |
| Candidate C — Fusion + EEFP | 7.93 | 26.97 ms | 40.41 ms | 3.16× | 100% | 0.8283 |

Hooks confirmed that actual decoder calls equaled the reported exit depth on every adaptive input; full-depth ran all 28 layers. OOD was detected in 5 A traces and 4 C traces and blocked the exit in all those traces; both candidates had zero OOD early-exit violations and zero false-positive `OPTIMIZE` recommendations on this small synthetic slice. Candidate C is selected for the sandbox runtime comparison because it matched its full-depth macro F1, matched all full-depth actions, and had the lower measured latency. Thirty samples are descriptive runtime evidence, not a statistical safety certificate or evidence of laboratory accuracy. MPS peak allocation is not exposed by the installed PyTorch build; current allocator and driver allocation are recorded instead.

Parity used identical token IDs and the same pinned checkpoint/cache. Exact token match was 30/30; intermediate hidden-state maximum absolute error was 0 at layers 7/14/21/28; maximum probability error was `5.66e-7` for A and `8.94e-7` for C against a `2e-4` tolerance; action and exit-layer parity were 30/30 for both. The runtime tensors are generated locally from the existing synthetic cache and loaded with `weights_only=True`.

Reports: `backend/reports/phase6_ee_runtime_parity.json`, `backend/reports/phase6_ee_actual_runtime.json`, and `backend/reports/phase6_ee_runtime_selection.json`. Reproduce with `backend/scripts/phase6_ee_runtime_parity.py` on the configured local machine with the pinned checkpoint and research cache present.

`P6-007` is now technically verified for isolated synthetic sandbox runtime only. Phase 6 remains `IN_PROGRESS`; Phase 7 remains `NOT_STARTED`; `EXTERNAL_SCIENTIFIC_VALIDATION_PENDING` remains open. Research-mode early exit and equipment/workflow execution remain disabled.

Backbone layer loop는 7/14/21층에서 calibrated confidence, valid provenance, in-calibration OOD score, pending-review gate를 모두 만족할 때 실제 다음 decoder layer 실행을 생략한다. layer 28은 최종 fallback이다. Sandbox 요청은 비검증 입력이므로 early exit을 허용하지 않는다. 별도 강제 full-depth 비교 경로가 동일한 입력에서 전체 층을 계산한다.

2026-11-01 실제 Qwen layer forward hook을 붙인 구조 테스트는 강제 0.0 test-only threshold로 layer 7에서 멈췄고, 28개 중 7개 layer call이 실제 실행되어 나머지 21개를 생략했다. 이는 구조 검증에만 해당하며 안전한 confidence threshold가 아니다. 120개 합성 사례의 독립 calibration 24개에서 모든 layer의 threshold가 `null`이었고, 실제 calibrated early-exit 비율은 19개 연구 입력 중 0/19, 평균 28/28층, 추정 절감 0%다. Early/full-depth p50은 87.8/87.4ms였으며 개선 증거가 아니다. 그러므로 P6-007은 `PARTIAL`이다. 안전/출처 gate는 높은 softmax confidence로 우회하지 않는다. 수치는 `phase6_early_exit_benchmark.json` 및 `phase6_early_exit_revalidation.json`에 보관한다.


## 2026-11-01 Expanded diagnostic addendum

`phase6_early_exit_diagnostics.json` records 480 grouped synthetic scenario contracts split into fit/calibration/controller/frozen evaluation (288/72/48/72), with 3 head structures across layers 7, 10, 14, 18, 21, 24 and 28. Every sequential policy failed the independent controller bound: Linear 1/20 errors (95% Wilson upper 0.236), MLP 2/18 (0.328), regularized MLP 2/16 (0.360), target ≤0.20 with at least 24 exits. No policy was promoted. Authorized exit rate therefore remains 0%, mean executed layers 28, measured savings 0%; candidate latency/forward-hook benchmark was not run because no safe candidate passed. See `backend/reports/phase6_early_exit_final.json`. Synthetic class imbalance and labels are diagnostic only.


## Expanded comparison — 2026-11-01

`backend/scripts/phase6_ee_research.py` audits 480/1,920/3,840 rule-generated cases, uses six mutually group-disjoint partitions (1,920/384/384/384/384/384 at 3,840), and compares class weighting, effective-number weights, class-balanced random oversampling, structured-only/fusion features, an MLP fusion head, actual soft-label intermediate-head distillation, plus Max Softmax/Entropy/Margin/PABEE/EEFP routing. A 384-case policy-selection set selected PABEE (370 exits/34 errors; Wilson upper 12.57%). On the separate 384-case risk certificate PABEE exited 377 cases with 46 errors (12.20%), Wilson upper 15.89%, exact-binomial upper 15.33%, both below the unchanged 20% target. EEFP did not pass policy-selection risk bound after its target was corrected to predict when deeper computation fixes a current error. OOD rejection is included. This is a **synthetic contract result only** and cannot authorize Research use.

On the untouched 384-case synthetic frozen split, offline PABEE routing estimated 15.42/28 mean layers and achieved macro F1 0.8446 versus full-depth 0.8487. PABEE had selection-set 34/370 errors/exits (Wilson 12.57%); EEFP had 64/380 (20.93% Wilson upper) and failed the selection gate; Max Softmax, Entropy and Margin also failed. These are cached-state estimates, not runtime savings. The actual Qwen3-0.6B MPS FP16 full-depth benchmark used 30 synchronized runs over a 471-token input and forward hooks: all 28 layers ran; latest-batch p50/p95 were 84.69/96.54 ms; across three batches p50 ranged 84.69–120.89 ms and p95 ranged 91.46–145.16 ms. No adaptive policy latency or real layer skip was run because only synthetic Sandbox labels were available. Therefore `P6-007` remains `PARTIAL`, production remains full-depth, and Phase 6 remains `IN_PROGRESS`.

An integrated BASELINE/COMBO-A~E comparison was added in `backend/scripts/phase6_ee_combo_comparison.py`. On the same synthetic contract and split, COMBO-C (hidden + structured feature fusion with EEFP) was selected on policy-selection data and passed a single independent synthetic-only certification: 381/384 exits, 52 errors, Wilson upper 0.1746, exact upper 0.1688. Its frozen offline estimate was 7.58/28 mean layers and macro F1 0.8233. This does not establish scientific validity or actual latency savings; the runtime adapter still does not implement EEFP/PABEE routing and production remains full-depth.

The comparison omits the optional contrastive head and explicit multiplicative gate. The tested class-balanced fusion uses concatenated scientific features and does not claim a learned multiplicative gate. All requested COMBO-A~E and baseline candidates were compared in a separate synthetic-only run; this does not constitute empirical scientific validation or actual runtime policy integration. See `PHASE6_EARLY_EXIT_RESEARCH.md`, `PHASE6_EARLY_EXIT_EXPERIMENTS.md`, `PHASE6_EARLY_EXIT_MODEL_SELECTION.md`, and the `phase6_ee_*.json` reports.
