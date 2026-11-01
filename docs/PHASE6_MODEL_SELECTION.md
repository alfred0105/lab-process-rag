# Phase 6 Model Selection

현재 호환 개발 기준은 `Qwen/Qwen3-0.6B` (Apache-2.0; pinned HF revision `c1899de289a04d12100db370d81485cdf75e47ca`)이다. Transformers 4.57.6와 Apple MPS에서 causal LM, hidden states, tied LM embedding 및 실제 layer 접근을 확인했다. 596,049,920 parameters, 28 layers, hidden size 1024, MPS float16. 더 최신 Qwen3.5-0.8B는 조사 당시 multimodal class 및 Transformers 5 계열 필요성 때문에 현재 설치된 호환 스택에서 바로 사용할 수 없어서 이번 실행 모델로 선택하지 않았다. 따라서 이 선택은 “최신 모델” 선언이 아니라 로컬 재현 가능한 호환 기준선이다.

가중치는 Hugging Face 사용자 캐시에 저장되고 저장소에는 포함되지 않는다. 8/4-bit는 현재 MPS 런타임에서 검증되지 않아 미지원으로 기록한다. RTX 4060 Ti는 이번 실행 기기에서 측정하지 않았다.
