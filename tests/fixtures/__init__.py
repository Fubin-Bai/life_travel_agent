"""导出固定 V0 测试数据，每次加载返回独立模型。"""

from .v0 import load_persons, load_relationships, load_trips

__all__ = ["load_persons", "load_relationships", "load_trips"]
