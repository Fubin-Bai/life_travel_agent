"""统一运行控制：包裹既有LangGraph，不决定推荐内容或替代领域守卫。"""
from contextlib import contextmanager
from datetime import datetime,timezone
from hashlib import sha256
import json
from time import perf_counter
from uuid import uuid4
from .policy import HarnessPolicy,HarnessConfigurationError
from .schemas import AgentRunContext,AgentRunSummary,HarnessError,TraceEvent
from life_journey.llm.base import LLMClientError,LLMResponseError
from life_journey.tools.base import ToolError,NoPlacesError

ROUTE_TOOLS={'get_walking_route','get_transit_route','get_driving_route'}
MESSAGES={'provider_model':'模型调用失败','tool':'工具调用失败','invalid_tool_arguments':'工具参数无效',
    'policy_violation':'运行策略拒绝操作','budget_exhausted':'运行预算已达到上限','memory_retrieval':'历史偏好检索失败',
    'validation':'约束校验未能执行','replanning':'局部修复未完成','unexpected_internal':'运行内部错误，已安全停止','hook':'观察hook执行失败'}

class HarnessFailure(LLMResponseError):
    """安全失败沿用现有API异常边界；错误详情仅包含结构化分类。"""


def call_fingerprint(name,arguments):
    """输入必须已通过Schema和城市/候选范围验证；key不保存原始参数正文。"""
    payload=json.dumps({'tool':name.strip().casefold(),'args':arguments.model_dump(mode='json')},ensure_ascii=False,sort_keys=True,separators=(',',':'))
    return sha256(payload.encode()).hexdigest()

class AgentHarness:
    """一个实例只允许执行一次run；缓存仅在本次进程对象内，不入Context/trace。"""
    def __init__(self,trip_id,planning_mode='agent',*,policy=None,hooks=(),clock=perf_counter):
        if policy is not None and not isinstance(policy,HarnessPolicy):raise HarnessConfigurationError('必须提供已验证的HarnessPolicy')
        self.policy=policy or HarnessPolicy.from_env()
        self.context=AgentRunContext(run_id='run_'+str(uuid4()),trip_id=trip_id,planning_mode=planning_mode,
            policy_snapshot=self.policy.model_dump())
        self.hooks=tuple(hooks);self.events=[];self.cache={};self.actions=[];self.decision_metrics=[]
        self.consecutive_duplicates=0;self.used_call_ids=set();self.repair_metrics={};self.draft_metrics={};self.observation_counts=(0,0,0);self._clock=clock;self._started=None;self._signals=set()

    def emit(self,event_type,**fields):
        """内部调用只传脱敏白名单；不接受任意metadata/payload。"""
        args=fields.pop('sanitized_args',{})
        fields['sanitized_args']={k:v for k,v in args.items() if k in {'keyword_length','limit','origin_place_id','destination_place_id'}}
        event=TraceEvent(event_id=f'{self.context.run_id}:{len(self.events)+1}',run_id=self.context.run_id,
            timestamp=datetime.now(timezone.utc),event_type=event_type,graph_node=self.context.current_graph_node,**fields)
        self.events.append(event);return event

    def error(self,category,code,*,recoverable=False,stage=None):
        """不读取str(exception)，原始Provider或hook错误不能进入输出。"""
        issue=HarnessError(code=code,category=category,message=MESSAGES[category],recoverable=recoverable,
            stage=stage or self.context.current_stage)
        self.context.errors.append(issue)
        return issue

    def hook(self,name,event=None):
        """隔离快照，避免观察hook修改运行状态；非critical失败仅记录。"""
        for hook in self.hooks:
            try:
                method=getattr(hook,name,None)
                if method is None:continue
                method(self.context.model_copy(deep=True),event.model_copy(deep=True) if event else None)
            except Exception:
                try:critical=getattr(hook,'critical',False) is True
                except Exception:critical=False
                self.error('policy_violation' if critical else 'hook','critical_hook_failed' if critical else 'hook_failed',recoverable=not critical,stage=name)
                if critical:raise HarnessFailure('critical policy hook拒绝继续运行') from None
                self.context.warnings.append('noncritical_hook_failed')

    def budget_signal(self,reason,event_type='BUDGET_REACHED'):
        """相同终止信号只记录一次；预算耗尽不是内部异常。"""
        if reason not in self._signals:
            self._signals.add(reason);self.emit(event_type,status='blocked',stop_reason=reason)

    def check_deadline(self):
        """协作式时限：不能中断已经阻塞的同步SDK/HTTP调用。"""
        if self.policy.max_run_seconds is not None and self._started is not None and self._clock()-self._started>=self.policy.max_run_seconds:
            self.context.stop_reason='run_timeout';self.budget_signal('run_timeout')
            self.error('budget_exhausted','run_timeout')
            raise HarnessFailure('Agent运行时长预算耗尽，已安全停止')

    def agent_stop_reason(self):
        """所有决策轮次/总尝试/连续重复终止统一在此判断。"""
        self.check_deadline();ctx=self.context;p=self.policy
        reason=('tool_budget_exhausted' if ctx.tool_call_count>=p.max_tool_calls else
                'decision_budget_exhausted' if ctx.decision_count>=p.max_decisions else
                'repeated_tool_calls' if self.consecutive_duplicates>=p.max_consecutive_duplicates else '')
        if reason:self.budget_signal(reason,'DUPLICATE_CALL_BLOCKED' if reason=='repeated_tool_calls' else 'BUDGET_REACHED')
        return reason

    def admit_tool(self):
        """非法参数/重复调用同样消耗尝试预算；上限后的批次项不再增加计数。"""
        self.check_deadline()
        if self.context.tool_call_count>=self.policy.max_tool_calls:
            self.budget_signal('tool_budget_exhausted');return False
        self.context.tool_call_count+=1;return True

    def tool_permission(self,name,key,candidate_count):
        """优先缓存，再检查真实执行预算；领域范围检查留在工具边界。"""
        ctx=self.context;p=self.policy
        if self.consecutive_duplicates>=p.max_consecutive_duplicates:
            self.budget_signal('repeated_tool_calls','DUPLICATE_CALL_BLOCKED');return 'duplicate_call_blocked',None
        if key in self.cache:
            self.consecutive_duplicates+=1;ctx.cache_hits+=1
            return None,self.cache[key].model_copy(deep=True,update={'cached':True})
        self.consecutive_duplicates=0
        route_count=sum(ctx.tool_counts.get(n,0) for n in ROUTE_TOOLS)
        error=('search_or_candidate_budget_exhausted' if name=='search_places' and (ctx.tool_counts.get(name,0)>=p.max_search_calls or candidate_count>=p.max_candidates) else
               'route_budget_exhausted' if name in ROUTE_TOOLS and (route_count>=p.max_route_calls or ctx.tool_counts.get(name,0)>=p.max_calls_per_route_mode) else None)
        if error:self.budget_signal(error);return error,None
        ctx.tool_counts[name]=ctx.tool_counts.get(name,0)+1;ctx.executed_tool_calls+=1
        return None,None

    def tool_started(self,name):
        """请求事件不包含未验证原始参数。"""
        event=self.emit('TOOL_REQUESTED',tool_name=name,status='requested');self.hook('before_tool',event)
        return self._clock()

    def tool_finished(self,trace,started,*,result_count=None):
        """工具错误继续以规范化Observation反馈，不用异常原文填入trace。"""
        self.actions.append(trace)
        if trace.error_code:
            code=trace.error_code
            category=('budget_exhausted' if 'budget' in code else 'invalid_tool_arguments' if code in {'invalid_arguments','unknown_place_id','city_out_of_scope','unsupported_tool','search_limit_exceeded'} else
                      'policy_violation' if code in {'excluded_keyword','duplicate_call_blocked'} else 'unexpected_internal' if code=='unexpected_tool_error' else 'tool')
            self.error(category,code,recoverable=code!='unexpected_tool_error')
        kind='TOOL_CACHE_HIT' if trace.cached else 'TOOL_FAILED' if trace.error_code or trace.status in {'error','unknown'} else 'TOOL_COMPLETED'
        event=self.emit(kind,tool_name=trace.tool_name,sanitized_args=trace.sanitized_arguments,status=trace.status,error_code=trace.error_code,
            duration_ms=max(0,(self._clock()-started)*1000),cache_hit=trace.cached,result_count=result_count)
        self.hook('after_tool',event)

    @contextmanager
    def node(self,name):
        """图节点边界只负责计时与观察，不替代条件边。"""
        self.check_deadline();previous=self.context.current_graph_node
        self.context.current_graph_node=name;self.context.current_stage=name
        self.emit('NODE_ENTERED');started=self._clock();status='ok'
        try:yield
        except Exception:status='failed';raise
        finally:
            duration=max(0,(self._clock()-started)*1000)
            self.context.timing_ms[name]=self.context.timing_ms.get(name,0)+duration
            self.emit('NODE_EXITED',status=status,duration_ms=duration)
            self.context.current_graph_node=previous

    def model_call(self,kind,operation):
        """每次真实模型尝试都计数，失败也计入；不保留Prompt/回复。"""
        self.check_deadline();self.hook('before_model')
        self.context.model_call_count+=1
        if kind=='decision':self.context.decision_count+=1
        started=self._clock();status='ok'
        try:return operation()
        except Exception as exc:
            status='failed';self.error('replanning' if kind=='replan' else 'provider_model','model_call_failed',recoverable=kind=='replan')
            exc.harness_recorded=True
            raise
        finally:
            event=self.emit('MODEL_CALLED',status=status,duration_ms=max(0,(self._clock()-started)*1000))
            self.hook('after_model',event)

    def retrieve_memory(self,operation):
        """按policy TopK调用，失败默认终止；可显式配置带提醒的无记忆降级。"""
        self.context.memory_retrieval_count+=1;self.hook('before_memory_retrieval');started=self._clock()
        try:
            from life_journey.schemas.memory import RetrievedMemory
            query,items=operation(self.policy.memory_top_k)
            if not isinstance(query,str) or not isinstance(items,list):raise ValueError('记忆检索规范化结果无效')
            items=[RetrievedMemory.model_validate_json(m.model_dump_json()) for m in items[:self.policy.memory_top_k]]
        except Exception as exc:
            recover=self.policy.memory_failure_mode=='continue_without_memory'
            self.error('memory_retrieval','memory_retrieval_failed',recoverable=recover);exc.harness_recorded=True
            event=self.emit('MEMORY_RETRIEVED',status='failed',error_code='memory_retrieval_failed',duration_ms=max(0,(self._clock()-started)*1000),result_count=0)
            self.hook('after_memory_retrieval',event)
            if not recover:raise
            self.context.memory_degraded=True;self.context.warnings.append('memory_retrieval_failed')
            return '',[]
        event=self.emit('MEMORY_RETRIEVED',result_count=len(items),memory_ids=[m.memory_id for m in items],
            retrieval_scores={m.memory_id:m.score for m in items},duration_ms=max(0,(self._clock()-started)*1000))
        self.hook('after_memory_retrieval',event);return query,items

    def validate(self,operation):
        """校验器不能执行时失败，不能返回未经验证的valid。"""
        self.hook('before_validate');started=self._clock()
        try:
            from life_journey.schemas.validation import ValidationResult
            result=operation()
            result=ValidationResult.model_validate_json(result.model_dump_json())
        except Exception as exc:
            self.error('validation','validator_failed');exc.harness_recorded=True
            event=self.emit('VALIDATION_COMPLETED',status='failed',error_code='validator_failed',duration_ms=max(0,(self._clock()-started)*1000))
            self.hook('after_validate',event);raise
        self.context.validation_passes+=1;self.context.validation_failures+=int(not result.valid)
        self.context.warnings.extend("validation:"+issue.type for issue in result.warnings)
        event=self.emit('VALIDATION_COMPLETED',status='valid' if result.valid else 'invalid',
            validation_issue_count=result.hard_violation_count+result.soft_warning_count,
            validation_issues=[{'issue_id':i.issue_id,'type':i.type,'severity':i.severity} for i in result.violations+result.warnings],replan_round=self.context.replan_round,
            duration_ms=max(0,(self._clock()-started)*1000))
        self.hook('after_validate',event);return result

    def should_replan(self,validation):
        """软提醒正常结束；硬冲突与修复轮次上限共同决定条件边。"""
        if validation.valid:return False
        if self.context.replan_round>=self.policy.max_replan_rounds:
            self.budget_signal('max_replan_rounds');return False
        return True

    def replan(self,operation):
        """局部修复尝试和hooks统一计数，失败也占一轮。"""
        if self.context.replan_round>=self.policy.max_replan_rounds:
            self.budget_signal('max_replan_rounds');raise HarnessFailure('局部修复次数预算耗尽')
        self.context.replan_round+=1
        event=self.emit('REPLAN_STARTED',replan_round=self.context.replan_round)
        self.hook('before_replan',event);started=self._clock();status='ok'
        try:return operation()
        except Exception:status='failed';raise
        finally:
            event=self.emit('REPLAN_COMPLETED',status=status,replan_round=self.context.replan_round,duration_ms=max(0,(self._clock()-started)*1000))
            self.hook('after_replan',event)

    def summary(self):
        """只导出标量，错误数不把正常预算停止算作内部错误。"""
        c=self.context
        return AgentRunSummary(run_id=c.run_id,final_status=c.status,total_duration_ms=c.timing_ms.get('total',0.0),
            model_calls=c.model_call_count,tool_calls=c.tool_call_count,executed_tool_calls=c.executed_tool_calls,
            cache_hits=c.cache_hits,memory_retrievals=c.memory_retrieval_count,validation_passes=c.validation_passes,
            validation_failures=c.validation_failures,replan_rounds=c.replan_round,warning_count=len(c.warnings),
            error_count=sum(e.category!='budget_exhausted' for e in c.errors),stop_reason=c.stop_reason)

    def _finish(self,status):
        """成功和失败都关闭生命周期并调用after_run，不记录业务输出。"""
        self.context.status=status;self.context.finished_at=datetime.now(timezone.utc);self.context.current_stage='finished'
        self.context.timing_ms['total']=max(0,(self._clock()-self._started)*1000)
        try:self.hook('after_run')
        except HarnessFailure:
            self.context.status='failed';self.context.stop_reason='critical_hook_failed'
            self.context.timing_ms['total']=max(0,(self._clock()-self._started)*1000)
            self.emit('RUN_FAILED',status='failed',stop_reason='critical_hook_failed');raise
        self.context.finished_at=datetime.now(timezone.utc)
        self.context.timing_ms['total']=max(0,(self._clock()-self._started)*1000)
        self.emit('RUN_FAILED' if status in {'failed','stopped'} else 'RUN_COMPLETED',status=status,stop_reason=self.context.stop_reason)

    def attach(self,error):
        """已有调用方仍可捕获原安全异常，并读取不含正文的诊断。"""
        error.harness_summary=self.summary();error.harness_trace=list(self.events);error.harness_context=self.context.model_copy(deep=True)

    def run(self,operation):
        """单次执行入口；恢复策略留在特定操作边界，不无限重试整个run。"""
        if self.context.status!='created':raise ValueError('Harness实例不能重复执行')
        self._started=self._clock();self.context.started_at=datetime.now(timezone.utc);self.context.status='running'
        self.context.current_stage='run';self.emit('RUN_STARTED',status='running')
        try:
            self.hook('before_run');result=operation(self);self.check_deadline()
            status='unresolved' if getattr(result,'final_status',None)=='unresolved' else 'completed'
            if not self.context.stop_reason:self.context.stop_reason='unresolved_constraints' if status=='unresolved' else 'completed'
            self._finish(status)
        except Exception as exc:
            if not getattr(exc,'harness_recorded',False) and not isinstance(exc,HarnessFailure):
                category='provider_model' if isinstance(exc,LLMClientError) else 'tool' if isinstance(exc,ToolError) else 'unexpected_internal'
                self.error(category,'run_failed')
            if any(e.code=='critical_hook_failed' for e in self.context.errors):self.context.stop_reason='critical_hook_failed'
            if self.context.stop_reason not in {'run_timeout','recursion_limit','critical_hook_failed'}:
                self.context.stop_reason='insufficient_evidence' if isinstance(exc,NoPlacesError) else (self.context.errors[-1].category+'_failed' if self.context.errors else 'run_failed')
            if self.context.finished_at is None:
                try:self._finish('stopped' if self.context.stop_reason in {'run_timeout','recursion_limit'} else 'failed')
                except HarnessFailure:pass
            if isinstance(exc,(LLMClientError,ToolError)):
                self.attach(exc);raise
            safe=HarnessFailure('Agent运行失败，详见脱敏Harness诊断');self.attach(safe);raise safe from None
        result.metrics={**(result.metrics or {}),'harness_summary':self.summary().model_dump_json(),
            'harness_trace':json.dumps([e.model_dump(mode='json') for e in self.events],ensure_ascii=False),
            'harness_context':self.context.model_dump_json()}
        return result
