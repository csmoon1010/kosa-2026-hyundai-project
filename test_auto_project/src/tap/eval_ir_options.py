"""고정 승인본으로 IR 생성 옵션 8개 조합을 비교한다.

eval_stages의 실행 흐름을 복제하고 정답셋 로딩과 채점은 같은 구현을 사용한다.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import time
from itertools import product
from pathlib import Path

from dotenv import load_dotenv

from tap.cli import ROOT, analyze_select, datetime_now
from tap.eval_stages import _stage_cost, compact_ir, load_gold, score
from tap.apis.gate import approve
from tap.ir.draft_build import IR_INPUTS, fixed_plan, generate
from tap.ir.handoff import hyejung_approved, missing_materials, save_hyejung_approved

OPTION_NAMES = ("stop_retry", "kb_rag", "dependency_projection")


def select_once(case, analyze, trace_dir):
    """①②③ 결과와 승인본 생성에 사용할 원본 객체를 반환한다."""
    out: dict[str, Any] = {"tasks": None, "paths": None, "apis": None, "gate": None, "ir": None, "error": None}
    r = None
    try:
        r = analyze(case["utterance"], trace_dir=trace_dir)
        out["trace_file"] = r.get("trace_file")
        out.update(tasks=r["tasks"].model_dump(), paths=r["paths"].dump(), apis=r["apis"].dump(),
                   gate=r["gate"].model_dump(), final_status=r["apis"].status, cost=_stage_cost(r["trace"].to_dict()))
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        out["final_status"] = "거절(검사)" if out["error"].startswith("GoalError") else \
            "중단" if out["error"].startswith(("BudgetExceeded", "Stopped")) else "오류"
        tr = getattr(e, "trace", None)
        out["cost"] = _stage_cost(tr.to_dict() if tr is not None else None)
        saved = next(trace_dir.glob("*.json"), None)
        out["trace_file"] = str(saved) if saved else None
    return out, r


def prepare_approved(root, selection):
    gate = selection["gate"]
    approval = approve(gate, "평가", scenario=True, steps=list(gate.need_steps))
    data = hyejung_approved(selection["tasks"], selection["paths"], selection["apis"],
                            gate, approval, {"trace": selection.get("trace_file")})
    missing = missing_materials(root, data, fixed_plan(data))
    if missing:
        raise ValueError("IR 자료 없음: " + "; ".join(missing))
    return save_hyejung_approved(root, data)


def run_ir(root, filename, options):
    started = time.monotonic()
    usage = {}
    trace_file = None
    reason = None

    def record(event):
        nonlocal usage, reason
        if "usage" in event:
            usage = event["usage"]
        if event.get("reason_code"):
            reason = event["reason_code"]

    try:
        result = generate(root, filename, on_event=record, generation_options=options)
        usage = result["usage"]
        trace_file = result["log_file"]
        out = compact_ir(result["ir"])
    except Exception as error:
        trace_file = getattr(error, "log_file", trace_file)
        out = {"error": f"{type(error).__name__}: {error}"}

    return {**out, "trace_file": str(root / trace_file) if trace_file else None,
            "stop_reason": reason if "error" in out else None,
            "latency_ms": round((time.monotonic() - started) * 1000),
            "cost_usd": usage.get("cost_usd"), "tokens": usage.get("total_tokens"),
            "llm_calls": usage.get("llm_calls")}


def evaluate(cases, analyze, run_dir, parameters, repeats, report, save):
    for index, case in enumerate(cases, 1):
        task_root = run_dir / f"task-{index:03d}"
        selection, raw = select_once(case, analyze, task_root / "selection_traces")
        expected = case.get("expect") or {}
        selection_case = {**case, "expect": {k: v for k, v in expected.items() if k != "params"}}
        selection_score = score(selection_case, selection)
        selection_score["stages"].pop("params")
        task = {"id": case["id"], "selection": selection,
                "selection_score": selection_score, "runs": []}
        report["tasks"].append(task)

        expected_gate = (expected.get("final") or {}).get("gate")
        if expected_gate == ["차단"] or not raw or raw["gate"].status not in ("자동", "승인 필요"):
            task["skip_reason"] = "정답상 IR 미진입" if expected_gate == ["차단"] else "승인 가능한 선택 결과 없음"
            save()
            continue

        material_dir = task_root / "data/out"
        material_dir.mkdir(parents=True)
        (material_dir / "parameters").symlink_to(parameters, target_is_directory=True)
        config_dir = task_root / "data/config"
        config_dir.mkdir()
        shutil.copyfile(ROOT / "data/config/llm.yaml", config_dir / "llm.yaml")
        try:
            approved = prepare_approved(task_root, raw)
        except (ValueError, OSError) as error:
            task["skip_reason"] = str(error)
            save()
            continue
        task["approved_file"] = str(task_root / IR_INPUTS / approved)
        save()

        for flags in product((False, True), repeat=len(OPTION_NAMES)):
            options = dict(zip(OPTION_NAMES, flags))
            for trial in range(1, repeats + 1):
                ir = run_ir(task_root, approved, options)
                ir_score = score(case, {**selection, "ir": ir})["stages"]["params"]
                task["runs"].append({"options": options, "trial": trial,
                                     "score": ir_score, "ir": ir})
                save()
                print(f"{case['id']} {flags} #{trial}: {ir_score['alone']}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--ids", help="쉼표로 구분한 태스크 ID")
    parser.add_argument("--runs", type=int, default=3, help="옵션 조합별 반복 수")
    parser.add_argument("--out", type=Path, default=ROOT / "data/out/eval/ir-options")
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs는 1 이상이어야 합니다.")
    cases = load_gold(args.gold)
    if args.ids:
        ids = {value.strip() for value in args.ids.split(",")}
        unknown = ids - {case["id"] for case in cases}
        if unknown:
            parser.error("알 수 없는 태스크 ID: " + ", ".join(sorted(unknown)))
        cases = [case for case in cases if case["id"] in ids]

    load_dotenv()
    args.out.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="ir-options-", dir=args.out.resolve()))
    output = run_dir / "results.json"
    parameters = run_dir / "parameters"
    shutil.copytree(ROOT / "data/out/parameters", parameters)
    report = {"meta": {"gold": str(args.gold.resolve()), "at": datetime_now(),
                       "model": os.getenv("OPENAI_DEFAULT_MODEL"), "runs_per_combination": args.runs,
                       "planning_stop_retry": True}, "tasks": []}

    def save():
        pending = output.with_suffix(".tmp")
        pending.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        pending.replace(output)

    def analyze(utterance, *, trace_dir):
        return analyze_select(utterance, rules_cfg=ROOT / "data/config/rules.ui.yaml",
                              trace_dir=trace_dir, stop_retry=True)

    save()
    print(f"평가 결과: {output}", flush=True)
    evaluate(cases, analyze, run_dir, parameters, args.runs, report, save)


if __name__ == "__main__":
    main()
