"""本地配置只使用临时虚构值，禁止读取开发者真实.env。"""
import os
import pytest
from life_journey import environment

# 保存函数引用，使默认离线夹具隔离真实.env后仍能测试加载器本身。
load_project_env = environment.load_project_env


def test_load_root_env_and_preserve_system(tmp_path, monkeypatch, capsys):
    """Input：临时根目录.env和既有系统变量；Expected Output：补齐缺值且系统值不变；测试优先级，目的为不覆盖DeepSeek凭据或输出Key。"""
    (tmp_path/'.env').write_text('ENV_TEST_EXISTING=file-value\nENV_TEST_NEW=mock-secret\nENV_TEST_EMPTY=file-value\n')
    monkeypatch.setattr(environment,'PROJECT_ROOT',tmp_path)
    monkeypatch.setenv('ENV_TEST_EXISTING','system-value')
    monkeypatch.setenv('ENV_TEST_EMPTY','')
    monkeypatch.delenv('ENV_TEST_NEW',raising=False)
    load_project_env()
    try:
        assert os.environ['ENV_TEST_EXISTING']=='system-value'
        assert os.environ['ENV_TEST_EMPTY']==''
        assert os.environ['ENV_TEST_NEW']=='mock-secret'
        assert capsys.readouterr().out==''
    finally:
        os.environ.pop('ENV_TEST_NEW',None)


def test_missing_env_and_unrelated_working_directory(tmp_path,monkeypatch):
    """Input：根目录无.env而工作目录存在.env；Expected Output：不加载别处配置且无异常；测试固定路径，目的为避免运行目录改变配置来源。"""
    root=tmp_path/'root';root.mkdir()
    elsewhere=tmp_path/'elsewhere';elsewhere.mkdir()
    (elsewhere/'.env').write_text('ENV_TEST_OTHER=should-not-load\n')
    monkeypatch.setattr(environment,'PROJECT_ROOT',root)
    monkeypatch.chdir(elsewhere)
    monkeypatch.delenv('ENV_TEST_OTHER',raising=False)
    load_project_env()
    assert 'ENV_TEST_OTHER' not in os.environ


@pytest.mark.parametrize('entry',['api','cli','smoke'])
def test_entry_loads_configuration(entry,tmp_path,monkeypatch):
    """Input：API工厂/CLI帮助/smoke帮助入口；Expected Output：各调用一次统一加载器且无网络；测试入口接线，目的为三种启动方式行为一致。"""
    calls=[]
    monkeypatch.setattr(environment,'load_project_env',lambda:calls.append(True))
    if entry=='api':
        from life_journey.api import create_app
        calls.clear()
        create_app(tmp_path/'test.sqlite3')
    else:
        if entry=='cli':
            from life_journey.cli import main
        else:
            from life_journey.tools.smoke import main
        with pytest.raises(SystemExit) as exc:main(['--help'])
        assert exc.value.code==0
    assert calls==[True]
