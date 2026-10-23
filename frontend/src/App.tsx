import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { api, interviewApi, planningApi } from "./api";
import type {
  PlanningResult,
  InterviewResult,
  Person,
  PersonInput,
  Relationship,
  RelationshipInput,
  Trip,
  TripInput,
} from "./api";

type Page = "profile" | "people" | "trip" | "interview";
type Pace = "slow" | "moderate" | "fast";
type Profile = {
  name: string;
  gender: PersonInput["gender"];
  mbti: string;
  interests: string[];
  dislikes: string[];
  food: string[];
  pace: Pace | null;
};
const paceLabels: Record<Pace, string> = {
  slow: "慢一点",
  moderate: "适中",
  fast: "充实一些",
};

function Arrow({ up = false }: { up?: boolean }) {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <path
        d={up ? "M12 19V5m-6 6 6-6 6 6" : "M4 12h15m-6-6 6 6-6 6"}
        stroke="currentColor"
        strokeWidth="1.5"
      />
    </svg>
  );
}

// 标签先编辑本地草稿，点击保存后通过 API 持久化。
function TagEditor({
  label,
  hint,
  values,
  onChange,
}: {
  label: string;
  hint: string;
  values: string[];
  onChange: (values: string[]) => void;
}) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const value = draft.trim();
    if (value && !values.includes(value)) onChange([...values, value]);
    setDraft("");
  };
  return (
    <div className="tag-editor">
      <div className="field-heading">
        <span>{label}</span>
        <small>{hint}</small>
      </div>
      <div className="tags">
        {values.map((value) => (
          <span className="tag" key={value}>
            {value}
            <button
              type="button"
              aria-label={`移除${value}`}
              onClick={() => onChange(values.filter((item) => item !== value))}
            >
              ×
            </button>
          </span>
        ))}
      </div>
      <div className="tag-input">
        <input
          aria-label={`添加${label}`}
          value={draft}
          placeholder="添加一个标签"
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.nativeEvent.isComposing) {
              event.preventDefault();
              add();
            }
          }}
        />
        <button type="button" aria-label={`添加${label}标签`} onClick={add}>
          ＋
        </button>
      </div>
    </div>
  );
}

function PaceSelector({
  value,
  onChange,
}: {
  value: Pace | null;
  onChange: (pace: Pace | null) => void;
}) {
  return (
    <div className="pace-options" role="group" aria-label="旅行节奏">
      <button
        type="button"
        aria-pressed={value === null}
        className={value === null ? "selected" : ""}
        onClick={() => onChange(null)}
      >
        未指定
      </button>
      {(Object.keys(paceLabels) as Pace[]).map((pace) => (
        <button
          type="button"
          key={pace}
          aria-pressed={value === pace}
          className={value === pace ? "selected" : ""}
          onClick={() => onChange(pace)}
        >
          {paceLabels[pace]}
        </button>
      ))}
    </div>
  );
}

const emptyProfile = (): Profile => ({
  name: "",
  gender: null,
  mbti: "",
  interests: [],
  dislikes: [],
  food: [],
  pace: null,
});
const toProfile = (person: Person): Profile => ({
  name: person.name,
  gender: person.gender ?? null,
  mbti: person.mbti ?? "",
  interests: [...person.interests],
  dislikes: [...person.dislikes],
  food: [...person.food_preferences],
  pace: person.preferred_pace,
});
const personInput = (profile: Profile): PersonInput => ({
  name: profile.name,
  gender: profile.gender,
  mbti: profile.mbti || null,
  interests: profile.interests,
  dislikes: profile.dislikes,
  food_preferences: profile.food,
  preferred_pace: profile.pace,
});
const relationshipTypes = [
  "spouse",
  "partner",
  "friend",
  "family",
  "sibling",
  "colleague",
  "other",
];

// 仅翻译展示名称，提交给后端的关系枚举保持不变。
const relationshipLabels: Record<string, string> = {
  spouse: "配偶",
  partner: "伴侣",
  friend: "朋友",
  family: "家人",
  sibling: "兄弟姐妹",
  colleague: "同事",
  other: "其他",
};

function PersonFields({
  value,
  onChange,
}: {
  value: Profile;
  onChange: (value: Profile) => void;
}) {
  const update = (patch: Partial<Profile>) => onChange({ ...value, ...patch });
  return (
    <>
      <div className="two-cols">
        <label>
          姓名
          <input
            value={value.name}
            onChange={(e) => update({ name: e.target.value })}
          />
        </label>
        <label>
          性别 <small>选填</small>
          <select value={value.gender ?? ""} onChange={(e) => update({ gender: (e.target.value || null) as Profile["gender"] })}>
            <option value="">暂不填写</option>
            <option value="female">女</option>
            <option value="male">男</option>
            <option value="other">其他</option>
            <option value="prefer_not_to_say">不愿透露</option>
          </select>
        </label>
        <label>
          MBTI <small>选填 · 仅记录自述</small>
          <select
            value={value.mbti}
            onChange={(e) => update({ mbti: e.target.value })}
          >
            <option value="">暂不填写</option>
            {[
              "INTJ",
              "INTP",
              "ENTJ",
              "ENTP",
              "INFJ",
              "INFP",
              "ENFJ",
              "ENFP",
              "ISTJ",
              "ISFJ",
              "ESTJ",
              "ESFJ",
              "ISTP",
              "ISFP",
              "ESTP",
              "ESFP",
            ].map((type) => (
              <option key={type}>{type}</option>
            ))}
          </select>
        </label>
      </div>
      <TagEditor
        label="喜欢的事"
        hint="Interests"
        values={value.interests}
        onChange={(interests) => update({ interests })}
      />
      <TagEditor
        label="不太喜欢"
        hint="Dislikes"
        values={value.dislikes}
        onChange={(dislikes) => update({ dislikes })}
      />
      <TagEditor
        label="饮食喜好"
        hint="Food preferences"
        values={value.food}
        onChange={(food) => update({ food })}
      />
      <div className="field-heading">
        <span>旅行节奏</span>
        <small>Preferred travel pace</small>
      </div>
      <PaceSelector value={value.pace} onChange={(pace) => update({ pace })} />
    </>
  );
}

export default function App() {
  const [page, setPage] = useState<Page>("interview");
  const [persons, setPersons] = useState<Person[]>([]);
  const [relationships, setRelationships] = useState<Relationship[]>([]);
  const [trips, setTrips] = useState<Trip[]>([]);
  const [profileId, setProfileId] = useState("");
  const [profileBound, setProfileBound] = useState(false);
  const [profile, setProfile] = useState<Profile>(emptyProfile);
  const [peerId, setPeerId] = useState("");
  const [peer, setPeer] = useState<Profile>(emptyProfile);
  const [relationshipId, setRelationshipId] = useState("");
  const [relationshipType, setRelationshipType] = useState("friend");
  const [shared, setShared] = useState<string[]>([]);
  const [sharedPace, setSharedPace] = useState<Pace | null>(null);
  const [destination, setDestination] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [min, setMin] = useState("");
  const [max, setMax] = useState("");
  const [currency, setCurrency] = useState("AUD");
  const [participants, setParticipants] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [lastTrip, setLastTrip] = useState<Trip | null>(null);
  const [activeTripId, setActiveTripId] = useState("");
  const [interview, setInterview] = useState<InterviewResult | null>(null);
  const [turnMessages, setTurnMessages] = useState<
    { role: "user" | "assistant"; text: string }[]
  >([]);
  const [interviewError, setInterviewError] = useState("");
  const [plan, setPlan] = useState<PlanningResult | null>(null);
  const [planning, setPlanning] = useState(false);

  // 主体由后端固定绑定，浏览器只保存未提交的编辑草稿。
  const selectRelationship = (id: string, collection = relationships) => {
    const relationship = collection.find((item) => item.relationship_id === id);
    setRelationshipId(relationship?.relationship_id ?? "");
    setRelationshipType(relationship?.relationship_type ?? "friend");
    setShared(relationship ? [...relationship.shared_travel_preferences] : []);
    setSharedPace(relationship?.preferred_pace_together ?? null);
  };
  const selectPeer = (
    id: string,
    me = profileId,
    people = persons,
    links = relationships,
  ) => {
    const person = people.find((item) => item.person_id === id);
    setPeerId(person?.person_id ?? "");
    setPeer(person ? toProfile(person) : emptyProfile());
    selectRelationship(
      links.find(
        (item) =>
          [item.person_a_id, item.person_b_id].includes(me) &&
          [item.person_a_id, item.person_b_id].includes(id),
      )?.relationship_id ?? "",
      links,
    );
  };
  const selectProfile = (id: string) => {
    const person = persons.find((item) => item.person_id === id);
    setProfileId(id);
    setProfile(person ? toProfile(person) : emptyProfile());
    selectPeer(
      persons.find((item) => item.person_id !== id)?.person_id ?? "",
      id,
    );
    setNotice("");
  };
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api<Person[]>("/persons"),
      api<Relationship[]>("/relationships"),
      api<Trip[]>("/trips"),
      api<Person | null>("/profile"),
    ])
      .then(([people, links, savedTrips, ownProfile]) => {
        if (cancelled) return;
        setPersons(people);
        setRelationships(links);
        setTrips(savedTrips);
        // 旧库多个人物时请用户明确绑定，不按姓名或浏览器旧选择猜测身份。
        const person = ownProfile;
        setProfileBound(!!ownProfile);
        const id = person?.person_id ?? "";
        setProfileId(id);
        setProfile(person ? toProfile(person) : emptyProfile());
        const other = people.find((item) => item.person_id !== id);
        selectPeer(other?.person_id ?? "", id, people, links);
      })
      .catch((error) => {
        if (!cancelled) {
          setLoadError(true);
          setNotice(error.message);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const act = async (work: () => Promise<void>) => {
    if (busy || loading || loadError) return;
    setBusy(true);
    setNotice("");
    try {
      await work();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "保存失败，请重试。");
    } finally {
      setBusy(false);
    }
  };
  const savePerson = (which: "profile" | "peer") =>
    act(async () => {
      const id = which === "profile" ? profileId : peerId;
      if (which === "profile" && !profileBound && persons.length) {
        if (!id) throw new Error("请先选择哪条已有资料是你自己。");
        await api<Person>(`/profile/${encodeURIComponent(id)}`, "PUT");
      }
      const saved = await api<Person>(
        which === "profile" ? "/profile" : `/persons${id ? `/${id}` : ""}`,
        which === "profile" || id ? "PUT" : "POST",
        personInput(which === "profile" ? profile : peer),
      );
      setPersons((current) =>
        id
          ? current.map((item) => (item.person_id === id ? saved : item))
          : [...current, saved],
      );
      if (which === "profile") {
        setProfileId(saved.person_id);
        setProfileBound(true);
        setProfile(toProfile(saved));
      } else {
        setPeerId(saved.person_id);
        setPeer(toProfile(saved));
      }
      setNotice("人物资料已保存。");
    });
  const saveRelationship = () =>
    act(async () => {
      if (!profileId || !peerId) throw new Error("请先保存两个人的个人资料。");
      const data: RelationshipInput = {
        person_a_id: profileId,
        person_b_id: peerId,
        relationship_type: relationshipType,
        shared_travel_preferences: shared,
        preferred_pace_together: sharedPace,
      };
      const saved = await api<Relationship>(
        `/relationships${relationshipId ? `/${relationshipId}` : ""}`,
        relationshipId ? "PUT" : "POST",
        data,
      );
      setRelationships((current) =>
        relationshipId
          ? current.map((item) =>
              item.relationship_id === relationshipId ? saved : item,
            )
          : [...current, saved],
      );
      selectRelationship(saved.relationship_id, [saved]);
      setNotice("关系资料已保存。");
    });
  const startTrip = (event: FormEvent) => {
    event.preventDefault();
    void act(async () => {
      const data: TripInput = {
        destination,
        start_date: start,
        end_date: end,
        participant_ids: participants,
        budget: { min_amount: min || null, max_amount: max || null, currency },
      };
      const saved = await api<Trip>("/trips", "POST", data);
      setTrips((current) => [...current, saved]);
      setLastTrip(saved);
      const state = await interviewApi(saved.trip_id);
      setPlan(null);
      setActiveTripId(saved.trip_id);
      setInterview(state);
      setTurnMessages([]);
      setInterviewError("");
      setPage("interview");
      setNotice("旅行已保存，可以开始访谈。");
    });
  };
  const openTrip = (id: string) =>
    act(async () => {
      setLastTrip(await api<Trip>(`/trips/${id}`));
    });
  const enterInterview = (id: string) =>
    act(async () => {
      if (!id) {
        setPlan(null);
        setActiveTripId("");
        setInterview(null);
        setTurnMessages([]);
        return;
      }
      const result = await interviewApi(id);
      setPlan(null);
      setActiveTripId(id);
      setInterview(result);
      setTurnMessages([]);
      setDraft("");
      setInterviewError("");
      setPage("interview");
    });
  const sendInterview = async (event: FormEvent) => {
    event.preventDefault();
    if (busy || !draft.trim()) return;
    if (!activeTripId || !interview) {
      setNotice("请先选择或创建一次旅行。");
      return;
    }
    if (interview.ready_to_plan) return;
    const message = draft;
    setBusy(true);
    setNotice("");
    setInterviewError("");
    try {
      const result = await interviewApi(activeTripId, message);
      setTurnMessages((current) => [
        ...current,
        { role: "user", text: message },
        { role: "assistant", text: result.assistant_message! },
      ]);
      setInterview(result);
      setDraft("");
      setTrips((current) =>
        current.map((trip) =>
          trip.trip_id === activeTripId
            ? { ...trip, context: result.context }
            : trip,
        ),
      );
      setLastTrip((current) =>
        current?.trip_id === activeTripId
          ? { ...current, context: result.context }
          : current,
      );
    } catch (error) {
      // 失败保留输入供用户检查；不自动重发，避免重复调用和重复状态更新。
      setInterviewError(
        error instanceof Error ? error.message : "访谈失败，请重试。",
      );
    } finally {
      setBusy(false);
    }
  };
  const startPlanning = async () => {
    if (busy || plan || !activeTripId || !interview?.ready_to_plan) return;
    setBusy(true);
    setPlanning(true);
    setInterviewError("");
    setPlan(null);
    try {
      setPlan(await planningApi(activeTripId));
    } catch (error) {
      setInterviewError(
        error instanceof Error ? error.message : "规划失败，请重试。",
      );
    } finally {
      setBusy(false);
      setPlanning(false);
    }
  };
  const activeTrip = trips.find((trip) => trip.trip_id === activeTripId);
  const peerOptions = persons.filter((item) => item.person_id !== profileId);
  const pairRelationships = relationships.filter(
    (item) =>
      [item.person_a_id, item.person_b_id].includes(profileId) &&
      [item.person_a_id, item.person_b_id].includes(peerId),
  );
  const disabled = busy || loading || loadError;

  return (
    <div
      className={`app-shell home-shell ${page !== "interview" ? "inner-shell" : ""}`}
    >
      <div className="home-backdrop" aria-hidden="true" />
      <header className="site-header">
        <button
          className="brand"
          onClick={() => setPage("interview")}
          aria-label="人生旅迹首页"
        >
          <span className="brand-symbol" aria-hidden="true">
            /
          </span>
          <span>
            人生旅迹<small>LIFE JOURNEY</small>
          </span>
        </button>
        <nav aria-label="主导航">
          {(
            [
              ["profile", "我的资料"],
              ["people", "同行人"],
              ["trip", "新建旅行"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              className={page === key ? "active" : ""}
              disabled={busy}
              onClick={() => {
                setPage(key);
                setNotice("");
              }}
            >
              {label}
            </button>
          ))}
        </nav>
      </header>
      {(loading || notice || loadError) && (
        <div className="data-status" role="status">
          {loading
            ? "正在读取本地资料…"
            : notice || "后端连接失败，请启动后端后刷新页面。"}
          {loadError && (
            <button onClick={() => window.location.reload()}>重新加载</button>
          )}
        </div>
      )}
      {page === "interview" ? (
        <main className="home-entry">
          <section className="home-content" aria-label="开始新的旅行">
            <h1>人生旅迹</h1>
            <p className="home-description">每一段旅途，都是人生中新的锚点。</p>
            <label className="record-selector interview-trip-selector">
              当前旅行
              <select
                aria-label="选择访谈旅行"
                disabled={disabled}
                value={activeTripId}
                onChange={(e) => void enterInterview(e.target.value)}
              >
                <option value="">选择已保存的旅行</option>
                {trips.map((trip) => (
                  <option key={trip.trip_id} value={trip.trip_id}>
                    {trip.destination} · {trip.start_date}
                  </option>
                ))}
              </select>
            </label>
            {!trips.length && !loading && (
              <button className="text-button" onClick={() => setPage("trip")}>
                先创建旅行 →
              </button>
            )}
            {activeTrip && interview && (
              <div className="web-interview">
                <div className="interview-caption">
                  {activeTrip.destination} · {activeTrip.start_date} —{" "}
                  {activeTrip.end_date}
                </div>
                {turnMessages.length === 0 && (
                  <p className="interview-hint">
                    {interview.ready_to_plan
                      ? "这次旅行的访谈已达到规划条件。"
                      : "可以直接说说这次旅行的想法。结构化状态已载入，聊天记录不会跨刷新保存。"}
                  </p>
                )}
                <div className="web-conversation" role="log" aria-live="polite">
                  {turnMessages.map((message, index) => (
                    <div className={`web-message ${message.role}`} key={index}>
                      <small>
                        {message.role === "user" ? "你" : "人生旅迹"}
                      </small>
                      <p>{message.text}</p>
                    </div>
                  ))}
                </div>
                {interview.ready_to_plan && (
                  <div className="planning-ready" role="status">
                    可以开始规划{" "}
                    <button
                      type="button"
                      className="primary-button save-button"
                      disabled={busy || !!plan}
                      onClick={() => void startPlanning()}
                    >
                      {plan ? "行程已生成" : planning ? "正在规划…" : "开始规划"}
                      <Arrow />
                    </button>
                  </div>
                )}
              </div>
            )}
            {plan && (
              <section className="itinerary-result" aria-label="旅行行程">
                <h2>这次旅行的安排</h2>
                <p className="itinerary-notice">{plan.notice}</p>
                <p className="itinerary-summary">{plan.itinerary.summary}</p>
                {plan.itinerary.days.map((day) => (
                  <article className="itinerary-day" key={day.date}>
                    <header>
                      <span>{day.date}</span>
                      <h3>{day.theme}</h3>
                    </header>
                    {day.activities.map((activity, index) => (
                      <div className="itinerary-activity" key={index}>
                        <small>
                          {
                            {
                              morning: "上午",
                              afternoon: "下午",
                              evening: "晚上",
                            }[activity.time_period]
                          }
                        </small>
                        <h4>{activity.title}</h4>
                        <p>{activity.description}</p>
                        <p className="activity-rationale">
                          为什么适合你 · {activity.rationale}
                        </p>
                      </div>
                    ))}
                  </article>
                ))}
              </section>
            )}
            <form
              className="home-input"
              autoComplete="off"
              onSubmit={sendInterview}
            >
              <label className="sr-only" htmlFor="message">
                旅行需求
              </label>
              <input
                id="message"
                name="travel-interview-message"
                autoComplete="off"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder={
                  activeTripId ? "写下你的旅行想法" : "请先选择一次旅行"
                }
                disabled={busy || !interview || interview.ready_to_plan}
              />
              <button
                aria-label="发送需求"
                disabled={
                  disabled ||
                  !draft.trim() ||
                  !interview ||
                  interview.ready_to_plan
                }
              >
                <Arrow />
              </button>
            </form>
            {busy && activeTripId && (
              <p className="home-feedback" role="status">
                {planning ? "正在生成行程，请稍候…" : "正在回复，请稍候…"}
              </p>
            )}
            {interviewError && (
              <p className="interview-error" role="alert">
                {interviewError}{" "}
                <button
                  disabled={busy}
                  onClick={() => void enterInterview(activeTripId)}
                >
                  刷新访谈状态
                </button>
              </p>
            )}
          </section>
        </main>
      ) : (
        <main className="standard-page">
          <div className="page-heading">
            <h1>
              {page === "profile"
                ? "我的资料"
                : page === "people"
                  ? "同行人"
                  : "新建旅行"}
            </h1>
            <p>
              {page === "profile"
                ? "你的偏好。"
                : page === "people"
                  ? "个人偏好，与共同偏好。"
                  : "确定这次旅行的基本信息。"}
            </p>
          </div>
          <fieldset className="data-fields" disabled={disabled}>
            {page === "profile" && (
              <div className="profile-layout">
                <aside className="profile-summary">
                  <div className="large-avatar">{profile.name[0] || "·"}</div>
                  <h2>{profile.name || "创建资料"}</h2>
                  {!profileBound && persons.length > 0 && <label className="record-selector">
                    首次设置：哪条资料是你自己？
                    <select
                      value={profileId}
                      onChange={(e) => selectProfile(e.target.value)}
                    >
                      <option value="">请选择已有资料</option>
                      {persons.map((person) => (
                        <option key={person.person_id} value={person.person_id}>
                          {person.name} · {person.person_id.slice(-8)}
                        </option>
                      ))}
                    </select>
                  </label>}
                  <small>{profileBound ? "这是你的固定个人资料，修改后保存即可。" : "首次保存后固定为我的资料。"}</small>
                  <button className="text-button" onClick={() => { setPage("people"); selectPeer(""); }}>＋ 添加同行人</button>
                </aside>
                <section className="form-panel">
                  <div className="panel-heading">
                    <h2>个人偏好</h2>
                  </div>
                  <PersonFields value={profile} onChange={setProfile} />
                  <button
                    className="primary-button save-button"
                    onClick={() => void savePerson("profile")}
                  >
                    {busy ? "保存中…" : "保存我的资料"}
                    <Arrow />
                  </button>
                </section>
              </div>
            )}
            {page === "people" && (
              <>
                <div className="people-top">
                  <label className="record-selector">
                    同行人
                    <select
                      value={peerId}
                      onChange={(e) => selectPeer(e.target.value)}
                    >
                      <option value="">选择或创建同行人</option>
                      {peerOptions.map((person) => (
                        <option key={person.person_id} value={person.person_id}>
                          {person.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    className="text-button"
                    onClick={() => selectPeer("")}
                  >
                    ＋ 添加同行人
                  </button>
                </div>
                <div className="people-layout">
                  <section className="person-card">
                    <div className="panel-heading">
                      <h2>个人资料</h2>
                    </div>
                    <PersonFields value={peer} onChange={setPeer} />
                    <button
                      className="primary-button save-button"
                      onClick={() => void savePerson("peer")}
                    >
                      保存同行人
                      <Arrow />
                    </button>
                  </section>
                  <section className="form-panel relationship-panel">
                    <h2>
                      {profile.name || "我的资料"} ＆ {peer.name || "同行人"}
                    </h2>
                    <p className="description">个人偏好与共同偏好分别保存。</p>
                    <label className="record-selector">
                      关系记录
                      <select
                        value={relationshipId}
                        onChange={(e) => selectRelationship(e.target.value)}
                      >
                        <option value="">＋ 新建关系</option>
                        {pairRelationships.map((link) => (
                          <option
                            key={link.relationship_id}
                            value={link.relationship_id}
                          >
                            {relationshipLabels[link.relationship_type] ?? link.relationship_type}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="record-selector">
                      关系类型
                      <select
                        value={relationshipType}
                        onChange={(e) => setRelationshipType(e.target.value)}
                      >
                        {relationshipTypes.map((type) => (
                          <option key={type} value={type}>{relationshipLabels[type]}</option>
                        ))}
                      </select>
                    </label>
                    <TagEditor
                      label="一起旅行时喜欢"
                      hint="Shared travel preferences"
                      values={shared}
                      onChange={setShared}
                    />
                    <div className="field-heading">
                      <span>一起旅行的节奏</span>
                    </div>
                    <PaceSelector value={sharedPace} onChange={setSharedPace} />
                    <button
                      className="primary-button save-button"
                      disabled={!profileId || !peerId}
                      onClick={() => void saveRelationship()}
                    >
                      保存关系资料
                      <Arrow />
                    </button>
                    {!profileId && (
                      <p className="field-note">请先创建“我的资料”。</p>
                    )}
                  </section>
                </div>
              </>
            )}
            {page === "trip" && (
              <div className="new-trip-layout">
                <form className="form-panel" onSubmit={startTrip}>
                  <div className="panel-heading">
                    <h2>旅行的起点</h2>
                  </div>
                  <label>
                    目的地
                    <input
                      required
                      value={destination}
                      onChange={(e) => setDestination(e.target.value)}
                    />
                  </label>
                  <div className="two-cols">
                    <label>
                      出发日期
                      <input
                        required
                        type="date"
                        value={start}
                        onChange={(e) => setStart(e.target.value)}
                      />
                    </label>
                    <label>
                      结束日期
                      <input
                        required
                        type="date"
                        min={start}
                        value={end}
                        onChange={(e) => setEnd(e.target.value)}
                      />
                    </label>
                  </div>
                  <div className="field-heading">
                    <span>旅行预算</span>
                  </div>
                  <div className="budget-inputs">
                    <label>
                      <span className="sr-only">最低预算</span>
                      <input
                        type="number"
                        min="0.01"
                        step="0.01"
                        value={min}
                        onChange={(e) => setMin(e.target.value)}
                        placeholder="最低"
                      />
                    </label>
                    <span>—</span>
                    <label>
                      <span className="sr-only">最高预算</span>
                      <input
                        type="number"
                        min="0.01"
                        step="0.01"
                        value={max}
                        onChange={(e) => setMax(e.target.value)}
                        placeholder="最高"
                      />
                    </label>
                    <label>
                      <span className="sr-only">币种</span>
                      <select
                        value={currency}
                        onChange={(e) => setCurrency(e.target.value)}
                      >
                        {["AUD", "CNY", "JPY", "USD", "EUR"].map((value) => (
                          <option key={value}>{value}</option>
                        ))}
                      </select>
                    </label>
                  </div>
                  <div className="field-heading">
                    <span>和谁一起</span>
                    <small>选择已保存的人物</small>
                  </div>
                  <div className="participant-options">
                    {persons.map((person) => (
                      <label
                        key={person.person_id}
                        className={
                          participants.includes(person.person_id)
                            ? "checked"
                            : ""
                        }
                      >
                        <span className="mini-avatar">{person.name[0]}</span>
                        <span>{person.name}</span>
                        <input
                          type="checkbox"
                          checked={participants.includes(person.person_id)}
                          onChange={(e) =>
                            setParticipants((current) =>
                              e.target.checked
                                ? [...current, person.person_id]
                                : current.filter(
                                    (id) => id !== person.person_id,
                                  ),
                            )
                          }
                        />
                      </label>
                    ))}
                  </div>
                  {!persons.length && (
                    <p className="field-note">请先保存个人资料或同行人。</p>
                  )}
                  <button
                    className="primary-button"
                    disabled={!participants.length}
                  >
                    创建旅行
                    <Arrow />
                  </button>
                  <label className="record-selector">
                    已有旅行
                    <select
                      value={lastTrip?.trip_id ?? ""}
                      onChange={(e) => {
                        if (e.target.value) void openTrip(e.target.value);
                      }}
                    >
                      <option value="">选择已保存的旅行</option>
                      {trips.map((trip) => (
                        <option key={trip.trip_id} value={trip.trip_id}>
                          {trip.destination} · {trip.start_date}
                        </option>
                      ))}
                    </select>
                  </label>
                  {lastTrip && (
                    <section className="saved-trip" aria-label="已保存的旅行">
                      <h2>{lastTrip.destination}</h2>
                      <p>
                        {lastTrip.start_date} — {lastTrip.end_date}
                      </p>
                      <p>
                        {lastTrip.participant_ids
                          .map(
                            (id) =>
                              persons.find((person) => person.person_id === id)
                                ?.name ?? id,
                          )
                          .join(" · ")}
                      </p>
                      <p>
                        {lastTrip.budget.min_amount ?? "不限下限"} —{" "}
                        {lastTrip.budget.max_amount ?? "不限上限"}{" "}
                        {lastTrip.budget.currency}
                      </p>
                      <button
                        type="button"
                        className="primary-button save-button"
                        onClick={() => void enterInterview(lastTrip.trip_id)}
                      >
                        进入 / 继续访谈
                        <Arrow />
                      </button>
                    </section>
                  )}
                </form>
              </div>
            )}
          </fieldset>
        </main>
      )}
    </div>
  );
}
