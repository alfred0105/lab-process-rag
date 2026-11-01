# Phase 6 조기 종료 연구 근거

## 목적과 제한

이 문서는 Qwen3-0.6B 공유 백본의 중간 결정 헤드와 순차 라우팅을 비교하기 위한 연구 설계다. 공개 논문에서 보고한 성능을 이 프로젝트의 성능으로 간주하지 않는다. 현재 생성 데이터의 라벨은 규칙 기반 시나리오 계약이며 연구실 실험의 정답이 아니다. 독립 실험실 데이터로 검증되기 전에는 연구 정확도나 실험 안전성을 보증하지 않는다.

## 참고 연구

| 연구 | 이 작업에서 참고한 아이디어 | 적용 한계 |
|---|---|---|
| [Rethinking Calibration for Early-Exit Neural Networks (ICML/PMLR 2026)](https://proceedings.mlr.press/v306/kubaty26a.html), [공개 코드](https://github.com/gmum/rethinking-calibration-for-eenns) | 신뢰도 보정만으로는 추가 계산의 효용을 포착하기 어렵다는 문제 설정과 EEFP | 원 구현은 이미지 분류 모델 중심이다. 본 구현은 Qwen decoder용 소형 causal router로 재작성했다. 공개 코드 라이선스와 종속성은 별도로 검토해야 하며 코드 복사는 하지 않는다. |
| [Fast yet Safe: Early-Exiting with Risk Control (NeurIPS 2024)](https://proceedings.neurips.cc/paper_files/paper/2024/hash/ea5a63f7ddb82e58623693fd1f4933f7-Abstract-Conference.html) | 예측 품질과 계산 절감 정책을 분리해 위험 통제 | 이 연구의 보장은 데이터 교환가능성 등 전제에 의존한다. 합성 분포 결과는 실험실 위험 보증이 아니다. |
| [When Does Confidence-Based Cascade Deferral Suffice?](https://arxiv.org/abs/2307.02764) | 단순 confidence 정책의 한계와 별도 deferral 학습 | 본 프로젝트에서 실제 이득을 독립 데이터로 확인해야 한다. |
| [BERT Loses Patience (PABEE)](https://arxiv.org/abs/2006.04152), [코드](https://github.com/JetRunner/PABEE) | 연속 헤드의 예측 일치 기반 종료 | Transformer encoder 연구 결과를 Qwen decoder 품질의 증거로 쓰지 않는다. |
| [EE-Tuning](https://arxiv.org/abs/2402.00518), [FastBERT](https://aclanthology.org/2020.acl-main.537/) | 중간 헤드 학습 및 깊은 헤드 지식 전달 | 생성 토큰의 조기 종료와 여섯 가지 workflow action 분류를 구별한다. |
| [Class-Balanced Loss](https://arxiv.org/abs/1901.05555) | 유효 표본 수에 따른 클래스 가중치 | 합성 라벨 불균형을 실제 연구실 행동 빈도로 해석하지 않는다. |
| [Selective Classification](https://arxiv.org/abs/1705.08500), [Learn then Test](https://arxiv.org/abs/2110.01052) | coverage-risk 균형, 독립 인증 및 선택 편향 통제 | 인증은 사전에 고정한 정책과 독립 표본에만 적용한다. 여러 정책을 인증 표본에서 고르는 방식은 허용하지 않는다. |
| [Enriching Tabular Data with Contextual LLM Embeddings](https://arxiv.org/abs/2411.01645) | 과학 상태의 정형 변수와 문맥 표현 결합 | 관련 아이디어를 단순 feature fusion으로 제한한다. |
| [SimLens](https://arxiv.org/html/2507.17618v2) | 일부 후속 연산으로 중간 상태 해석을 돕는 접근 | 본 작업의 후보에 직접 이식하지 않았다. Qwen 호환성과 실제 연산 비용이 별도 연구 대상이다. |

## 통계 및 실행 원칙

- 공식 위험 기준은 `R_target = 0.20`, 조기 종료 인증 사례는 최소 24건으로 고정한다.
- head 학습, router 학습, 보정, 정책 선택, 단일 정책 위험 인증, 최종 평가 표본을 서로 분리한다.
- 정책을 선택 데이터에서 하나로 고정한 뒤에만 독립 위험 인증을 수행한다. Wilson 및 one-sided exact binomial 상한을 모두 기록한다.
- 현재까지 실행된 레이어만 라우터 입력으로 사용한다. 미래 레이어 출력은 학습 target을 만들 때만 사용 가능하다.
- cached hidden state를 이용한 오프라인 라우팅은 실제 transformer 연산 생략의 증거가 아니다. 물리적 layer skip과 latency는 실제 prefix 실행에서 별도로 측정해야 한다.
- Production model은 자동 승격하지 않으며 기존 provenance/OOD/safety gate를 우회하지 않는다.

## 구현 해석

실험 구현과 실제 수치 결과는 [`PHASE6_EARLY_EXIT_EXPERIMENTS.md`](PHASE6_EARLY_EXIT_EXPERIMENTS.md), 최종 후보 채택 여부는 [`PHASE6_EARLY_EXIT_MODEL_SELECTION.md`](PHASE6_EARLY_EXIT_MODEL_SELECTION.md)에 기록한다. 보고 JSON은 `backend/reports/phase6_ee_*.json`이다.
