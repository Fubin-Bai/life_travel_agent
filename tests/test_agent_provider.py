"""DeepSeek Responses原生function calling映射，完全使用内存HTTP。"""
import json
import httpx
import pytest
from openai import OpenAI
from life_journey.llm.deepseek import DeepSeekInterviewClient
from life_journey.llm.base import LLMResponseError, LLMRequestError, LLMConfigurationError
from life_journey.schemas.agent import AgentPrompt, tool_definitions
from life_journey.application.agent_planning import AGENT_SYSTEM_PROMPT
from test_deepseek_client import response_body


def prompt():
    """最小Provider请求，不包含真实用户资料。"""
    return AgentPrompt(system_prompt=AGENT_SYSTEM_PROMPT,messages=[{'role':'user','content':'固定虚构输入'}],tools=tool_definitions())


def client_for(monkeypatch,body,status=200):
    """假Key及MockTransport，记录协议字段但不打印请求内容。"""
    monkeypatch.setenv('DEEPSEEK_API_KEY','offline-provider-key')
    calls=[]
    def handler(request):
        """内存Response模拟，无外部HTTP。"""
        calls.append(json.loads(request.content))
        return httpx.Response(status,json=body)
    sdk=OpenAI(api_key='offline-key',http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    return DeepSeekInterviewClient(sdk_client=sdk),calls


def tool_body(arguments='{"city":"北京","keyword":"艺术展","limit":2}'):
    """官方function_call信封形状，arguments可非法以测试应用层修正。"""
    body=response_body()
    body['output']=[{'type':'function_call','id':'fc1','call_id':'c1','name':'search_places','arguments':arguments,'status':'completed'}]
    return body


def test_native_tool_call_mapping_and_request_contract(monkeypatch):
    """Input：原生function_call；Expected Output：规范化AgentDecision及四工具契约；测试SDK映射，目的为不以自由文本模拟tool calling。"""
    client,calls=client_for(monkeypatch,tool_body())
    try:result=client.decide(prompt())
    finally:client.close()
    assert result.tool_calls[0].name=='search_places' and not result.ready_to_plan
    assert result.call_metrics.total_tokens==110 and result.call_metrics.latency_ms>=0
    assert calls[0]['tool_choice']=='auto' and len(calls[0]['tools'])==4
    assert calls[0]['reasoning']=={'effort':'none'} and calls[0]['stream'] is False
    assert calls[0]['max_output_tokens']==1536
    assert calls[0]['text']['format']['name']=='AgentReady'


def test_ready_decision_mapping(monkeypatch):
    """Input：无工具且结构化ready；Expected Output：ready=true无推理字段；测试最终路由决定，目的为只发送可观察动作。"""
    body=response_body();body['output'][0]['content'][0]['text']='{"ready_to_plan":true}'
    client,_=client_for(monkeypatch,body)
    try:result=client.decide(prompt())
    finally:client.close()
    assert result.ready_to_plan and result.tool_calls==[]


@pytest.mark.parametrize('text',['不是JSON','{"ready_to_plan":false}','{"ready_to_plan":true,"reasoning":"不允许"}'])
def test_invalid_ready_output_is_safe_error(monkeypatch,text):
    """Input：非JSON/false/额外推理字段；Expected Output：安全LLMResponseError；测试结束契约，目的为不接受隐式或越界决定。"""
    body=response_body();body['output'][0]['content'][0]['text']=text
    client,_=client_for(monkeypatch,body)
    try:
        with pytest.raises(LLMResponseError):client.decide(prompt())
    finally:client.close()


def test_invalid_tool_json_is_left_for_structured_argument_error(monkeypatch):
    """Input：function arguments非法JSON字符串；Expected Output：原生调用仍可交给Pydantic工具边界；测试分层，目的为允许Agent观察参数错误后修正。"""
    client,_=client_for(monkeypatch,tool_body('invalid-json'))
    try:result=client.decide(prompt())
    finally:client.close()
    assert result.tool_calls[0].arguments=='invalid-json'


def test_provider_http_error_and_tool_contract_tampering(monkeypatch):
    """Input：HTTP500或工具列表被篡改；Expected Output：安全错误且HTTP无重试；测试传输/允许列表，目的为不能扩展任意工具。"""
    client,calls=client_for(monkeypatch,{'error':{'message':'不应透传'}},500)
    try:
        with pytest.raises(LLMRequestError):client.decide(prompt())
        assert len(calls)==1
        altered=prompt();altered.tools=[]
        with pytest.raises(LLMConfigurationError):client.decide(altered)
        assert len(calls)==1
    finally:client.close()


@pytest.mark.parametrize('method,model_name',[('generate_draft','DraftItinerary'),('repair_itinerary','ReplanPatch')])
def test_v3_structured_provider_contract(monkeypatch,method,model_name):
    """Input：草稿或局部补丁的Responses信封；Expected Output：正确Schema名称、结构与真实usage；测试新增Provider方法，目的为不只依赖fake Client。"""
    from life_journey.schemas.validation import DraftItinerary,ReplanPatch
    from life_journey.schemas.planning import PlanningPrompt
    from test_constraint_replanning import fixture
    model=DraftItinerary if method=='generate_draft' else ReplanPatch
    output=fixture()[3] if method=='generate_draft' else ReplanPatch(trip_id='corrected')
    body=response_body();body['output'][0]['content'][0]['text']=output.model_dump_json()
    client,calls=client_for(monkeypatch,body)
    try:result=getattr(client,method)(PlanningPrompt(system_prompt='固定测试任务',user_prompt='虚构输入',output_schema=model.model_json_schema()))
    finally:client.close()
    assert result.output==output and result.total_tokens==110
    assert calls[0]['text']['format']['name']==model_name and calls[0]['reasoning']=={'effort':'none'}
