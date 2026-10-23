"""Neutral pairwise relationships with separately recorded travel preferences."""
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .person import NonEmptyString, TravelPace

RelationshipType = Literal[
    "spouse", "partner", "friend", "family", "sibling", "colleague", "other"
]


class Relationship(BaseModel):
    """A/B are unordered references, not roles or ownership.

    Shared preferences are explicitly recorded, never inferred from personal interests.
    Person existence and duplicate relationships require separate collection checks.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    relationship_id: NonEmptyString
    person_a_id: NonEmptyString
    person_b_id: NonEmptyString
    relationship_type: RelationshipType = Field(
        description=(
            "spouse: explicit marriage; partner: partnership without declaring marital status; "
            "sibling: explicit sibling relationship; family: family relationship with no "
            "specific role, never an inference of parent/child."
        )
    )
    shared_travel_preferences: list[NonEmptyString] = Field(default_factory=list)
    preferred_pace_together: TravelPace | None = None

    @model_validator(mode="after")
    def reject_self_relationship(self) -> Self:
        if self.person_a_id == self.person_b_id:
            raise ValueError("A relationship must connect two different person IDs")
        return self
