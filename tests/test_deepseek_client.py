"""使用官方 SDK 与内存 fake HTTP transport，不发真实网络请求。"""

from copy import deepcopy
import json

import httpx
from openai import OpenAI
import pytest

from fixtures import load_persons, load_relationships, load_trips
from life_journey.application import build_interview_prompt, build_travel_context, initialize_interview
from life_journey.llm import (
    InterviewLLMClient, LLMCallResult, LLMConfigurationError, LLMRequestError, LLMResponseError,
)
from life_journey.llm.deepseek import BASE_URL, DeepSeekConfig, DeepSeekInterviewClient
from life_journey.schemas import InterviewTurnResult


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    """所有单元测试覆盖真实环境凭据，仅使用明显无效的占位值，不读取真实 Key。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-placeholder")
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)


@pytest.fixture
def prompt():
    """使用既有 V0 场景与 Prompt Builder 构造当前输出契约。"""
    context = build_travel_context(load_trips()["trip_tokyo_alex_bella"],
                                   load_persons().values(), load_relationships().values())
    return build_interview_prompt(context, initialize_interview(context), "这次想放松，不想太赶。")


def turn_payload():
    """模拟单次响应的结构化数据与完整自然回复，省略的增量字段必须继续省略。"""
    return {
        "context_update": {"purpose": "放松", "preferred_pace": "slow", "required_activities": []},
        "confirmed_topics": ["purpose", "preferred_pace", "required_activities"],
        "missing_topics": ["excluded_activities"], "ready_to_plan": False,
        "assistant_message": "明白，我们以放松为主。有没有明确不想安排的体验？",
    }


def response_body():
    """只模拟官方 Responses 返回形状，不构造另一个生产响应 Schema。"""
    return {
        "id": "response_test", "object": "response", "created_at": 0,
        "status": "completed", "model": "model-returned-by-provider",
        "error": None, "incomplete_details": None,
        "output": [{"type": "message", "id": "message_test", "status": "completed",
                    "role": "assistant", "content": [{"type": "output_text",
                    "text": json.dumps(turn_payload(), ensure_ascii=False), "annotations": []}]}],
        "usage": {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110,
                  "input_tokens_details": {"cached_tokens": 0},
                  "output_tokens_details": {"reasoning_tokens": 2}},
    }


@pytest.fixture
def make_client():
    """注入内存 HTTP handler，记录请求；即使 SDK 默认有重试，Provider 也必须关闭。"""
    clients = []

    def make(handler=None, *, body=None, status_code=200, config=None):
        calls = []
        def dispatch(request):
            calls.append(request)
            if handler is not None:
                return handler(request)
            return httpx.Response(status_code, json=body if body is not None else response_body())
        sdk = OpenAI(api_key="transport-placeholder", base_url=BASE_URL,
                     http_client=httpx.Client(transport=httpx.MockTransport(dispatch)))
        client = DeepSeekInterviewClient(config, sdk_client=sdk)
        clients.append(client)
        return client, calls
    yield make
    for client in clients:
        client.close()


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_key_fails_without_network(monkeypatch, value):
    """Input：缺失、空串或空白环境 Key；Expected Output：配置错误；在创建任何网络请求前失败且不显示凭据。"""
    if value is None:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    else:
        monkeypatch.setenv("DEEPSEEK_API_KEY", value)
    with pytest.raises(LLMConfigurationError, match="DEEPSEEK_API_KEY 未配置"):
        DeepSeekInterviewClient()


def test_model_default_environment_and_explicit_configuration(monkeypatch, make_client):
    """Input：默认、环境配置与显式配置；Expected Output：分别选择对应模型；不把模型名称散落在业务函数。"""
    assert DeepSeekConfig.from_env().model == "deepseek-flash"
    monkeypatch.setenv("DEEPSEEK_MODEL", " environment-model ")
    assert DeepSeekConfig.from_env().model == "environment-model"
    client, _ = make_client(config=DeepSeekConfig(model="explicit-model"))
    assert client.config.model == "explicit-model"


@pytest.mark.parametrize("changes", [{"model": " "}, {"max_output_tokens": 0},
    {"max_output_tokens": True}, {"timeout_seconds": 0}, {"timeout_seconds": float("inf")}])
def test_invalid_config_fails(changes):
    """Input：空模型或无效上限/超时；Expected Output：配置错误；避免无界或无效调用配置。"""
    with pytest.raises(LLMConfigurationError):
        DeepSeekConfig(**changes)


def test_request_mapping_and_one_call(prompt, make_client):
    """Input：现有 Prompt 与显式模型；Expected Output：一次 /responses 请求，正确映射指令、输入、原生 Schema；SDK 不修改稀疏字段契约。"""
    client, calls = make_client(config=DeepSeekConfig(model="configured-model", max_output_tokens=1024))
    before = prompt.model_dump()
    client.generate_interview_turn(prompt)
    assert len(calls) == 1
    request = calls[0]
    assert str(request.url) == BASE_URL + "/responses"
    assert request.headers["authorization"] == "Bearer unit-test-placeholder"
    payload = json.loads(request.content)
    assert payload["model"] == "configured-model"
    assert payload["instructions"] == prompt.system_prompt
    assert payload["input"] == prompt.user_prompt
    assert payload["text"]["format"] == {
        "type": "json_schema", "name": "InterviewTurnResult",
        "schema": InterviewTurnResult.model_json_schema(mode="validation"),
    }
    assert payload["reasoning"] == {"effort": "none"}
    assert payload["max_output_tokens"] == 1024
    assert payload["stream"] is False
    assert "tools" not in payload
    assert "required" not in payload["text"]["format"]["schema"]["$defs"]["TripContextUpdate"]
    assert client._client.max_retries == 0
    assert prompt.model_dump() == before


def test_schema_mismatch_fails_before_request(prompt, make_client):
    """Input：被篡改的 Prompt 输出 Schema；Expected Output：配置错误且零请求；禁止传输和校验使用不同契约。"""
    prompt.output_schema = {}
    client, calls = make_client()
    with pytest.raises(LLMConfigurationError, match="output_schema"):
        client.generate_interview_turn(prompt)
    assert not calls


def test_valid_response_preserves_output_and_metrics(prompt, make_client):
    """Input：合法 structured response；Expected Output：Pydantic 输出、原回复与 unset、token 映射准确，latency 非负；不伪造模型或用量。"""
    client, _ = make_client()
    result = client.generate_interview_turn(prompt)
    assert isinstance(result.output, InterviewTurnResult)
    assert result.output.model_dump() == turn_payload()
    assert result.output.context_update.model_fields_set == {"purpose", "preferred_pace", "required_activities"}
    assert result.output.assistant_message == turn_payload()["assistant_message"]
    assert (result.provider, result.model) == ("deepseek", "model-returned-by-provider")
    assert (result.input_tokens, result.output_tokens, result.total_tokens) == (100, 10, 110)
    assert (result.cached_input_tokens, result.reasoning_tokens) == (0, 2)
    assert result.latency_ms >= 0


def test_missing_usage_is_none_not_zero(prompt, make_client):
    """Input：无 usage 的合法响应；Expected Output：所有 token 指标为 None，latency 仍有值；不编造缺失指标。"""
    body = response_body()
    body["usage"] = None
    client, _ = make_client(body=body)
    result = client.generate_interview_turn(prompt)
    assert result.input_tokens is result.output_tokens is result.total_tokens is None
    assert result.cached_input_tokens is result.reasoning_tokens is None
    assert result.latency_ms >= 0


def test_reasoning_is_not_used_as_assistant_output(prompt, make_client):
    """Input：推理 item 在正常 message 前；Expected Output：只解析最终 output_text；不返回或记录推理内容。"""
    body = response_body()
    body["output"].insert(0, {"type": "reasoning", "id": "reasoning_test", "summary": [],
                              "content": [{"type": "reasoning_text", "text": "not-user-output"}]})
    client, _ = make_client(body=body)
    result = client.generate_interview_turn(prompt)
    assert result.output.model_dump() == turn_payload()
    assert "not-user-output" not in result.model_dump_json()


@pytest.mark.parametrize("text", ["not JSON", "```json\n{}\n```"])
def test_invalid_json_fails_without_retry(prompt, make_client, text):
    """Input：非 JSON 或 Markdown 包裹响应；Expected Output：安全 JSON 错误且只请求一次；不偷偷修复或重新生成。"""
    body = response_body()
    body["output"][0]["content"][0]["text"] = text
    client, calls = make_client(body=body)
    with pytest.raises(LLMResponseError, match="不是合法 JSON"):
        client.generate_interview_turn(prompt)
    assert len(calls) == 1


@pytest.mark.parametrize("data", [{}, [], {**turn_payload(), "assistant_message": " "},
    {**turn_payload(), "context_update": {"required_activities": None}},
    {**turn_payload(), "confirmed_topics": ["invalid_topic"]}])
def test_schema_failure_never_returns_raw_dict(prompt, make_client, data):
    """Input：合法 JSON 但不满足领域字段或跨字段校验；Expected Output：安全 Schema 错误；未经校验数据不能进入应用层。"""
    body = response_body()
    body["output"][0]["content"][0]["text"] = json.dumps(data)
    client, _ = make_client(body=body)
    with pytest.raises(LLMResponseError, match="未通过 InterviewTurnResult 校验"):
        client.generate_interview_turn(prompt)


@pytest.mark.parametrize("status", ["incomplete", "failed", "in_progress"])
def test_unfinished_status_fails(prompt, make_client, status):
    """Input：未完成、失败或仍进行中的响应；Expected Output：明确失败；即使已有合法 JSON 也不得接受不完整响应。"""
    body = response_body()
    body["status"] = status
    client, _ = make_client(body=body)
    with pytest.raises(LLMResponseError, match="未完成"):
        client.generate_interview_turn(prompt)


@pytest.mark.parametrize("changes", [
    {"incomplete_details": {"reason": "max_output_tokens"}},
    {"error": {"code": "server_error", "message": "private server error"}},
])
def test_error_or_truncation_details_fail(prompt, make_client, changes):
    """Input：即使 status 完成仍带错误或截断详情；Expected Output：LLMResponseError；不静默接受矛盾响应或泄露原始详情。"""
    body = response_body()
    body.update(changes)
    client, _ = make_client(body=body)
    with pytest.raises(LLMResponseError) as error:
        client.generate_interview_turn(prompt)
    assert "private server error" not in str(error.value)


@pytest.mark.parametrize("output", [[], None])
def test_no_assistant_message_fails(prompt, make_client, output):
    """Input：空或 null output；Expected Output：明确无 Assistant Message 错误；不将空响应当作有效轮次。"""
    body = response_body()
    body["output"] = output
    client, _ = make_client(body=body)
    with pytest.raises(LLMResponseError, match="一个可用"):
        client.generate_interview_turn(prompt)


@pytest.mark.parametrize("content", [[], [{"type": "output_text", "text": " ", "annotations": []}],
    [{"type": "refusal", "refusal": "refused"}]])
def test_empty_text_or_refusal_fails(prompt, make_client, content):
    """Input：空内容、空白文本或 refusal；Expected Output：明确无可用文本；不从推理或拒绝文本猜测结构化数据。"""
    body = response_body()
    body["output"][0]["content"] = content
    client, _ = make_client(body=body)
    with pytest.raises(LLMResponseError, match="没有可用文本"):
        client.generate_interview_turn(prompt)


def test_multiple_messages_and_incomplete_message_fail(prompt, make_client):
    """Input：两条 assistant message 或单条未完成 message；Expected Output：明确失败；保留一轮一个结果的边界。"""
    body = response_body()
    body["output"].append(deepcopy(body["output"][0]))
    client, _ = make_client(body=body)
    with pytest.raises(LLMResponseError, match="一个可用"):
        client.generate_interview_turn(prompt)
    body = response_body()
    body["output"][0]["status"] = "incomplete"
    client, _ = make_client(body=body)
    with pytest.raises(LLMResponseError, match="Message 未完成"):
        client.generate_interview_turn(prompt)


@pytest.mark.parametrize("status", [401, 429, 500, 503])
def test_http_errors_are_safe_and_not_retried(prompt, make_client, status, capsys, caplog):
    """Input：认证、限流与服务错误，body 含私密占位；Expected Output：仅公开状态码、单次请求，无凭据/Prompt/body 输出。"""
    body = {"error": {"message": "private-response-sentinel", "type": "test_error"}}
    client, calls = make_client(body=body, status_code=status)
    with pytest.raises(LLMRequestError, match=str(status)) as error:
        client.generate_interview_turn(prompt)
    assert len(calls) == 1
    assert error.value.__suppress_context__
    visible = str(error.value) + repr(client) + capsys.readouterr().out + caplog.text
    for secret in ("unit-test-placeholder", "private-response-sentinel", prompt.user_prompt):
        assert secret not in visible


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
def test_network_errors_fail_once(prompt, make_client, error_type):
    """Input：fake transport 连接或超时错误；Expected Output：安全请求错误且只调用一次；覆盖 SDK 的重试关闭策略。"""
    def handler(request):
        raise error_type("private-network-detail", request=request)
    client, calls = make_client(handler)
    with pytest.raises(LLMRequestError, match="网络连接或请求超时") as error:
        client.generate_interview_turn(prompt)
    assert len(calls) == 1
    assert "private-network-detail" not in str(error.value)


def test_fake_client_works_with_public_protocol(prompt):
    """Input：不继承任何 Provider 的 fake client；Expected Output：满足统一接口并返回相同领域结果；证明上层只依赖公共契约。"""
    class FakeClient:
        """只实现公共方法的离线替身，不包含 SDK 或 Endpoint。"""
        def generate_interview_turn(self, request):
            """返回已校验结果；不解析请求或改变业务规则。"""
            return LLMCallResult(output=InterviewTurnResult(**turn_payload()), provider="fake",
                                 model="fake-model", latency_ms=0.0)
    client: InterviewLLMClient = FakeClient()
    assert isinstance(client, InterviewLLMClient)
    assert client.generate_interview_turn(prompt).output.model_dump() == turn_payload()



def test_planning_uses_same_transport_with_itinerary_contract(make_client):
    """Input：假的 Responses 行程 JSON；Expected Output：一次请求、Itinerary 契约、日期还原和指标；验证无真实网络的 Provider 适配。"""
    from life_journey.schemas.itinerary import Itinerary
    from life_journey.schemas.planning import PlanningPrompt
    data={"trip_id":"trip_test","summary":"慢节奏","days":[{"date":"2026-11-10","theme":"看展","activities":[{"time_period":"afternoon","title":"展览","description":"待核实信息","rationale":"符合明确兴趣"}]}]}
    body=response_body()
    body["output"][0]["content"][0]["text"]=json.dumps(data)
    client,calls=make_client(body=body)
    prompt=PlanningPrompt(system_prompt="规划测试",user_prompt="{}",output_schema=Itinerary.model_json_schema(mode="validation"))
    result=client.generate_itinerary(prompt)
    assert result.output.model_dump(mode="json") == data
    assert len(calls) == 1
    assert json.loads(calls[0].content)["text"]["format"]["name"] == "Itinerary"
    assert result.total_tokens == 110
