# Phase 4 Stage 3 — 다목적 GP·Pareto 추천

**범위:** 두 개 목적, 연속 입력 변수 최대 6개, 결정론적 Stage 2 제약, 후보 batch 1~4개
**Stage 상태:** `PHASE_4_STAGE_3_IMPLEMENTED` (로컬 검증 및 원격 CI 통과)
**Phase 4 상위 상태:** `PHASE_4_CORE_COMPLETE`
**실제 연구 성능 검증:** `PENDING` — 승인된 실측 다목적 데이터가 준비되지 않음

## 구현 내용

- 기존 단일 목적 GP, Stage 1·2 API, 저장 JSON 및 Stage 2 제약 엔진은 유지한다. 새 모델은 `gpbo-moo-stage3-1` 유형으로 식별한다.
- 연구 학습 데이터는 같은 Topic·Method Version의 비데모 실험에서 `ACCEPTED` 상태인 `LAB_RECORD` 입력과 `LAB_RESULT`/`ANALYSIS_OUTPUT` 목적값만 사용한다. 수치 단위는 기존 과학 데이터 정규화 규칙으로 변환한다.
- 두 목적 관측값은 동일한 Experiment에서만 연결한다. Replicate가 있으면 같은 replicate ID를 우선 연결하고, replicate가 없는 Experiment 수준 관측만 공유 관측으로 쓴다. 서로 다른 replicate 또는 Experiment의 값을 임의로 결합하지 않는다.
- 기본 데이터 정책은 두 목적 모두 있는 complete-case다. 불완전 행은 버리며 보간하지 않고 개수와 provenance를 모델 구성에 남긴다. 독립 실험 3개, 입력 조건 2개 미만이면 거부한다.
- 목적별로 Stage 2 `GaussianProcess`를 독립 학습한다. 목적 단위·방향, 단위가 정규화된 입력, GP JSON, 데이터 해시, 승인 관측 ID/출처, 실험 그룹 분할, 검증 지표와 제한사항을 저장한다. 연구 데이터는 두 목적에 동일한 Experiment-group holdout을 사용한다.
- Pareto dominance는 최소/최대 혼합 방향을 최소화 좌표로 바꾸어 정확 비교한다. 목적값이 같은 Front 위치는 1개 대표점을 반환하면서 원본 ID들을 유지한다. 부적합 후보는 Front에서 제외한다.
- 2차원 Hypervolume은 고정 Reference Point와 양수 목적별 스케일을 받아 정확한 직사각형 합집합 면적으로 계산한다. 기준점이 Front보다 열등하지 않으면 오류를 반환한다. 기준점과 스케일은 추천/이력에 저장한다.
- 추천은 각 독립 GP의 latent posterior를 사용해 Monte Carlo Hypervolume Improvement를 계산한다. 단일 목적 EI·PI·UCB·Noisy EI는 수정하지 않는다.
- Batch 1개는 `mc_ehvi`, batch 2~4개는 `greedy_mc_hvi`로 명명한다. 각 목적 내 후보점 간 joint posterior covariance를 보존하고 순차 greedy 개선량으로 최대 4개 후보를 고른다. 목적 간 출력 공분산은 독립 GP 가정으로 모델링하지 않는다. 후보 선택용 Monte Carlo 표본과 별도의 seed 표본으로 개선량 및 Monte Carlo 표준오차를 다시 추정한다.
- 탐색 후보 생성량은 최대 2,000, GP joint posterior 계산은 최대 256개 후보로 제한한다. 연구 입력 범위는 관측 정규화 단위로 변환하며, 후보는 기존 학습 입력 및 같은 batch 후보와 표준화 입력공간 거리 기준으로 중복을 걸러낸다. 배치×후보×MC 연산 예산도 제한하며 초과 시 계산을 시작하지 않고 오류를 돌려준다. 불가능한 제약 영역이나 후보 부족을 임의 값으로 채우지 않는다.
- 후보의 예상 개선량은 성공 확률이 아니며, 예측은 관측값이 아니다. 추천은 `PENDING_RESEARCHER_REVIEW`에 머물고 실험 실행 기능은 연결하지 않는다.

## API와 화면

다목적 API는 기존 단일 목적 경로와 분리했다.

- `POST /api/optimization/multiobjective/models/train`
- `GET /api/optimization/multiobjective/models/{model_id}?topic_id=...`
- `POST /api/optimization/multiobjective/models/{model_id}/predict`
- `GET /api/optimization/multiobjective/pareto?model_id=...&topic_id=...`
- `POST /api/optimization/multiobjective/models/{model_id}/recommend`
- `GET /api/optimization/multiobjective/recommendations/{recommendation_id}?topic_id=...`
- `POST /api/optimization/multiobjective/sandbox/benchmark`
- `POST /api/optimization/multiobjective/sandbox/benchmark/compare`

새 DB 마이그레이션은 필요하지 않았다. 기존 `optimization_model_runs` 및 `optimization_recommendation_runs` JSON 계약을 재사용하되, 모델 유형 버전으로 Stage 1·2 역직렬화와 구분한다. 기존 단일 목적 모델 조회는 기존 `GaussianProcess.from_dict()`로 계속 처리한다.

`OptimizationPanel` 안에 샌드박스/승인 연구 데이터 모드, 목적 두 개와 방향, 조건 범위, Hypervolume 기준점/스케일, batch 크기, MC 예산, 2D Pareto scatter, 전체 관측·Pareto·예측 후보 구분, 추천 표와 연구자 검토 상태를 추가했다. 공개 자료 없는 연구 데이터를 데모 값으로 대체하지 않는다. Sandbox는 격리된 합성 ZDT1 수치 함수만 저장 모델/추천 기록에 기록하며 ScientificObservation을 만들지 않는다.

## 합성 벤치마크

재현 명령: `cd backend && .venv/bin/python scripts/benchmark_phase4_stage3.py`
출력: [`backend/reports/phase4_stage3_benchmark.json`](../backend/reports/phase4_stage3_benchmark.json)

ZDT1과 Branin–Currin 두 함수에서 Random Feasible Search, scalarized GP, single MC-EHVI, greedy batch MC-HVI를 같은 seed별 초기 설계와 총 목적값 쌍 평가 횟수로 비교했다. 각각 5개 seed, 정책마다 10개 총 평가(초기 6개 포함), MC 32개, 후보 pool 48개를 사용했다.

| 합성 문제 | Random HV | Scalarized GP HV | MC-EHVI HV | Greedy Batch MC-HVI HV |
|---|---:|---:|---:|---:|
| ZDT1 | 8.06270 | 9.91452 | 10.01507 | 9.93745 |
| Branin–Currin | 2.16403 | 2.29610 | 2.23204 | 2.34158 |

Hypervolume은 문제별 고정 기준점에 대한 값이므로 서로 다른 benchmark 간 직접 비교하면 안 된다. ZDT1의 알려진 Front는 분석적 기준, Branin–Currin 기준 Front와 HV는 고정된 조밀 격자 근사로 표시했다. 실행마다 결과가 정책 우위를 보장하지 않는다. 현재 JSON에 기록된 로컬 실행은 **19.34초**, 프로세스 최고 RSS **72.2 MiB**였다. 실행 시간은 동시 시스템 부하에 따라 달라진다. RSS는 benchmark 하나의 추가 메모리가 아니라 Python 프로세스 전체 high-water mark다. 이는 M5 24GB에서 전체 서비스 부하/열 상태의 메모리 프로파일이 아니다.

## 요구 ID 추적

| 요구사항 | 상태 | 관련 구현 | 완료/검증 근거 | 남은 점 |
|---|---|---|---|---|
| P4-S3-001 — 두 승인 목적 complete-case 연결 | IMPLEMENTED | `backend/app/api/optimization_multiobjective.py:_research_rows` | 동일 Experiment·replicate·공정 단계와 source provenance API 테스트; 목적 결측·다른 실험 혼합 거부 | 실제 연구 campaign 데이터로 외부 점검 |
| P4-S3-002 — 목적별 GP 학습/불확도/그룹 holdout | IMPLEMENTED | `backend/app/services/optimization/gpbo.py`; MOO train API | 서로 분리된 GP, posterior 예측 및 동일 그룹 holdout·목적별 지표 테스트 | 교차 목적 공분산 미모델링 |
| P4-S3-003 — Pareto 지배/Front | IMPLEMENTED | `multiobjective.py:pareto_front` | 혼합 방향, 지배/비지배, 동일 벡터, feasibility 테스트 | 수치 안정성은 부동소수점 exact comparison |
| P4-S3-004 — 정확 2D Hypervolume | IMPLEMENTED | `multiobjective.py:hypervolume_2d` | 손계산 면적, 중첩/중복/지배, 방향/스케일/기준점/빈 Front 테스트 | 스케일 선택은 연구자가 고정해야 함 |
| P4-S3-005 — MC-EHVI | IMPLEMENTED | `multiobjective.py:mc_hvi` | 독립 GP posterior 공분산 기반 seeded sampling; 유한·재현 점수 테스트 | noisy EHVI / qNEHVI가 아님 |
| P4-S3-006 — Batch 1~4 greedy MC-HVI | IMPLEMENTED | `multiobjective.py:greedy_batch`; API | 후보점 joint covariance, distinct-candidate 제한, 개선량의 독립 MC 오차 추정 및 q=2 E2E | 범용 scheduling/asynchronous batch 아님 |
| P4-S3-007 — 두 benchmark/동일 예산 비교 | IMPLEMENTED | `run_moo_benchmarks`; benchmark script/report | 2개 함수 × 4 정책 × 5 seeds × 같은 예산 실행; 보고서 JSON 및 단위 테스트 | 합성 수치 테스트이며 연구 성능 아님 |
| P4-S3-008 — 다목적 API | IMPLEMENTED | `optimization_multiobjective.py`; FastAPI router | 학습·조회·예측·Pareto·추천·저장·오류 통합 API 테스트 | 제한된 Stage 3 scope |
| P4-S3-009 — DB/provenance/호환성 | IMPLEMENTED | 기존 optimization JSON 테이블; MOO `model_type` | 모델/추천 조회 지속성, 주제 격리, 기존 단일목적 회귀 전체 suite | 별도 관계형 Pareto 테이블은 추가하지 않음 |
| P4-S3-010 — Pareto UI | IMPLEMENTED | `frontend/src/components/MultiObjectivePanel.tsx`; CSS/API | production build 및 2후보 browser flow; 관측/Pareto/예측 점, 기준점, HV, 검토 표시 | Research 실제 데이터 UI 사용은 승인 데이터 대기 |
| P4-S3-011 — 데이터·수치·제약 안전 | IMPLEMENTED | 연구 데이터 builder, constraints, numerical guards | unit/finite/reference/compute-budget/topic/source/feasibility/approval 회귀 테스트 | 로그인 사용자별 인가 및 실제 재료 안전 제약은 프로젝트 공통 backlog |
| P4-S3-012 — backend/frontend/E2E/CI | VERIFIED | `backend/tests/test_multiobjective_stage3.py`; Playwright spec; CI workflow | 로컬 pytest **195 passed**, frontend production build 성공, browser E2E **4 passed**, temporary SQLite DB에서 Alembic `upgrade head`가 revision `0008_gpbo_mvp`에 도달; commit `a3bc55ae9702548e138e365328dc404eb5d6a217`의 GitHub Actions [run 41185807419](https://github.com/alfred0105/lab-process-rag/actions/runs/41185807419)에서 backend/frontend/browser-e2e 모두 성공 | 기존 Node.js 20 deprecation 및 `ubuntu-latest` 전환 알림은 CI warning; 실제 연구 데이터 검증은 별도 미완료 |

로컬 전체 회귀에서는 기존 API/PHREEQC·XRD·AFM·SEM/TEM·Worker 테스트도 함께 실행됐다. pytest는 **310개 deprecation 경고**(주로 기존 `datetime.utcnow`, Starlette TestClient/httpx, SWIG bindings)를 출력했으나 실패는 없었다. Stage 3은 기존 테이블의 JSON 필드를 재사용하므로 새 DB migration은 추가하지 않았다.

## 판정

P4-S3-001~011은 기능 구현 및 로컬 검증 완료, P4-S3-012는 로컬 검증과 원격 CI를 통과했다. Stage 3 상태는 `PHASE_4_STAGE_3_IMPLEMENTED`다. 코드 commit `a3bc55ae9702548e138e365328dc404eb5d6a217`의 GitHub Actions [run 41185807419](https://github.com/alfred0105/lab-process-rag/actions/runs/41185807419)에서 backend, frontend, browser-e2e가 모두 성공했다. Phase 3은 `PHASE_3_CORE_COMPLETE`, Stage 1 `PHASE_4_MVP_IMPLEMENTED`, Stage 2 `PHASE_4_STAGE_2_IMPLEMENTED`, Phase 4 상위 상태 `PHASE_4_CORE_COMPLETE`, External Scientific Validation `PENDING`, Phase 5–7 `NOT_STARTED`로 유지한다. 승인된 실제 다목적 연구 데이터가 없어 모델 예측 정확도·재료별 효율성·실험 성공률은 검증되지 않았다.
