"""使用独立 fake Client 验证编排与终端，不依赖具体 Provider 或网络。"""

import json

import pytest

from fixtures import load_persons, load_relationships, load_trips
from life_journey.application import build_travel_context, initialize_interview, run_interview_turn
from life_journey.application.interview_prompt import build_interview_prompt
from life_journey.cli import run_cli
from life_journey.llm import LLMCallResult, LLMRequestError, LLMResponseError
from life_journey.schemas import InterviewTurnResult, TravelContext


class FakeClient:
    """按顺序返回已验证结果，记录收到的请求；不导入真实 Provider。"""

    def __init__(self, turns):
        self.turns = iter(turns)
        self.prompts = []

    def generate_interview_turn(self, prompt):
        """保存请求并模拟一次成功或明确失败。"""
        self.prompts.append(prompt)
        turn = next(self.turns)
        if isinstance(turn, Exception):
            raise turn
        return LLMCallResult(output=turn, provider="fake", model="fake-model",
                             input_tokens=100, output_tokens=20, total_tokens=120,
                             latency_ms=12.5, cached_input_tokens=10, reasoning_tokens=None)


def turns():
    """构造两轮结果；第一轮模型提前就绪，第二轮模型保守但系统满足门槛。"""
    return [
        InterviewTurnResult(context_update={"purpose": "放松", "preferred_pace": "slow"},
                            confirmed_topics=["purpose", "preferred_pace"],
                            missing_topics=["required_activities", "excluded_activities"],
                            ready_to_plan=True, assistant_message="  先慢下来，有没有必须安排的活动？  "),
        InterviewTurnResult(context_update={"required_activities": [], "excluded_activities": []},
                            confirmed_topics=["required_activities", "excluded_activities"],
                            missing_topics=[], ready_to_plan=False,
                            assistant_message="已确认没有必去或排除活动，可以结束访谈。"),
    ]


def context_and_state():
    """每次建立独立的固定 Alex/Bella 场景。"""
    context = build_travel_context(load_trips()["trip_tokyo_alex_bella"],
                                  load_persons().values(), load_relationships().values())
    return context, initialize_interview(context)


def test_runner_connects_prompt_update_metrics_without_mutation():
    """Input：固定场景、首轮结果和原文；Expected Output：一次调用、新上下文/状态、完整指标及原样回复；验证职责串联和输入隔离。"""
    context, state = context_and_state()
    turn = turns()[0]
    before = (context.model_dump(), state.model_dump(), turn.model_dump())
    client = FakeClient([turn])
    result = run_interview_turn(context, state, "想放松", client)
    assert client.prompts == [build_interview_prompt(context, state, "想放松")]
    assert result.assistant_message == turn.assistant_message
    assert result.updated_context.trip.context.purpose == "放松"
    assert result.updated_context.trip.context.preferred_pace == "slow"
    assert result.updated_state.topics.purpose == "confirmed"
    assert result.llm_ready_to_plan is True
    assert result.deterministic_ready_to_plan is False
    assert result.metrics == dict(provider="fake", model="fake-model", input_tokens=100,
                                  output_tokens=20, total_tokens=120, latency_ms=12.5,
                                  cached_input_tokens=10, reasoning_tokens=None)
    assert (context.model_dump(), state.model_dump(), turn.model_dump()) == before
    assert result.updated_context is not context and result.updated_state is not state
    assert TravelContext.model_validate_json(result.updated_context.model_dump_json()) == result.updated_context
    result.updated_context.participants[0].interests.append("结果新增")
    result.updated_context.relationships[0].shared_travel_preferences.clear()
    result.updated_context.trip.context.required_activities.append("结果新增")
    assert context.model_dump() == before[0]
    assert turn.model_dump() == before[2]


def test_two_rounds_carry_state_and_context():
    """Input：连续两轮互补确认；Expected Output：第二轮请求含首轮数据，四主题累计确认后系统就绪；验证模型建议不能覆盖系统门槛。"""
    context, state = context_and_state()
    client = FakeClient(turns())
    first = run_interview_turn(context, state, "想休息", client)
    second = run_interview_turn(first.updated_context, first.updated_state, "没有必去或排除", client)
    payload = json.loads(client.prompts[1].user_prompt)
    assert payload["current_trip_context"]["purpose"] == "放松"
    assert payload["interview_state"]["confirmed_topics"] == ["purpose", "preferred_pace"]
    assert second.updated_context.trip.context.purpose == "放松"
    assert second.updated_state.ready_to_plan is True
    assert second.llm_ready_to_plan is False
    assert second.deterministic_ready_to_plan is True
    assert len(client.prompts) == 2
    assert context.trip.context.purpose is None


@pytest.mark.parametrize("message", ["", "  "])
def test_invalid_input_does_not_call_client(message):
    """Input：空白消息；Expected Output：调用前 ValueError 且零请求；验证失败不产生费用。"""
    context, state = context_and_state()
    client = FakeClient([])
    with pytest.raises(ValueError):
        run_interview_turn(context, state, message, client)
    assert client.prompts == []


@pytest.mark.parametrize("command", ["/quit", "/exit", " /QUIT "])
def test_cli_exit_without_call(monkeypatch, capsys, command):
    """Input：退出命令；Expected Output：正常结束且零模型调用、零 AI 回复；验证退出边界。"""
    monkeypatch.setattr("builtins.input", lambda _: command)
    client = FakeClient([])
    assert run_cli(client) == 0
    assert client.prompts == []
    assert "AI:" not in capsys.readouterr().out


@pytest.mark.parametrize("debug", [False, True])
def test_cli_carries_two_turns_and_stops_once_ready(monkeypatch, capsys, debug):
    """Input：两轮确认后附加一个不应读取的输入；Expected Output：两调用两回复、系统就绪后停止，debug 才显示指标；验证单一 Assistant Turn。"""
    messages = iter(["想休息", "无必去或排除", "不应读取"])
    monkeypatch.setattr("builtins.input", lambda _: next(messages))
    client = FakeClient(turns())
    assert run_cli(client, debug=debug) == 0
    out = capsys.readouterr().out
    assert out.count("AI: ") == 2
    for turn in turns():
        assert out.count(turn.assistant_message) == 1
    assert out.count("[READY TO PLAN]") == 1
    assert ("model=fake-model" in out) is debug
    assert len(client.prompts) == 2
    assert json.loads(client.prompts[1].user_prompt)["current_trip_context"]["purpose"] == "放松"
    assert next(messages) == "不应读取"


@pytest.mark.parametrize("error", [LLMRequestError("模拟请求失败"), LLMResponseError("模拟输出无效"),
                                  ValueError("不应输出的原始输入")])
def test_cli_errors_stop_without_retry(monkeypatch, capsys, error):
    """Input：请求、响应或应用错误；Expected Output：非零退出、仅一次调用且不输出应用原文；验证明确失败且不重试。"""
    monkeypatch.setattr("builtins.input", lambda _: "测试输入")
    client = FakeClient([error])
    assert run_cli(client) == 1
    out = capsys.readouterr().out
    assert "失败" in out and "AI: " not in out
    assert "不应输出的原始输入" not in out
    assert len(client.prompts) == 1


@pytest.mark.parametrize("error", [EOFError, KeyboardInterrupt])
def test_cli_input_end_is_normal(monkeypatch, capsys, error):
    """Input：终端 EOF 或输入期间中断；Expected Output：正常结束且不调用模型；验证最小退出行为而非流式取消。"""
    def end(_):
        """模拟终端停止输入。"""
        raise error
    monkeypatch.setattr("builtins.input", end)
    client = FakeClient([])
    assert run_cli(client) == 0
    assert not client.prompts


def test_cli_blank_input_skips_call(monkeypatch, capsys):
    """Input：空白后退出；Expected Output：提示有效输入且零请求；避免空轮次调用。"""
    messages = iter(["  ", "/quit"])
    monkeypatch.setattr("builtins.input", lambda _: next(messages))
    client = FakeClient([])
    assert run_cli(client) == 0
    assert not client.prompts
    assert "非空消息" in capsys.readouterr().out
