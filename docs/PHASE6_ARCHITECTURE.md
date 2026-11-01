# Phase 6 Architecture — Shared Backbone / Decision-first

상태: `PHASE_6_IN_PROGRESS`. 실제 Qwen3 checkpoint, 단일 모델 인스턴스, 동일 hidden states 위의 독립 학습형 action heads, 결정 우선 API, 조건부 설명, layer-wise 실행 루프가 구현됐다. 2026-11-01 integrity fixes로 분류 학습/추론을 `scientific-state-canonical-v2` 입력 계약으로 통합했고, API research/sandbox 모드, DB citation 조회, decision-locked explanation schema와 artifact version check를 추가했다. 합성 sandbox 외부의 연구 정확도는 검증되지 않았다.

```text
Research API: topic+non-demo experiment DB lookup → source/quality gate
Sandbox API: explicit arbitrary state → provenance forcibly UNVERIFIED
Both → Canonical Context Adapter v2 → one Qwen3 backbone
    → layer 7/14/21/28 decision heads → calibration/OOD/review/safety
    → decision-only (0 generation tokens) or explicit explanation request
Research explanation → topic-scoped DB EvidenceChunk IDs → decision-locked JSON contract
    → citation/action validator → full-prefill fallback + autoregressive KV reuse
```

현재 지원 checkpoint는 Qwen3-0.6B Apache-2.0, 고정 revision `c1899de289a04d12100db370d81485cdf75e47ca`다. Phase6 path는 기존 Gemma/Phase5 model을 대체하거나 활성화하지 않으며 모든 응답 `workflow_triggered=false`다. 설명용 논문 청크는 서버가 저장소·주제 범위로 다시 조회한다. 격리 synthetic DB integration에서 실제 생성까지 실행했지만 모델이 JSON citation contract를 만족하지 못해 출력이 거부되고 안전 fallback이 반환됐다. 따라서 P6-006/008은 `PARTIAL`이다. early exit에서 얻은 KV는 불완전하므로 LM generation에 넘기지 않고 full prefill fallback을 명시한다.

중요한 보안 한계: 앱에는 인증된 사용자/주제별 권한 계층이 없다. topic-scoped lookup은 주제 간 citation 섞임을 막지만 사용자 authorization은 제공하지 않는다. 이를 응답과 readiness에 `TOPIC_SCOPED_NO_AUTHENTICATED_USER_IDENTITY`로 노출한다. 모델 artifact는 `SYNTHETICALLY_TRAINED_UNVALIDATED_DECISION_MODEL`이며 연구 판단을 검증하지 않는다.

실행은 `backend/.venv/bin/python backend/scripts/train_phase6_sandbox.py` (backend 디렉터리에서 `scripts/train_phase6_sandbox.py`)로 수행한다. checkpoint와 artifact는 사용자 캐시 경로에만 두며 Git에 추가하지 않는다.


2026-11-01 closure update: Research requests in `LOCAL_SINGLE_USER` are allowed only from loopback peers; `AUTHENTICATED_MULTI_USER` fails closed until actual authentication exists. Explanation generation now uses token-level JSON Schema constraints and verifies locked action and allowlisted DB citation identity. In isolated synthetic fixtures 4/5 scenario outputs passed while one malicious conflicting-action output was rejected; semantic entailment is not verified. Expanded synthetic early-exit diagnostics found no policy meeting the predeclared sequential risk gate; the production path remains full-depth. Phase 6 stays `IN_PROGRESS`. Details: `PHASE6_CORE_COMPLETION.md`.
