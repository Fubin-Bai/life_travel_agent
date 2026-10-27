"""确定性、保守的V3校验；语义有限词表与窄事实规则不冒充通用裁判。"""
from collections import Counter
from datetime import timedelta
from math import hypot
import re
from life_journey.schemas.validation import ConstraintIssue, ValidationResult
from life_journey.tools.opening_hours import check_opening_hours
from .planning import unsupported_open_claim, apply_route_evidence, check_explicit_pace_conflict
from .planning_observation import excluded, family_names

PERIODS = {'morning':0,'afternoon':1,'evening':2}

def matches(need, text):
    """已知同义类别或明确字面命中，不从标签推断。"""
    return need.casefold() in text.casefold() or bool(family_names(need) & family_names(text))

def validate_itinerary(context, draft, observation):
    """纯函数；不修改草稿，不发网络，所有硬规则独立累积。"""
    issues=[]
    def add(kind,message,di=None,ai=None,soft=False,evidence='TripContext',hint='仅修复受影响活动，保留其他日期与明确偏好'):
        """证据使用标识符，不记录用户完整正文。"""
        issues.append(ConstraintIssue(issue_id=f'i{len(issues)+1}',severity='soft' if soft else 'hard',type=kind,
            message=message,day=di,date=draft.days[di].date if di is not None else None,
            activity_reference=f'd{di}:a{ai}' if ai is not None else None,evidence_reference=evidence,repair_hint=hint))
    trip=context.trip
    dates=[trip.start_date+timedelta(days=i) for i in range((trip.end_date-trip.start_date).days+1)]
    actual=[d.date for d in draft.days]
    if draft.trip_id!=trip.trip_id: add('trip_id','行程ID与当前旅行不同')
    if actual!=dates: add('dates','日期必须逐日完整覆盖、递增且无重复',hint='补缺失日期、删除越界或重复日期；不得改变旅行日期')
    places={p.place_id:p for p in observation.places}
    seen=Counter();meal=Counter();coverage={}
    if unsupported_open_claim(draft.summary):add('unsupported_fact','摘要将条件营业写成已确认事实',evidence='opening_checks')
    if re.search(r'(?:步行|公交|地铁|驾车|开车)[^，。；\n]{0,8}?\d+\s*分钟|已(?:验证|确认|查询).{0,12}(?:分钟|可达|路线)',draft.summary):add('unsupported_fact','摘要交通声明没有有向活动端点',evidence='routes')
    if re.search(r'已(?:验证|确认|查询).{0,12}(?:价格|费用|门票|天气|人流|拥堵|预订)',draft.summary):add('unsupported_fact','摘要声明工具未提供的现实事实',evidence='unsupported_source')
    for di,day in enumerate(draft.days):
        order=[PERIODS[a.time_period] for a in day.activities]
        if order!=sorted(order):add('time_order','同日时段顺序非法',di)
        pace=trip.context.preferred_pace
        if (pace=='fast' and len(day.activities)<3) or (pace=='slow' and len(day.activities)>4):
            add('pace_density','当日活动数量与明确节奏不匹配',di,soft=True)
        families=[];day_ids=[]
        for ai,a in enumerate(day.activities):
            text=' '.join([a.title,a.description])
            p=places.get(a.place_id)
            evidence=' '.join([text,p.name if p else '',p.category or '' if p else ''])
            for required in trip.context.required_activities:
                if matches(required,evidence) and not re.search(r'未找到|无法安排|尚未满足|没有.{0,8}可验证',text):coverage.setdefault(required,set()).add(di)
            if excluded(text,trip.context.excluded_activities) or (p and excluded(p.name+' '+(p.category or ''),trip.context.excluded_activities)):
                add('excluded_activity','安排了明确排除的活动',di,ai)
            if a.place_id and not p:add('candidate_outside','地点不在已查询候选池',di,ai,evidence='places')
            if not a.place_id and any(p.name in a.title for p in places.values()):add('candidate_reference','具体地点缺少候选引用',di,ai,evidence='places')
            if p:
                seen[p.place_id]+=1;day_ids.append(p.place_id)
                if check_opening_hours(p,day.date,a.time_period).status=='closed':
                    add('closed','周规则在对应时段明确关闭',di,ai,evidence=f'opening:{p.place_id}',hint='优先同类别且非closed候选；无替代则删除并明确未满足需求')
                if a.opening_status=='open_by_weekly_rule' and check_opening_hours(p,day.date,a.time_period).status!='open':
                    add('unsupported_fact','未知营业状态被标为周规则开放',di,ai,evidence='opening_checks')
                if any(v in (p.category or '')+a.title for v in ('餐','饭','美食','烤鸭','涮肉')):meal[p.place_id]+=1
            if unsupported_open_claim(text+' '+a.rationale):add('unsupported_fact','未知或条件营业被描述为已确认营业',di,ai,evidence='opening_checks')
            if re.search(r'已(?:验证|确认|查询).{0,12}(?:价格|费用|天气|拥堵)',text):add('unsupported_fact','声明了工具未提供的事实',di,ai,evidence='unsupported_source')
            for clause in re.split(r'[。；;，,]',text):
                if re.search(r'已(?:验证|确认|查询)',clause) and not re.search(r'不能|未|不代表|需核实|用户|偏好|需求|节奏|访谈',clause):
                    route_claim=bool(re.search(r'步行|公交|地铁|驾车|开车|路线|可达',clause))
                    supported_existence=bool(p and p.name in clause and re.search(r'地点存在|POI存在|已查询地点',clause))
                    if not route_claim and not supported_existence and not unsupported_open_claim(clause):
                        add('unsupported_fact','确认性事实声明超出已取得证据',di,ai,evidence='observations')

            if len(a.rationale.strip())<10 or a.rationale.strip() in {'很热门所以推荐','适合所有人旅游'}:
                add('weak_rationale','个性化理由过弱',di,ai,soft=True)
            families.extend(family_names(evidence))
            # 复用V1精确模式/分钟/端点守卫；只检查截至当前活动的副本定位问题。
            prefix=draft.model_copy(deep=True);prefix.summary='待核实交通';prefix.days=[day.model_copy(deep=True)]
            prefix.days[0].activities=prefix.days[0].activities[:ai+1]
            for prior in prefix.days[0].activities[:-1]:
                prior.title='前序地点';prior.description='活动参考';prior.rationale='按本次明确偏好安排'
            try:apply_route_evidence(prefix,observation)
            except ValueError: add('route_fact','交通模式、数值或已验证声明无对应成功路线证据',di,ai,evidence='routes')
            except RuntimeError: add('route_fact','交通模式、数值或已验证声明无对应成功路线证据',di,ai,evidence='routes')
        if Counter(families) and Counter(families).most_common(1)[0][1]>=3:add('category_density','同类别活动过密',di,soft=True)
        for i in range(2,len(day_ids)):
            a,b,c=[places[x] for x in day_ids[i-2:i+1]]
            dist=lambda x,y:hypot(x.location.longitude-y.location.longitude,x.location.latitude-y.location.latitude)
            if dist(a,c)<0.01 and min(dist(a,b),dist(b,c))>0.06:add('backtracking','坐标显示明显折返',di,soft=True,evidence='places.location')
        for a,b in zip(day_ids,day_ids[1:]):
            rs=[r for r in observation.routes if r.origin_place_id==a and r.destination_place_id==b and r.status=='ok']
            if rs and min(r.duration_s for r in rs)>3600:
                alternatives=[p for p in places.values() if p.place_id!=b and (family_names(p.category or '') & family_names(places[b].category or '') or set(p.source_keywords)&set(places[b].source_keywords))]
                if alternatives:add('route_cost','交通成本高且存在同需求候选，需权衡',di,soft=True,evidence='routes')
    for required in trip.context.required_activities:
        if required not in coverage:add('required_missing','明确必需活动没有匹配安排',evidence='TripContext.required_activities',hint=f'补入明确要求：{required}；只用已取得证据')
    if len(coverage)>1 and len(draft.days)>1 and len(set.union(*coverage.values()))==1:add('required_concentration','多类必需活动集中在一天',soft=True)
    for pid,n in seen.items():
        if n>2:add('place_repetition','同一地点重复超过两次',soft=True,evidence=f'place:{pid}')
    for pid,n in meal.items():
        if n>1:add('meal_repetition','饮食安排重复同一地点',soft=True,evidence=f'place:{pid}')
    try:check_explicit_pace_conflict(context,draft)
    except RuntimeError:add('pace_conflict','文案与本次明确fast节奏冲突')
    hard=[i for i in issues if i.severity=='hard'];soft=[i for i in issues if i.severity=='soft']
    return ValidationResult(valid=not hard,violations=hard,warnings=soft,hard_violation_count=len(hard),soft_warning_count=len(soft),
        affected_days=sorted({i.day for i in issues if i.day is not None}),affected_activity_ids=sorted({i.activity_reference for i in issues if i.activity_reference}),
        constraint_types=sorted({i.type for i in issues}),summary=f'{len(hard)}项硬冲突，{len(soft)}项提醒；自然语言规则仅覆盖明确可判断情况')
