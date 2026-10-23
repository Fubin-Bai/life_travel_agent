"""只测评分器和基准装配；真实模型 benchmark 通过独立命令手动执行。"""

import pytest

from life_journey.application import apply_interview_update
from life_journey.evaluation.cases import load_cases, prepare_case
from life_journey.evaluation.interview import run_benchmark, score_case
from life_journey.llm import LLMCallResult, LLMResponseError
from life_journey.schemas import InterviewTurnResult


def make_turn(case, **changes):
    """用固定期望构造理想输出，仅用于校验评分器，不用于真实 benchmark。"""
    values = dict(context_update=case.expected_context, confirmed_topics=list(case.expected_confirmed),
                  missing_topics=[], ready_to_plan=case.expected_ready or False,
                  assistant_message="信息已经足够，可以进入规划阶段。" if case.expect_closure else "收到。")
    values.update(changes)
    return InterviewTurnResult(**values)


def score(case, turn):
    """通过现有应用逻辑构造评分输入。"""
    context, state = prepare_case(case)
    return score_case(case, turn, apply_interview_update(context, state, turn))


@pytest.mark.parametrize("index", range(6))
def test_expected_outputs_pass(index):
    """Input：六例各自理想输出；Expected Output：全部 PASS；验证规则能接受明确目标而非固定回复整段相等。"""
    case = load_cases()[index]
    assert score(case, make_turn(case))["status"] == "PASS"


def test_cases_are_independent_and_last_has_one_unknown():
    """Input：多次加载基准；Expected Output：可变数据独立，第五例 partner，第六例仅排除主题未知；保证稳定场景输入。"""
    cases = load_cases()
    cases[3].initial_context["activity_preferences"].append("污染")
    assert load_cases()[3].initial_context["activity_preferences"] == ["cafes", "shopping"]
    context, _ = prepare_case(cases[4])
    assert context.relationships[0].relationship_type == "partner"
    _, state = prepare_case(cases[5])
    assert state.missing_topics == ["excluded_activities"]
    assert state.ready_to_plan is False


@pytest.mark.parametrize("index", [1, 2, 5])
def test_omitted_update_and_confirmation_fail(index):
    """Input：需要确认的字段省略且无 confirmed；Expected Output：FAIL 并指出缺失；防止默认空列表偶然通过。"""
    case = load_cases()[index]
    result = score(case, make_turn(case, context_update={}, confirmed_topics=[]))
    assert result["status"] == "FAIL"
    assert any("confirmed" in failure for failure in result["failures"])
    assert any("省略" in failure for failure in result["failures"])


def test_merge_is_rejected():
    """Input：保留旧 coffee/shopping 的合并列表；Expected Output：FAIL；保证评分器识别撤销偏好未清除。"""
    case = load_cases()[3]
    turn = make_turn(case, context_update={"activity_preferences": ["cafes", "shopping", "art exhibitions", "architecture"]})
    assert score(case, turn)["status"] == "FAIL"


@pytest.mark.parametrize("index,message,update", [
    (0, "给你安排 spa。", {"purpose": "relaxation", "preferred_pace": "slow"}),
    (4, "你们是伴侣，适合浪漫晚餐。", {}),
    (4, "收到。", {"activity_preferences": ["romantic dinner"]}),
    (4, "INFP 所以适合安静旅行。", {}),
])
def test_forbidden_inference_separate_from_field_checks(index, message, update):
    """Input：自然回复或结构字段出现禁用推断词；Expected Output：独立 forbidden FAIL 与命中来源；覆盖标签和偏好越界风险。"""
    case = load_cases()[index]
    result = score(case, make_turn(case, assistant_message=message, context_update=update))
    assert result["status"] == "FAIL"
    assert result["forbidden_inference"]["status"] == "FAIL"
    assert result["forbidden_inference"]["hits"]


@pytest.mark.parametrize("message", ["还有什么想告诉我的？", "请问还有哪些想安排的", "明白了。"])
def test_closure_needs_finish_signal_and_no_followup(message):
    """Input：继续提问或未明确收束的末轮回复；Expected Output：系统 ready 仍 true 但评分 FAIL；区分后端就绪与回复质量。"""
    case = load_cases()[5]
    result = score(case, make_turn(case, assistant_message=message))
    assert result["actual"]["deterministic_ready"] is True
    assert result["closure_passed"] is False
    assert result["status"] == "FAIL"


class FakeClient:
    """顺序返回理想结果或固定失败；不导入 Provider、不访问网络。"""

    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def generate_interview_turn(self, prompt):
        """只读取 Prompt，不读取发给模型的期望值。"""
        case = load_cases()[self.calls]
        self.calls += 1
        if self.fail:
            raise LLMResponseError("模拟响应校验失败")
        return LLMCallResult(output=make_turn(case), provider="fake", model="fake-model", latency_ms=1.0)


@pytest.mark.parametrize("fail", [False, True])
def test_benchmark_counts_failures_and_metrics(fail):
    """Input：六次理想输出或六次响应错误；Expected Output：6/6 或 0/6、无重试、失败不从分母移除；验证汇总和指标。"""
    client = FakeClient(fail)
    report = run_benchmark(client)
    assert client.calls == 6
    assert report["passed"] == (0 if fail else 6)
    assert report["total"] == 6
    assert report["pass_rate"] == (0.0 if fail else 1.0)
    if fail:
        assert all(item["forbidden_inference"]["status"] == "NOT_EVALUATED" for item in report["results"])
    else:
        assert all(item["metrics"]["model"] == "fake-model" for item in report["results"])



def test_reasking_known_purpose_fails_dialogue_rule():
    """Input：结构提取正确但继续追问目的；Expected Output：dialogue_strategy FAIL；验证提取正确不等于自然对话正确。"""
    from life_journey.evaluation.cases import load_dialogue_cases
    case=load_dialogue_cases()[0]
    result=score(case,make_turn(case,assistant_message="这次旅行的目的是什么？"))
    assert result["dialogue_strategy"]["status"] == "FAIL"
    assert result["status"] == "FAIL"


def test_dialogue_closes_without_optional_topics_confirmed():
    """Input：仅剩最低必需活动确认的自然回复；Expected Output：ready 和收束 PASS，建议主题未知不阻塞；验证最低充分条件。"""
    from life_journey.evaluation.cases import load_dialogue_cases
    case=load_dialogue_cases()[1]
    result=score(case,make_turn(case))
    assert result["status"] == "PASS"
    assert result["actual"]["deterministic_ready"] is True


def test_natural_phase_closure_is_accepted():
    """Input：就绪后的自然收束；Expected Output：PASS；测试非固定文案收束，目的为避免评分器误报。"""
    case = load_cases()[5]
    turn = make_turn(case, assistant_message="目前已经了解得差不多了，可以进入下一步了。")
    assert score(case, turn)["status"] == "PASS"
