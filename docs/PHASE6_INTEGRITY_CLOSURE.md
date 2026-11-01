# Phase 6 Integrity & Reliability Fix — 2026-11-01

## 판정

Phase 6는 **`IN_PROGRESS`**다. 이번 범위의 네 결함을 수정하고 실제 Qwen3 체크포인트까지 실행했지만, 일부 안전·성능 수용 기준은 데이터 부족으로 아직 통과하지 못했다. 아래 `VERIFIED`는 명시한 소프트웨어 계약만의 통과이며, 연구 정확도 검증을 뜻하지 않는다.

기준 저장소 HEAD는 `b4b797b5b65d5d8e97a6813919492936303795ec`였다. 이번 구현은 해당 HEAD 위에서 진행했다. 기존 Phase 5 보고서와 frozen benchmark는 보존했다.

## 변경 요약

| Fix | 결과 | 실제 확인 |
|---|---|---|
| FIX-P6-001 입력 일치 | `VERIFIED` — 입력 계약에 한정 | `scientific-state-canonical-v2`에서 training/runtime 토큰 ID 일치. ID·결과 라벨 제거, 섭씨/화씨 정규화 동일성, user request 무영향 확인. Qwen 실제 checkpoint로 헤드 재학습 및 artifact 저장·복원. |
| FIX-P6-002 출처·RAG 보안 | `PARTIAL` | Research는 서버 DB의 non-demo experiment에서만 state를 구성하고 provenance/quality 통과를 요구. Sandbox는 명시적 모드이며 제출 provenance를 UNKNOWN으로 덮어씀. Citation은 topic-scoped DB chunk ID 재조회. 사용자 권한 계층이 프로젝트에 없어 topic ID 범위는 사용자 인증/인가가 아님. |
| FIX-P6-003 결정 고정 설명 | `PARTIAL` | 실제 같은 Qwen이 설명 토큰을 생성. 출력은 정확한 최종 action 및 저장 citation ID를 담은 JSON이어야 하며 validator가 위반을 거부. 격리 테스트에서는 모델 출력이 schema/citation 검증에 실패하여 fallback으로 거부됨. |
| FIX-P6-004 조기 종료 | `PARTIAL` | 실제 Qwen layer hook structural test가 layer 7 뒤 21 layer 생략 확인. 보정 기준이 없어 calibrated 운영 threshold는 모두 null, 실제 조기 종료율 0/19이며 절감은 0%. |

세부 변경 파일은 아래를 포함한다.

- `backend/app/services/phase6_hybrid.py`
- `backend/app/api/hybrid_decisions.py`
- `backend/scripts/train_phase6_sandbox.py`
- `backend/scripts/validate_phase6_integrity.py`
- `backend/tests/test_phase6_hybrid.py`
- `backend/tests/test_phase6_integrity_api.py`
- `frontend/src/components/DecisionPanel.tsx`
- `frontend/src/api/client.ts`
- `frontend/src/style.css`
- `backend/reports/phase6_integrity_fix.json`
- `backend/reports/phase6_context_alignment.json`
- `backend/reports/phase6_generation_validation.json`
- `backend/reports/phase6_early_exit_revalidation.json`

기존 네 benchmark JSON은 이번 실행 결과로 갱신하기 전에 Git 기준 HEAD의 원본을 `backend/reports/historical/phase6-pre-integrity-2026-11-01/`에 보존했다.

## 입력 정합성 및 새 artifact

하나의 canonical adapter가 ScientificState V2를 안정 JSON으로 정규화하고 고정된 분류 task와 같은 chat template/tokenizer를 사용한다. User prose와 retrieved evidence는 분류 context에서 제외한다. Evidence는 선택 요청의 설명에만 들어간다. 지원 단위의 표기 차이는 canonical numeric field로 정규화되며 원래 표기와 ID·사후 outcome은 모델 입력에 남기지 않는다.

새 artifact는 기존 v1을 조용히 재사용하지 않는다. 이전 파일은 `~/.cache/lab-process-rag/phase6-decision-heads.adapter-v1-archived.pt`에 보관했고 새 v2 artifact는 `~/.cache/lab-process-rag/phase6-decision-heads.pt`에 저장했다. 모델, tokenizer, adapter, action mapping, 데이터/분할 hash, 그룹 ID와 calibration 정책이 맞지 않으면 로드를 거부한다.

- Backbone: Qwen3-0.6B revision `c1899de289a04d12100db370d81485cdf75e47ca`
- Split: 합성 row 120개, fit/calibration/evaluation 72/24/24; group 교집합 없음
- 실제 tokenizer equality: PASS
- user request 세 가지 변화: token IDs와 분류 action 동일; 요청 문장은 의사결정 분류 입력에서 의도적으로 배제
- 같은 고정 합성 평가 24개에서 layer 28: accuracy 0.500, macro F1 0.295. 이는 연구 정확도가 아니다.

## Research 출처 및 Evidence 경계

Research API는 `topic_id`와 `experiment_id`로 기존 ResearchTopic 및 non-demo Experiment를 조회하고 서버가 ScientificState를 생성한다. 본문에 `scientific_state`가 같이 들어오면 422로 거부한다. 서버 생성 상태의 provenance `VALID` 및 data-quality `PASS`가 아니면 모델 추론으로 넘기지 않는다.

Sandbox는 `mode=sandbox`와 ScientificState가 명시돼야 한다. topic/experiment reference나 client evidence IDs는 거부한다. Client state의 provenance를 덮어써 비검증 상태로 처리하며 연구 기록 저장이나 workflow 실행은 하지 않는다.

Research citation은 `EvidenceChunk`와 `Paper`에서 DB 조회하며 선택 topic과 일치하지 않는 ID, 없는 ID를 거부한다. Client가 임의 text와 `SUPPORTED` 표기를 올려도 서버 검증 evidence가 되지 않는다. 저장된 PDF chunk는 출처와 topic 연결이 확인된 발췌문이며, 그 논문 내용의 사실성이나 현재 연구에 대한 적용 가능성이 독립적으로 검증됐다는 뜻은 아니다.

**제한:** 저장소의 기존 앱에는 사용자 인증/주제별 권한 시스템이 없다. 주제 ID 검사는 주제 교차 접근을 막지만 사용자 authorization은 아니다. 응답은 이를 `TOPIC_SCOPED_NO_AUTHENTICATED_USER_IDENTITY`로 표시한다. 이 코드 상태를 multi-user access control 완료로 간주할 수 없다.

## Decision-grounded generation 및 cache

분류 결과와 safety/OOD/review gate가 결정한 `final_safe_action`을 서버가 JSON explanation context에 고정한다. LM이 반환하는 JSON은 `final_safe_action`, `explanation`, `citations`를 포함해야 한다. Action이 최종 action과 다르거나 citation이 서버 조회된 ID와 다르거나 누락되면 설명을 표시하지 않고 고정된 fallback을 반환한다. Decision-only는 생성 토큰 0개다. Decision prefill cache와 explanation prompt가 다르므로 전자를 재사용하지 않으며, 설명은 full-depth prefill 후 동일 모델 인스턴스의 autoregressive KV cache를 사용한다.

실제 checkpoint와 API 함수, 임시 SQLite, topic-scoped stored chunk를 엮은 격리 통합에서 Qwen이 81 token을 생성했고 103,907,328 cache bytes가 기록됐다. 생성 JSON에 필수 explanation/citation이 없어 validator가 거부했다. 따라서 실제 citation-accepted scientific explanation이나 cache/full-generation equivalence는 **아직 통과하지 않았다**. fixture는 전부 인위적 소프트웨어 테스트 데이터이며 실험/논문 검증 데이터가 아니다.

## Early exit 재검증

실제 layer forward hook을 등록하고 테스트 전용 threshold 0.0으로 구조 확인: layer 7까지 실제 계산했고 layer 8–28은 호출하지 않았다. 이 테스트는 조기 종료 코드가 compute를 생략할 수 있음을 보일 뿐, 안전한 운영 threshold가 아니다.

독립 calibration split은 24개의 합성 사례다. 현재 fail-closed risk threshold는 모든 layer에서 `null`을 반환했다. 실제 연구 입력 조건의 조기 종료는 0/19, 평균 실행 28/28 layers, 실행 절감 0%다. Early/full-depth p50은 87.8/87.4ms로 early path 이득이 없다. threshold를 낮춰 조기 종료를 만들지 않았다.

## 로컬 실행 측정

- Python 3.12.14, PyTorch 2.15.0, Apple M5 MPS, FP16
- Qwen3-0.6B 596,049,920 parameters; 모델 load 측정 1.75초
- MPS driver allocation after run 3,574,267,904 bytes (peak 아님)
- Process `ru_maxrss` high-water mark 3,617,243,136 bytes (모델만의 메모리 아님)
- Decision-only 0 generated tokens, 한 측정 약 86.8ms
- Quantization, 에너지/발열, RTX 4060 Ti 측정은 미실시

## 테스트 및 미완료 항목

Phase 6 focused tests: 17 passed. 전체 backend suite: **243 passed, 353 warnings (45.44s)**. Frontend production build: **PASS** (TypeScript와 Vite 6.4.5, 1,760 modules). Browser E2E: **6 passed (44.6s)**. Backend suite에는 migration regression 및 Phase 5/6 회귀 테스트가 포함됐다. 실제 모델 통합 스크립트 `backend/scripts/validate_phase6_integrity.py` 성공: generation 호출/토큰·KV 기록·workflow 미실행 확인, 출력 검증은 안전하게 거부됨. GitHub Actions는 push 후 실행 결과를 추가한다.

| Gate | 상태 |
|---|---|
| FIX-P6-001 canonical token equality / v2 retrain / artifact reload | `VERIFIED` (software contract) |
| FIX-P6-002 Research/Sandbox isolation / DB citation ID scope | `PARTIAL` (authentication/authorization layer missing) |
| FIX-P6-003 actual LM explanation passes action+citation validator | `PARTIAL` (actual generation rejected; fail-closed fallback verified) |
| FIX-P6-004 structural layer skip / calibrated real early exit | `PARTIAL` (structural PASS, calibrated exits 0%) |
| Phase 6 official state | `IN_PROGRESS` |
| Phase 7 | `NOT_STARTED` |
| External research validation | `EXTERNAL_VALIDATION_PENDING` |

## Push / CI 기록

최신 변경의 커밋 및 GitHub Actions 결과는 원격 push가 완료된 뒤 기록한다. 로컬 검증 결과와 GitHub CI 상태는 구분한다.

Phase 7 autonomous experiment loop는 시작하지 않았다.
