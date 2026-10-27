"""普通 pytest 隔离开发机凭据/模式，并阻止真实 HTTP transport。"""
import httpx
import pytest


@pytest.fixture(autouse=True)
def offline_environment(monkeypatch):
    """Input：任意本机环境；Expected Output：默认V0、无真实Key、只允许fake transport；测试目的为配置好生产Key后pytest也不访问网络。"""
    # 测试不能在删除环境凭据后又从开发者.env重新加载真实Key。
    monkeypatch.setattr('life_journey.environment.load_project_env', lambda: None)
    monkeypatch.setenv('LIFE_JOURNEY_PLANNING_MODE','v0')
    monkeypatch.delenv('AMAP_WEB_SERVICE_KEY',raising=False)
    monkeypatch.delenv('DEEPSEEK_API_KEY',raising=False)
    for name in ('LIFE_JOURNEY_MAX_TOOL_CALLS','LIFE_JOURNEY_MAX_RUN_SECONDS','LIFE_JOURNEY_VALIDATION','LIFE_JOURNEY_EMBEDDING_URL','LIFE_JOURNEY_EMBEDDING_MODEL','LIFE_JOURNEY_EMBEDDING_KEY'):
        monkeypatch.delenv(name,raising=False)
    def blocked(*args,**kwargs):
        """真实同步 HTTP 一律失败；MockTransport/TestClient 不经过此方法。"""
        raise AssertionError('普通 pytest 禁止真实 HTTP；请注入 fake/mock transport')
    async def blocked_async(*args,**kwargs):
        """异步真实 HTTP 同样禁止，防止后续测试意外产生外部调用。"""
        raise AssertionError('普通 pytest 禁止真实 HTTP；请注入 fake/mock transport')
    monkeypatch.setattr(httpx.HTTPTransport,'handle_request',blocked)
    monkeypatch.setattr(httpx.AsyncHTTPTransport,'handle_async_request',blocked_async)

    try:
        import httpx2
    except ImportError:
        pass
    else:
        monkeypatch.setattr(httpx2.HTTPTransport,'handle_request',blocked)
        monkeypatch.setattr(httpx2.AsyncHTTPTransport,'handle_async_request',blocked_async)
