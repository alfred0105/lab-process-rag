# Phase 6 Evaluation

필수 비교 축: synthetic-only V1/V2/tree baseline, frozen-backbone full-depth head, layer-wise early exit, decision-only 대 conditional explanation. 2026-11-01 canonical adapter 재학습 후 same frozen 24-row synthetic test에서 Phase 6 final head는 accuracy 0.500 / Macro F1 0.295였다. Layer 7/14/21 heads는 accuracy 0.375/0.333/0.542, macro F1 0.162/0.144/0.304를 기록했다. 같은 시점의 기존 Phase 5 baseline JSON은 역사적 데이터이며 Phase 6 변경 후 재계산된 비교가 아니므로 수치 우열을 주장하지 않는다. Early exit calibration threshold는 모두 null이라 0%, 모두 28/28 layers를 수행했고, 19개 runtime subset에서 p50 87.8ms 대 full-depth 87.4ms로 개선이 확인되지 않았다. 실제 Qwen layer hook structural test는 forced test-only threshold에서 7/28층 실행 및 21층 skip을 확인했지만 calibrated 성능이 아니다. Decision-only는 생성 토큰 0개(실행 보고서 약 86.8ms), 실제 synthetic DB integration generation은 81 token을 냈으나 citation schema 실패로 거부됐다. 실제 연구 레이블이 없어 scientific accuracy, groundedness, 성공확률, 자동 분석 정확도를 검증했다고 주장하지 않는다. 측정 환경, 표본과 제한은 JSON 보고서가 보존한다.


## Closure diagnostic update (2026-11-01)

The expanded 480-case grouped synthetic experiment is diagnostic only. Linear, MLP and regularized MLP heads at seven candidate layers were evaluated with separate calibration, controller and frozen groups; all policies failed the predeclared sequential risk bound, leaving authorized early-exit rate at 0% and execution at 28/28 layers. The old 120-case benchmark above is retained as historical evidence. Current results are in `backend/reports/phase6_early_exit_diagnostics.json` and `phase6_early_exit_final.json`.


## Early Exit expanded evaluation — 2026-11-01

Expanded split hashes, class counts, family-held-out diagnostic, selection and one-policy independent risk certificate are in `backend/reports/phase6_ee_dataset_audit.json` and `phase6_ee_router_comparison.json`. PABEE's synthetic certificate passed with 377 exits/46 errors (Wilson upper 0.1589; exact upper 0.1533); frozen offline macro F1 was 0.8446 versus 0.8487 full-depth. Since this dataset is rule-generated, this result is only a synthetic software-policy test, not scientific validation. Router method frozen scores are descriptive and were not used for policy selection.
