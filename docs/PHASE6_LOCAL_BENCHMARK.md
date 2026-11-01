# Phase 6 Local Benchmark

실행 환경: Apple Silicon MacBook Air M5 / 24GB unified memory, macOS arm64. Checkpoint: pinned Qwen3-0.6B, MPS float16. `backend/scripts/train_phase6_sandbox.py`는 실제 hidden-state extraction, decision-head train/load, canonical token equality, request variation, early/full-depth 비교, decision-only token count, KV bytes와 device 메모리를 기록한다. `backend/scripts/validate_phase6_integrity.py`는 임시 격리 SQLite에서 실제 API·citation 조회·Qwen generation 경로를 실행하며 DB는 synthetic software-test fixture다. MPS 값은 peak이 아닌 실행 종료 후 Metal driver allocation이다. host RSS는 process high-water mark로 새로 기록했으며 모델만의 RSS가 아니다. 직접 FLOPs/전력/열, int4/int8, RTX 4060 Ti는 측정하지 않았다. 산출물은 `backend/reports/phase6_*.json`이다.


## Early-exit closure update — 2026-11-01

The grouped 480-case diagnostic is recorded in `backend/reports/phase6_early_exit_diagnostics.json`. No architecture passed the separate sequential controller bound, so no candidate early-exit latency benchmark was eligible. Production inference remains full-depth and no speedup is claimed.
