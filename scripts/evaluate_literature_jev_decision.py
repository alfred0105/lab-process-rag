"""Evaluate Gemma analysis + Jev-style choice on imported paper run tables.

Each paper/process dataset remains isolated. Two reported candidate outcomes
are hidden from model context; the remaining runs and candidate conditions are
shared with Gemma analysis and both choice mechanisms.
"""
from __future__ import annotations

import json
import os
import statistics
import time
from pathlib import Path

import httpx

from app.services.benchmark_data import dataset_records
from app.services.llm import AISettings, OllamaProvider

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "LITERATURE_JEV_DECISION_EVALUATION.md"
OUTCOMES = {
    "pmma_mex_taguchi_l25_2023": ("tensile_strength_MPa", "maximize", "MPa"),
    "water_hyacinth_htl_ccd_2023": ("bio_oil_yield_percent", "maximize", "%"),
    "water_hyacinth_htl_uncatalyzed_ccd_2023": ("bio_oil_yield_percent", "maximize", "%"),
    "mgal_ldh_coprecip_factorial_2024": ("product_yield_g", "maximize", "g"),
    "co_zno_ciprofloxacin_ccd_2024": ("ciprofloxacin_removal_percent_actual", "maximize", "%"),
}


def number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, dict):
        value = value.get("mean")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def pairs_for(dataset_id):
    outcome_key, objective, unit = OUTCOMES[dataset_id]
    rows = dataset_records(dataset_id)
    measured = [(number(row["outcomes"].get(outcome_key)), row) for row in rows]
    measured = [(value, row) for value, row in measured if value is not None]
    measured.sort(key=lambda item: item[0], reverse=(objective == "maximize"))
    best_value, best_row = measured[0]
    distinct_runner_up = next(((value, row) for value, row in measured[1:] if value != best_value), None)
    median_row = measured[len(measured) // 2]
    selected = []
    for pair_label, alternative in (("best_vs_runner_up", distinct_runner_up), ("best_vs_median", median_row)):
        if alternative is None:
            continue
        alt_value, alt_row = alternative
        if alt_row["run_id"] == best_row["run_id"]:
            continue
        selected.append((pair_label, [(best_value, best_row), (alt_value, alt_row)]))
    return rows, outcome_key, objective, unit, measured, selected


def analyze_with_gemma(settings, dataset, train_rows, candidates, outcome_key, unit):
    source = {
        "dataset_id": dataset[0]["dataset_id"],
        "domain": dataset[0]["domain"],
        "process_family": dataset[0]["process_family"],
        "material_or_system": dataset[0]["material_or_system"],
        "source_url": dataset[0]["source_url"],
        "source_location": dataset[0]["source_location"],
    }
    visible_training = [{
        "run_id": row["run_id"], "process_variant": row["process_variant"],
        "factors": row["factors"], "reported_outcome": row["outcomes"].get(outcome_key),
    } for row in train_rows]
    visible_candidates = [{"candidate_id": chr(65 + index), "run_id": row["run_id"],
                           "process_variant": row["process_variant"], "factors": row["factors"]}
                          for index, (_, row) in enumerate(candidates)]
    prompt = (
        "Analyze this one paper's experimental runs for the stated measured outcome. Summarize only patterns visible in the supplied training runs, "
        "state confounding or small-sample limits, and compare the two candidate conditions qualitatively. Candidate outcome values are deliberately withheld. "
        "Do not choose A or B, do not invent an outcome, do not claim causation, and do not estimate success probability. Keep it to 3 short sentences.\n"
        f"Outcome to maximize: {outcome_key} ({unit}).\n"
        f"Source and process: {json.dumps(source, ensure_ascii=False)}\n"
        f"Training runs (candidate result rows excluded): {json.dumps(visible_training, ensure_ascii=False)}\n"
        f"Candidates (conditions only; results hidden): {json.dumps(visible_candidates, ensure_ascii=False)}"
    )
    payload = {
        "model": settings.ollama_model,
        "messages": [
            {"role": "system", "content": "You are a careful experimental-data analyst. Discuss reported associations and limitations only. Do not choose a candidate, invent measurements, or state causal conclusions."},
            {"role": "user", "content": prompt},
        ],
        "stream": False, "think": False, "keep_alive": settings.keep_alive,
        "options": {"num_ctx": settings.context_tokens, "num_predict": 140, "temperature": 0},
    }
    started = time.perf_counter()
    response = httpx.post(f"{settings.ollama_base_url}/api/chat", json=payload, timeout=settings.request_timeout_seconds)
    response.raise_for_status()
    content = response.json().get("message", {}).get("content", "").strip()
    if not content:
        raise RuntimeError("Gemma returned an empty literature-data analysis")
    return content, round((time.perf_counter() - started) * 1000), source, visible_training


def main():
    settings = AISettings.from_environment()
    if not settings.enabled or not settings.ollama_model:
        raise SystemExit("Set AI_PROVIDER=ollama and OLLAMA_MODEL to a local model.")
    provider = OllamaProvider(settings)
    # Warm the same Ollama runner before latency collection.
    httpx.post(f"{settings.ollama_base_url}/api/chat", json={
        "model": settings.ollama_model, "messages": [{"role": "user", "content": "Reply ready."}],
        "stream": False, "think": False, "keep_alive": settings.keep_alive,
        "options": {"num_ctx": settings.context_tokens, "num_predict": 1, "temperature": 0},
    }, timeout=settings.request_timeout_seconds).raise_for_status()

    results = []
    trial_no = 0
    for dataset_id in OUTCOMES:
        all_rows, outcome_key, objective, unit, measured, pairs = pairs_for(dataset_id)
        first = all_rows[0]
        for pair_label, pair in pairs:
            trial_no += 1
            # Counterbalance candidate position so a model that always picks the
            # first option cannot appear accurate simply from our pair ordering.
            if trial_no % 2 == 0:
                pair = list(reversed(pair))
            candidate_ids = {row["run_id"] for _, row in pair}
            train_rows = [row for row in all_rows if row["run_id"] not in candidate_ids]
            # Gemma performs interpretation; Jev-style token selection consumes that
            # interpretation plus the same-paper data and candidate conditions.
            # Held-out candidate outcomes stay local for evaluation only.
            analysis, analysis_ms, source, visible_training = analyze_with_gemma(
                settings, all_rows, train_rows, pair, outcome_key, unit,
            )
            options = [{
                "id": f"candidate_{chr(97 + index)}",
                "label": f"Run {row['run_id']}",
                "description": f"{row['process_variant']}; conditions={json.dumps(row['factors'], ensure_ascii=False)}",
            } for index, (_, row) in enumerate(pair)]
            state = {
                "source": source,
                "objective": f"Choose the condition with the higher reported {outcome_key} ({unit}).",
                "training_runs": visible_training,
                "gemma_analysis": analysis,
            }
            question = f"Which candidate is better supported for maximizing {outcome_key}? Choose only A or B; do not state success probability."
            try:
                decision = provider.decide_choice(state, question, options)
                jev_pick = decision["selected_option_id"]
                jev_ms = decision["latency_ms"]
            except Exception as exc:
                jev_pick, jev_ms = None, 0
                jev_error = f"{type(exc).__name__}: {exc}"
            else:
                jev_error = ""
            values = [value for value, _ in pair]
            best_value = max(values) if objective == "maximize" else min(values)
            range_values = [value for value, _ in measured]
            data_range = max(range_values) - min(range_values)
            expected_ids = {row["run_id"] for value, row in pair if value == best_value}
            by_id = {f"candidate_{chr(97 + i)}": row for i, (_, row) in enumerate(pair)}
            item = {
                "dataset_id": dataset_id, "process_family": first["process_family"],
                "domain": first["domain"], "source_url": first["source_url"],
                "pair": pair_label, "outcome_key": outcome_key, "unit": unit,
                "candidates": [{"id": key, "run_id": row["run_id"], "factors": row["factors"],
                                "held_out_outcome": number(row["outcomes"].get(outcome_key))}
                               for key, row in by_id.items()],
                "expected_run_ids": sorted(expected_ids), "jev_pick": jev_pick, "jev_latency_ms": jev_ms,
                "analysis_latency_ms": analysis_ms,
                "analysis": analysis, "jev_error": jev_error,
                "jev_correct": bool(jev_pick and by_id[jev_pick]["run_id"] in expected_ids),
                "jev_normalized_regret": (best_value-number(by_id[jev_pick]["outcomes"].get(outcome_key)))/data_range if jev_pick and data_range else None,
            }
            results.append(item)
            print(f"{dataset_id} {pair_label}: Jev selected {jev_pick}", flush=True)

    latencies = [item["jev_latency_ms"] for item in results]
    regrets = [item["jev_normalized_regret"] for item in results if item["jev_normalized_regret"] is not None]
    jev = {
        "valid": sum(bool(item["jev_pick"]) for item in results),
        "correct": sum(item["jev_correct"] for item in results),
        "accuracy": sum(item["jev_correct"] for item in results)/len(results),
        "normalized_regret": statistics.mean(regrets) if regrets else None,
        "mean_latency": statistics.mean(latencies),
        "median_latency": statistics.median(latencies),
    }
    md = [
        "# 논문 데이터 기반 Jev 선택 모듈 점검", "",
        f"- 실행 시각: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"- 사용 모델: 로컬 Ollama `{settings.ollama_model}`",
        "- 데이터 출처: 앱에 가져온 `cross-domain-process-outcomes.csv`. 논문 및 공정 데이터셋은 서로 섞지 않고 각각 따로 처리했습니다.",
        "- 역할 분담: Gemma가 같은 논문의 나머지 실험 데이터를 분석하고 경향과 한계를 설명했습니다. Jev 선택 모듈은 그 분석과 실험 기록을 바탕으로 후보 조건 중 하나를 골랐습니다.",
        "- 특정 후보가 항상 첫 번째에 오지 않도록 후보 순서를 번갈아 배치했습니다.",
        "- 정답 기준은 후보 두 조건 중 논문에 보고된 측정값이 더 높은 조건입니다. 이미 발표된 결과를 이용한 회고 점검이며, 원인이나 새 실험의 성공 확률을 검증한 것은 아닙니다.", "",
        "| 선택 모듈 | 유효 선택 | 관측 결과가 더 높았던 조건 선택 | 선택 정확도 | 정규화 손실 평균¹ | 선택 시간 평균 / 중앙값 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    accuracy = f"{jev['accuracy']:.1%}"
    regret = f"{jev['normalized_regret']:.3f}" if jev["normalized_regret"] is not None else "n/a"
    latency = f"{jev['mean_latency']:.0f} / {jev['median_latency']:.0f} ms"
    md.append(f"| Jev 선택 모듈 (Gemma 분석 후) | {jev['valid']}/{len(results)} | {jev['correct']}/{jev['valid']} | {accuracy} | {regret} | {latency} |")
    md += ["", "¹ 정규화 손실은 각 논문 데이터의 전체 측정값 범위에 비해 최선 조건을 놓친 정도를 나타냅니다. 결과가 다른 단위인 데이터셋끼리 단순 크기를 비교하지 않도록 범위로 나눈 뒤 평균했습니다.", "",
           "## 사용한 논문 데이터", "", "| 데이터셋 | 논문에 수록된 실행 수 | 평가한 결과값 | 논문 출처 |", "|---|---:|---|---|"]
    for dataset_id in OUTCOMES:
        rows = dataset_records(dataset_id)
        outcome_key, _, _ = OUTCOMES[dataset_id]
        md.append(f"| {dataset_id} | {len(rows)} | `{outcome_key}` | [논문 보기]({rows[0]['source_url']}) |")
    md += ["", "## 조건별 선택 결과", "", "| 데이터셋 | 비교 상황 | 후보 A (논문 결과값) | 후보 B (논문 결과값) | 실제로 더 높았던 조건 | Jev 선택 |", "|---|---|---|---|---|---|"]
    for item in results:
        expected = ", ".join(item["expected_run_ids"])
        cand_a, cand_b = item["candidates"]
        fmt = lambda c: f"{c['run_id']} ({c['held_out_outcome']} {item['unit']})"
        jev_run = next((c["run_id"] for c in item["candidates"] if c["id"] == item["jev_pick"]), "unavailable")
        md.append(f"| {item['dataset_id']} | {item['pair']} | {fmt(cand_a)} | {fmt(cand_b)} | {expected} | {jev_run} |")
    md += ["", "## 두 모듈의 역할", "", "Gemma는 측정된 논문 데이터를 해석하고, 관측된 경향과 불확실성, 추가로 필요한 근거를 설명합니다. Jev는 Gemma의 분석과 실험 기록을 입력으로 받아 주어진 다음 조건 후보 중 하나를 선택합니다. Jev가 과학적 원인 분석을 대신하지 않으며, 이번 평가에서 Gemma를 Jev와 경쟁하는 선택기로 점수 매기지 않았습니다.", ""]
    md += ["## 해석할 때 주의할 점", "", "- 서로 다른 5개 공정군에서 10개 조건 쌍만 점검한 소규모 평가입니다. Jev의 전반적인 신뢰성을 입증하지는 않습니다.",
           "- 각 데이터셋 안에서 후보 실험이 일부 겹칩니다. 논문별 실험 절차와 측정 방식도 서로 다릅니다.",
           "- 인장강도, 바이오오일 수율, 생성물 질량, 오염물질 제거율을 각각 높이는 문제로 설정했습니다. 다른 측정값이나 부호 해석이 필요한 CuFeO2 광전류 데이터는 섞지 않았습니다.",
           "- 후보 점수는 보정된 성공 확률이 아니라 모델이 후보 토큰에 부여한 상대 점수입니다.",
           "- 각 조건과 원 논문 링크를 보존했습니다. 문헌 데이터를 사용자의 실제 실험 기록으로 저장하지 않았습니다. 이번 점검은 Gemma 분석과 백엔드 Jev 선택 서비스를 대상으로 했으며, 화면에서 분석을 누르는 전체 흐름까지 확인한 것은 아닙니다.", ""]
    REPORT.write_text("\n".join(md), encoding="utf-8")
    print(f"Wrote {REPORT}")
    print("Jev selector", jev)


if __name__ == "__main__":
    main()
