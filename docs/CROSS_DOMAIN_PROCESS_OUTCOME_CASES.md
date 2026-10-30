# 서로 다른 분야의 실험 공정-결과 데이터 수집

작성일: 2026-10-28

## 이번 수집의 범위

이번 자료는 특정 기법(예: spin coating)이나 재료(ZnO)에 한정하지 않는다. 공통 목표는 **실험 공정의 선택·조건·변형이 측정 결과와 어떻게 연결되는지 기록하고 분석하는 것**이다. 그래서 수열합성, 공침, 광촉매 운전, 수열액화, 고분자 3D 프린팅처럼 서로 다른 분야의 실행 데이터를 모았다.

다만 “큰 틀이 비슷하다”는 이유만으로 서로 다른 재료나 물리적 공정을 한 모델에 섞어도 된다는 뜻은 아니다. 비교·학습은 우선 같은 `dataset_id`와 공정군 안에서 수행해야 한다. 다른 분야 자료는 공정 기록 구조, 분석 흐름, 모델링 방식의 검증에 활용하고, 물리적 결과 예측은 공정군 별 모델 또는 재료·장비·측정 조건을 포함한 명시적 도메인 모델에서만 시도해야 한다.

## 수집 결과

CSV에는 **7개 데이터셋, 125개 실험 실행(run)**이 들어 있다. 각 행은 논문에서 제시한 실행 하나이며, 공정 요인과 측정 결과는 JSON 열에 원문 단위로 보존했다.

| 데이터셋 | 실행 수 | 큰 분야 / 공정 | 주요 입력 | 결과 예시 | 근거 위치 |
|---|---:|---|---|---|---|
| `cu_fe_o2_bbd_2026` | 25 | 광전기화학 / CuFeO₂ 수열 박막 합성 및 후열처리 | 수열 온도·시간, 어닐링 온도·시간 | 0.4 V vs RHE에서 광전류 밀도 | Supporting Information 표 S1 |
| `water_hyacinth_htl_uncatalyzed_ccd_2023` | 13 | 바이오에너지 / 무촉매 수열액화 | 온도, 체류 시간 | 바이오오일 수율 | 논문 표 1 |
| `water_hyacinth_htl_ccd_2023` | 20 | 바이오에너지 / Fe₃O₄-NiO 촉매 수열액화 | 온도, 체류 시간, 촉매량 | 바이오오일 수율 | 논문 표 2 |
| `co_zno_ciprofloxacin_ccd_2024` | 30 | 환경 촉매 / Co-ZnO 광촉매 운전 조건 | 촉매 투입량, 오염물 농도, 교반 속도, pH | ciprofloxacin 제거율 | 논문 표 4 |
| `mgal_ldh_coprecip_factorial_2024` | 8 | 재료 합성 / MgAl-LDH 공침 | 교반 속도, 혼합·숙성 시간, 배플 여부 | 생성량, 유도 시간 등 | 논문 표 3 |
| `cu_mn_oxide_coprecip_2012` | 4 | 촉매·재료 합성 / Cu-Mn 산화물 공침 | 금속 전구체, 침전제 조합 | 표면적, 기공 부피, CO 산화 온도, H₂ 소비량 | 논문 표 1 |
| `pmma_mex_taguchi_l25_2023` | 25 | 적층제조 / PMMA 재료압출 3D 프린팅 | 충전율, 적층 각도, 노즐 온도, 속도, 층 높이, 베드 온도 | 인장강도, 에너지 소비 | 논문 표 1–3 |

## 파일

- 실행별 데이터: [`docs/research-data/cross-domain-process-outcomes.csv`](research-data/cross-domain-process-outcomes.csv)
- 이 문서: `docs/CROSS_DOMAIN_PROCESS_OUTCOME_CASES.md`

CSV 열은 `dataset_id`, `run_id`, `domain`, `process_family`, `material_or_system`, `process_variant`, `factors_json`, `outcomes_json`, `source_url`, `source_location`, `quality_notes`이다. PMMA 자료의 결과는 논문이 보고한 5개 시편 평균과 표준편차를 함께 기록했다. 나머지 자료는 이번 추출에서 논문의 실행별 측정값만 입력했으며, 보고되지 않은 오차·반복 측정 분산은 만들어 넣지 않았다.

## 비교할 때 지켜야 할 것

1. **실험 주제와 공정군은 별도 계층이다.** 큰 주제는 “공정 조건을 바꿔 원하는 결과를 얻는 실험”으로 통일할 수 있지만, 수열 합성, 공침, 광촉매 반응, 3D 프린팅은 서로 다른 process family로 남긴다.
2. **공정 변경과 조건 변경을 분리한다.** 예를 들어 촉매가 없는 수열액화와 Fe₃O₄/NiO를 넣은 수열액화는 같은 연구 목표의 비교군일 수 있지만, 촉매 사용 여부는 공정 버전/분기 정보다. 그 안에서 온도·시간만 달라진 실행은 조건 변화다.
3. **결과 단위와 측정 조건을 유지한다.** 광전류 밀도, 제거율, 바이오오일 수율, 인장강도, 에너지 소비는 하나의 공통 수치로 정규화해 같은 목적함수처럼 취급하지 않는다.
4. **성공/실패 라벨은 임의로 만들지 않는다.** 논문이 명시한 경우에만 그 라벨을 기록한다. 현재 CSV는 연속 측정치를 보존하며 이진 성공/실패 판정은 포함하지 않는다.
5. **관찰된 최댓값을 성공확률로 읽지 않는다.** 데이터는 제한된 설계공간의 실행 결과다. 확률 또는 일반화 성능을 주장하려면 사전 정의한 성공 기준, 반복/검증 실험, 공정군별 외부 검증이 필요하다.

## 자료 품질 및 주의사항

- CuFeO₂ 자료는 25개 Box-Behnken 조건의 SI 표를 옮겼다. 광전류 밀도 부호는 논문 표기 그대로 유지했다. SI의 ANOVA 표에는 순수 오차 자유도 0이므로 높은 적합도만으로 일반화 성능을 결론 내리지 않는다.
- 무촉매/촉매 수열액화는 같은 논문의 두 설계표에서 따로 가져왔다. 촉매 유무는 공정 차이이므로 두 시리즈를 동일한 실행군으로 무표시 병합하면 안 된다.
- Co-ZnO 표는 **합성조건 최적화가 아니라** 이미 만든 10% Co-ZnO 촉매의 ciprofloxacin 분해 운전조건 최적화다. 논문 표의 중앙점 반복값이 소수점 네 자리까지 동일하게 인쇄되어 있어 CSV 주석에 표시했다. 이를 반복 측정의 실제 분산이 0이라는 뜻으로 간주하지 않는다.
- LDH 표의 용액 부피와 반응 유도 시간은 저자가 결과/관찰로 보고한 항목이지, 이 설계의 독립 입력 인자로 간주하지 않는다.
- PMMA 표는 조건별 5개 시편의 평균±표준편차를 보고한다. CSV에는 우선 강도와 에너지 소비 두 지표만 추출했다. 이 논문은 **필라멘트 압출을 포함한 재료 준비 후 재료압출 3D 프린팅** 연구이므로, 프린팅 변수와 선행 필라멘트 준비 조건을 혼동하지 않는다.
- 표의 숫자는 원문 반올림 자릿수로 보존했다. 숫자 변환 과정에서 추정 또는 보간하지 않았다.

## 출처

1. El Idrissi et al., “Design of experiments guided hydrothermal synthesis of CuFeO₂ photocathodes for photoelectrochemical hydrogen evolution,” *Materials Advances* (2026). [논문](https://pubs.rsc.org/en/content/articlehtml/2026/ma/d6ma00088f), [Supporting Information, Table S1](https://pubs.rsc.org/ma/article-supplement/1223590/pdf/d6ma00088f1_suppl/).
2. Aturagaba et al., “Catalytic Hydrothermal Liquefaction of Water Hyacinth Using Fe₃O₄/NiO Nanocomposite: Optimization of Reaction Conditions by Response Surface Methodology,” *Journal of Sustainable Bioenergy Systems* (2023). [논문 및 표 1–2](https://doi.org/10.4236/jsbs.2023.133005).
3. Meky et al., “Hydrothermal fabrication, characterization and RSM optimization of cobalt-doped zinc oxide nanoparticles for antibiotic photodegradation under visible light,” *Scientific Reports* (2024). [논문, 표 4](https://pmc.ncbi.nlm.nih.gov/articles/PMC11231344/).
4. Gabriel et al., “Synthesis of layered double hydroxides: Investigating the impact of stirring conditions and reactor design parameters,” *Heliyon* (2024). [논문, 표 3](https://pmc.ncbi.nlm.nih.gov/articles/PMC11063454/).
5. Cai et al., “The choice of precipitant and precursor in the co-precipitation synthesis of copper manganese oxide for maximizing carbon monoxide oxidation,” *Journal of Molecular Catalysis A: Chemical* (2012). [논문 및 표 1](https://www.sciencedirect.com/science/article/pii/S1381116912001070).
6. Vidakis et al., “Energy Consumption vs. Tensile Strength of Poly[methyl methacrylate] in Material Extrusion 3D Printing: The Impact of Six Control Settings,” *Polymers* (2023). [논문 및 표 1–3](https://pmc.ncbi.nlm.nih.gov/articles/PMC9966017/).

## 추가 수집 후보

이번 CSV는 지금 당장 실행별 수치와 출처 표를 함께 검증할 수 있었던 자료만 담았다. 배터리 전극의 파일럿 코팅·건조 연구는 12개 실험 run과 여러 전극/셀 측정 결과가 보충자료 Excel로 제공된다고 논문이 명시한다. 원본 보충자료의 행·열 대응을 검토해 CSV로 옮기는 후속 수집 대상으로 남겨 둔다. [Data in Brief 원문과 데이터 설명](https://doi.org/10.1016/j.dib.2021.107720), [공정 변수와 실험 설계 논문](https://doi.org/10.1016/j.jpowsour.2021.230689).

또한 zeolite 합성 문헌에는 대규모 추출 데이터셋이 제안되어 있으나, 해당 집계 데이터는 run-level 원문 출처와 변환 이력을 별도로 검증해야 하므로 이번의 논문 표 기반 실행 데이터와 섞지 않았다. [ZeoSyn 연구](https://pubs.acs.org/doi/full/10.1021/acscentsci.3c01615).
