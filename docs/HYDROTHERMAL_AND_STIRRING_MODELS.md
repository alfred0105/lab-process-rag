# 범용 수열합성·마그네틱 교반 계산

## 범용 앱에 추가한 구성

- **마그네틱 교반 특성 계산**: 사용자가 기록한 바의 길이·지름, 실제 회전수, 액체 밀도·점도를 이용해 각속도, 바 끝 속도, 바 길이 기준 Reynolds/Froude 수를 계산한다. 비커/간극 치수가 입력되면 형상 비도 반환한다. 이는 물리량 계산이며 CFD 유동장 계산이 아니다.
- **수열합성 물 상태**: IAPWS-IF97로 순수한 물의 포화증기압을 온도에 따라 계산한다. 용질, 초기 headspace 공기, 용액 열팽창, autoclave 강도 및 안전율은 계산하지 않는다. 기기 등급 선정이나 안전 운전에 사용할 수 없다.
- **기판 용액 박막 코팅**: Emslie–Bonner–Peck의 Newtonian 회전 원판 박막 얇아짐 식으로 스핀 코팅 중 습윤막 두께 변화를 계산하고, 입력한 비휘발 부피분율로 1회·반복 횟수의 명목 건조막 두께를 근사한다. 수열 반응 전에 하는 기판 seed/박막 증착 단계로 일반 공정 기록에 사용할 수 있다. 증발·겔화·건조·열처리·기판 젖음/edge bead는 현재 계산하지 않는다.
- **재료별 kinetics plugin 예시**: 현재는 ZnO 나노로드 배열의 공개 문헌 결과만 별도 예시로 제공한다. 범용 물 상태/교반 도구의 기본 전제가 아니다. 5.5 nm/min, 첫 8시간, 보고된 최대 2.4 μm를 문헌 참고 곡선으로 제한해 표시하며 사용자 실험 또는 개별 rod 치수의 예측이라고 표시하지 않는다.

## 현재 미구현 범위

- OpenFOAM 14는 로컬 VM에서 사용 가능하지만 기존 설치 사례는 기계식 임펠러 또는 일반 mixer 예제다. 마그네틱바 형상·작은 바닥 간극·개방 자유액면·회전/미끄럼을 포함하는 검증된 전용 CFD case는 아직 연결하지 않았다. 따라서 공간 3D 유속, 사각지대, 추적자 혼합시간은 반환하지 않는다.
- 범용 수열합성 반응/결정 성장 예측기는 아직 없다. 용액 내 화학종 및 포화도는 별도 PHREEQC 계산으로 가능하나 이는 반응속도·핵생성·결정상·형태·수율 계산이 아니다.
- 코팅 결과의 기판·코팅 재료명과 추산 두께는 사용자가 버튼을 눌러 수열 단계 계산에 맥락 정보로 전달할 수 있다. 이는 아직 계산 간 물리 결합이 아니며 막의 결정성·배향·거칠기는 XRD/AFM/SEM 등 측정 결과로 확인해야 한다.
- 결정성장 도구는 결정 재료, seed/substrate, 농도, pH, 온도 이력, 교반/물질전달 등 모델별 필수 입력과 실험별 속도 상수가 있어야 한다. 각 재료 plugin은 적용 범위를 지정하고 별도의 SEM/XRD/수율 데이터로 검증해야 한다.

## 후속 모델 연결 기준

1. 기존 문헌이나 재현 가능한 오픈소스 구현을 먼저 찾고, 적용 물질계·조성·시드·온도·시간 범위를 명시한다.
2. 적합한 것이 없을 때에만 별도 계산을 만들며, 추정·비교·가설 계산으로 분명하게 표시한다.
3. 문헌 곡선, 열역학 상태 계산, 측정 실험 데이터, 모델 예측을 서로 다른 유형으로 저장하고 그래프에서도 출처를 구분한다.
4. 실제 3D 교반/수열 성장 예측을 주장하기 전에, 실제 실험의 추적자 농도/혼합시간 및 SEM/XRD 결과로 각각 검증한다.

## 문헌과 공식 계산 기준

- 마그네틱 로드 교반 CFD: Li et al., *Water Science and Technology* (2015), DOI [10.2166/wst.2015.314](https://doi.org/10.2166/wst.2015.314). 연구는 moving-reference-frame과 VOF 자유표면 모델을 사용했고, 접선 속도 예측과 모델별 축/반경 속도 한계를 보고한다. 이 논문 자체가 현재 앱에 검증된 CFD 구현으로 이식된 것은 아니다.
- ZnO 배열 성장 속도: Guo et al., *Chinese Journal of Engineering* 29(7), 735–738 (2007), DOI [10.13374/j.issn1001-053x.2007.07.019](https://doi.org/10.13374/j.issn1001-053x.2007.07.019). 앱은 초록에 공개된 근사 속도/길이 범위를 문헌 참고로만 표현한다.
- 수열 ZnO 성장의 조성·온도 의존성: Ahson et al., accepted version record, [University of Cambridge repository](https://www.repository.cam.ac.uk/items/8888235f-3ffa-4e3b-aee9-8b33feec8a59). 특정 seed와 저온 조건의 ZnO 모델이며 범용 결정 성장 모델이 아니다.
- 스핀 코팅 유동: Emslie, Bonner & Peck, “Flow of a Viscous Liquid on a Rotating Disk,” *Journal of Applied Physics* 29, 858–862 (1958), DOI [10.1063/1.1723300](https://doi.org/10.1063/1.1723300). 이 유도는 비휘발 Newtonian 액막의 이상 회전 원판 모델이다.
- 수열 나노로드에서 seed 중요성의 특정 재료계 근거: [Effect of Seed Layer on the Growth of ZnO Nanorods](https://doi.org/10.1021/jp0655017) 및 [Density-controlled hydrothermal growth of well-aligned ZnO nanorod arrays](https://doi.org/10.1088/0957-4484/18/3/035605). 이 문헌들은 ZnO 결과이며 다른 재료계에 그대로 일반화할 수 없다.
- 물/수증기 상태: [IAPWS-IF97 official release](https://iapws.org/technical-guidance/release/IF97-Rev), 공식 열역학 공식이다. 앱은 Python `iapws` 구현을 통해 물 포화 상태량만 계산한다.
