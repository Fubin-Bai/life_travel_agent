"""可替换Embedding接口；生产使用显式配置的兼容HTTP服务，测试注入fake。"""
from typing import Protocol
import math
import os
import httpx
from .base import LLMConfigurationError, LLMRequestError, LLMResponseError

class EmbeddingProvider(Protocol):
    """模型标识必须包含版本，避免混用不同向量空间。"""
    model: str
    def embed(self,texts:list[str])->list[list[float]]: ...

def validate_vectors(vectors, count):
    """拒绝非有限、零向量、维数不一致；不把坏向量存入SQLite。"""
    if not isinstance(vectors,list) or len(vectors)!=count:raise LLMResponseError('Embedding返回数量无效')
    size=None
    for vector in vectors:
        if not isinstance(vector,list) or not vector or any(type(x) not in (float,int) or not math.isfinite(x) for x in vector):raise LLMResponseError('Embedding向量格式无效')
        if not any(vector) or (size is not None and size!=len(vector)):raise LLMResponseError('Embedding向量维数或范数无效')
        size=len(vector)
    return [[float(x) for x in v] for v in vectors]

class CompatibleEmbeddingProvider:
    """无默认服务商或Key复用；显式端点、不跳转、不重试、不打印请求。"""
    def __init__(self, *, transport=None):
        self.model=os.environ.get('LIFE_JOURNEY_EMBEDDING_MODEL','').strip()
        endpoint=os.environ.get('LIFE_JOURNEY_EMBEDDING_URL','').strip()
        key=os.environ.get('LIFE_JOURNEY_EMBEDDING_KEY','').strip()
        if not self.model or not endpoint or not key:raise LLMConfigurationError('memory模式需要配置独立Embedding URL、MODEL和KEY；不假设DeepSeek提供Embedding')
        if not key.isascii() or any(ord(c)<33 or ord(c)>126 for c in key):raise LLMConfigurationError('Embedding Key格式无效')
        try:url=httpx.URL(endpoint)
        except (httpx.InvalidURL,ValueError):raise LLMConfigurationError("Embedding端点格式无效") from None
        if url.scheme!='https' or url.username or url.password or url.query or not url.host:raise LLMConfigurationError('Embedding端点必须为无凭据参数的HTTPS完整URL')
        self.endpoint=endpoint
        self._client=httpx.Client(timeout=15,follow_redirects=False,transport=transport,headers={'Authorization':'Bearer '+key})
    def close(self):
        """释放请求客户端。"""
        self._client.close()
    def embed(self,texts):
        """只返回验证后的向量，原始响应不进入Planner。"""
        if not texts or len(texts)>32:raise ValueError('Embedding批次必须为1至32')
        try:
            response=self._client.post(self.endpoint,json={'model':self.model,'input':texts})
            response.raise_for_status()
            data=response.json()['data']
            if not isinstance(data,list) or any(type(x['index']) is not int for x in data) or sorted(x['index'] for x in data)!=list(range(len(texts))):raise ValueError()
            vectors=[x['embedding'] for x in sorted(data,key=lambda x:x['index'])]
        except httpx.HTTPError:raise LLMRequestError('Embedding请求失败或超时；未重试') from None
        except (ValueError,TypeError,KeyError):raise LLMResponseError('Embedding响应格式无效') from None
        return validate_vectors(vectors,len(texts))
