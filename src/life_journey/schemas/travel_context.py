"""Context Builder 的结构化输出，不包含 Prompt 或推断结果。"""

from pydantic import BaseModel, ConfigDict

from .person import Person
from .relationship import Relationship
from .trip import Trip


class TravelContext(BaseModel):
    """保留本次 Trip、参与人物与参与者之间的关系，偏好分层保存。

    选择一致性由 build_travel_context 保障；本模型验证嵌套数据类型。
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    trip: Trip
    participants: list[Person]
    relationships: list[Relationship]
