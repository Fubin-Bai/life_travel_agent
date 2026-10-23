// HTTP 边界只传输用户字段；系统 ID、持久化和领域校验由后端负责。
export type Pace = "slow" | "moderate" | "fast" | null;
export type PersonInput = {
  name: string;
  gender: "female" | "male" | "other" | "prefer_not_to_say" | null;
  mbti: string | null;
  interests: string[];
  dislikes: string[];
  food_preferences: string[];
  preferred_pace: Pace;
};
export type Person = PersonInput & { person_id: string };
export type RelationshipInput = {
  person_a_id: string;
  person_b_id: string;
  relationship_type: string;
  shared_travel_preferences: string[];
  preferred_pace_together: Pace;
};
export type Relationship = RelationshipInput & { relationship_id: string };
export type TripInput = {
  destination: string;
  start_date: string;
  end_date: string;
  participant_ids: string[];
  budget: {
    min_amount: string | null;
    max_amount: string | null;
    currency: string;
  };
};
export type Trip = TripInput & {
  trip_id: string;
  context: {
    purpose: string | null;
    preferred_pace: Pace;
    activity_preferences: string[];
    required_activities: string[];
    excluded_activities: string[];
  };
};

export type InterviewResult = {
  trip_id: string;
  assistant_message: string | null;
  ready_to_plan: boolean;
  llm_ready_to_plan: boolean | null;
  context: Trip["context"];
  state: {
    trip_id: string;
    topics: Record<string, "unknown" | "confirmed">;
    missing_topics: string[];
    ready_to_plan: boolean;
    phase: string;
  };
};

// 除 HTTP 状态外，检查访谈关键字段，避免成功响应格式错误却静默显示。
export async function interviewApi(
  id: string,
  userMessage?: string,
): Promise<InterviewResult> {
  const result = await api<InterviewResult>(
    `/trips/${encodeURIComponent(id)}/interview`,
    userMessage === undefined ? "GET" : "POST",
    userMessage === undefined ? undefined : { user_message: userMessage },
  );
  if (
    !result ||
    result.trip_id !== id ||
    typeof result.ready_to_plan !== "boolean" ||
    !result.state ||
    result.state.trip_id !== id ||
    typeof result.state.ready_to_plan !== "boolean" ||
    !result.state.topics ||
    !Array.isArray(result.state.missing_topics) ||
    !result.context ||
    (userMessage !== undefined &&
      (typeof result.assistant_message !== "string" ||
        !result.assistant_message.trim()))
  ) {
    throw new Error("访谈响应格式不正确，请刷新以确认最新状态。");
  }
  return result;
}

export async function api<T>(
  path: string,
  method = "GET",
  data?: unknown,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      cache: "no-store",
      headers:
        data === undefined ? undefined : { "Content-Type": "application/json" },
      body: data === undefined ? undefined : JSON.stringify(data),
    });
  } catch {
    throw new Error("无法连接本地后端，请确认 API 已启动。");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail
              .map(
                (item: { loc: string[]; msg: string }) =>
                  `${item.loc.join(".") || "输入"}: ${item.msg}`,
              )
              .join("；")
          : `请求失败（${response.status}）`;
    throw new Error(message);
  }
  try {
    return (await response.json()) as T;
  } catch {
    throw new Error("后端返回了无法解析的响应，请检查服务并重试。");
  }
}

export type Itinerary = {
  trip_id: string;
  summary: string;
  days: {
    date: string;
    theme: string;
    activities: {
      time_period: "morning" | "afternoon" | "evening";
      title: string;
      description: string;
      rationale: string;
    }[];
  }[];
};
export type PlanningResult = { itinerary: Itinerary; notice: string };

export async function planningApi(id: string): Promise<PlanningResult> {
  const result = await api<PlanningResult>(
    `/trips/${encodeURIComponent(id)}/planning`,
    "POST",
  );
  if (
    !result?.itinerary ||
    result.itinerary.trip_id !== id ||
    typeof result.itinerary.summary !== "string" ||
    !Array.isArray(result.itinerary.days) ||
    !result.itinerary.days.length ||
    typeof result.notice !== "string" ||
    result.itinerary.days.some(
      (day) =>
        typeof day.date !== "string" ||
        typeof day.theme !== "string" ||
        !Array.isArray(day.activities) ||
        !day.activities.length ||
        day.activities.some(
          (activity) =>
            !["morning", "afternoon", "evening"].includes(
              activity.time_period,
            ) ||
            [activity.title, activity.description, activity.rationale].some(
              (value) => typeof value !== "string" || !value.trim(),
            ),
        ),
    )
  ) {
    throw new Error("规划响应格式不正确，请重试。");
  }
  return result;
}
