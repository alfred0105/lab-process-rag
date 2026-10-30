# 문헌 레퍼런스 기반 분석·시뮬레이션 점검

작성일: 2026-10-29

## 목적과 데이터 원칙

기존 연구 주제와 저장된 기록은 수정하지 않았다. 합성 데모 run을 분석·시뮬레이션 검증에 사용하지 않았다. 문헌 표에서 추출한 공정 조건과 결과만 `문헌 레퍼런스 검증 테스트`라는 별도 연구 주제에 등록했다. 등록 항목의 상태는 `reference`이고, 각 기록에 데이터셋 ID, 원문 run ID, 표 위치, 원문 링크, 품질 주의사항을 남겼다. 이는 연구실에서 직접 실행한 실험, 성공/실패 판정, 측정 장비 파일로 취급하지 않는다.

## 별도 연구 주제에 구성한 자료

| 공정 방법 | 논문 run | 사용 목적 | 적용 한계 |
| --- | ---: | --- | --- |
| CuFeO₂ 수열 박막 합성·어닐링 | 25 | 수열 온도 조건과 광전류 결과를 이용한 문헌 run 유사 사례 흐름 점검 | ZnO 나노와이어와 재료·결과 측정이 다르다. 동일 공정의 성능 검증이 아니다. |
| MgAl-LDH 교반·공침 | 8 | 교반 속도·혼합/숙성 시간·배플 조건과 생성량 등의 문헌 run 분석 | 공침 자료다. 수열 ZnO 자료와 합쳐 추정하지 않는다. |

합계 33개 문헌 run, 합성 데모 run 0개를 새 연구 주제에 가져왔다. 재실행해도 중복 등록되지 않게 가져오기 스크립트를 만들었다. 같은 연구 주제에 현재 ZnO 수열성장 공정의 단계 4개와 조건 정의 13개만 별도 방법 사본으로 복사했다. 기존 6개 데모 run은 복사하지 않아 이 방법 사본의 실행 수는 0이다. CuFeO₂ 문헌 run은 같은 ZnO 공정 자료로 간주하지 않고 인접 공정군으로만 남겼다.

## 실행한 점검

### 1. 현재 앱의 문헌 run 유사 사례 추정

앱의 유사 사례 방식과 같은 방식으로, 한 조건만 지정하고 그 조건에서 가까운 문헌 3건의 결과를 거리 가중 평균했다. 범위 바깥 외삽은 허용하지 않는다.

| 자료군 | 제외한 문헌 run | 조건 | 나머지 run 3건의 추정값 | 원문 보고값 | 절대 오차 |
| --- | --- | --- | ---: | ---: | ---: |
| CuFeO₂ 수열 박막 | run 1 | 수열 110 °C | −1.3481 mA/cm² | −1.6715 mA/cm² | 0.3234 mA/cm² |
| MgAl-LDH 공침 | HT1 | 교반 200 rpm | 60.013 g | 51.94 g | 8.073 g |

각 제외 run의 조건은 해당 문헌 행에서 자동으로 읽고, 추정 시 그 run의 결과는 학습 후보에서 빼뒀다. 단일 공정조건 최근접 방식이라 다른 조건 차이는 통제하지 않는다. 두 값은 소규모 문헌 leave-one-run-out 기능 점검이며, 독립 시험자료에 대한 일반화 성능 검증이나 성공확률이 아니다. UI에서도 문헌 레퍼런스를 중립 점으로 표시한다.

### 2. 수집한 7개 문헌 데이터셋 전체의 별도 baseline 점검

`scripts/evaluate_benchmark_backtest.py`를 실행했다. 동일 조건의 반복 run을 한 fold에 묶은 leave-one-condition-group-out 평가이며, 고정 ridge 회귀의 MAE를 학습 집합 평균 예측의 MAE와 비교했다.

- 7개 데이터셋, 125개 run을 읽었다.
- 평가 결과가 나온 14개 결과변수 중 ridge MAE가 평균 baseline보다 작았던 항목: 14/14.
- 이 수치는 앱의 유사 사례 UI나 PHREEQC/Reaktoro 정확도 검증이 아니다. 소규모 문헌 설계표에 대한 단순 회귀 baseline 비교다.
- Cu-Mn 자료는 공정 조건이 4개뿐이라 일반화 성능 근거로 보기 어렵다. CuFeO₂ 자료는 논문 SI의 pure-error 자유도가 0이라는 주의사항이 있다.
- 데이터셋 간 물질·공정 결과를 합쳐 학습하지 않았다.

### 3. 전문 분석 도구 연결 상태

`GET /api/analysis/tools`가 정상 응답했다. XRD 피크 미리보기, AFM 평탄화·거칠기, SEM/TEM 임계값 분할 pilot adapter는 `ready`로 나왔다. 다만 현재 수집한 125개 문헌 run에는 원본 XRD 패턴, AFM 높이 맵, SEM/TEM 이미지가 없다. 따라서 실제 전문 분석 정확도를 실행·판정했다고 보고하지 않는다.

GSAS-II, Gwyddion, HyperSpy/ExSpy, py4DSTEM/LiberTEM, ilastik 설치 상태는 API가 확인했지만, 이 도구들은 앱 adapter 연결과 적합한 입력 파일이 별도로 있어야 실제 분석할 수 있다. 설치 상태만으로 앱 통합이나 분석 성공을 뜻하지 않는다.

### 4. PHREEQC 입력 적합성

현재 문헌 CSV에는 공정 인자와 저자가 표에 보고한 결과는 있지만, 해당 run을 PHREEQC에 재현할 용존 원소 분석 총량, 초기 pH, 전하균형 기준이 없다. 따라서 이 자료를 수용액 조성으로 변환해 PHREEQC를 실행하지 않았다. 적합하지 않은 입력을 새로 만들어 넣지 않았다.

UI의 PHREEQC 영역은 선택한 실험 기록의 조건값을 읽도록 바꿨다. pH, 온도, 지원 원소의 농도와 단위가 공정 기록에 없으면 누락된 값을 표시하고 실행을 막는다. 기본값이나 데모 농도는 자동 삽입하지 않는다. 농도 단위 M 또는 mM를 PHREEQC 몰랄농도로 바꿀 때는 묽은 수용액의 1 kg 물≈1 L 용액 근사를 화면에 표시한다.

## 복잡한 평형 계산을 보완할 별도 시뮬레이션 검토

PHREEQC를 대체하지 않는다. 공식 USGS 문서상 PHREEQC 자체는 특정 활동도 모델, 산화환원 couple/pe, 사용자 정의 속도식 기반 KINETICS를 지원한다. 다만 현재 앱 wrapper는 `phreeqc.dat`로 고정 pH의 수용액 종분포·포화지수 중심 계산만 노출한다. 논문에 속도식이나 용액 조성이 없으면 기능이 있어도 해당 논문 run 재현에는 쓸 수 없다.

다른 엔진 후보는 Reaktoro다. 공식 문서는 평형과 화학반응속도를 결합한 계산을 설명하며, macOS ARM64 및 Python 3.12용 conda-forge 배포 파일도 확인했다. PHREEQC 활동도 모델도 Reaktoro에서 사용할 수 있어, 두 모델을 같은 연구 안에서 교차 확인하거나 속도식을 더한 별도 모듈을 붙일 수 있다. 하지만 현재 수집한 CuFeO₂·MgAl-LDH run에는 적용 가능한 용액 조성/속도식이 없어 이번 테스트 데이터로 Reaktoro의 예측을 검증할 수 없다. 이번에는 설치·연결·성능을 확인한 것처럼 처리하지 않았다.

추가 모듈 입력은 별도 복잡한 설정 폼이 아니라 공정 과정에서 저장한 조건과 재료를 자동으로 가져오는 원칙을 따른다. 시뮬레이터가 요구하는 값을 공정 기록에서 찾을 수 없으면 실행하지 않고 빠진 공정값만 보여준다. 물질별 핵생성·입자 크기·형태·수율은 적합한 물리/경험 모델, 속도 상수, 동일 공정군 검증자료를 확보한 뒤에만 제안값으로 계산한다.

## 구현·검증 위치

- 별도 연구 주제 자료 입력: `scripts/import_literature_validation_workspace.py`
- 논문 실행 데이터: `docs/research-data/cross-domain-process-outcomes.csv`
- 데이터셋 출처와 품질 제한: `docs/CROSS_DOMAIN_PROCESS_OUTCOME_CASES.md`
- baseline 비교 스크립트: `scripts/evaluate_benchmark_backtest.py`
- process-run 조건을 읽는 PHREEQC UI: `frontend/src/components/PHREEQCWorkbench.tsx`
- 문헌 run 하나씩 제외 검증 UI: `frontend/src/components/HistoricalOutcomeSimulator.tsx`

## 참고 자료

- USGS, [PHREEQC Version 3 capabilities](https://water.usgs.gov/water-resources/software/PHREEQC/documentation/phreeqc3-html/phreeqc3-2.htm)
- USGS, [PHREEQC KINETICS input and rate expressions](https://water.usgs.gov/water-resources/software/PHREEQC/documentation/phreeqc3-html/phreeqc3-24.htm)
- Reaktoro, [chemical kinetics combined with equilibrium](https://reaktoro.org/v1/tutorials/kinetics/index.html)
- Reaktoro, [using PHREEQC activity models](https://reaktoro.org/tutorials/basics/specifying-activity-models.html)
- conda-forge, [Reaktoro package and macOS ARM64 builds](https://anaconda.org/conda-forge/reaktoro)
