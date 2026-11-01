# Phase 6 Decision Head Training

백본은 고정하고 layer 7/14/21/28 각각에 독립적인 trainable linear action head를 학습한다. `scientific-state-canonical-v2` 단일 adapter와 동일한 chat template/tokenizer를 training, calibration, evaluation, runtime decision에서 함께 사용한다. 분류 입력에서 user prose, 원본 단위 표기, identity, label, 사후 outcome, ID를 제거한다. User request variation은 decision head token에 영향을 주지 않는다. `SYNTHETIC_SANDBOX` 이외 source label은 학습을 거부한다. row와 group 분할의 중복도 검증한다.

2026-11-01 실제 Qwen tokenizer로 training/runtime token equality를 확인한 뒤 120개 합성 row에서 72/24/24 group-disjoint fit/calibration/evaluation으로 head를 다시 학습했다. 모델 artifact v2는 backbone/tokenizer revision, adapter/action mapping version, dataset/calibration/evaluation hash, group IDs, calibration 및 evaluation metrics를 보관한다. 이전 v1 파일은 `~/.cache/lab-process-rag/phase6-decision-heads.adapter-v1-archived.pt`로 보존했고 v1은 로드 호환되지 않는다.

실제 human-reviewed research dataset이 없으므로 현재 학습은 software execution 증명에 한정된다. 새 합성 split의 final layer 평가 accuracy는 0.500, macro F1은 0.295 (24 eval rows)였고, 이 값은 과학적 정확도가 아니다. Layer 7/14/21/28은 각각 accuracy 0.375/0.333/0.542/0.500, macro F1 0.162/0.144/0.304/0.295였다. Calibration 24개 사례에서 위험 제한을 만족하는 threshold가 나오지 않아 confidence threshold는 전부 `null`이다. Loss/metrics와 frozen-backbone digest는 `backend/reports/phase6_decision_benchmark.json`에 기록한다.


## Closure diagnostic (2026-11-01)

A separate diagnostic trained Linear, MLP and regularized MLP heads on the same pinned frozen Qwen backbone, using group-disjoint fit/calibration/controller/frozen sets (288/72/48/72) and layers 7/10/14/18/21/24/28. Synthetic-only comparisons are in `backend/reports/phase6_early_exit_diagnostics.json`; none of the head/layer sequential policies passed the controller risk bound. These diagnostic heads were not promoted and production artifacts were not changed.


## Expanded early-exit training experiment — 2026-11-01

See `PHASE6_EARLY_EXIT_EXPERIMENTS.md` and `backend/scripts/phase6_ee_research.py`. All normalizers fit on the 1,920-case fit partition. Tested hidden-only, ScientificState-only, concatenated feature fusion, class/effective-number weights, balanced random oversampling and a torch linear student trained with hard-label CE plus deep-teacher KL on router-fit cases unseen by the teacher. Generated labels remain synthetic and no artifact is promoted. Optional contrastive and explicit multiplicative-gate heads are not included.
