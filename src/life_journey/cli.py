"""开发用内存访谈终端；不保存历史、不自动规划。"""

from life_journey import environment

import argparse

from life_journey.application import (
    build_travel_context, initialize_interview, run_interview_turn,
)
from life_journey.llm import InterviewLLMClient, LLMClientError
from life_journey.sample_data import load_persons, load_relationships, load_trips


def run_cli(client: InterviewLLMClient, *, debug: bool = False) -> int:
    """每轮仅展示一条完整回复，并将新上下文和状态传入下一轮。"""
    context = build_travel_context(
        load_trips()["trip_tokyo_alex_bella"],
        load_persons().values(), load_relationships().values(),
    )
    state = initialize_interview(context)
    trip = context.trip
    print("人生旅迹 V0 Travel Interview（虚构测试场景）")
    print(f"Destination: {trip.destination} | Dates: {trip.start_date} — {trip.end_date}")
    print("Participants: " + ", ".join(person.name for person in context.participants))
    print(f"Budget: {trip.budget.min_amount}–{trip.budget.max_amount} {trip.budget.currency}")
    print("输入 /quit 或 /exit 退出；本程序不生成行程。")
    while True:
        try:
            message = input("You: ")
        except (EOFError, KeyboardInterrupt):
            print("\n访谈已结束。")
            return 0
        if message.strip().lower() in {"/quit", "/exit"}:
            return 0
        if not message.strip():
            print("请输入非空消息。")
            continue
        try:
            result = run_interview_turn(context, state, message, client)
        except LLMClientError as exc:
            print(f"调用失败：{exc}")
            return 1
        except (ValueError, TypeError):
            # 校验错误可能包含原始输入；终端只展示分类信息，避免泄露内容。
            print("访谈应用失败：输入、状态或更新未通过校验；本次运行结束。")
            return 1
        context, state = result.updated_context, result.updated_state
        print("AI: " + result.assistant_message)
        if debug:
            metrics = result.metrics
            print(f"[model={metrics['model']} | tokens={metrics['total_tokens']} | "
                  f"latency={metrics['latency_ms']:.0f}ms | "
                  f"llm_ready={result.llm_ready_to_plan} | system_ready={result.deterministic_ready_to_plan}]")
        if result.deterministic_ready_to_plan:
            print("[READY TO PLAN]")
            return 0


def main(argv: list[str] | None = None) -> int:
    """仅在终端入口组合具体 Provider；沿用环境变量配置。"""
    environment.load_project_env()
    parser = argparse.ArgumentParser(description="人生旅迹 V0 开发访谈")
    parser.add_argument("--debug", action="store_true", help="显示每轮调用指标与就绪状态")
    args = parser.parse_args(argv)
    from life_journey.llm.deepseek import DeepSeekInterviewClient

    try:
        client = DeepSeekInterviewClient()
    except LLMClientError as exc:
        print(f"配置失败：{exc}")
        return 1
    try:
        return run_cli(client, debug=args.debug)
    except KeyboardInterrupt:
        print("\n访谈已结束。")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
