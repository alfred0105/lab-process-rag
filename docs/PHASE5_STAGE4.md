# Phase 5 Stage 4 — 최종 보정

상태: `PHASE_5_STAGE_4_VERIFIED` (소프트웨어·synthetic protocol 한정; 과학적 일반화 아님)

## FPR@95%TPR 정정

기존 ID calibration 5% 분위수는 운영 threshold 후보에 해당하며 FPR@95%TPR가 아니었다. 수정본은 OOD를 positive로 두고 평가 partition의 ROC curve에서 TPR ≥ 0.95를 만족하는 점의 최소 FPR로 계산한다. 이 보고용 ROC 지표는 평가 라벨을 기술 통계 계산에만 사용하며 운영 threshold 선정에는 사용하지 않는다. 운영 TPR@5% ID-FPR은 계속 ID calibration에서 threshold를 고른 뒤 독립 평가한다. 이전 잘못된 필드는 `id-calibration-lower-quantile-mislabeled-as-fpr95-v0`로 식별하고 최신 공식 값은 `roc-ood-positive-label-v1`이다.

회귀 검증: 완전 분리, 반대 순서, 겹침, 동일 점수 tie, 잘못된 NaN 입력, sklearn ROC 동등성 및 운영 threshold 비사용을 검사한다. 최종 로컬 회귀에서 backend 전체 233개 테스트, production build, 6개 browser E2E가 통과했다.

## Zero-shot 교차 공정

`phase5-stage4-zero-shot-cross-recipe-v1`은 source recipe에서만 fit/calibrate한 모델을 별도 target recipe 평가셋에 그대로 적용한다. 같은 target test에 대한 target-trained 대조군도 별도로 만든다. source/target group overlap은 없고, target test 라벨로 학습·정규화·선택하지 않는다. 보고 파일 `backend/reports/phase5_stage4_cross_recipe_transfer.json`의 모든 레이블과 recipe는 합성 software fixture다. 이 결과를 연구실 일반화 능력이나 물질 특성으로 해석하지 않는다.

두 프로토콜의 독립 단위 테스트 및 전체 backend regression은 통과했다. GitHub Actions 결과는 변경사항 push 이후 갱신한다.

교차 공정 테스트(115 target test rows, 모두 합성): V1 zero-shot accuracy/Macro-F1 0.235/0.127, target-retrained 0.791/0.573; V2 0.261/0.154 대 0.774/0.547; class-weighted V2 0.461/0.414 대 0.643/0.559; HistGradientBoosting 0.539/0.432 대 0.878/0.731. 이는 새로운 합성 recipe 규칙 간 이전 격차를 보여줄 뿐 실제 실험 재현성·연구실 일반화 성능을 나타내지 않는다. Source/target group overlap은 0이고 source 모델 digest는 target 추론 전후 동일했다.
