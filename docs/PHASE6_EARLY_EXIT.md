# Phase 6 Early Exit

Backbone layer loop는 7/14/21층에서 calibrated confidence, valid provenance, in-calibration OOD score 조건을 모두 만족할 때 실제 다음 decoder layer 실행을 생략한다. layer 28은 최종 fallback이다. 별도 강제 full-depth 비교 경로가 동일한 입력에서 전체 층을 계산한다. 보고는 software synthetic fixture이며 평균 실행 층 수는 연산량의 대리 지표이지 직접 측정 FLOPs가 아니다. 안전/출처 gate는 높은 softmax confidence로 우회하지 않는다. 수치는 `phase6_early_exit_benchmark.json`에 보관한다.
