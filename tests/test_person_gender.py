"""性别由用户提供，可选且不替代明确偏好，旧人物 JSON 可继续读取。"""
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from life_journey.api import create_app
from life_journey.schemas import Person, PersonCreate
from life_journey.application.create import create_person


@pytest.mark.parametrize('gender', [None, 'female', 'male', 'other', 'prefer_not_to_say'])
def test_gender_create_and_roundtrip(gender):
    """Input：各合法性别或 None；Expected Output：创建及 JSON 往返保留，偏好仍空；测试目的为保证自述数据不会生成隐含偏好。"""
    person = create_person(PersonCreate(name='人物', gender=gender))
    assert person.gender == gender
    assert person.interests == [] and person.preferred_pace is None
    assert Person.model_validate_json(person.model_dump_json()) == person


@pytest.mark.parametrize('gender', ['unknown', '', 1, True])
def test_invalid_gender(gender):
    """Input：未定义文本或非字符串；Expected Output：ValidationError；测试目的为严格枚举校验。"""
    with pytest.raises(ValidationError):
        PersonCreate(name='人物', gender=gender)


def test_legacy_person_and_gender_persistence(tmp_path):
    """Input：旧 JSON、本人和伙伴更新；Expected Output：旧数据默认 None，刷新/重启保留性别和 ID；测试目的为兼容旧库且前后端共用保存规则。"""
    assert Person.model_validate_json('{"person_id":"old","name":"旧人物"}').gender is None
    path = tmp_path / 'gender.sqlite3'
    with TestClient(create_app(path)) as client:
        own = client.put('/api/profile', json={'name':'我','gender':'female'}).json()
        peer = client.post('/api/persons', json={'name':'伙伴','gender':'male'}).json()
        result = client.put('/api/persons/'+peer['person_id'], json={'name':'伙伴','gender':'prefer_not_to_say'}).json()
        assert result['gender'] == 'prefer_not_to_say'
    with TestClient(create_app(path)) as client:
        assert client.get('/api/profile').json() == own
        assert client.get('/api/persons/'+peer['person_id']).json() == result
