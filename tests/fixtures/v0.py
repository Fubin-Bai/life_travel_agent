"""保留测试导入兼容；固定数据与开发 CLI 共用唯一来源。"""

from life_journey.sample_data import load_persons, load_relationships, load_trips

__all__ = ["load_persons", "load_relationships", "load_trips"]
