# Lab Process RAG — Master Roadmap

**관리 기준일:** 2026-10-30
**저장소:** [alfred0105/lab-process-rag](https://github.com/alfred0105/lab-process-rag)
**검토 기준:** origin/main / 0ccad66006c311c30b96af4233377cab0f720d0d; 작업 브랜치 main에는 이전 로드맵 커밋 d168cef가 추가로 있음. Phase 3 변경분은 현재 작업 중이며 아직 미커밋.

이 문서는 전체 개선 프롬프트(2026-10-30), 이후의 데이터 신뢰성 개선 프롬프트, 기존 감사·설계·검증 문서와 사용자가 확정한 제품 흐름을 통합 추적한다. 요구를 임의로 삭제하지 않는다. 범위가 바뀌면 원래 ID를 유지하고 변경 이유와 대체 방안을 기록한다.

## 상태 정의

| 상태 | 뜻 |
|---|---|
| NOT_STARTED | 확인된 구현/검증 작업 없음 |
| IN_PROGRESS | 일부 구현 또는 검증 중이며 완료 조건 미충족 |
| IMPLEMENTED | 소스코드에 구현되어 있으나 요구별 검증 완료를 입증하지 못함 |
| VERIFIED | 실제 코드와 관련 테스트, 필요한 통합/실데이터 검증 완료 및 한계 문서화 |
| REVISED | 근거를 기록하고 원 요구를 대안으로 변경함. 대안 검증 전에는 완료가 아님 |
| BLOCKED | 외부 의존성/자료 부족으로 진행할 수 없으며 해소 조건을 기록함 |

모의 테스트·문서·타입 정의·더미 함수·호출되지 않는 어댑터만으로 VERIFIED를 부여하지 않는다.

## 전역 원칙과 검증 기준

- 기존 API, UI, 실험기록, 원본 측정파일, 논문 및 출처를 보존한다. DB 변경 전 백업, 버전 마이그레이션, 재실행 및 복구 검증을 갖춘다.
- 실측·파생계산·시뮬레이션·문헌·모델지식·합성 데모를 출처와 함께 분리한다. 시뮬레이션을 실측으로 승격하지 않는다.
- 수치 계산은 결정론적 계산기와 검증된 물리/수치 모델이 담당한다. LLM은 근거 설명, 제한된 선택, 추가 정보 요청을 맡는다.
- 인과관계·성공확률·확신도·측정 정밀도를 근거 없이 만들지 않는다. 자료/모델이 부족하면 보류한다.
- 자동선택만으로 외부 코드, CFD, 장비, 실험 조건을 실행하지 않는다. 사람 검토 및 안전 게이트를 통과시킨다.
- 목표 하드웨어는 MacBook Air M5, 통합 메모리 24GB. AI 피크 약 12GB 목표는 전체 RAM 한도와 구분하고 실제 기기에서 측정한다.
- 사용자가 선택한 Gemma 계열은 교체 가능한 백본 후보로 둔다. JEV는 실험에서 다음 행동/도구를 선택하는 별도 Decision Head이며 분석 도구를 대체하지 않는다. 모델 가중치는 저장소에 포함하지 않는다.

## 기준선

| 항목 | 2026-10-30 기준 증거 |
|---|---|
| 최신 main | 0ccad66006c311c30b96af4233377cab0f720d0d, 원격과 일치 확인 |
| Phase 3 작업 검증 | backend 전체 89 tests passed; npm run build 성공(Vite 6.4.3, 1756 modules). 경고는 SQLAlchemy/Starlette/SWIG deprecation 중심 |
| 로컬 DB | Alembic 0003_science_compat; Phase 3 전 백업 보관; observations 265 중 LITERATURE 173, SYNTHETIC_DEMO 92, LAB_RECORD/LAB_RESULT 0 (현재 local DB에는 이들 유형의 별도 데이터 없음); reference 실험에서 lab로 잘못 분류된 observation 0 |
| 백업 | data/backups/lab_process_pre_phase3_2026-10-30.db (이번 출처 분류 수정 전) |
| API smoke | TestClient startup 및 /api/health, /api/tools/registry, /api/data/observations, /api/optimization/observations/approved 모두 200. 승인 관측값이 없을 때 insufficient 상태를 반환 |
| 제한 | reviewer 표시이름은 인증되지 않음; 원격 GitHub Actions 결과는 미확인; 실제 OpenFOAM/모델 성능은 이 작업에서 검증하지 않음 |

각 표 행은 독립 ID로 관리한다. “완료 조건/검증”, “관련 소스·대안”, “커밋”, “남은 일”을 모든 요구에 기록한다. 대표 파일은 모듈 분리 시 갱신한다.

## Phase 0 — 원본 보존, 안정화, 비교와 실패 분석

| ID | 요구사항 상세 | 우선순위 | 상태 | 관련 소스·구현/대안 | 완료 조건 및 현재 검증 | 커밋 | 남은 작업·의존성 |
|---|---|---:|---|---|---|---|---|
| STAB-001 | 점진적 수정, 원본 보존, migration 전 백업 및 복구 | P0 | VERIFIED | backend/app/main.py, db/database.py, data/backups | 실제 DB integrity ok, 백업/현행 핵심 행 수 동일; 전체 81 tests | 0ccad66 | 별도 임시 DB에 백업 복원하는 자동 테스트 |
| STAB-002 | 변수 이름만으로 비교하지 않고 공정 버전·단계 순서/유형/이름·정의·재료를 사용; 같은 이름의 여러 단계와 반복변수 보존 | P0 | VERIFIED | backend/app/services/experiment/compare.py, failure_analysis/service.py | 단계/중복변수 회귀 테스트 및 81 tests 통과 | 0ccad66 | 안정적인 parameter ID/alias 사전 |
| STAB-003 | 같은 알려진 버전 비교가 기본; unknown None 버전 차단; 교차버전은 같은 method임을 확인 후 명시; 이름/순서 변경 단계는 mapping 없이는 병합 금지 | P0 | VERIFIED | compare.py, routes.py | unknown/cross-version/method tests 통과 | 0ccad66 | 사용자 단계 mapping API/UI |
| STAB-004 | 데모·실측·문헌을 혼합하지 않음; 비교불가 자료는 별도 표시; 상관을 인과로 표현하지 않음 | P0 | VERIFIED | failure_analysis/service.py, scientific_data.py, routes.py | 데모 혼합 차단, unresolved 분리, UNKNOWN 문구 및 승인 source gate tests | 0ccad66 | 장기 문헌-record link 및 cross-domain audit |
| STAB-005 | 숫자/범주/문자열/논리값, 결측과 0, 단위누락/불일치를 구분; 호환단위만 정규화 | P0 | VERIFIED | compare.py, scientific_data.py | 시간환산, 잘못된 단위, pH, zero/missing/type tests | 0ccad66 | 물리량 사전 및 parameter 정의 버전관리 |
| STAB-006 | 불확도·분해능이 있으면 비교에 반영; 없으면 임의 정밀도 금지; 온도 불확도는 delta 변환 | P0 | VERIFIED | compare.py, scientific_data.py | 불확도 유/무 및 °C/°F delta 테스트 | 0ccad66 | 원본 ProcessVariable의 uncertainty 저장 및 입력 UI |
| STAB-007 | 실패 후보키에 버전·단계·변수·재료·반복순서를 반영; 비교불가 후보는 원인 후보로 승격 금지 | P0 | VERIFIED | failure_analysis/service.py | 서로 다른 단계/재료/반복 후보 보존 테스트 | 0ccad66 | 다수 대조군 반복/민감도 통계 |
| STAB-008 | OpenFOAM 선택 template과 설치/상태검사 경로 일치; 정상 종료 로그만으로 물리 정확성 판정 금지; mesh·수렴·timeout 처리 | P0 | IMPLEMENTED | backend/app/services/simulation/openfoam.py, readiness.py, tests/test_openfoam_plan.py | template/readiness 모의검사 있음 | 969f153 | 실제 VM solver·mesh·convergence·version end-to-end |
| STAB-009 | 기존 API 계약·오류/필수입력 검증 유지, 도메인별 라우트와 서비스 계층으로 점진 분리 | P0 | IN_PROGRESS | backend/app/api/routes.py, schemas/core.py, frontend/src/api/client.ts | 기존 통합 테스트 통과 및 API smoke | 0ccad66 | 대형 routes.py 분리, API 계약/오류 호환 통합 테스트 |
| STAB-010 | 기존 대형 frontend 컴포넌트 분할, any 축소, Pydantic/TypeScript schema 일치, 로딩/오류/취소/재시도와 stale response 관리 | P1 | IN_PROGRESS | frontend/src/components/, api/client.ts, types/index.ts | 타입검사 및 build 통과 | 0ccad66 | 비동기 화면 전환·취소 및 컴포넌트 테스트 |
| ARCH-001 | routes.py를 experiments/materials/papers/analysis/simulation/decisions/optimization/assistant API 모듈로 점진 분리하고 공통 오류·응답 schema 및 기존 route 호환을 유지 | P1 | NOT_STARTED | backend/app/api/routes.py | 현 routes.py에 집중된 구조를 확인; 전체 test baseline은 통과 | — | endpoint별 migration/contract tests부터 분리 |
| ARCH-002 | llm.py의 문장 생성, 기존 Gemma 후보 token 선택, JEV 추론, tool 선택/실행, 의미 매핑, 모델 resource lifecycle를 독립 service로 분리 | P1 | NOT_STARTED | backend/app/services/llm.py, tool_registry.py | 현재 registry 경계만 존재 | — | API 분리와 provider 계약 정의 후 순차 이관 |

## Phase 1 — 정규화 데이터, 승인 검토 및 마이그레이션

| ID | 요구사항 상세 | 우선순위 | 상태 | 관련 소스·구현/대안 | 완료 조건 및 현재 검증 | 커밋 | 남은 작업·의존성 |
|---|---|---:|---|---|---|---|---|
| DATA-001 | additive observation schema: topic/experiment/version/step/parameter/material, original/normalized value+unit, type, uncertainty, replicate, source type/id, analysis run, review status, created_at | P0 | VERIFIED | backend/app/db/models.py ScientificObservation, scientific_data.py | 기존 원본 유지; 265 observation; DB integrity와 migration test | 0ccad66 | 독립 Parameter/Material 정규 사전 |
| DATA-002 | Pint 정규화; 수치·범주·논리·문자열·pH 처리; ambiguous unit 자동환산 금지; 오류 명시 및 원문 연결 | P0 | VERIFIED | scientific_data.py | 정상/unknown unit, pH, 값 종류, uncertainty tests | 0ccad66 | 차원별 표준단위 registry 및 version |
| DATA-003 | 반복실험별 개별 관측·replicate_id·측정불확도와 변동성 보존 | P0 | IMPLEMENTED | ScientificObservation replicate_id/measurement_uncertainty | 필드와 정규화 지원 | 0ccad66 | 기록 UI/API, 반복 산포 계산 및 실데이터 검증 |
| DATA-004 | 실측·결과·분석파생·문헌·시뮬레이션·데모를 분리; 원본 파일 hash, 분석 tool/version/settings 연결 | P0 | IN_PROGRESS | models.py, routes.py, MeasurementReviewEvent | 분석 run 원본/hash/tool 기록, 출처 분리 tests | 0ccad66 | 문헌/시뮬레이션 backfill과 모든 분석 설정 정형화 |
| DATA-005 | PENDING→COMPUTED→REVIEWED→ACCEPTED/REJECTED; 계산상태와 과학검토 분리; 승인 취소/재검토도 append-only | P0 | VERIFIED | models.py, routes.py, frontend AnalysisPanel.tsx | 승인/거부순서, 조기승인 차단, 이력 API tests | 0ccad66 | 실제 기존 측정의 일괄 검토; 인증된 reviewer ID/권한 |
| DATA-006 | reviewer·시각·의견·사유·분석 프로그램/version·원본 hash·설정 저장 | P0 | IN_PROGRESS | MeasurementReviewEvent, routes.py | 이벤트 이력 및 metadata 필드 테스트 | 0ccad66 | reviewer 인증, observation 재검토 UI, 원본 파일 연계 전수검증 |
| DATA-007 | 승인된 실측 조건/결과만 학습조회에 반환; 시뮬레이션·문헌·데모/오류값 혼입 금지 | P0 | VERIFIED | GET /api/optimization/observations/approved | 필터 및 API smoke 200, 빈 실측 승인자료를 insufficient로 보고 | 0ccad66 | version/campaign별 학습·검증셋 contract |
| DATA-008 | main.py 임시 schema migration을 Alembic으로 이동; SQLite 호환, backup, idempotence, 원본 보존, rollback 복구 절차 | P0 | VERIFIED | backend/alembic.ini, backend/migrations/, main.py | 0001-0003 반복 migration·legacy 행 보존 tests; 실제 revision 0003 및 백업 확인 | 0ccad66 | 실제 backup restore 자동 회귀테스트, FK 전체 검사 |
| DATA-009 | FK 활성화/참조 무결성/orphan·중복·변환실패 검사 | P0 | IN_PROGRESS | db/database.py, models.py, migrations | SQLite integrity ok, FK 설정 및 migration tests | 0ccad66 | 실제 PRAGMA foreign_key_check, 모든 관계 orphan audit |
| DATA-010 | 원본을 수정/삭제하지 않는 재실행 안전 backfill, 이전/실패 건수 및 복구 이력 기록 | P0 | IMPLEMENTED | main.py backfill_scientific_observations | source_id dedupe, 265 existing observation, 원본 count 유지 | 0ccad66 | 영구 migration report/실패 카탈로그와 복구도구 |

## Phase 2 — PDF/RAG/근거와 장비 분석

| ID | 요구사항 상세 | 우선순위 | 상태 | 관련 소스·구현/대안 | 완료 조건 및 현재 검증 | 커밋 | 남은 작업·의존성 |
|---|---|---:|---|---|---|---|---|
| RAG-001 | PDF 파싱/검증 후 Paper, chunks, summary, topic 연결을 원자적으로 저장; 오류 시 전체 롤백 | P0 | IMPLEMENTED | backend/app/services/ingestion/pdf.py, tests/test_pdf.py | PDF 회귀 테스트 포함 전체 pytest 통과 | 969f153 | 실패시 DB·파일 원자성 통합테스트 강화 |
| RAG-002 | 손상/대용량 PDF, 페이지/크기/처리시간 제한, hash, file cleanup 및 OCR/복잡문서 경계 처리 | P1 | IN_PROGRESS | ingestion/pdf.py, upload APIs | 일부 validation 테스트 | 969f153 | 자원제한·timeout·OCR 레이아웃 처리·부하 테스트 |
| RAG-003 | FTS5 추가/수정/삭제 동기화, topic 격리, index 재구축 방지 및 원문 page provenance | P0 | IMPLEMENTED | retrieval modules, IMPROVEMENT_AUDIT_2026-10-30.md | 기존 검색 경로 동작 | 969f153 | update/delete/topic leak/재빌드 회귀테스트 |
| RAG-004 | 논문 요약은 후보 탐색 색인용; 필요한 원문 excerpt만 컨텍스트에 넣고 page/paragraph/source ID를 인용 | P1 | IMPLEMENTED | backend/app/services/retrieval/, ingestion/pdf.py | 요약→원문 연결 설계가 기존 구현에 기록 | 이전 기능, 최초 commit 추적 필요 | recall/citation/page correctness labelled benchmark |
| RAG-005 | BM25와 의미검색/reranker 비교; 부족한 근거는 UNKNOWN; 표·수식·OCR 결과의 extraction provenance 별도 | P1 | NOT_STARTED | retrieval/provider.py, docs/AI_ARCHITECTURE.md | hybrid retrieval 및 OCR 평가셋 없음 | — | 한국어·영어 query/evidence 자료, 로컬 모델 자원 비교 |
| RAG-006 | citation ID 실제 존재·topic 소속·주장 근거성 검토를 분리; 실측/시뮬/문헌/모델지식 혼동 방지 | P0 | IN_PROGRESS | services/evidence/claims.py, assistant schemas | citation identity checking/source labels 일부 구현 | 969f153 | entailment/주제 교차 인용/허위 citation/인과 표현 공격테스트 |
| RAG-007 | PDF/검색/OCR 문서는 untrusted text; prompt injection을 명령으로 수행하지 않음 | P0 | NOT_STARTED | assistant/retrieval/security | 전용 보안검증 없음 | — | 고정 tool ACL과 injection test corpus |
| RAG-008 | native text와 OCR/layout extraction을 분리하고 PDF 제목·초록·본문·표·수식별 provenance와 page/region을 보존; 표/수식 추출을 무조건 신뢰하지 않으며 ambiguous extraction은 검토 대상 | P1 | IN_PROGRESS | backend/app/services/ingestion/pdf.py, retrieval modules | 현재 text-layer 경로 및 page chunks 존재 | 969f153 | scanned/table/equation PDF 검증셋, OCR adapter 및 human review 필요 |
| RAG-009 | 웹/논문 검색은 신뢰 가능한 학술·공인 출처와 식별자/URL을 기록; discovery metadata와 실제 확인한 논문 본문 evidence를 분리하고 검색결과를 lab fact로 자동 저장하지 않음 | P1 | IMPLEMENTED | papers/discovery routes, retrieval, AI_ARCHITECTURE.md | Crossref discovery와 PDF upload/index 경로 구분됨 | existing docs | 현재 DOI/PDF acquisition·publisher access·결과 신뢰성 integration tests 강화 |
| ANA-001 | XRD background removal, noise, peak parameter validation, Gaussian/Lorentzian/pseudo-Voigt fit, center/area/intensity/FWHM/uncertainty | P1 | IN_PROGRESS | backend/app/services/material_analysis/, docs/XRD_PHASE_CANDIDATES.md | local maxima preview만 있고 제한 표기 | 기존 pilot | 합성 golden pattern·전문가 reference; 피팅/불확도 미구현 |
| ANA-002 | XRD wavelength/calibration, d-spacing·lattice/Scherrer conditions, full-pattern texture, overlap/mixtures, COD candidate vs confirmed phase; Rietveld 검토 | P1 | IN_PROGRESS | material_analysis/, docs/XRD_PHASE_CANDIDATES.md | COD 후보비교 존재, 확정동정 아님 | 기존 + 0ccad66 | 실제 장비 metadata 및 전문가 ground truth, 정량상분율 미완료 |
| ANA-003 | SEM/TEM calibrated scale, denoise, 객체 분리·길이/직경/면적분포/밀도/방향 및 원본-mask 검토 | P1 | IN_PROGRESS | material_analysis/service.py, docs/MATERIAL_DATA_REVIEW.md | 전역 Otsu preview | 기존 pilot | 전문가 label/실제 이미지 ground truth, 객체분리 및 신뢰도 검증 |
| ANA-004 | AFM plane leveling, Sa/Sq/Sz 정의, artifact/outlier/mask, calibration, uncertainty, 반복 scan | P1 | IN_PROGRESS | material_analysis/service.py | roughness preview | 기존 pilot | 표준 AFM 검증 값·반복 스캔 |
| ANA-005 | 모든 분석 run에 algorithm ID/version, 파라미터, 시간, input hash, 원본·파생물 및 리뷰 연결; reference 데이터 평가 | P0 | IN_PROGRESS | models.py, routes.py, material_analysis/ | checksum/tool/artifact/review 연결 테스트 | 0ccad66 | settings와 elapsed time 정형화, 전문가 검증 fixture |
| ANA-006 | 장비 상황별 그래프/축·단위·스케일·mask·후보상 표현과 원본 run 추적 | P1 | IMPLEMENTED | frontend/src/components/AnalysisPanel.tsx, api/client.ts | production build success | 0ccad66 | 실제 여러 제조사 포맷의 browser E2E |
| ANA-007 | 도구 선정 시 GSAS-II, Gwyddion, HyperSpy/eXspy, py4DSTEM/LiberTEM, ilastik 등 공개 전문도구를 modality·실제 파일 형식·측정 metadata에 맞춰 평가; 설치 여부만으로 검증됨이라 하지 않음 | P1 | NOT_STARTED | docs/MATERIAL_DATA_REVIEW.md, tool registry | 현재 deterministic pilot tool 위주 | — | 실제 exports·전문가 검증자료와 OS/library/license/resource 비교 |

## Phase 3 — 물리 시뮬레이션과 Tool Registry

| ID | 요구사항 상세 | 우선순위 | 상태 | 관련 소스·구현/대안 | 완료 조건 및 현재 검증 | 커밋 | 남은 작업·의존성 |
|---|---|---:|---|---|---|---|---|
| SIM-001 | PHREEQC 입력 화학량·단위/pH/T/전하수지/활동도/착물/고체상/database 확인; 평형 과포화와 실제 침전·성장·수율을 구분 | P0 | IMPLEMENTED | simulation services, docs/PH_SIMULATION.md, docs/LITERATURE_VALIDATION_TEST_REPORT.md | 가정/한계 및 integrated tests | 기존 기능 | 실제 reference solution 대조와 charge/database 적합성 강화 |
| SIM-002 | OpenFOAM 설치/template/geometry/mesh/convergence/timeout/cancel/restart/solver version 검증, 사용자 승인 후 실행 | P0 | IMPLEMENTED | simulation/openfoam.py, readiness.py, docs/SIMULATION_ENGINES.md | 준비 계획과 mocked tests, Registry approval gate | 969f153, 0ccad66 | 실제 VM solver 및 유동/동력 validation; durable queue 필요 |
| SIM-003 | 수용액 혼합·마그네틱바·Rushton CFD·수열·spin coating·건조·열처리 도구별 공개 source/물리모델, 가정/범위/불확도/입력 출처 명시 | P1 | IN_PROGRESS | backend/app/services/simulation/, docs/HYDROTHERMAL_AND_STIRRING_MODELS.md, COATING_DRYING_THERMAL_MODELS.md, SOLUTION_MIXING_SIMULATION_PLAN.md | 일부 계산과 문헌계획 존재 | 기존 + 0ccad66 | 각 모델별 golden data와 실험 대조; 범위 밖 도구선택 차단 |
| SIM-004 | 성장 길이/형태는 검증된 재료별 kinetics가 없으면 정량 예측 금지; 모델 없는 나노로드 성장은 unsupported로 표시 | P0 | VERIFIED | docs/HYDROTHERMAL_AND_STIRRING_MODELS.md, tool_registry.py | registry unsupported conditions 명시 | 0ccad66 | 재료별 실험/kinetic data가 확보될 때만 재검토 |
| SIM-005 | 단계별 계산 값을 다음 모델에 typed input/source/version으로 넘기고 실패·누락 시 중단하며 provenance 보존 | P1 | IN_PROGRESS | simulation services, tool_registry.py, docs/SIMULATION_ENGINES.md | 일부 coated substrate context handoff | 기존 | 실제 여러 단계 chaining API/UI·복구·통합 테스트 |
| SIM-006 | Tool Registry metadata: id/name/version/category, inputs/modality/units, output schema, applicability/unsupported, runtime/memory, uncertainty, validation, execution 및 실패 policy. 등록 대상은 XRD peaks/COD candidates, AFM, SEM/TEM, PHREEQC equilibrium/pH sweep, OpenFOAM Rushton, hydrothermal, spin coating, experiment comparison/data quality다. | P0 | VERIFIED | backend/app/services/tool_registry.py, GET /api/tools/registry | 11개 도구 등록; runtime/memory 미측정은 null; API smoke/81 tests | 0ccad66 | 실측 리소스/각 tool schema adapter와 표준 실패/재시도 contract |
| SIM-007 | 입력·물리량·단위·적용 범위·자원·검증·승인으로 READY/MISSING_INPUT/UNSUPPORTED/UNAVAILABLE/REQUIRES_REVIEW/ABSTAIN 결정 | P0 | IMPLEMENTED | tool_registry.py, recommend endpoint | 실제 숫자·단위 검증 및 상태 분기 테스트; 키워드 단독 readiness 제거 | 0ccad66 | 이름 토큰 검사를 typed physical input validator로 교체 |
| SIM-008 | 공통 validate→prepare→execute→verify→persist 계약; 이번 단계에선 준비 기반, 위험한 자동 실행 금지 | P0 | IN_PROGRESS | tool_registry.py, POST /api/tools/execute, existing analysis API | PHREEQC/Data Quality 실행 경로; 결과 검증·출처 저장·중복 결과 재사용 API tests | 현재 Phase 3 작업 | 공통 adapter protocol 정식 분리, 모든 실행 오류/취소/timeout 상태, retry/cancel, OpenFOAM orchestration |
| SIM-009 | 후보 simulation library를 문제에 따라 검토: kinetics, reaction-diffusion/FEM, phase-field, DFT, LAMMPS, Cantera/Reaktoro 및 PHREEQC/OpenFOAM. applicability·공개 구현·검증자료 없이는 억지 연결하지 않음 | P1 | IN_PROGRESS | docs/SIMULATION_ENGINES.md, model-specific plans | 여러 기존/후보 엔진이 문서화됨 | prior docs | 각 도구의 논문 근거, 자원, chemistry/geometry fit 및 Mac 실행 가능성 조사 필요 |
| SIM-010 | 한 단계 도구의 검증된 산출값만 다음 도구 입력으로 넘기며 단위·재료 identity·출처·불확도를 전달; chain 중간 실패·입력 누락은 해당 후속 run을 막음 | P1 | IN_PROGRESS | simulation services, tool_registry.py | 일부 context handoff | existing | chained typed schemas, failure propagation and end-to-end test |

## Phase 3 구현 감사 — 과학 도구 자동 선택·실행·검증 (2026-10-30)

이 표는 첨부 Phase 3 프롬프트의 하위 요건을 누락 없이 추적한다. 구현과 검증은 구분했다. `SIM-*`와 `ORCH-*` 상위 항목과 연결되며 다음 상세 ID를 임의로 축약하지 않는다.

| ID | 요구사항 상세 | 우선순위 | 상태 | 관련 소스·구현/대안 | 완료 조건 및 현재 검증 | 커밋 | 남은 작업·의존성 |
|---|---|---:|---|---|---|---|---|
| P3-DATA-01 | 문헌 reference 관측과 실제 실험·합성 demo 출처를 분리하고 재실행 가능한 backfill 유지 | P0 | VERIFIED | main.py `classify_observation_source`, `backfill_scientific_observations`; data/backups/lab_process_pre_phase3_2026-10-30.db | 265개 observation 재분류; LITERATURE 173, SYNTHETIC_DEMO 92, reference→LAB 오분류 0; 분류 단위 테스트 | 이번 Phase 3 작업 | 영속 migration report, 실패/복구 catalog 및 별도 실제 LAB_RECORD 자료의 승인 흐름 |
| P3-REG-01 | 변수명 키워드만으로 readiness를 READY로 만들지 않고 숫자/단위/물리 차원을 확인 | P0 | IN_PROGRESS | tool_registry.py `_number_with_unit`, PHREEQC validators | PHREEQC pH·온도·원소총량 단위 검사 및 회귀 테스트 | 이번 Phase 3 작업 | 모든 시뮬레이션 입력별 Pydantic 단위/차원 schemas, 범위·누락·미확인 상태 체계 |
| P3-REG-02 | 원본값·단위와 normalized 값 연결, process step 및 material 문맥 반영 | P0 | IN_PROGRESS | ScientificObservation, ScientificStateBuilder | 기존 값은 읽기만 하며 PHREEQC 사용자 입력은 typed request 검증 | 기존 + 이번 Phase 3 작업 | Registry state에서 ScientificObservation 원본/정규화·material identity·normalization_error 직접 사용 |
| P3-REG-03 | 연구 목표·도구 적합성·기존 결과를 이용하며 첫 READY 도구를 무조건 선택하지 않음 | P0 | VERIFIED | tool_registry.py `RuleBasedDecisionPolicy`, GET recommend `goal`, AnalysisPanel goal picker | 목표별 도구 제한, 완료 분석은 ALREADY_ANALYZED, 단위 검증은 RUN_DATA_VALIDATION; 단위/API tests | 이번 Phase 3 작업 | 현실 평가셋으로 도구 선택·보류 정확도 측정 |
| P3-REG-04 | READY/ALREADY_ANALYZED/REANALYSIS_REQUIRED/MISSING_INPUT/UNSUPPORTED/UNAVAILABLE/REQUIRES_REVIEW/ABSTAIN 전 상태를 사용 | P0 | IN_PROGRESS | tool_registry.py readiness literal, measurement readiness | ALREADY_ANALYZED 및 MISSING_INPUT/REQUIRES_REVIEW 등 일부 검증 | 이번 Phase 3 작업 | 각 도구·상태 전이마다 테스트 및 재분석 hash/parameter 판단 |
| P3-REG-05 | data quality 선택은 독립 RUN_DATA_VALIDATION 행동; 설명 생성 행동과 혼동 금지 | P0 | VERIFIED | RuleBasedDecisionPolicy, POST /tools/execute, AnalysisPanel | goal-driven action·실행 API mock integration tests | 이번 Phase 3 작업 | 모든 사용자 연구 목표와 번역·접근성 세부 검증 |
| P3-ADAPT-01 | Pydantic 구조 입력·도구별 실행 adapter, LLM 문자열을 명령/코드로 실행하지 않음 | P0 | IN_PROGRESS | ToolExecutionRequest, `/api/tools/execute`, 기존 material analysis API | 명시적 allowlist; PHREEQC equilibrium/sweep의 Pydantic 입력 처리; 데이터 검증 직접 실행 | 이번 Phase 3 작업 | 공통 Adapter protocol의 `validate_inputs/prepare/execute/validate_outputs/persist`로 모든 도구 통일 |
| P3-ADAPT-02 | XRD/AFM/SEM/TEM 기존 엔진을 실제 파일 분석 및 원본/hash/계산 결과 저장에 연결 | P0 | VERIFIED | material_analysis/service.py, POST /analysis/run, MaterialAnalysisRun | 기존 API 테스트에서 영상처리·원본/hash/artifact 확인; 기기별 수치분석 모듈 테스트 | 기존 기능, 이번 Phase 3 재검토 | 알고리즘/parameter version을 모든 결과에 빠짐없이 기록하고 원본별 reanalysis를 구분 |
| P3-ADAPT-03 | XRD 축 단위/파장/후보 동정의 한계와 COD 후보를 확정 상동정과 구분 | P0 | IN_PROGRESS | XRD analyzer/phase_match.py, AnalysisPanel | local peak 및 COD 후보 UI/API 기존 검증; 상 후보 일치도는 확률 아님 | 기존 기능 | 파장/장비 메타데이터 typed mandatory 검증, FWHM/격자/불확도 고도화 |
| P3-ADAPT-04 | SEM/TEM 크기 보정, Otsu 분할/객체 연결, 중첩·스케일 오류 검토 | P0 | IN_PROGRESS | microscopy analyzer, material_analysis API | 이미지 segmentation 및 scale parameter API tests | 기존 기능 | 고급 instance segmentation/중첩 오류 QA 및 원본 overlay 검수 테스트 |
| P3-ADAPT-05 | AFM 높이맵 단위·plane leveling·Sa/Sq/Sz·artifact review 연결 | P0 | IN_PROGRESS | AFM analyzer | 입력 grid·거칠기 계산 unit tests | 기존 기능 | calibration axis/height units, scan artifact detection and algorithm parameters end-to-end |
| P3-ADAPT-06 | 승인상태/동일 공정버전/단계별 조건 비교 및 문헌/시뮬/실측 구분 | P0 | IN_PROGRESS | compare.py, scientific_data.py, approved observation APIs | provenance category 및 method comparison 기능 일부 존재 | 기존 기능 | 승인·정규화 관측 상태를 tool selection/comparison 전체에서 통합 시험 |
| P3-SIM-01 | PHREEQC 입력·단위·종·database 검사, 실행·결과·가정 저장, 평형과 침전/성장을 분리 | P0 | IN_PROGRESS | phreeqc.py, `POST /api/tools/execute`, SimulationRun | 실제 PHREEQC-3 계산: Ca/C(4), pH 8.3, Calcite, 8 species, SI 0.3068; database에 없는 상은 null/unknown; API persist/reuse integration test | 이번 Phase 3 작업 | 전하수지/화학계 적합성을 실행 전 정량검증하고 설치 버전/database hash 기록 |
| P3-SIM-02 | OpenFOAM 템플릿/geometry/VM 검증 후 명시적 사용자 승인; 잘못된 형상은 차단 | P0 | IN_PROGRESS | existing openfoam plan/run API, validation and approval guards | Registry가 OpenFOAM을 자동 호출하지 않으며 execute API는 거부; 기존 계획/승인 테스트 | 기존 기능 + 이번 Phase 3 작업 | 실제 VM 설치/template run·mesh/convergence/timeout; 승인된 외부 실행만 검증 |
| P3-SIM-03 | 기타 기존 시뮬레이터의 요구 입력·범위·가정·실행 가능성을 표시하고 미연결 모델을 차단 | P1 | IN_PROGRESS | existing simulation services, ToolRegistry | 등록은 되어 있으나 미구현 typed adapter는 MISSING_INPUT 처리 | 기존 + 이번 Phase 3 작업 | hydrothermal/spin coating/stirring/drying/thermal의 입력검증·실행/persist/통합 평가 |
| P3-VAL-01 | 결과 schema·finite·범위·단위·필수 출력 검증, tool/model provenance와 가정 연결 | P0 | IN_PROGRESS | `ResultValidator`, SimulationRun/MaterialAnalysisRun | PHREEQC 필수 출력/model ID 및 finite 검사; microscopy/XRD/AFM output guard tests | 이번 Phase 3 작업 | 단위/과학적 범위별 validator registry와 모든 출력 provenance/version |
| P3-VAL-02 | 원본, 파생 분석, simulation, paper, synthetic, AI reasoning source type 격리 | P0 | VERIFIED | ScientificObservation/source types; corrected backfill | reference 173 / demo 92 분리; simulation scalar는 SIMULATION으로 기록; 실측 범주에 섞인 reference 0 | 이번 Phase 3 작업 | AI reasoning 전용 source taxonomy 및 cross-topic source access tests |
| P3-ORCH-01 | 상태→목표기반 후보→gate→실행→출력검증→출처 저장→추가/보류 파이프라인 | P0 | IN_PROGRESS | tool_registry.py, routes.py | goal recommendation + data quality/PHREEQC execution; inputs, outputs, saved provenance; test coverage | 이번 Phase 3 작업 | 분석+시뮬 단계 orchestration, typed handoff, retry/cancel/resume queue |
| P3-ORCH-02 | 중복실행 방지, 상태·실패·재시도·취소·timeout·CPU/RAM 제한 | P0 | IN_PROGRESS | SimulationRun and hash/input based completed-result reuse | 같은 PHREEQC 입력의 재계산을 재사용; 실패/invalid_output은 저장 | 이번 Phase 3 작업 | DB unique idempotency key, concurrency race tests, queue/resource caps, retry/cancel/timeout |
| P3-JEV-01 | RuleBasedDecisionPolicy가 향후 JEV와 동일 interface를 사용하고 Safety gate와 설명 생성을 분리 | P1 | IN_PROGRESS | DecisionPolicy Protocol, RuleBasedDecisionPolicy, ValidationGate | JEV head 부재 상태 표시; 규칙 선택과 execution gate 분리 | 기존 + 이번 Phase 3 작업 | JEV model/action schema/evaluation data; 현재 학습 head 미구현 |
| P3-UI-01 | 목표 선택, 추천 근거, 누락 데이터, 실행/검토/결과 이력 UI | P1 | IN_PROGRESS | AnalysisPanel goal picker, data-quality execute button; existing analysis/simulation screens | TypeScript production build 및 API integration tests | 이번 Phase 3 작업 | 공통 실행 진행/취소/오류/재시도 이력 화면, OpenFOAM approval flow E2E |
| P3-PERF-01 | 선택 정확도, abstain, 성공율, 실행/선택 시간, LLM 비율, RAM 측정 | P2 | NOT_STARTED | — | 측정 없음 (임의 성능 주장 없음) | — | 대표 평가셋과 MacBook에서 재현 가능한 profiling harness |
| P3-CI-01 | Phase 3 회귀/evaluation 테스트를 GitHub Actions에서 실행 | P1 | IMPLEMENTED | `.github/workflows/ci.yml` runs full pytest and npm build; new tests are included automatically | Workflow config reviewed; local 89 pytest and build pass | 이번 Phase 3 작업 | GitHub-hosted workflow execution result remains unverified |

## Phase 4 — 사용자 연구 흐름과 UI

| ID | 요구사항 상세 | 우선순위 | 상태 | 관련 소스·구현/대안 | 완료 조건 및 현재 검증 | 커밋 | 남은 작업·의존성 |
|---|---|---:|---|---|---|---|---|
| PROD-001 | 연구주제→공정 방법/버전→날짜별 개별 실행→단계별 조건/부분 실험/결과 계층; 같은 방법 조건 변경과 공정 분기를 구분 | P0 | IMPLEMENTED | method/version/experiment models and frontend workspaces | 기존 기능 구현 | 이전 구현 commit 추적 필요 | 사용자 여정 E2E로 version/date/step 연결 확인 |
| PROD-002 | 공정 변경을 기존 값을 덮지 않고 v1.1 식 분기로 남기고 분기시점·현재 주 tree를 표시 | P0 | IMPLEMENTED | process tree UI/API | 기능 구현 | 이전 구현 commit 추적 필요 | 단계 매핑과 버전 migration 테스트 |
| PROD-003 | 공정 단계별 박스 기반 조건/단위/재료 입력 및 재사용 가능한 소재 라이브러리; 모르는 값 공란 허용 | P1 | IMPLEMENTED | MethodWorkspace, method/material schemas | 기존 화면 기능 | 기존 commit 추적 필요 | 입력 실수·신규 사용자 입력시간 usability 평가 |
| PROD-004 | 과정 탭은 과정만, 결과 탭은 날짜별 결과만; 세부 실험을 접고 펼치고 공정 경로/분기를 읽기 쉽게 한다 | P1 | IMPLEMENTED | frontend experiment/process components | 사용자 요구 반영 | 기존 commit 추적 필요 | browser regression/접근성 검사 |
| PROD-005 | 측정 데이터·사진·중간 관측을 해당 실행/단계에 연결; 분석은 기록 흐름에서 실행; 원본/파생 결과 구별 | P1 | IMPLEMENTED | AnalysisPanel, analysis API, ExperimentAttachment | run/original/hash/artifact 연결 및 build | 기존 + 0ccad66 | 여러 측정 일괄분석 UI E2E/결과 workflow |
| PROD-006 | 한눈에 읽기, 빠른 시작/간결 입력, Korean/English 지원, 가로/세로 레이아웃 및 단계 탐색 usability | P2 | IMPLEMENTED | frontend/src/, language.tsx, style.css | TypeScript/build 성공 | 기존 + 0ccad66 | 실제 사용자 usability 및 keyboard/screen reader |
| PROD-007 | 분석을 통해 개선 후보/다음 조건을 근거·불확도·누락·제약과 함께 보되 원인/성공률을 과장하지 않고 적용 전 승인 | P0 | NOT_STARTED | future optimization UI | 아직 추천 optimizer 없음 | — | OPT-001~006 필요 |

## Phase 5 — 의사결정 및 Bayesian Optimization

| ID | 요구사항 상세 | 우선순위 | 상태 | 관련 소스·구현/대안 | 완료 조건 및 현재 검증 | 커밋 | 남은 작업·의존성 |
|---|---|---:|---|---|---|---|---|
| ORCH-001 | ScientificStateBuilder가 topic/method/version/run/steps/materials/results/modalities, 누락/승인/provenance/uncertainty를 읽기 전용 state로 구성 | P0 | IN_PROGRESS | backend/app/services/tool_registry.py | 실행 이력 상태·도구 및 분석 결과를 state에 반영; 전체 tests | 현재 Phase 3 작업 | 승인, source type, uncertainty, OOD, observation normalization을 전체 context에 반영 |
| ORCH-002 | ToolRegistry, DecisionPolicy, ValidationGate, ToolExecutor, ResultValidator, ExplanationProvider 분리; 모델 선택만으로 도구 실행 불가 | P0 | IN_PROGRESS | tool_registry.py, routes.py | PHREEQC와 저장된 분석 결과 adapter 실행/검증, CFD 승인 차단 통합 테스트 | 현재 Phase 3 작업 | 모든 분석/시뮬 도구의 동일한 validate/prepare/execute/persist adapter 계약; explanation wiring |
| ORCH-003 | RUN_ANALYSIS, RUN_SIMULATION, RUN_OPTIMIZATION, REQUEST_DATA, REVIEW_RESULT, GENERATE_EXPLANATION, ABSTAIN 구조화 행동 | P0 | IN_PROGRESS | RuleBasedDecisionPolicy, registry API/UI | 연구 목표 입력 선택, RUN_DATA_VALIDATION, 중복 분석 보류, 실제 API action 테스트 | 현재 Phase 3 작업 | 모든 action 실행 계약, 정책 평가셋, JEV 인터페이스 통합 (학습 head 없음) |
| ORCH-004 | Gemma는 필요 입력을 질문하고 결과를 설명하되 측정/계산/근거를 창작하지 않음; 대화 전체를 KV에 오래 쌓지 않고 정제 요약/기록으로 필요한 맥락만 조회 | P1 | IN_PROGRESS | backend/app/services/llm.py, assistant interaction, docs/AI_ARCHITECTURE.md | local provider/evidence boundary 일부 구현 | 기존 | 정보 요청·저장·재개, 요약 품질, KV/RAM 실제 벤치마크 |
| OPT-001 | BO 문제에 입력변수 범위/고정변수, 목표 결과·방향, constraints, 비용, 반복수, 불확도, 승인관측값, 실측/시뮬 분리를 정의 | P0 | IN_PROGRESS | approved observations API | 승인된 input/outcome projection·uncertainty/source 일부 | 0ccad66 | OptimizationProblem API/UI/schema 미구현 |
| OPT-002 | Ridge 등 단순 대리모델을 baseline으로 하고 논문·실험 누수 없는 split/OOD를 사용; 문헌 backtest를 앱 추천 성능이라 하지 않음 | P1 | IMPLEMENTED | scripts/evaluate_benchmark_backtest.py, docs/BENCHMARK_BACKTEST_REPORT.md | 논문별 holdout 결과와 한계 설명 | report existing | 앱 campaign 데이터로 independent validation |
| OPT-003 | 승인 실험을 기본으로 GP+Bayesian Optimization 및 constrained acquisition으로 다음 조건 추천; 미검증 score는 성공확률로 표시하지 않음 | P0 | NOT_STARTED | future optimization service | 제품 기능 없음 | — | OPT-001·충분한 비데모 데이터·목표 기준 |
| OPT-004 | Active Learning이 정보가치/불확도/실험비용/위험을 고려; 사람 승인 없이 실제 실험·장비 실행하지 않음 | P1 | NOT_STARTED | future optimizer | 미구현 | — | OPT-003, 승인 프로토콜/기록 |
| OPT-005 | paired data로 시뮬레이션 bias/discrepancy를 보정하고 출처를 유지; sim output은 실측 학습 라벨이 아님 | P1 | NOT_STARTED | ScientificObservation, future calibration module | source-type 구분만 구현 | 0ccad66 | 실제 같은 조건의 sim/lab 자료 |
| OPT-006 | 실험→JEV action→분석/시뮬→BO→연구자 승인→결과→검토의 폐루프를 재현 가능한 campaign으로 보존 | P0 | NOT_STARTED | future campaign schema/API/UI | 전체 chain 미연결 | — | Phase 1, 3, 5 선행 |
| OPT-007 | 평균 예측, Ridge, Random Forest, Gaussian Process 및 필요한 물리제약 회귀를 공정군별 baseline으로 비교; EI 등 acquisition, 다목표·잡음 반복측정·복수 후보를 고려하고 근거 부족 때 탐색/보류 | P1 | NOT_STARTED | benchmark and future optimizer | Ridge 문헌 baseline만 존재 | benchmark report | 최적화 목표/범위/제약 정의와 승인 실험자료 선행 |

## Phase 6 — Shared Transformer JEV, Early Exit, 리소스

| ID | 요구사항 상세 | 우선순위 | 상태 | 관련 소스·구현/대안 | 완료 조건 및 현재 검증 | 커밋 | 남은 작업·의존성 |
|---|---|---:|---|---|---|---|---|
| JEV-001 | 기존 Gemma 후보토큰 선택은 비교 기준선; 독립 JEV Decision Head는 실험 상태로 next action/tool/request/abstain 선택, 분석기 역할과 분리 | P0 | NOT_STARTED | llm.py, future decision module | 현재 학습된 JEV head 없음(Registry 명시) | — | 승인 행동 라벨·기준선 평가셋·checkpoint 접근 |
| JEV-002 | 단일 Transformer 백본에 별도 action head를 공유 연결; structured action, 근거, 누락값, 금지 tool, abstain 반환 | P0 | NOT_STARTED | future model/runtime | interface only | — | 선택된 Gemma 및 교체 모델에서 hidden-state API/license 조사 |
| JEV-003 | 학습 데이터에 정답행동·근거·필요 입력·허용/금지 tool·보류 포함; 알려지지 않은 실험 결과를 라벨로 만들지 않음 | P0 | NOT_STARTED | future labelled dataset | dataset 없음 | — | 전문가 라벨, privacy/license governance |
| JEV-004 | Gemma 백본 및 더 작은 후보를 동일 interface로 비교; head/LM의 중복 적재 방지 | P1 | NOT_STARTED | docs/OPEN_WEIGHT_MODELS_2026.md, runtime | 연구 문서만 존재 | — | Mac 실기기 MLX/model artifacts |
| JEV-005 | Early Exit은 중간 layer 이후 실제 연산을 생략; 입력 충족·OOD·안전·보정 확인 후만 허용 | P2 | NOT_STARTED | future runtime | 미구현 | — | JEV 학습/실측 prerequisite |
| JEV-006 | Temperature scaling, Brier, ECE, OOD, selective classification, risk-coverage로 보정 및 abstain 평가 | P1 | NOT_STARTED | future eval | 미구현 | — | 독립 평가 데이터 |
| JEV-007 | 언어 설명 필요 시 LM Head만 생성; shared KV/hiddens 재사용은 정확성 검증 뒤 사용; 다른 모델 계열의 cache/state 차이 고려 | P2 | NOT_STARTED | future runtime | conditional generation 없음 | — | correctness와 latency baseline |
| JEV-008 | Ollama 설명 경로 기준선/폴백 유지; 중간 layer 제어 필요 시 MLX adapter 평가; 모델 가중치는 저장소에 넣지 않음 | P2 | NOT_STARTED | llm.py, model config | Ollama provider 일부 | 기존 | MLX/공유 weight 및 fallback 검증 |
| JEV-009 | 백본 평가에서 intermediate hidden-state 접근, MLX 구조변경 난이도, 공유가중치, Early Exit 가능성, RAM, 과학 데이터 이해, tool 선택 정확성, 출력 안정성을 같은 조건에서 비교 | P1 | NOT_STARTED | docs/OPEN_WEIGHT_MODELS_2026.md, future eval | 모델 조사 문서만 있고 현 기기 성능 검증 없음 | — | 선택 Gemma와 작은 대체모델의 직접 Mac benchmark |
| PERF-001 | MacBook Air M5 24GB에서 weight/head/KV/Python/API/UI/OpenFOAM VM/GPU·OS memory를 따로 측정; AI 약 12GB 목표는 실제 측정으로 판정 | P1 | NOT_STARTED | future benchmarks | Tool Registry memory fields unknown으로 명시 | 0ccad66 | 실기기 peak RSS/Metal 계측 |
| PERF-002 | 4K/8K context, quantization, model loading, decision/tool latency, Early Exit, LM invocation, throughput, 발열을 같은 workload로 측정 | P2 | NOT_STARTED | future benchmark scripts | 수치 결과 없음 | — | 실행 가능한 JEV/모델 |
| PERF-003 | AI와 기존 8GB Multipass OpenFOAM VM 동시 사용 메모리 압박을 관리하고 필요 시 queue/resource cap 적용 | P1 | NOT_STARTED | simulation worker/runtime | 동시성 자원 테스트 없음 | — | 실제 Mac/VM workload |
| PERF-004 | Gemma 선택안을 포함한 양자화/소형 오픈웨이트 모델을 context별 RAM·속도·정확도·열화로 비교; 앞선 Qwen 후보는 필요 시 비교 기준선으로만 두고 선택 모델을 고정 가정하지 않음 | P1 | NOT_STARTED | docs/OPEN_WEIGHT_MODELS_2026.md, runtime | 보고서 조사만 존재 | — | 현재 노트북의 실측 및 과학 도메인 평가 |
| INFO-001 | 시료·시약 정보가 결정에 필요하면 논문/공인 DB/공급자 자료를 provenance와 함께 검색해 제안; 일반 이름만으로 purity·hydrate·농도·밀도 등을 추측하지 않고 필요값과 단위를 사용자에게 요청하며 모르면 blank로 유지 | P1 | IN_PROGRESS | material lookup, Gemma assistant, ScientificStateBuilder | 소재 정보 및 누락정보 요청 경계 일부 존재 | existing | source-ranked lookup, confirmation workflow, tested material identifier/units and retrieval citations |

## Phase 7 — 보안·UI·테스트·CI·성능과 폐루프

| ID | 요구사항 상세 | 우선순위 | 상태 | 관련 소스·구현/대안 | 완료 조건 및 현재 검증 | 커밋 | 남은 작업·의존성 |
|---|---|---:|---|---|---|---|---|
| SAFE-001 | PDF/장비 업로드 크기·타입·경로·filename을 검사; secret 및 notebook을 외부 모델로 전송하지 않음 | P0 | IN_PROGRESS | upload APIs, ingestion, analysis | 분석 업로드 25MiB 제한 등 일부 | 기존 + 0ccad66 | 전 modality/PDF malware, traversal, secret tests |
| SAFE-002 | long-running worker의 queued/running/cancel/fail/timeout/retry/restart recovery와 중복 방지 | P1 | IN_PROGRESS | simulation services | 일부 상태 추적 | 기존 | durable worker/queue 미구현 |
| SAFE-003 | 안전하지 않은 자동 장비제어·실험 조건 적용·arbitrary code 금지; 사용자 승인 gate | P0 | VERIFIED | tool_registry.py, ValidationGate | CFD 등 human approval 및 prepare-only tests | 0ccad66 | 모든 이후 adapter에 공통 permission integration tests |
| SAFE-004 | local service 접근범위·외부 network authentication, 파일 upload type/size/path 및 path traversal, prompt injection, OS 명령/파일삭제 차단, CPU/RAM/time cap, 중요 오류·계산 audit를 관리 | P0 | IN_PROGRESS | main.py CORS, upload APIs, simulation worker | 업로드 일부 제한, CORS 존재 | existing | authentication/authorization, command isolation, quotas, security tests 미완료 |
| SAFE-005 | 실험 위험 경고·범위 제한을 시스템 정책으로 enforce; LLM/JEV 권고는 실행승인이 아니며 실제 장비·실험 조작은 승인된 사람만 수행 | P0 | IN_PROGRESS | future decisions/simulation APIs | 현재 일부 tool review policy | 0ccad66 | 역할기반 사용자 승인과 audit trail, 실패 시 안전상태 정의 |
| AUTH-001 | 다른 연구자/사용자도 사용할 수 있게 사용자·연구실별 인증/인가 및 주제·DB·논문·첨부 격리를 제공; 로컬 단일사용자 경로와 외부 네트워크 접근 정책을 명시 | P1 | NOT_STARTED | backend auth, database access layer, frontend session | 현재 로컬 단일 workspace이며 인증/tenant 구현 확인 안 됨 | — | 사용자 수/공유모델 선택, 개인정보·기관운영 요구 및 schema 결정 |
| UI-001 | 통합분석 화면에서 원 run, 과정, 결과, 검토상태, 출처, 도구 추천과 필요한 입력 표시; 오류/로딩/재시도 처리 | P1 | IN_PROGRESS | frontend/src/components/AnalysisPanel.tsx | 검토·추천 UI, production build | 0ccad66 | 표준관측값 전용 review table 및 browser E2E |
| UI-002 | optimizer UI에 변수 범위/고정/목표방향/제약/비용·후보·근거·불확도, 제안 승인 기능 | P1 | NOT_STARTED | future optimization frontend | 기능 없음 | — | OPT-001/003 |
| UI-003 | JEV 행동·abstain·input gaps·도구실행·latency/memory/LM/exit을 실제 telemetry로 표시 | P2 | NOT_STARTED | future monitoring UI | learned head와 telemetry 없음 | — | JEV runtime/metrics |
| UI-004 | 자율분석 화면에는 연구목표·데이터품질·사용 가능 도구·선택 tool/이유/검증수준·missing inputs·진행 작업·결과/불확도를 표시; optimizer 화면에는 목표·조정/고정 변수·범위·비용·후보/불확도·기존 run 차이·제약·승인·다음 결과 입력 제공 | P1 | NOT_STARTED | future Analysis/Optimization workspace | 현 분석 화면은 registry recommendation 일부만 | — | optimizer/model contract와 task lifecycle |
| TEST-001 | backend regressions: version/step/duplicates/units/uncertainty, migration/data preservation, approvals, source filtering, registry/readiness/abstain | P0 | VERIFIED | backend/tests/ | 기준 81 passed | 0ccad66 | 35 warning cleanup 및 FK/restore 추가 |
| TEST-002 | API integration: original→normalized→review→tool/optimizer→UI; 실제 데이터/서비스 필요 시 mock-only가 아닌 integration 분리 | P0 | IN_PROGRESS | tests/test_api.py, test_material_analysis_api.py | TestClient 및 API smoke 성공 | 0ccad66 | 실제 브라우저 end-to-end, 현재 승인 실험자료가 없어 real optimizer flow 미검증 |
| TEST-003 | TypeScript/type/API mismatch, production build, stale async results, client error states 회귀검증 | P1 | IN_PROGRESS | frontend/, package scripts | npm run build 통과 | 0ccad66 | browser/component-level async tests |
| TEST-004 | GitHub Actions Python 3.12 pytest / Node 22 npm ci + build; OpenFOAM/Ollama/장비는 일반 CI와 분리 | P1 | IMPLEMENTED | .github/workflows/ci.yml | workflow committed; 동등 local checks 통과 | 0ccad66 | 원격 CI 첫 실행 미확인 |
| TEST-005 | tool accuracy/success/abstention, calibration, OOD, regret, experiments-to-target, constraint violations, latency, memory 등 비교 | P1 | IN_PROGRESS | docs/BENCHMARK_BACKTEST_REPORT.md, scripts | 논문 데이터 Ridge baseline 보고서 | existing report | 동일예산 비교군 및 live campaign 검증 |
| TEST-006 | 동일조건 반복은 한 fold; 논문/실험군/시간별 누수 방지; OOD/외삽/후보순서 bias와 sample-size 한계 공개 | P1 | IMPLEMENTED | scripts/evaluate_benchmark_backtest.py, report | 조건-group holdout과 한계 명시 | existing report | 논문별/시간별/OOD split을 제품 평가까지 적용 |
| TEST-007 | 회귀 매트릭스에 PDF transaction rollback, FK/migration/backup restore, 잘못된 simulation 입력 및 OpenFOAM 실패복구, evidence ID 존재, JEV abstain, BO constraint·data leakage, API/UI 승인과 모델 비활성 폴백 포함 | P0 | IN_PROGRESS | backend/tests/, frontend tests | 일부 PDF/API/migration/tool tests가 현재 81개 통과 | 0ccad66 | restore, FK 전체검사, optimizer, evidence adversarial, OpenFOAM restart, UI fallback tests 추가 |
| TEST-008 | 최소 비교군은 규칙 tool selection, Gemma candidate-token, learned JEV, JEV+Early Exit, Random Search, Ridge, GP+BO, JEV+BO; 같은 데이터/예산으로 accuracy뿐 아니라 tool success, abstention, calibration, regret/target, constraint, latency, RAM 평가 | P1 | NOT_STARTED | benchmark scripts/reports | 문헌 Ridge preliminary report만 존재 | existing report | 실제 decision/optimizer 구현 후 공정군별 holdout benchmark |
| TEST-009 | CI에서 Python tests, static analysis, TypeScript checks, frontend build, 핵심 API integration 수행; 외부 서비스는 분리된 integration job과 명시 fixture 사용 | P1 | IN_PROGRESS | .github/workflows/ci.yml | backend pytest와 frontend build job 구현 | 0ccad66 | lint/static analysis 및 API job 분리, 원격 Actions run 증거 |
| LOOP-001 | 연구 주제, method version, evidence, observation, analysis, simulation, JEV choice, BO proposal, human decision, outcome을 campaign으로 재현 가능하게 연결 | P0 | NOT_STARTED | future campaign data/API/UI | 전체 폐루프 없음 | — | Phase 1–7 |
| LOOP-002 | 새로운 연구/실험 조건에서 목표 개선량·비용·안전준수율을 반복 실제실험으로 검증; 분류 정확도/속도만으로 성공 결론 금지 | P0 | NOT_STARTED | validation protocol/report | 실제 campaign 검증 없음 | — | 승인된 장기 실험자료/연구자 프로토콜 |
| LOOP-003 | 장기 실행에서 backup/restore, 재시작, 모델 reload, resource contention, 누적데이터 및 권한 운영 점검 | P1 | NOT_STARTED | future operations scripts | 운영 시험 없음 | — | final runtime and worker |

## 사용자 확정 제품 구조도 계속 보존

- 연구 주제 → 공정 방법/버전 트리 → 날짜별 세부 실험 실행 → 단계별 조건·기록·측정 결과 구조.
- 같은 공정에서 값을 바꾼 실행과 공정 절차 자체가 바뀐 branch를 구분하고, 과거 결과를 덮어쓰지 않는다.
- 과정 정의 탭과 실험 결과 탭은 책임을 분리한다. 세부 실행은 접고 펼 수 있으며 측정자료와 결과는 원 실행 및 공정 단계에 연결한다.
- 재료·시약 라이브러리, 과정별 단위 있는 입력, 이미지·중간값 기록을 지원한다. 모르는 물성값은 비워 두고 Gemma가 출처 또는 사용자 입력을 요청한다.
- 장비별 분석 및 시뮬레이션은 실험 기록에서 연결하고, 원본측정·파생 계산·simulation output은 별도 출처로 표시한다.
- 여러 AI/전문 tool의 routing은 backend의 고정된 허용 목록을 사용한다. 모델 confidence는 근거나 성공확률이 아니다.

## 다음 Phase 및 우선순위

Phase 3는 핵심 조각을 연결했지만 전체 orchestration 완료는 아니다. 다음은 typed adapters/실패관리/통합 UI를 보완하고 Phase 1 데이터 검토·권한·migration report 작업을 계속한다.

1. standard observations의 원본값/normalized 값/단위/오류/출처를 비교하고 검토하는 화면.
2. analysis와 observation의 REVIEWED→ACCEPTED/REJECTED→재검토를 한 계약으로 정리하고 인증된 reviewer 권한 경계 설계.
3. replicate·measurement uncertainty·tool settings·file hash·parameter identity를 입력 API/UI까지 연결.
4. SQLite foreign_key_check/orphan audit, migration 전용 복구본 restore, 기존 데이터 보존 테스트 자동화.
5. migration/backfill 건수와 오류를 기록할 영속 report 추가.

그 뒤 PHREEQC 전하/종 검증, 모든 도구의 typed adapter 및 공통 실행상태 UI, durable queue와 CI, RAG transaction/citation 및 검색평가, BO 문제 정의, JEV 평가 데이터, 실기기 자원 벤치마크, 제한된 폐루프 순으로 진행한다. JEV/BO 미구현 상태를 완료라고 표시하지 않는다.

## 다음 작업 실행 체크리스트

1. git fetch origin main 후 remote HEAD, branch, dirty working tree를 확인하고 사용자 변경을 보존한다.
2. 이 로드맵과 관련 audit/design/test report를 읽고 현재 Phase의 ID별 acceptance criteria를 확정한다.
3. 기존 코드·DB·API·UI에서 문제가 남았는지 재현한다. 정상 기능은 불필요하게 다시 작성하지 않는다.
4. 필요할 때 migration 전 일관된 DB 백업을 만든다.
5. 좁은 코드 변경과 재현 테스트를 만들고 API/프런트/DB 연결 테스트를 실행한다.
6. 성능 변경은 같은 실제 기기·입력·예산에서 전후 측정한다.
7. 전체 관련 ID와 인접 기능 회귀를 다시 확인하고 문서의 상태/증거/commit/의존성을 갱신한다.
8. 작업마다 완료·부분완료·미완료를 나누어 보고한다. push/commit은 사용자의 요청과 일치시킨다.

## 변경 이력

| 날짜 | 변경 | 검증 근거 |
|---|---|---|
| 2026-10-30 | 전체 개선 프롬프트, Phase 3 요구사항, 이전 제품 흐름과 감사자료를 ID 로드맵으로 통합. 문헌 출처 오분류 수정, goal 기반 tool policy, PHREEQC 실행/검증/persist 및 일부 UI를 추가. | 89 backend tests; npm build; real PHREEQC calculation; 265 local observations source audit. Phase 3 변경은 이번 작업 커밋에 연결할 예정. |
