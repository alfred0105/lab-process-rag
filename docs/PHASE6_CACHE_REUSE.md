# Phase 6 Hidden State and KV Cache

Decision-only 경로는 `generate()`를 호출하지 않고 생성 토큰 0개를 반환한다. Early exit는 중간 깊이에서 멈춰 완전한 all-layer KV cache를 만들지 않으므로 explanation 요청 때 full-depth prefill을 다시 한다. 이후 autoregressive token마다 같은 요청의 DynamicCache를 이어 쓴다. 따라서 구현 상태는 `FULL_PREFILL_FALLBACK_AND_TOKEN_KV_REUSE`; “decision cache 재사용” 또는 early-exit 후 남은 층 재개라고 주장하지 않는다. 생성 경로에서는 매 token의 attention mask/cache position을 runtime API에 넘기고 cache bytes를 기록한다. 비교 출력과 제한은 generation report에 남긴다.
