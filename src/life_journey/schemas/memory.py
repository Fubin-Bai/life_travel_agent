"""V4记忆与检索契约；偏好来源、作用域与本次情境分开。"""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .person import NonEmptyString

from life_journey.harness.policy import DEFAULT_POLICY
MEMORY_TOP_K=DEFAULT_POLICY.memory_top_k

class MemoryCandidate(BaseModel):
    """仅稳定信息可写入；scope人物集合用于检索前隔离。"""
    model_config=ConfigDict(extra='forbid',strict=True)
    memory_type: Literal['person','relationship','trip']='person'
    person_id: NonEmptyString
    participant_ids: list[NonEmptyString] = Field(min_length=1)
    relationship_id: NonEmptyString | None=None
    trip_id: NonEmptyString | None=None
    destination: str | None=None
    content: NonEmptyString = Field(max_length=500)
    structured_tags: dict[str,str] = Field(default_factory=dict)
    source_type: Literal['explicit','inferred','confirmed']='explicit'
    confidence: float = Field(default=1.0,ge=0,le=1,allow_inf_nan=False)
    source_reference: NonEmptyString
    stable: bool=False
    observation_count: int=Field(default=1,ge=1)

    @model_validator(mode='after')
    def scope(self):
        """禁止没有人物归属或不完整的组合记忆。"""
        if self.person_id not in self.participant_ids or len(set(self.participant_ids))!=len(self.participant_ids):raise ValueError('记忆人物范围无效')
        if self.memory_type=='person' and self.participant_ids!=[self.person_id]:raise ValueError('个人记忆只能属于一个人')
        if self.memory_type=='relationship' and (not self.relationship_id or len(self.participant_ids)<2):raise ValueError('关系记忆需要明确关系与组合')
        if self.memory_type=='trip' and (not self.trip_id or not self.destination):raise ValueError('旅行记忆需要旅行与目的地')
        return self

class Memory(MemoryCandidate):
    """保留被覆盖记录但不再召回；向量与内容一并版本化。"""
    memory_id: str
    created_at: datetime
    updated_at: datetime
    last_confirmed_at: datetime | None=None
    active: bool=True
    superseded_by: str | None=None
    embedding_model: str
    embedding_dimensions: int=Field(gt=0)
    vector_id: str

class RetrievedMemory(BaseModel):
    """只把TopK及来源放入图，不传全部历史。"""
    model_config=ConfigDict(extra='forbid',strict=True)
    memory_id: str
    memory_type: str
    person_id: str
    content: str
    structured_tags: dict[str,str]
    source_type: str
    confidence: float
    source_reference: str
    score: float
    similarity: float
    hard_constraint: Literal[False]=False

class FeedbackInput(BaseModel):
    """本机单用户原型，不把主体选择当作生产鉴权。"""
    model_config=ConfigDict(extra='forbid',strict=True)
    feedback: NonEmptyString=Field(max_length=3000)
    rating: int | None=Field(default=None,ge=1,le=5)
    person_id: str | None=None
    memory_type: Literal['person','relationship','trip']='person'
    relationship_id: str | None=None

    confirm_memory_ids: list[NonEmptyString] = Field(default_factory=list,max_length=10)
