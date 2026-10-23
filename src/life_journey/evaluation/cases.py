"""Owner 指定的六个固定访谈场景；期望不发送给被评估模型。"""

from dataclasses import dataclass, field

from life_journey.application import build_travel_context
from life_journey.sample_data import load_persons, load_relationships, load_trips
from life_journey.schemas import InterviewState, TravelContext, TripContext
from life_journey.schemas.interview import ALL_INTERVIEW_TOPICS, InterviewTopic


@dataclass(frozen=True)
class InterviewCase:
    """字段值按精确值比较；正则只作可解释的启发式风险检查。"""

    case_id: str
    user_message: str
    expected_context: dict
    expected_confirmed: tuple[InterviewTopic, ...] = ()
    initial_context: dict = field(default_factory=dict)
    initially_confirmed: tuple[InterviewTopic, ...] = ()
    partner: bool = False
    forbidden_patterns: tuple[str, ...] = ()
    expected_ready: bool | None = None
    expect_closure: bool = False
    forbidden_question_patterns: tuple[str, ...] = ()


def load_cases() -> list[InterviewCase]:
    """每次返回独立定义，避免可变期望或初始值污染后续运行。"""
    return [
        InterviewCase("case_1_relaxation", "最近工作特别累，这次就想轻松一点，不想每天跑很多地方。",
                      {"purpose": "relaxation", "preferred_pace": "slow"},
                      forbidden_patterns=(r"nature|自然|spa|水疗|温泉",),
                      forbidden_question_patterns=(r"(?:目的|目标).{0,16}(?:什么|哪|吗|？|\?)", r"(?:想|希望).{0,8}(?:什么|哪种).{0,8}(?:目的|节奏)",)),
        InterviewCase("case_2_required_excluded", "樱花一定要看，迪士尼我绝对不去。",
                      {"required_activities": ["cherry blossom viewing"], "excluded_activities": ["Disneyland"]},
                      ("required_activities", "excluded_activities")),
        InterviewCase("case_3_explicit_none", "没有什么一定要去的，也没有什么特别不想去的。",
                      {"required_activities": [], "excluded_activities": []},
                      ("required_activities", "excluded_activities")),
        InterviewCase("case_4_replace", "算了，这次不太想逛街和咖啡馆了，更想看看艺术展和一些建筑。",
                      {"activity_preferences": ["art exhibitions", "architecture"]},
                      initial_context={"activity_preferences": ["cafes", "shopping"]}),
        InterviewCase("case_5_no_stereotypes", "这是我们第一次一起去东京，正常玩就行。",
                      {"preferred_pace": None, "activity_preferences": [],
                       "required_activities": [], "excluded_activities": []},
                      partner=True,
                      forbidden_patterns=(r"romantic|浪漫|烛光|photo spots?|拍照|摄影|打卡|slow|慢节奏|放慢",
                                          r"MBTI|INFP|ENFJ|内向|外向|人格")),
        InterviewCase("case_6_closure", "没有什么特别不能去的。",
                      {"purpose": "relaxation", "preferred_pace": "slow",
                       "required_activities": ["cherry blossom viewing"], "excluded_activities": []},
                      ("excluded_activities",),
                      initial_context={"purpose": "relaxation", "preferred_pace": "slow",
                                       "required_activities": ["cherry blossom viewing"]},
                      initially_confirmed=tuple(t for t in ALL_INTERVIEW_TOPICS if t != "excluded_activities"),
                      expected_ready=True, expect_closure=True),
    ]


def prepare_case(case: InterviewCase) -> tuple[TravelContext, InterviewState]:
    """从共享虚构数据建立独立场景；第六例仅排除主题未知。"""
    trip = load_trips()["trip_tokyo_alex_bella"]
    trip.context = TripContext.model_validate(case.initial_context)
    relationships = load_relationships()
    if case.partner:
        relationships["relationship_alex_bella"].relationship_type = "partner"
    context = build_travel_context(trip, load_persons().values(), relationships.values())
    state = InterviewState(trip_id=trip.trip_id, trip_setup_complete=True,
                           topics={topic: "confirmed" for topic in case.initially_confirmed})
    return context, state


def load_dialogue_cases() -> list[InterviewCase]:
    """额外对话回归，不改变原六例 benchmark 的定义与可比较性。"""
    return [
        InterviewCase("dialogue_whole_sentence", "最近很累，想轻松一点",
                      {"purpose":"relaxation","preferred_pace":"slow"},
                      ("purpose","preferred_pace"),
                      forbidden_question_patterns=(r"(?:目的|目标).{0,16}(?:什么|哪|吗|？|\?)",r"(?:想|希望).{0,8}(?:什么|哪种).{0,8}(?:目的|节奏)")),
        InterviewCase("dialogue_no_reconfirmation", "目的和慢节奏不变，也没有必须安排或排除的活动。",
                      {"purpose":"relaxation","preferred_pace":"slow","required_activities":[],"excluded_activities":[]},
                      ("required_activities","excluded_activities"),
                      initial_context={"purpose":"relaxation","preferred_pace":"slow"},
                      initially_confirmed=("purpose","preferred_pace"), expected_ready=True, expect_closure=True),
    ]
