# Phase 6 Hidden State and KV Cache

Decision-only 경로는 autoregressive generation을 호출하지 않고 생성 토큰 0개를 반환한다. Early exit는 중간 깊이에서 멈춰 완전한 all-layer KV cache를 만들지 않으므로 explanation 요청 때 full-depth prefill을 다시 한다. 이후 autoregressive token마다 같은 요청의 DynamicCache를 이어 쓴다. Decision context와 explanation context는 다르므로 prefill cache를 공유하지 않는다. 격리 DB 기반 실제 체크포인트 경로에서 81 token 생성 및 103,907,328 cache bytes를 확인했으나 출력 JSON에 citation이 빠져 거부됐다. 따라서 실제 증거 기반의 성공 설명이나 cache correctness는 아직 검증되지 않았다. 비교 출력과 제한은 generation report 및 `phase6_generation_validation.json`에 남긴다.
