# Phase 3 software closure — latest audit

## Current follow-up — 2026-10-31

Current official status remains **`PHASE_3_SOFTWARE_IN_PROGRESS`**; see [`PHASE3_FINAL_CLOSURE_2026-10-30.md`](PHASE3_FINAL_CLOSURE_2026-10-30.md) for the superseding current audit and evidence. Since the prior snapshot, the XRD Bragg-law axis conversion/child-run lineage was implemented, PHREEQC and XRD browser E2E were made Workflow-ID-specific and run in reversed order, and the complete backend suite passed 178 tests. The production build succeeded; Playwright passed 2/2.

The durable workflow benchmark now covers 20 repeats each for four analysis modalities, warm PHREEQC and typed two-node PHREEQC; one fresh Worker PHREEQC run; an actual cached workflow reuse; and concurrent same-key/different-key Worker processes. JSON and CSV are in `backend/reports/phase3_durable_benchmark.*`. It uses temporary synthetic data only. API/Worker memory separation, confidence-grade repeated cold/cache measurements, restart/retry latency, worker-count throughput scaling, the complete artifact recovery contract audit and full Phase 3 safety matrix are still open. This update does not claim Phase 3 closure.

> This file preserves the preceding audit snapshot. The newer additive closure result, with artifact integrity, XRD reanalysis, PHREEQC equivalent-deck checks, browser workflow, benchmark, and updated status, is [PHASE3_FINAL_CLOSURE_2026-10-30.md](PHASE3_FINAL_CLOSURE_2026-10-30.md). Use that document for the current state.

검토일: 2026-10-30  
Repository: `alfred0105/lab-process-rag`  
기준: `origin/main` commit `115d591c6509f95ad7da6ceddc2e6548812fb7cc`  
현재 판정: **`PHASE_3_SOFTWARE_IN_PROGRESS`**  
외부 검증: **`EXTERNAL_VALIDATION_PENDING`**

이 문서는 과거 감사를 덮어쓰지 않는 최신 closure 기록이다. 첨부된 `Phase 3 Final Closure & Master Roadmap Realignment`에서 요구한 범위로 코드를 재감사했다. VERIFIED는 실제 실행 증거가 확인된 항목에만 사용하며, synthetic fixtures는 과학적 측정 정확도 증거로 취급하지 않는다.

## 수정한 실제 결함

### PHREEQC Typed Handoff

`typed_phreeqc_outputs()`가 생성한 값에 `review_status`가 빠져 Worker의 유효한 입력 검사와 계약이 달라 downstream 노드가 거부될 수 있었다. 새 출력은 `COMPUTED` 상태, tool ID/version, PHREEQC database SHA-256, 부모 데이터 ID, source ID, 단위, 물리적 의미, numerical validation 상태 및 명시적 `uncertainty: null`을 포함한다. 계산 완료는 연구자 `ACCEPTED`를 의미하지 않는다. direct API 결과에도 `COMPUTED` provenance를 저장한다. 구 저장 결과는 필수 tool/version/database fingerprint를 회수할 수 없으면 typed artifact 생성에서 명시적으로 거부한다.

실제 integration test는 `PHREEQC Node A → Engine → typed_outputs → Node B`를 실행한다. Node B는 A의 calculated pH를 handoff로 받아 자신의 PHREEQC 계산 입력에 실제 사용한다. 두 계산 결과와 저장된 source/review metadata를 검사한다. 같은 계산을 동시 Worker DAG 둘이 요청하는 테스트도 한 번의 계산을 재사용하고 원래 계보·검토 상태를 유지하는지 확인한다.

### PHREEQC Planner

`WorkflowPlanRequest`는 명시적인 분석 총량(mol/kgw), temperature, fixed pH 또는 pH sweep 범위, database identifier, process step, approval을 받는다. 기존 입력 없이 레시피에서 녹은 총량/전하균형을 추측하지 않는다.

- 입력 누락: `REQUEST_DATA`와 필드별 요구사항
- 지원 외 데이터베이스·화학종 또는 adapter schema 실패: `ABSTAIN`
- 입력 정상·승인 전: `REQUIRES_REVIEW`, DAG preview만 제공
- 입력 정상·명시 승인: 실제 allowlisted PHREEQC Worker DAG를 `RUN_SIMULATION`으로 등록
- 동일한 완료 계산 발견: `REVIEW_RESULT`와 기존 결과 ID를 노출하고 재계산하지 않음

실제 API → 승인 게이트 → Worker → PHREEQC Engine → DB 저장을 검증한다. Sweep 입력은 `phreeqc.aqueous_sweep.v1`로 라우팅한다.

## 실행한 검증

| 검사 | 결과 | 범위와 제한 |
|---|---|---|
| Targeted Planner / PHREEQC integration tests | **33 passed** | PHREEQC 실 엔진, Node-to-Node 실제 수치 소비, 승인 Planner, 누락·허위 typed source 검사 포함 |
| Backend 전체 `pytest -q` | **164 passed** | synthetic material fixtures는 구현 경로 검사이며 실측 정확도 아님 |
| Frontend production build | **성공** | TypeScript 빌드와 Vite 6.4.5, 1,757 modules 변환 |
| Browser Playwright E2E | **1 passed** | 실제 브라우저에서 planner→enqueue→cancel→완료→refresh 복원→실패/retry와 Topic 격리 확인. 이 E2E는 XRD 시나리오이며 PHREEQC Planner UI를 다루지는 않음 |
| GitHub Actions | **성공** | run [41011813494](https://github.com/alfred0105/lab-process-rag/actions/runs/41011813494), commit `73b65c1`: backend, frontend build, browser-e2e 세 job 모두 성공 |

전체 pytest는 173개 경고도 출력한다. 경고는 현재 실행 실패를 일으키지 않지만 SQLAlchemy `datetime.utcnow()`, SWIG 및 Starlette TestClient deprecation이 남아 있다.

## 12개 통합 시나리오 최신 분류

| ID | 소프트웨어 경로 | 상태 | 실제 근거/잔여 |
|---|---|---|---|
| INT-01 | synthetic XRD 원본→durable Worker→분석→검증·저장 | VERIFIED | synthetic XY 파일 전체 worker 경로 통과. 실제 ZnO 원본·장비 metadata에 대한 정확도는 별도 외부 검증 |
| INT-02 | SEM/TEM calibration→segmentation→mask/provenance | VERIFIED | isolated synthetic worker 경로 통과. 실제 장비 이미지 수치 정확도는 외부 검증 |
| INT-03 | AFM map→plane leveling→Sa/Sq/Sz | VERIFIED | synthetic known-plane 기준 worker 테스트 통과. 실제 calibrated 장비 map 정확도는 외부 검증 |
| INT-04 | PHREEQC→species/SI persist | VERIFIED | 실제 PHREEQC engine 실행·저장 테스트 및 USGS Example 2 기준 경로 보존 |
| INT-05 | 누락/잘못된 입력 단위 실행 차단 | VERIFIED | Pydantic/API/adapter/Worker input gate 회귀 |
| INT-06 | 미지원 CFD 형상 차단 | VERIFIED | OpenFOAM preflight/gate 회귀; 실제 CFD는 실행하지 않음 |
| INT-07 | 문헌 파생값을 실측 최적화에서 격리 | VERIFIED | source type 및 승인 관측 필터 테스트 |
| INT-08 | 중복 계산 재사용·동시성 | VERIFIED | 2개 Worker DAG가 같은 PHREEQC run 하나를 재사용; 계보 및 typed metadata 확인 |
| INT-09 | 선행 node 실패가 후속 node 차단 | VERIFIED | durable DAG failure propagation 테스트 |
| INT-10 | Worker process kill→lease 복구/fencing | VERIFIED | 별도 subprocess 강제 종료·expired lease·늦은 generation 거부 테스트 |
| INT-11 | 목표/입력/승인에 따른 Planner 행동 | VERIFIED | 30개 결정론적 목표 회귀셋 및 결측/unsupported/approval·PHREEQC equilibrium/sweep/cache 행동 테스트. 실제 자연어 분포의 정확도 일반화는 별도 평가 |
| INT-12 | 미승인 관측을 optimizer 입력에서 제외 | VERIFIED | accepted source/review 상태 기반 optimization API 테스트 |

이 표의 IMPLEMENTED는 구현·합성경로가 존재한다는 뜻이며, 실제 기기 기반 과학 정확도 검증과 다르다.

## 도구 계약 및 데이터 상태

- PHREEQC typed scalar output은 값/단위/의미/source/source ID/tool/version/parent IDs/검증 및 검토 상태/불확도 슬롯을 제공한다. Consumer는 simulation source ID가 실제 완료된 DB 결과를 가리키는지, 같은 topic/experiment인지, 값·tool/version·database hash·review status가 저장 결과와 일치하는지 확인한다. 존재하지 않는 SimulationRun을 가리키는 테스트 source ID는 차단됨을 확인한다.
- Worker의 분석 typed scalar도 tool/version 및 parent file/experiment ID를 포함한다.
- pH와 saturation index는 로그·무차원 물리 의미를 지키며 일반 단위 변환을 허용하지 않는다. 단위가 같은 경우 값은 그대로 보존된다.
- 마스크·이미지와 같은 구조 출력은 숫자로 위장하지 않는다. 모든 adapter의 범용 typed-artifact hash 계약은 아직 전수 검증되지 않았다.
- 계산 상태 `COMPUTED`와 연구자 승인 `ACCEPTED`는 분리한다. Worker는 `REVIEWED`를 계산 승인처럼 자동 생성하지 않는다.

## PHREEQC reference 수준

USGS Example 2 official reference test는 원래 공식 batch/equilibrium phase case를 실행하는 별도 경로다. 일반 adapter는 analytical totals를 고정 pH로 계산하는 다른 계약이다. 이 둘을 동등한 입력 기준 사례라고 하지 않는다. 일반 Adapter의 이번 검증은 실제 엔진 실행, 입력 validation, 파서·저장·node-to-node handoff 확인이며 독립된 동일조건 물리 benchmark를 뜻하지 않는다.

## 성능

현재 M5에서 같은 Calcite 입력으로 PHREEQC adapter를 30회 반복 실행했다. `p50 1.763 ms`, nearest-rank `p95 2.092 ms`, min `1.681 ms`, max `71.333 ms`, 프로세스 최대 RSS `140.58 MB`였고 모든 결과가 schema validation을 통과했다. 전체 결과는 [`docs/benchmarks/phase3_phreeqc_m5_2026-10-30.json`](benchmarks/phase3_phreeqc_m5_2026-10-30.json)에 기록했다. 이 측정은 import+PHREEQC adapter process RSS를 포함하고 한 번의 adapter 계산만 잰다. Planner, queue, Worker claim, SQLite transaction, 분석 adapters, 전체 DAG의 cold/warm p50/p95와 API/Worker 분리 peak RSS는 아직 계측되지 않았으므로 통합 성능 요건은 미완료다.

## 남은 소프트웨어 일과 외부 검증

1. 현재 코드 상태의 browser E2E와 GitHub Actions 세 job을 commit `73b65c1`에서 통과했다. 후속 문서-only commit의 CI 상태도 최종 확인한다.
2. 어댑터 단위 결과를 넘는 반복 Planner/queue/worker/SQLite/analysis/full-DAG cold-warm 벤치마크와 JSON/CSV 결과를 만든다.
3. OpenFOAM parser/mesh/residual/termination/cancel/timeout/approval의 정상·비정상 fixture matrix가 모든 필수 상태를 실제로 덮는지 closure assertion을 정리한다. VM 내부 solver 물리 계산은 연구자 승인 전 실행하지 않는다.
4. 모든 Phase 3 실행 도구의 typed scalar/artifact contract, cache/retry/restart metadata를 전수 점검한다.
5. 기존 roadmap 상세 ID는 유지한 채 Phase 0~7의 현재 구조로 이관한다. 과거 `Phase 4=UI`, `Phase 5=BO` 표기는 historical mapping에서만 해석한다.
6. 실제 XRD/AFM/SEM/TEM 장비 파일, reviewer 검증, 승인된 OpenFOAM VM 사례가 제공되면 별도의 과학·물리 검증을 한다.

따라서 지금은 `PHASE_3_SOFTWARE_VERIFIED`가 아니다. 통합 성능 요구와 전 도구 typed-artifact/cache 계약 감사가 남아 있다. 실제 장비 정확도와 승인 CFD는 그 판정과 분리된 `EXTERNAL_VALIDATION_PENDING` 항목이다.
