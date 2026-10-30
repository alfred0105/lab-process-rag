"""Create an isolated, provenance-labeled literature validation research topic.

This imports only selected published run tables, not demo or synthetic records.
It is idempotent: rerunning it does not duplicate an already populated topic.
"""
import csv
import json
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "http://localhost:8000/api"
TOPIC_NAME = "문헌 레퍼런스 검증 테스트"
DATASETS = {
    "cu_fe_o2_bbd_2026": {
        "method": "CuFeO₂ 수열 박막 합성·어닐링 (문헌 레퍼런스)",
        "steps": [
            ("수열 처리", "수열 온도와 시간을 원문 표 S1 그대로 기록했습니다."),
            ("후열처리", "후열처리 온도와 시간을 원문 표 S1 그대로 기록했습니다."),
        ],
        "factor_step": {
            "hydrothermal_temperature_C": 0, "hydrothermal_time_h": 0,
            "annealing_temperature_C": 1, "annealing_time_h": 1,
        },
        "outcome_units": {"photocurrent_density_at_0.4V_vs_RHE_mA_cm2": "mA/cm²"},
        "caveat": "수열 박막 CuFeO₂ 문헌 데이터입니다. 현재 연구의 ZnO 나노와이어 합성과 물질·목표 측정이 다르므로 동일 공정의 검증으로 해석하면 안 됩니다.",
    },
    "mgal_ldh_coprecip_factorial_2024": {
        "method": "MgAl-LDH 교반·공침 (문헌 레퍼런스)",
        "steps": [("교반·공침·숙성", "문헌 표 3에 보고된 교반 및 혼합/숙성 조건입니다.")],
        "factor_step": {"agitation_rpm": 0, "mixing_or_aging_time_h": 0, "baffles_present": 0},
        "outcome_units": {"induction_onset_min": "min", "solution_A_volume_mL": "mL", "product_yield_g": "g"},
        "caveat": "MgAl 층상이중수산화물 공침의 문헌 데이터입니다. 교반·용기 요인 흐름을 점검하는 별도 공정군이며 ZnO 수열합성 결과와 병합하지 않습니다.",
    },
}
UNITS = {
    "hydrothermal_temperature_C": "°C", "hydrothermal_time_h": "h",
    "annealing_temperature_C": "°C", "annealing_time_h": "h",
    "agitation_rpm": "rpm", "mixing_or_aging_time_h": "h",
    "baffles_present": "boolean",
}


def call(path, payload=None):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    request = urllib.request.Request(f"{API}{path}", data=data, headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def main():
    topics = call("/topics")
    topic = next((item for item in topics if item["name"] == TOPIC_NAME), None)
    if topic is None:
        topic = call("/topics", {"name": TOPIC_NAME, "description": "논문에 실제 보고된 공정 run을 별도 연구 주제에 레퍼런스 상태로 보관합니다. 실험실 측정 기록이나 성공/실패 판정이 아닙니다. 합성 데모 데이터는 포함하지 않습니다."})
    methods = call(f"/topics/{topic['id']}/methods")
    by_name = {item["name"]: item for item in methods}
    csv_path = ROOT / "docs/research-data/cross-domain-process-outcomes.csv"
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    made = 0
    for dataset_id, config in DATASETS.items():
        method = by_name.get(config["method"])
        if method is None:
            method = call(f"/topics/{topic['id']}/methods", {
                "name": config["method"], "description": config["caveat"], "category": "literature_reference",
                "process_map": [{"name": name, "description": description, "step_type": "process"} for name, description in config["steps"]],
                "condition_definitions": [{"step_name": config["steps"][step][0], "name": factor, "unit": UNITS.get(factor, ""), "value_type": "boolean" if isinstance(next((json.loads(row["factors_json"])[factor] for row in rows if row["dataset_id"] == dataset_id and factor in json.loads(row["factors_json"])), None), bool) else "number", "required": False} for factor, step in config["factor_step"].items()],
                "material_definitions": [],
            })
        version_id = method["versions"][0]["id"]
        existing = call(f"/experiments?method_version_id={version_id}")
        existing_names = {item["name"] for item in existing}
        for row in rows:
            if row["dataset_id"] != dataset_id:
                continue
            name = f"문헌 run {row['run_id']}"
            if name in existing_names:
                continue
            factors = json.loads(row["factors_json"])
            outcomes = json.loads(row["outcomes_json"])
            steps = [{"name": step_name, "step_type": "process", "order_index": index, "description": description, "variables": []} for index, (step_name, description) in enumerate(config["steps"])]
            for factor, value in factors.items():
                step = steps[config["factor_step"][factor]]
                step["variables"].append({"name": factor, "value": value, "unit": UNITS.get(factor, ""), "source_type": "literature", "source_id": f"{dataset_id}:{row['run_id']}"})
            source_note = f"LITERATURE_REFERENCE | {dataset_id} / run {row['run_id']} | {row['source_location']} | {row['source_url']} | {row['quality_notes']}"
            payload = {
                "name": name, "target": row["material_or_system"], "operator": "문헌 데이터",
                "notes": f"{source_note}\n\n주의: {config['caveat']}", "status": "reference", "demo": False,
                "topic_id": topic["id"], "method_version_id": version_id, "steps": steps,
                "results": [{"key": key, "value": value.get("mean") if isinstance(value, dict) else value, "unit": config["outcome_units"].get(key, "")} for key, value in outcomes.items()],
                "observations": [{"category": "literature_reference", "description": source_note, "severity": None}],
            }
            call("/experiments", payload)
            made += 1
    print(json.dumps({"topic_id": topic["id"], "topic_name": topic["name"], "created_reference_runs": made, "methods": [{"name": item["name"], "run_count": len(call(f"/experiments?method_version_id={item['versions'][0]['id']}"))} for item in call(f"/topics/{topic['id']}/methods")], "notice": "All imported entries are visibly marked literature reference, not lab experiments."}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except urllib.error.URLError as exc:
        raise SystemExit(f"Local API is not reachable at {API}: {exc}")
