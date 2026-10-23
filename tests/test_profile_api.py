"""固定本机主体资料测试；使用临时库，不修改真实用户数据。"""
from fastapi.testclient import TestClient
from life_journey.api import create_app


def test_profile_read_never_creates_and_save_retains_id(tmp_path):
    """Input：空库反复读取/保存；Expected Output：读取为空、保存始终同一 ID 和一人；测试目的为阻止刷新或重试重复创建。"""
    path = tmp_path / "profile.sqlite3"
    with TestClient(create_app(path)) as client:
        for _ in range(3):
            assert client.get('/api/profile').json() is None
        assert client.get('/api/persons').json() == []
        first = client.put('/api/profile', json={'name': '本人'}).json()
        for _ in range(3):
            saved = client.put('/api/profile', json={'name': '本人修改', 'interests': ['设计']}).json()
            assert saved['person_id'] == first['person_id']
        assert len(client.get('/api/persons').json()) == 1
    with TestClient(create_app(path)) as client:
        assert client.get('/api/profile').json() == saved


def test_existing_people_require_explicit_binding_and_remain_independent(tmp_path):
    """Input：同名旧记录及新增伙伴；Expected Output：先明确选主体，保存不增人且不改伙伴，不能换绑；验证目的为安全迁移旧库及主体独立。"""
    with TestClient(create_app(tmp_path / 'existing.sqlite3')) as client:
        a = client.post('/api/persons', json={'name': '同名', 'interests': ['艺术']}).json()
        b = client.post('/api/persons', json={'name': '同名', 'interests': ['咖啡']}).json()
        assert client.get('/api/profile').json() is None
        assert client.put('/api/profile', json={'name': '不能猜测'}).status_code == 409
        assert client.put('/api/profile/missing').status_code == 404
        assert client.put('/api/profile/' + a['person_id']).json() == a
        assert client.put('/api/profile/' + a['person_id']).json() == a
        assert client.put('/api/profile/' + b['person_id']).status_code == 409
        assert client.put('/api/profile', json={'name': '我'}).json()['person_id'] == a['person_id']
        assert client.get('/api/persons/' + b['person_id']).json() == b
        client.post('/api/persons', json={'name': '新伙伴'})
        assert client.get('/api/profile').json()['person_id'] == a['person_id']
        assert len(client.get('/api/persons').json()) == 3


def test_invalid_profile_does_not_create_or_overwrite(tmp_path):
    """Input：空姓名、外部 ID、错误 MBTI；Expected Output：422，原数据不变；测试目的为复用人物校验且错误不留下半成品。"""
    with TestClient(create_app(tmp_path / 'invalid.sqlite3')) as client:
        assert client.put('/api/profile', json={'name': ' '}).status_code == 422
        assert client.get('/api/persons').json() == []
        saved = client.put('/api/profile', json={'name': '我'}).json()
        for data in ({'name': '改', 'person_id': 'forged'}, {'name': '改', 'mbti': 'XXXX'}):
            assert client.put('/api/profile', json=data).status_code == 422
            assert client.get('/api/profile').json() == saved
