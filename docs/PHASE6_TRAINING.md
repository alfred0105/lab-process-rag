# Phase 6 Decision Head Training

백본은 고정하고 layer 7/14/21/28 각각에 독립적인 trainable linear action head를 학습한다. 입력 adapter는 versioned ScientificState V2를 deterministic JSON 템플릿으로 바꾸며 label/outcome/experiment IDs를 제거한다. `SYNTHETIC_SANDBOX` 이외 source label은 학습을 거부한다. group-based fit/calibration/evaluation split을 사용하고 temperature, confidence gate, hidden-state RMS OOD threshold는 calibration/fit partition에서 설정한다. Artifact는 `~/.cache/lab-process-rag/phase6-decision-heads.pt`에 저장되며 모델 revision 불일치 시 로딩을 거부한다.

실제 human-reviewed research dataset이 없으므로 현재 학습은 software execution 증명에 한정된다. Loss/metrics와 frozen-backbone digest는 `backend/reports/phase6_decision_benchmark.json`에 기록한다.
