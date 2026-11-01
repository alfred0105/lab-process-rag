# Phase 6 Architecture — Shared Backbone / Decision-first

상태: `PHASE_6_IN_PROGRESS`. 실제 Qwen3 checkpoint, 단일 모델 인스턴스, 동일 hidden states 위의 독립 학습형 action heads, 결정 우선 API, 조건부 설명, layer-wise 실행 루프가 구현됐다. 합성 sandbox 외부의 연구 정확도는 검증되지 않았다.

```text
ScientificState V2 → provenance/evidence filter → one Qwen3 backbone
    → layer 7/14/21/28 decision heads → calibration/OOD/safety
    → decision-only (0 generation tokens) or explicit explanation request
    → full-prefill fallback + autoregressive KV reuse
```

현재 지원 checkpoint는 Qwen3-0.6B Apache-2.0, 고정 revision `c1899de289a04d12100db370d81485cdf75e47ca`다. Phase6 path는 기존 Gemma/Phase5 model을 대체하거나 활성화하지 않으며 모든 응답 `workflow_triggered=false`다. early exit에서 얻은 KV는 불완전하므로 LM generation에 넘기지 않고 full prefill fallback을 명시한다.

실행은 `backend/.venv/bin/python backend/scripts/train_phase6_sandbox.py` (backend 디렉터리에서 `scripts/train_phase6_sandbox.py`)로 수행한다. checkpoint와 artifact는 사용자 캐시 경로에만 두며 Git에 추가하지 않는다.
