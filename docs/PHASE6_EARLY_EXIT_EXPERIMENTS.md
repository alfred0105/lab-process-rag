# Phase 6 조기 종료 실험 기록

## 실험 목적

동일한 Qwen3-0.6B 체크포인트, tokenizer, 데이터 분할, 위험 기준 및 로컬 장비에서 intermediate decision head와 순차 router의 효과를 비교한다. 생성 합성 데이터는 소프트웨어 정책 계약을 확인하는 용도이며 실제 연구 결과를 나타내지 않는다.

## 재현 방법

```bash
cd backend
.venv/bin/python scripts/phase6_ee_research.py
```

Hidden-state 캐시는 모델/tokenizer revision, context adapter, 데이터 hash, layer 집합, 입력 token hash 및 precision이 모두 같을 때만 재사용한다. 보고서는 다음 파일에 생성된다.

- `backend/reports/phase6_ee_dataset_audit.json`
- `backend/reports/phase6_ee_head_comparison.json`
- `backend/reports/phase6_ee_router_comparison.json`
- `backend/reports/phase6_ee_final_benchmark.json`
- `backend/reports/phase6_ee_model_selection.json`

## 분할과 방법

480, 1,920, 3,840 생성 사례의 label/family 분포를 감사한다. 주 실험은 사례 group 단위로 fit/router-fit/calibration/policy-selection/risk-certification/frozen-evaluation으로 나누며, 어느 두 집합도 같은 group을 공유하지 않는지 확인한다. 시나리오 family 전체를 제외하는 교차 recipe 진단도 별도로 수행한다.

중간 layer 후보는 7, 14, 21층과 full-depth 28층이다. Linear CE, class-weighted linear, effective-number weighted linear, class-balanced sampling, 153개 ScientificState feature only, hidden+structured fusion 및 소형 fusion MLP를 비교한다. 지표는 accuracy, balanced accuracy, macro F1, 클래스별 precision/recall/F1, 고확신 오답을 포함한다. Distillation은 진단 후보이며 production head로 승격하지 않는다.

라우터 후보는 max softmax, entropy, top-two margin, PABEE-style 연속 일치, causal EEFP다. 각 router threshold는 calibration 집합에서 선택하고, 정책 후보 하나는 별도 selection 집합에서 고정한다. 위험 인증 집합은 선택된 정책에 한 번만 사용한다. 인증 실패 시 final evaluation에서 조기 종료를 강제로 보고하지 않고 full-depth로 대체한다.

## 결과와 상태

실측 결과, 데이터 hash, 각 split의 크기, 선택된 정책, Wilson/exact 상한 및 제한사항은 machine-readable report를 기준으로 아래에 갱신한다. 실제 decoder의 레이어 생략과 p50/p95 지연시간은 승인된 정책이 있을 때만 실제 prefix 실행으로 확인할 수 있다. offline cached-head 점수나 강제/mock exit는 실제 속도 개선으로 계산하지 않는다.

## 현재 검증 경계

- 데이터는 deterministic rule 기반 synthetic scenario contract이며 human-reviewed label이 아니다.
- Group-disjoint 사례 분할만으로 동일 family/recipe 분포 이동을 검증할 수 없다. 별도 family-held-out 결과도 여전히 합성 진단이다.
- Synthetic risk bound는 실제 실험실 운영 안전성을 보증하지 않는다.
- 어떠한 후보도 독립 인증과 실제 decoder skip/latency 검증 전에는 production routing이 아니다.


## 실제 실행 기록 — 2026-11-01

최신 보고서에서 PABEE가 synthetic risk certification 기준만 통과했다(377/384 exits, 46 errors, observed risk 12.20%, Wilson upper 15.89%, exact upper 15.33%). OOD rejection을 사용했고 20%/최소 24개 기준을 유지했다. Frozen synthetic 평가의 offline 조기 exit 비율은 97.14%, 평균 layer 수 15.42/28이나 macro F1은 full-depth 0.8487 대비 0.8446이었다.

실제 Qwen 실행 측정은 full-depth baseline만 수행했다. 최신 30회 MPS FP16 측정은 471 input tokens, 모든 회차에서 hook 28/28 layer, latest p50 84.69ms, p95 96.54ms; three-batch ranges 84.69–120.89ms p50 and 91.46–145.16ms p95다. 합성 데이터는 안전 경계상 Research 조기 종료를 승인할 수 없으므로 실제 adaptive skip/latency는 `NOT_RUN`이다. 전체 JSON 결과와 hook별 증거는 `backend/reports/phase6_ee_final_benchmark.json`에 보관한다.

## 통합 조합 실험 — 2026-11-01

BASELINE 및 COMBO-A~E를 같은 Qwen revision, 캐시된 중간 표현, 동일 3,840 synthetic 사례 및 group-disjoint split으로 통합 비교했다. 실행 명령은 `cd backend && .venv/bin/python scripts/phase6_ee_combo_comparison.py`다. 숨은 표현은 모델 revision과 dataset hash가 맞는 기존 캐시만 사용한다. 모든 조합에 calibration 기반 OOD gate를 적용한다. threshold는 calibration, 후보 선택은 policy-selection, 최종 위험 인증은 선택된 한 조합에만 독립 risk-certification set을 사용하며 frozen set은 설명용으로만 쓴다.

| 조합 | Head / Router | Selection 조기 종료 / 오류 | Wilson 상한 | 선택 기준 통과 |
|---|---|---:|---:|---|
| BASELINE | Linear CE / Max Softmax | 380 / 67 | 21.78% | 아니오 |
| COMBO-A | Linear CE / PABEE식 연속 일치 + 보정 Confidence | 371 / 34 | 12.53% | 예 |
| COMBO-B | Class-balanced Linear / Risk-controlled Confidence | 380 / 70 | 22.63% | 아니오 |
| COMBO-C | Hidden + 153개 구조화 특징 Fusion / EEFP | 380 / 44 | 15.19% | 예 |
| COMBO-D | Class-balanced Fusion / EEFP + Layer Agreement | 375 / 40 | 14.20% | 예 |
| COMBO-E | 중간 Head Distillation / Risk-controlled Confidence | 380 / 73 | 23.47% | 아니오 |

Selection partition만 사용해 COMBO-C를 고른 뒤 한 번만 독립 인증했다. 합성 인증은 381/384 조기 종료, 52 오류, 관측 위험 13.65%, Wilson 상한 17.46%, exact one-sided 상한 16.88%로 내부 20% 기준을 통과했다. 선택 조합의 frozen synthetic 평가에서 offline 추정은 383/384 조기 종료, 평균 7.58/28층, 정확도 86.46%, Macro F1 0.8233이다. 이는 실제 decoder 실행이 아니고 학습 규칙이 만든 라벨에 대한 진단 결과다. COMBO-C는 Production/Research 기본 Router로 채택하지 않는다.

통합 비교는 component별 기존 실험에 policy-selection 후보 비교를 추가했다. 독립 인증 보고서는 `backend/reports/phase6_ee_combinations.json`에 저장한다. 이 스크립트는 비교 실험이며 `phase6_hybrid.py` 런타임 router에는 연결되지 않았다.

## 연구 코드 라이선스 확인

외부 저장소 코드를 복사하지 않고 논문에 설명된 아이디어를 독립 구현했다. [EEFP 공개 코드 저장소](https://github.com/gmum/rethinking-calibration-for-eenns/blob/main/LICENSE)는 MIT LICENSE를 제공한다. [PABEE 공개 저장소](https://github.com/JetRunner/PABEE)에서 확인한 경로에는 명시적 LICENSE 파일이 없어 코드 재사용 라이선스가 확인되지 않았다. [EE-Tuning 공개 저장소](https://github.com/pan-x-c/EE-LLM/blob/dev/LICENSE)는 별도 라이선스 문서를 포함하지만 본 구현은 코드를 복사하지 않았다. 논문 아이디어 참고와 소스 코드 재사용 권한은 별개이며, 라이선스가 확인되지 않은 구현 코드는 재사용하지 않는다.
