# Phase 6 조기 종료 후보 선정

## 선정 규칙

후보는 위험 기준 `0.20`, 최소 24개 인증된 early exit, Wilson 95% 상한과 one-sided exact binomial 95% 상한, 기존 safety/OOD/provenance gate, frozen macro F1, cross-family 성능 및 실제 물리적 layer skip/latency를 함께 고려해야 한다. 기준을 낮춰 통과시키지 않는다. 후보 선택은 policy-selection 집합에서 끝내고, 단 하나의 고정 정책만 독립 risk-certification 집합에서 검사한다.

## 결과

최종 선택 또는 실패 원인은 [`backend/reports/phase6_ee_model_selection.json`](../backend/reports/phase6_ee_model_selection.json), 위험 세부는 [`backend/reports/phase6_ee_router_comparison.json`](../backend/reports/phase6_ee_router_comparison.json), 실제 실행 근거는 [`backend/reports/phase6_ee_final_benchmark.json`](../backend/reports/phase6_ee_final_benchmark.json)에 기록한다.

## 승격 상태

이 문서의 후보 비교나 synthetic certification만으로 champion 승격을 허용하지 않는다. 실제 연구실 데이터와 최종 software/regression 검증이 없으면 Phase 6은 `IN_PROGRESS`, Phase 7은 `NOT_STARTED`를 유지한다.


## 이번 실험의 선택 결과

정책 선택 표본에서 selection Wilson upper ≤0.20과 최소 24개 exit 조건을 충족한 PABEE가 selection Wilson 기준을 만족했고 EEFP는 통과하지 못했다. PABEE는 적격 후보 중 가장 많은 exit를 보였다. 단 하나만 위험 인증 표본에서 검사했다. OOD rejection 포함 인증 결과는 377/384 exit, 46 errors, Wilson upper 0.1589, exact-binomial upper 0.1533으로 synthetic 기준은 통과했다. 이는 synthetic Sandbox 입력에 대한 `SYNTHETIC_RISK_CONTROLLED_EXIT_ONLY`다. 실제 Qwen hook benchmark는 full-depth만 측정했으며 adaptive skip은 실행하지 않았다. 합성 산출물은 research mode에서 exit할 수 없으므로 production 선택 후보는 `없음`이며 routing은 계속 28층 full-depth다. 최종 고정 정책과 분할 hash는 machine-readable report를 참조한다.

**미완료:** COMBO-A~E 전 조합 비교/선정, 선택된 정책의 실제 adaptive decoder-loop 실행, 실제 layer-skip·p50/p95 비교, review된 lab label 및 recipe-shift 인증. 따라서 프로젝트의 조기 종료 승격과 Phase 6 완료는 허용하지 않는다.
