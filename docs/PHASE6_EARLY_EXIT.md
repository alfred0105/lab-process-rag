# Phase 6 Early Exit

Backbone layer loop는 7/14/21층에서 calibrated confidence, valid provenance, in-calibration OOD score, pending-review gate를 모두 만족할 때 실제 다음 decoder layer 실행을 생략한다. layer 28은 최종 fallback이다. Sandbox 요청은 비검증 입력이므로 early exit을 허용하지 않는다. 별도 강제 full-depth 비교 경로가 동일한 입력에서 전체 층을 계산한다.

2026-11-01 실제 Qwen layer forward hook을 붙인 구조 테스트는 강제 0.0 test-only threshold로 layer 7에서 멈췄고, 28개 중 7개 layer call이 실제 실행되어 나머지 21개를 생략했다. 이는 구조 검증에만 해당하며 안전한 confidence threshold가 아니다. 120개 합성 사례의 독립 calibration 24개에서 모든 layer의 threshold가 `null`이었고, 실제 calibrated early-exit 비율은 19개 연구 입력 중 0/19, 평균 28/28층, 추정 절감 0%다. Early/full-depth p50은 87.8/87.4ms였으며 개선 증거가 아니다. 그러므로 P6-007은 `PARTIAL`이다. 안전/출처 gate는 높은 softmax confidence로 우회하지 않는다. 수치는 `phase6_early_exit_benchmark.json` 및 `phase6_early_exit_revalidation.json`에 보관한다.
