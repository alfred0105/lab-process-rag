# Phase 3 software verification report

## 최신 closure 감사 추가 — 2026-10-30

외부 최신 기준 커밋 `115d591c6509f95ad7da6ceddc2e6548812fb7cc`에서 다시 실행한 전체 테스트는 **153 passed** 였다. 추가 감사에서 PHREEQC DAG 출력의 `review_status`/출처 계약이 빠져 Worker consumer에서 실패할 수 있는 결함과, 정상 입력에서도 Planner가 PHREEQC를 `REQUEST_DATA`로만 반환하는 미연결 경로를 확인했다.

이번 코드 변경은 PHREEQC Typed Output에 계산 상태(`COMPUTED`), 도구·버전, DB SHA-256, 계보를 기록하고, 사용자가 승인하기 전에는 실행 불가한 구조화 입력 기반 평형/pH-sweep Planner DAG를 연결했다. 테스트는 실제 PHREEQC 엔진으로 첫 노드의 calculated pH를 두 번째 계산 입력으로 전달해 실제 수치계산에 사용했으며, 동시 DAG 캐시 재사용도 Typed metadata를 보존하는지 확인한다. 지원하지 않는 원소/데이터베이스 입력은 보류한다.

수정 후 다시 실행한 로컬 결과는 backend **164 passed**, production build 성공, browser E2E **1 passed**다. 코드 commit `73b65c1`의 GitHub Actions run [41011813494](https://github.com/alfred0105/lab-process-rag/actions/runs/41011813494)에서 backend, frontend build, browser E2E 세 job 모두 통과했다. full DAG/도구별 통합 성능 계측과 전 도구 typed-artifact/cache 계보 감사가 남아 공식 판정은 **`PHASE_3_SOFTWARE_IN_PROGRESS`** 다. 외부 장비 자료 기반 정확도와 승인 CFD는 `EXTERNAL_VALIDATION_PENDING` 이다. 변경 상세와 잔여 조건은 [`PHASE3_SOFTWARE_CLOSURE.md`](PHASE3_SOFTWARE_CLOSURE.md)를 기준으로 한다.

검증일: 2026-10-30
기준 브랜치: `main`
상태: `PHASE_3_SOFTWARE_IN_PROGRESS` (브라우저·소프트웨어 통합 검증 진행 중)

## 판정 범위

이 문서는 실제 과학적 타당성 검증과 소프트웨어 경로 검증을 구분한다. 합성 자료로 통과한 테스트는 코드·수치 처리·계보의 회귀 검증이며 실험 장비의 정확도를 뜻하지 않는다. 실제 장비 자료의 독립 교차 검증, 실제 OpenFOAM VM CFD 실행·수렴, 장비 제어는 별도 검증이다.

## 이번 변경 및 실행 근거

| 범위 | 구현 및 실행 경로 | 검증 | 판정 |
|---|---|---|---|
| AFM durable worker | 원본 → queue worker → adapter → 평면 보정/Sa/Sq/Sz → 영속 결과 | 격리 SQLite와 임시 파일에서 기울어진 평면 및 독립 NumPy 기준 비교 | 합성 경로 통과 |
| SEM/TEM durable worker | 합성 이미지 → 픽셀 보정 → Otsu 분할 → 파생 마스크·계보 저장 | 알려진 합성 마스크 IoU 및 두 modality 실행 | 합성 경로 통과. 중첩/저대비 인스턴스 분리에는 한계가 있음 |
| 분석 입력 gate | XRD 축 단위, AFM 높이 단위, SEM/TEM 픽셀 크기 검증 | 누락·비정상 교정 입력 API 테스트 | 거부 동작 통과 |
| XRD | 합성 Gaussian 피크/겹친 피크/배경/축/비유한 입력 검사 | peak preview 수치 회귀 테스트 | 계산 경로 통과. 상 동정은 수행하지 않음 |
| PHREEQC 기준 | PHREEQCAdapter의 명시적 공식 Example 2 실행 | 25°C 공식 gypsum/anhydrite 평형 예제와 pH, Ca/S, SI 비교 | 선택된 기준 사례 통과. 일반 분석 총량 입력 API와 동일한 입력 의미라고 주장하지 않음 |
| Planner | 다국어 목표·도구 적합성·결측/abstain 분류 | 30개 목표 평가 + modality 누락 측정 6개 | 목표 action 30/30, unsupported CFD 거부 5/5, missing 측정 선택 6/6. 평가셋은 결정론적 회귀셋이며 실제 연구 분포 정확도 아님 |
| 단위 handoff | Pint 물리 차원 변환 및 불확도 변환 | uL→mL 실제 workflow handoff, C→K·비호환·pH/SI 거부 테스트 | 지정 경로 통과 |
| 전체 backend | 현재 저장소의 pytest 전체 | `pytest -q` | 153 passed, 164 warnings (13.31 s) |
| PHREEQC 성능 | 실제 설치 Adapter 반복 실행 | Apple M5, 24 GiB RAM, Python 3.12.14, 30회 | p50 1.902 ms, nearest-rank p95 3.168 ms, 최대 75.226 ms, 프로세스 최대 RSS 140.72 MB. Import+엔진 포함. 전체 API/worker 동시 실행 메모리는 아님 |
| 브라우저 E2E | 격리 DB·임시 파일·별도 API/worker/Vite | Playwright 실제 브라우저에서 계획→등록→대기 중 취소→Worker 기동→완료→새로고침/상태 복원→잘못된 XRD 실패→재시도→재실패 및 타 Topic 조회 격리를 검증 | 로컬 1 passed; GitHub Actions run 41009238796 browser-e2e job passed. 합성 테스트 입력은 임시 DB와 명시 test flag에서만 workflow 실행 허용 |

## 외부·미완료 요구사항

- 실제 ZnO XRD, AFM, SEM/TEM 장비 데이터 기반의 독립 측정 정확도는 검증되지 않았다.
- PHREEQC 공식 사례는 Adapter를 통해 실행했으나 현재 사용자 분석 계약의 모든 종·전하수지·입력 의미를 동일 조건으로 황금 기준 비교하는 테스트는 아직 없다.
- Workflow Planner의 최소 30개 회귀 분류는 측정됐지만 전체 명시 지표, 고정 레이블 파일, 실제 목표 분포 검증은 부족하다.
- Worker 강제종료/lease fencing 테스트 및 브라우저의 취소·재시도·Topic 격리 E2E가 있다. API 서버와 Worker를 서로 다른 재시점으로 재시작하는 브라우저 조합 테스트는 아직 없다.
- 성능 프로파일은 PHREEQC 어댑터 마이크로벤치마크에 한정된다. Planner, queue/claim, AFM, SEM/TEM, DB 저장, DAG p50/p95 및 메모리 분리 측정은 없다.
- OpenFOAM 물리 계산은 실행하지 않았다. 정상·수렴 실패·mesh 실패·비정상 종료·완료 흔적 누락의 합성 parser fixture와 OS process cancel/timeout 테스트는 통과했다. 실제 VM 게스트 자원 정리 및 실제 solver 수렴은 검증하지 않았다.
- INT-01~12 통합 시나리오의 전체 종료 기준은 아직 통과로 선언하지 않는다.

## 경고

전체 pytest에서 기존 `datetime.utcnow()` 및 일부 의존성 deprecation 경고가 보고됐다. 기능 실패는 아니나 후속 호환성 정리가 필요하다. `npm audit`은 신규 Playwright 의존성 포함 0 vulnerabilities. 테스트는 운영 DB나 원본 연구 자료를 사용하지 않는다.

## Remote CI

GitHub Actions run [41009238796](https://github.com/alfred0105/lab-process-rag/actions/runs/41009238796) for commit `51953fc` completed successfully: `backend`, `frontend`, and `browser-e2e` all passed. Re-run results will be attached to the final documentation commit after it is pushed.
