"""保守的高德营业文本规范化与周规则判断；不扩展为自然语言/节假日解析器。"""
import re
from datetime import date, timedelta
from pydantic import ValidationError
from .schemas import OpeningHours, WeekdayOpening, OpeningInterval, OpeningCheck, Place

# 时段是可能安排访问的本地时间窗，不表示已知确切到达/离开时间。
PERIOD_WINDOWS = {'morning': (480, 720), 'afternoon': (720, 1080), 'evening': (1080, 1440)}
DAY_INDEX = {value: index for index, value in enumerate('一二三四五六日')}
DAY_INDEX['天'] = 6
DAY_PREFIX = re.compile(r'^(?:周|星期)([一二三四五六日天])(?:(?:至|到|-|~)(?:周|星期)?([一二三四五六日天]))?')
EXCEPTIONS = re.compile(r'节假|假日|法定|临时|调整|通知|以.*为准|旺季|淡季|季节|春节|国庆|预约|特殊|例外|活动期间')
TIME_RANGE = r'(?:[01]?\d|2[0-3]):[0-5]\d\s*-\s*(?:(?:[01]?\d|2[0-3]):[0-5]\d|24:00)'


def _empty(value):
    """只识别合理的缺失占位，不将列表/对象强转为营业文本。"""
    return value is None or value == [] or (isinstance(value, str) and not value.strip())


def normalize_opening_hours(biz_ext, fetched_at) -> OpeningHours:
    """优先详细opentime2；坏/复杂详细文本不能被较简单fallback覆盖。"""
    base = {'source': 'amap', 'fetched_at': fetched_at}
    if not isinstance(biz_ext, dict):
        return OpeningHours(**base, unknown_reason='missing_or_invalid_business_info')
    field = 'opentime2'
    value = biz_ext.get(field)
    if _empty(value):
        field = 'open_time'
        value = biz_ext.get(field)
    if _empty(value):
        return OpeningHours(**base, unknown_reason='missing')
    base['source_field'] = 'biz_ext.' + field
    if not isinstance(value, str):
        return OpeningHours(**base, unknown_reason='invalid_type')
    text = value.strip()
    base['source_text'] = text[:1000]
    if len(text) > 1000:
        return OpeningHours(**base, unknown_reason='text_too_long')
    if EXCEPTIONS.search(text):
        return OpeningHours(**base, unknown_reason='exceptions_need_verification')
    # 仅规范化全角标点/常见区间符号；不删除可能改变语义的文字。
    text = text.replace('：', ':').replace('–', '-').replace('—', '-').replace('～', '~')
    rules = {}
    try:
        clauses = re.split(r'[；;\n]+|[，,](?=(?:周|星期|每天|每日))', text)
        for clause in clauses:
            clause = clause.strip().rstrip('。')
            if not clause:
                raise ValueError()
            match = DAY_PREFIX.match(clause)
            if clause.startswith(('每天', '每日')):
                days = list(range(7)); body = clause[2:]
            elif match:
                first = DAY_INDEX[match[1]]
                last = DAY_INDEX[match[2]] if match[2] is not None else first
                if first > last:
                    raise ValueError()
                days = list(range(first, last + 1)); body = clause[match.end():]
            elif clause in {'24小时营业', '全天24小时营业', '永久停业', '已停业'}:
                days = list(range(7)); body = clause
            else:
                # 裸时间可能只表示今天，不得扩展到未来整周。
                return OpeningHours(**base, unknown_reason='missing_or_unsupported_weekday')
            body = body.strip(' :')
            if body in {'闭馆', '闭店', '休息', '停业', '不营业', '全天关闭', '全天闭馆', '全天休息', '关闭', '永久停业', '已停业'}:
                status = 'closed'; intervals = []
            elif body in {'24小时营业', '全天24小时营业', '全天开放', '全天营业'}:
                status = 'open'; intervals = [OpeningInterval(start_minute=0,end_minute=1440)]
            else:
                if not re.fullmatch(TIME_RANGE + r'(?:[\s、,，]+' + TIME_RANGE + r')*', body):
                    raise ValueError()
                intervals = []
                for item in re.findall(TIME_RANGE, body):
                    start, end = item.split('-')
                    def minute(value):
                        """解析已经通过窄格式检查的HH:MM。"""
                        hour, minute_value = value.strip().split(':')
                        return int(hour) * 60 + int(minute_value)
                    intervals.append(OpeningInterval(start_minute=minute(start),end_minute=minute(end)))
                status = 'open'
            for day in days:
                rule = WeekdayOpening(weekday=day,status=status,intervals=intervals)
                if day in rules:
                    # 重复/覆盖规则保守视为有歧义，不推断优先级。
                    raise ValueError()
                rules[day] = rule
        if not rules:
            raise ValueError()
        return OpeningHours(**base,status='known',weekly=[rules[d] for d in sorted(rules)],unknown_reason=None)
    except (ValueError, ValidationError):
        return OpeningHours(**base,unknown_reason='unsupported_or_ambiguous_format')


def check_opening_hours(place: Place, day: date, period: str) -> OpeningCheck:
    """open表示与时段有营业交集，closed表示明确无交集，其他未知；均须核实实际营业。"""
    start, end = PERIOD_WINDOWS[period]
    hours = place.opening_hours
    rule = next((r for r in hours.weekly if r.weekday == day.weekday()), None) if hours.status == 'known' else None
    base = {'place_id': place.place_id, 'weekday': day.weekday(), 'time_period': period}
    if rule is None:
        return OpeningCheck(**base,status='unknown',reason=hours.unknown_reason or 'weekday_not_specified')
    if rule.status == 'closed':
        return OpeningCheck(**base,status='closed',reason='explicit_weekday_closed')
    overlap = [OpeningInterval(start_minute=max(start,v.start_minute),end_minute=min(end,v.end_minute))
               for v in rule.intervals if max(start,v.start_minute) < min(end,v.end_minute)]
    if not overlap:
        return OpeningCheck(**base,status='closed',reason='weekly_rule_no_overlap')
    return OpeningCheck(**base,status='open',available_intervals=overlap,reason='weekly_rule_overlap')


def build_opening_checks(places: list[Place], start: date, end: date) -> list[OpeningCheck]:
    """仅按本次出现的weekday生成矩阵，最多12×7×3项，不随多周行程重复膨胀。"""
    days = [start + timedelta(days=i) for i in range(min((end-start).days+1,7))]
    return [check_opening_hours(place,day,period) for place in places for day in days for period in PERIOD_WINDOWS]
