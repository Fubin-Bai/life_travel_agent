"""运行独立访谈基准并比较 actual/expected；不训练、不修正模型输出。"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from life_journey.application import apply_interview_update, build_interview_prompt
from life_journey.application.interview_prompt import INTERVIEW_SYSTEM_PROMPT
from life_journey.llm import InterviewLLMClient, LLMClientError
from life_journey.schemas import InterviewTurnResult
from .cases import InterviewCase, load_cases, load_dialogue_cases, prepare_case


def score_case(case: InterviewCase, turn: InterviewTurnResult, applied) -> dict:
    """精确比较结构字段；独立列出禁用词命中，收束采用公开启发式规则。"""
    actual = applied.updated_context.model_dump(mode="json")
    failures = []
    for name, expected in case.expected_context.items():
        if actual[name] != expected:
            failures.append(f"{name}: expected={expected!r}, actual={actual[name]!r}")
    for topic in case.expected_confirmed:
        if topic not in turn.confirmed_topics or getattr(applied.updated_state.topics, topic) != "confirmed":
            failures.append(f"{topic}: 本轮未明确 confirmed")
        # 即便初始为空，也要求明确输出 []，而不是省略后碰巧保留默认值。
        if topic in case.expected_context and topic not in turn.context_update.model_fields_set:
            failures.append(f"{topic}: update 省略，未显式表达本轮值")
    if case.expected_ready is not None and applied.deterministic_ready_to_plan != case.expected_ready:
        failures.append(f"deterministic_ready_to_plan: expected={case.expected_ready}, actual={applied.deterministic_ready_to_plan}")
    if case.partner:
        for topic in ("preferred_pace", "activity_preferences", "required_activities", "excluded_activities"):
            if topic in turn.confirmed_topics:
                failures.append(f"{topic}: 用户未明确提供，不能自动 confirmed")
    structured_text = json.dumps(turn.context_update.model_dump(mode="json"), ensure_ascii=False)
    hits = []
    for pattern in case.forbidden_patterns:
        for scope, text in (("context_update", structured_text), ("assistant_message", turn.assistant_message)):
            matches = re.findall(pattern, text, flags=re.IGNORECASE)
            if matches:
                hits.append({"scope": scope, "pattern": pattern, "matches": matches})
    if hits:
        failures.append("forbidden inference 词汇规则命中（需复核是否为推断、否定或澄清）")
    closure_passed = None
    if case.expect_closure:
        # 不仅检查问号；同时识别常见无问号追问和明确阶段收束。
        follow_up = re.search(r"[?？]|有没有|是否|哪[些个种里]|想再|还想|请问|告诉我|would you|do you|what |which ",
                              turn.assistant_message, re.IGNORECASE)
        closing = re.search(r"规划|行程|下一阶段|信息.*足够|了解.*清楚|了解.*差不多|进入下一步|planning|itinerary|ready", turn.assistant_message, re.IGNORECASE)
        closure_passed = follow_up is None and closing is not None
        if not closure_passed:
            failures.append("assistant_message 未通过自然收束规则：继续追问或缺少明确结束信号")
    dialogue_hits = []
    patterns = (*case.forbidden_question_patterns,
                r"purpose|preferred_pace|activity_preferences|required_activities|excluded_activities|special_requirements",
                r"(?:依次|逐项).{0,8}(?:确认|填写|回答)")
    for pattern in patterns:
        if re.search(pattern, turn.assistant_message, re.IGNORECASE):
            dialogue_hits.append(pattern)
    if dialogue_hits:
        failures.append("对话策略规则命中：重复追问已表达信息或暴露内部 checklist（需人工复核）")
    return {
        "case_id": case.case_id, "status": "FAIL" if failures else "PASS",
        "failures": failures, "expected": {"context": case.expected_context,
            "confirmed_topics": list(case.expected_confirmed), "deterministic_ready": case.expected_ready},
        "actual": {"turn": turn.model_dump(mode="json"), "context": actual,
            "state": applied.updated_state.model_dump(mode="json"),
            "deterministic_ready": applied.deterministic_ready_to_plan},
        "forbidden_inference": {"status": "FAIL" if hits else "PASS", "hits": hits,
                                "method": "词汇启发式；不是语义裁判，否定/澄清可能误报"},
        "closure_passed": closure_passed,
        "dialogue_strategy": {"status": "FAIL" if dialogue_hits else "PASS", "hits": dialogue_hits, "method": "重复提问/checklist 词汇启发式，不是自然性完整评分"},
    }


def run_benchmark(client: InterviewLLMClient, *, include_dialogue: bool = False) -> dict:
    """六例独立、每例一次调用；调用失败计入总分，不重试、不跳过失败例。"""
    results = []
    for case in load_cases() + (load_dialogue_cases() if include_dialogue else []):
        context, state = prepare_case(case)
        try:
            call = client.generate_interview_turn(build_interview_prompt(context, state, case.user_message))
            applied = apply_interview_update(context, state, call.output)
            result = score_case(case, call.output, applied)
            result["metrics"] = call.model_dump(mode="json", exclude={"output"})
        except LLMClientError as exc:
            result = {"case_id": case.case_id, "status": "FAIL", "failures": [str(exc)],
                      "forbidden_inference": {"status": "NOT_EVALUATED", "hits": []}}
        except (ValueError, TypeError):
            result = {"case_id": case.case_id, "status": "FAIL", "failures": ["应用或输出校验失败"],
                      "forbidden_inference": {"status": "NOT_EVALUATED", "hits": []}}
        results.append(result)
    passed = sum(item["status"] == "PASS" for item in results)
    return {"benchmark": "interview-v0-8-cases-v2" if include_dialogue else "interview-v0-6-cases-v2", "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "prompt_sha256": hashlib.sha256(INTERVIEW_SYSTEM_PROMPT.encode()).hexdigest(),
            "scoring": "字段/列表顺序精确比较；禁用推断与收束为透明词汇启发式，无额外 LLM judge",
            "results": results, "passed": passed, "total": len(results), "pass_rate": passed / len(results)}


def main(argv: list[str] | None = None) -> int:
    """手动命令入口；仅此处组合真实 Provider，可选择保存虚构 benchmark 报告。"""
    parser = argparse.ArgumentParser(description="V0 Interview Evaluation（会产生六次真实调用）")
    parser.add_argument("--output", type=Path, help="保存 JSON 报告，含固定虚构输入的实际输出")
    parser.add_argument("--include-dialogue", action="store_true", help="另加整句理解与不重复确认的两例回归")
    args = parser.parse_args(argv)
    from life_journey.llm.deepseek import DeepSeekInterviewClient
    try:
        client = DeepSeekInterviewClient()
    except LLMClientError as exc:
        print(f"配置失败：{exc}")
        return 2
    try:
        report = run_benchmark(client, include_dialogue=args.include_dialogue)
    finally:
        client.close()
    for item in report["results"]:
        print(f"{item['case_id']}: {item['status']} | forbidden={item['forbidden_inference']['status']}")
        for failure in item["failures"]:
            print(f"  - {failure}")
    print(f"通过率：{report['passed']}/{report['total']} ({report['pass_rate']:.1%})")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"报告已保存：{args.output}")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
