# Phase 4 handoff: Gaussian Process & Bayesian Optimization

상태: **NOT_STARTED**. 현재 문서는 Phase 3 이후 GP/BO 구현 요구와 입력 계약을 정의한다. Bayesian optimization 실행, 학습, 후보 추천은 아직 포함하지 않는다. Phase 4는 학습형 JEV를 선행조건으로 요구하지 않으며 기존 RuleBasedDecisionPolicy와 독립된 optimizer로 시작한다.

## Phase 3 entry gate status — 2026-10-31

Phase 4 implementation has **not** started. The latest Phase 3 software status remains `PHASE_3_SOFTWARE_IN_PROGRESS`: local code/test improvements include XRD axis conversion and a real queued Worker benchmark, but the final artifact/recovery audit, independent API and Worker resource profiling, restart/retry performance and safety matrix are not closed. Do not treat this handoff document as approval to start GP/BO. Continue using only the accepted-data contract below after the Phase 3 entry gate is verified. External instrument accuracy and approved CFD remain `EXTERNAL_VALIDATION_PENDING` and are tracked separately.

## 목표 구현 범위

- 승인된 실험 데이터의 optimization-ready contract와 실측/source/review 필터
- feature engineering, 물리 단위 정규화, 변수 bounds 및 물리 제약
- Gaussian Process regression, kernel 후보 선택, hyperparameter 최적화와 predictive uncertainty
- Bayesian acquisition: Expected Improvement, Probability of Improvement, Upper Confidence Bound
- constraint-aware/noise-aware optimization, replicate 및 다목적/Pareto 지원
- baseline 비교, grouped/campaign-aware cross-validation, leakage 방지와 surrogate validation
- 다음 실험 후보 ranking, 불확도 높은 구간 abstention 및 필수 입력 요청

Phase 4는 합성·공개 benchmark로 엔진 동작을 검증할 수 있지만, 실제 연구 최적화 성능은 승인된 실측 데이터와 사전에 정한 목표/제약 평가 없이는 VERIFIED로 처리하지 않는다.

Phase 4는 아래 계약을 충족한 승인 실측 관측만 최적화 데이터로 사용할 수 있다.

```json
{
  "topic_id": 0,
  "experiment_id": 0,
  "method_version_id": 0,
  "process_step_id": 0,
  "material_ids": [],
  "parameters": [{"name": "", "value": 0, "unit": "", "normalized_value": 0, "normalized_unit": "", "bounds": [0, 1], "physical_constraint": ""}],
  "outcomes": [{"name": "", "value": 0, "unit": "", "uncertainty": null, "replicate_id": null}],
  "review_status": "APPROVED",
  "source_type": "LAB_RESULT",
  "provenance": {"source_id": "", "original_sha256": "", "tool_id": null, "tool_version": null},
  "validation_status": "REFERENCE_VALIDATED"
}
```

## 필수 데이터 보호

- `source_type`은 실제 승인된 `LAB_RESULT`만 학습 허용한다. `LITERATURE`, `SIMULATION`, `SYNTHETIC_DEMO`, 모델 추론값은 보류/제외한다.
- `review_status`가 `APPROVED`가 아니거나 필수 provenance·단위·검토 계보가 없으면 학습을 시작하지 않는다.
- 서로 다른 topic, material identity, method version 또는 process step은 자동으로 한 집단에 합치지 않는다.
- 반복 측정 ID와 불확도를 유지한다. 불확도나 측정값을 추측해 채우지 않는다.
- 값은 물리 차원이 호환될 때만 명시적으로 정규화한다. pH/SI처럼 로그·모델 척도인 값은 일반 농도처럼 변환하지 않는다.
- 승인 가능한 데이터가 부족하면 최적화를 보류하고 부족한 필드와 승인 기준을 알려준다.

현재 저장소에는 이 문서가 설명하는 최적화 실행 및 실험-시뮬레이션 오차 보정이 완성되지 않았다. 본 문서는 Phase 4 구현자의 입력 계약이며 성능·과학 검증 증거가 아니다.
