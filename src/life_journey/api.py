"""最薄本地 HTTP 层：复用已有 Create/领域模型与创建函数，访谈复用现有 runner，不复制业务规则。"""

from contextlib import asynccontextmanager
import os
from pathlib import Path
import sqlite3

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from life_journey.application.create import create_person, create_relationship, create_trip
from life_journey.schemas import Person, PersonCreate, Relationship, RelationshipCreate, Trip, TripCreate
from life_journey.storage import (
    connect, initialize_database, read_models, write_model,
    interview_snapshot, read_interview_state, save_interview,
)
from life_journey.application.context_builder import build_travel_context
from life_journey.application.interview import initialize_interview, check_minimum_readiness
from life_journey.application.interview_runner import run_interview_turn
from life_journey.llm.base import InterviewLLMClient, LLMClientError, LLMConfigurationError
from life_journey.application.planning import run_planning
from life_journey.llm.planning import PlanningLLMClient
from life_journey.schemas.planning import PlanningResponse
from life_journey.schemas.interview_api import InterviewMessage, InterviewResponse


async def parse_input(request: Request, schema):
    """直接校验 JSON 字节，保留 strict 模型的日期/Decimal JSON 输入语义。"""
    try:
        return schema.model_validate_json(await request.body())
    except ValidationError as exc:
        # 不回显完整用户输入；仅提供可定位的字段和规则信息。
        errors = [{"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
                  for error in exc.errors(include_input=False, include_context=False)]
        raise HTTPException(422, detail=errors) from None


def create_app(database_path: str | Path | None = None, *, llm_client: InterviewLLMClient | None = None, planning_client: PlanningLLMClient | None = None) -> FastAPI:
    """允许测试注入临时数据库；默认本地文件不依赖运行目录。"""
    path = Path(database_path or os.environ.get("LIFE_JOURNEY_DB", "") or
                Path(__file__).resolve().parents[2] / ".local" / "life_journey.sqlite3").expanduser().resolve()

    @asynccontextmanager
    async def lifespan(app):
        """启动时初始化文件，导入模块时不创建数据库。"""
        initialize_database(path)
        yield

    app = FastAPI(title="人生旅迹 V0 Local API", lifespan=lifespan)
    app.add_middleware(CORSMiddleware,
                       allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["GET", "POST", "PUT"], allow_headers=["Content-Type"])

    @app.exception_handler(sqlite3.IntegrityError)
    async def integrity_error(request, exc):
        """引用错误与重复冲突明确区分，不暴露 SQL 或用户数据。"""
        if "FOREIGN KEY" in str(exc):
            return JSONResponse(status_code=422, content={"detail": "引用的 Person 不存在"})
        return JSONResponse(status_code=409, content={"detail": "记录或同一人物对的同类型关系已存在"})

    def get_one(db, table, object_id):
        """缺失 ID 统一 404，不执行 upsert。"""
        result = read_models(db, table, object_id)
        if result is None:
            raise HTTPException(404, "记录不存在")
        return result

    def read_profile(db):
        """本机唯一主体指向现有 Person，不复制人物数据。"""
        row = db.execute("SELECT person_id FROM local_profile WHERE singleton=1").fetchone()
        return get_one(db, "persons", row[0]) if row else None

    @app.get("/api/profile", response_model=Person | None)
    def get_profile():
        """读取固定的我的资料；未设置时返回 null，读取绝不创建人物。"""
        with connect(path) as db:
            return read_profile(db)

    @app.put("/api/profile/{person_id}", response_model=Person)
    def bind_profile(person_id: str):
        """首次明确选择已有主体；已绑定时不允许静默换成另一个人。"""
        with connect(path) as db:
            db.execute("BEGIN IMMEDIATE")
            person = get_one(db, "persons", person_id)
            current = read_profile(db)
            if current is not None and current.person_id != person_id:
                raise HTTPException(409, "我的资料已经绑定，不能切换为其他人物")
            db.execute("INSERT OR IGNORE INTO local_profile(singleton,person_id) VALUES (1,?)", (person_id,))
            return person

    @app.put("/api/profile", response_model=Person)
    async def save_profile(request: Request):
        """首次创建并绑定同一事务；后续保存始终保留原 ID，不重复创建。"""
        data = await parse_input(request, PersonCreate)
        with connect(path) as db:
            db.execute("BEGIN IMMEDIATE")
            current = read_profile(db)
            if current is None:
                if read_models(db, "persons"):
                    raise HTTPException(409, "请先从已有资料中选择哪一条是你自己")
                person = create_person(data)
                write_model(db, person)
                db.execute("INSERT INTO local_profile(singleton,person_id) VALUES (1,?)", (person.person_id,))
            else:
                person = Person(person_id=current.person_id, **data.model_dump(mode="python"))
                write_model(db, person, replace=True)
            return person

    @app.get("/api/persons", response_model=list[Person])
    def list_persons():
        """读取独立人物集合。"""
        with connect(path) as db:
            return read_models(db, "persons")

    @app.get("/api/persons/{person_id}", response_model=Person)
    def get_person(person_id: str):
        """读取一个人物。"""
        with connect(path) as db:
            return get_one(db, "persons", person_id)

    @app.post("/api/persons", response_model=Person, status_code=201)
    async def post_person(request: Request):
        """ID 仍由现有 application create 生成。"""
        person = create_person(await parse_input(request, PersonCreate))
        with connect(path) as db:
            write_model(db, person)
        return person

    @app.put("/api/persons/{person_id}", response_model=Person)
    async def put_person(person_id: str, request: Request):
        """完整替换用户字段，保留系统 ID；省略字段使用 Create 默认值。"""
        data = await parse_input(request, PersonCreate)
        person = Person(person_id=person_id, **data.model_dump(mode="python"))
        with connect(path) as db:
            get_one(db, "persons", person_id)
            write_model(db, person, replace=True)
        return person

    @app.get("/api/relationships", response_model=list[Relationship])
    def list_relationships():
        """读取关系，不自动选择参与者。"""
        with connect(path) as db:
            return read_models(db, "relationships")

    @app.get("/api/relationships/{relationship_id}", response_model=Relationship)
    def get_relationship(relationship_id: str):
        """读取一个关系。"""
        with connect(path) as db:
            return get_one(db, "relationships", relationship_id)

    @app.post("/api/relationships", response_model=Relationship, status_code=201)
    async def post_relationship(request: Request):
        """既有字段验证后由外键验证人物存在性。"""
        relationship = create_relationship(await parse_input(request, RelationshipCreate))
        with connect(path) as db:
            write_model(db, relationship)
        return relationship

    @app.put("/api/relationships/{relationship_id}", response_model=Relationship)
    async def put_relationship(relationship_id: str, request: Request):
        """完整替换关系用户字段，不覆盖个人偏好。"""
        data = await parse_input(request, RelationshipCreate)
        relationship = Relationship(relationship_id=relationship_id, **data.model_dump(mode="python"))
        with connect(path) as db:
            get_one(db, "relationships", relationship_id)
            write_model(db, relationship, replace=True)
        return relationship

    @app.get("/api/trips", response_model=list[Trip])
    def list_trips():
        """读取已创建旅行；不生成或提取情境。"""
        with connect(path) as db:
            return read_models(db, "trips")

    @app.get("/api/trips/{trip_id}", response_model=Trip)
    def get_trip(trip_id: str):
        """回读预算、日期和上下文的完整模型。"""
        with connect(path) as db:
            return get_one(db, "trips", trip_id)

    @app.post("/api/trips", response_model=Trip, status_code=201)
    async def post_trip(request: Request):
        """只接受 Trip Setup；旅行及全部参与者引用在同一事务内写入。"""
        trip = create_trip(await parse_input(request, TripCreate))
        with connect(path) as db:
            write_model(db, trip)
        return trip

    def load_interview(db, trip_id):
        """数据库仅查询当前参与者及双方均参与的关系，选择验证仍由 Builder 完成。"""
        trip = get_one(db, "trips", trip_id)
        persons = [get_one(db, "persons", person_id) for person_id in trip.participant_ids]
        rows = db.execute(
            "SELECT r.data FROM relationships r "
            "JOIN trip_participants a ON a.person_id=r.person_a_id AND a.trip_id=? "
            "JOIN trip_participants b ON b.person_id=r.person_b_id AND b.trip_id=? ORDER BY r.rowid",
            (trip_id, trip_id),
        ).fetchall()
        context = build_travel_context(trip, persons, [Relationship.model_validate_json(row[0]) for row in rows])
        state = read_interview_state(db, trip_id) or initialize_interview(context)
        return context, state

    @app.get("/api/trips/{trip_id}/interview", response_model=InterviewResponse)
    def get_interview(trip_id: str):
        """恢复结构化状态，不调用模型，不伪造历史回复，不写入空状态。"""
        with connect(path) as db:
            context, state = load_interview(db, trip_id)
        return InterviewResponse(trip_id=trip_id, context=context.trip.context, state=state,
                                 ready_to_plan=check_minimum_readiness(context, state))

    @app.post("/api/trips/{trip_id}/interview", response_model=InterviewResponse)
    def post_interview(trip_id: str, data: InterviewMessage, debug: bool = False):
        """一次消息一次模型调用；网络期间不占写锁，成功后情境与状态原子提交。"""
        with connect(path) as db:
            db.execute("BEGIN")
            context, state = load_interview(db, trip_id)
            before = interview_snapshot(db, trip_id)
        owned_client = None
        try:
            if llm_client is None:
                from life_journey.llm.deepseek import DeepSeekInterviewClient
                owned_client = DeepSeekInterviewClient()
            result = run_interview_turn(context, state, data.user_message, llm_client or owned_client)
        except LLMConfigurationError as exc:
            raise HTTPException(503, str(exc)) from None
        except LLMClientError as exc:
            raise HTTPException(502, str(exc)) from None
        except (ValueError, TypeError):
            raise HTTPException(502, "访谈结果或状态校验失败；本轮未保存") from None
        finally:
            if owned_client is not None:
                owned_client.close()
        response = InterviewResponse(
            trip_id=trip_id, assistant_message=result.assistant_message,
            ready_to_plan=result.deterministic_ready_to_plan,
            llm_ready_to_plan=result.llm_ready_to_plan,
            context=result.updated_context.trip.context, state=result.updated_state,
            metrics=result.metrics if debug else None,
        )
        with connect(path) as db:
            db.execute("BEGIN IMMEDIATE")
            if interview_snapshot(db, trip_id) != before:
                raise HTTPException(409, "该旅行的访谈状态已变化，请刷新后重试；本轮未覆盖")
            save_interview(db, result.updated_context.trip, result.updated_state)
        return response

    @app.post("/api/trips/{trip_id}/planning", response_model=PlanningResponse)
    def post_planning(trip_id: str, debug: bool = False):
        """只在系统就绪后按用户明确点击规划；不自动规划，不更新确认状态。"""
        with connect(path) as db:
            db.execute("BEGIN")
            context, state = load_interview(db, trip_id)
            before = interview_snapshot(db, trip_id)
        if not check_minimum_readiness(context, state):
            raise HTTPException(409, "请先完成这次旅行的访谈")
        owned_client = None
        try:
            if planning_client is None:
                from life_journey.llm.deepseek import DeepSeekInterviewClient, DeepSeekConfig
                config = DeepSeekConfig.from_env()
                owned_client = DeepSeekInterviewClient(DeepSeekConfig(model=config.model, max_output_tokens=8192, timeout_seconds=120))
            result = run_planning(context, state, planning_client or owned_client)
        except LLMConfigurationError as exc:
            raise HTTPException(503, str(exc)) from None
        except LLMClientError as exc:
            raise HTTPException(502, str(exc)) from None
        except (ValueError, TypeError):
            raise HTTPException(502, "规划输出未通过校验，请稍后重试") from None
        finally:
            if owned_client is not None:
                owned_client.close()
        with connect(path) as db:
            if interview_snapshot(db, trip_id) != before:
                raise HTTPException(409, "访谈状态已变化，请按最新状态重新规划")
        if not debug:
            result.metrics = None
        return result

    return app


app = create_app()
