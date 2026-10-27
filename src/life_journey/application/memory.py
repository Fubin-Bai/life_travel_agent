"""SQLite向量存储、保守写入和先隔离后检索；不保存原始聊天。"""
import json
import math
import re
from datetime import datetime,timezone
from uuid import uuid4
from life_journey.schemas.memory import Memory, MemoryCandidate, RetrievedMemory, MEMORY_TOP_K
from life_journey.storage import connect
from life_journey.llm.embedding import validate_vectors
from .planning_observation import family_names

MAX_SCOPED_MEMORIES=200
SOURCE_WEIGHT={'confirmed':0.24,'explicit':0.14,'inferred':0.0}
TEMPORARY=r'今天|这次|本次|今晚|这一顿|这顿|天气|临时|现在很累|今天累'
STABLE=r'一直|长期|以后|今后|通常|每次|最近更喜欢|平时|我们一起旅行时|确认长期'

def initialize_memory(db):
    """仅新增独立表和索引，不修改原人物/旅行记录。"""
    db.executescript("""CREATE TABLE IF NOT EXISTS memories (
        id TEXT PRIMARY KEY, person_id TEXT NOT NULL, memory_type TEXT NOT NULL,
        active INTEGER NOT NULL, updated_at TEXT NOT NULL, data TEXT NOT NULL, vector TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS memory_scope ON memories(person_id,active,updated_at);""")

def extract_candidates(feedback,context,person_id, *, memory_type='person',relationship_id=None,source_reference='feedback'):
    """有限显式语句抽取：逐句过滤临时信息，不让一次偏好自动变长期。"""
    result=[]
    for clause in re.split(r'[。；;！!\n]',feedback):
        clause=clause.strip()
        if not clause or re.search(TEMPORARY,clause) or not re.search(STABLE,clause):continue
        if not re.search(r'喜欢|偏好|习惯|避免|更希望|倾向',clause):continue
        tags={}
        families=family_names(clause)
        if len(families)==1:
            tags['activity:'+next(iter(families))]='avoid' if re.search(r'不喜欢|不爱|讨厌|避免|不再喜欢',clause) else 'prefer'
        negated_pace=bool(re.search(r'不喜欢|不爱|避免|不再喜欢',clause))
        if not negated_pace and re.search(r'紧凑|快节奏|充实',clause):tags['preferred_pace']='fast'
        elif not negated_pace and re.search(r'慢节奏|悠闲|留白',clause):tags['preferred_pace']='slow'
        elif not negated_pace and '适中' in clause:tags['preferred_pace']='moderate'
        # 非pace的明确长期喜好原句保留，不推断gender/MBTI/关系标签。
        if not tags and not re.search(r'喜欢|不喜欢|偏好|习惯|避免',clause):continue
        if len(clause)>500:continue
        ids=[person_id] if memory_type=='person' else sorted(context.trip.participant_ids)
        result.append(MemoryCandidate(memory_type=memory_type,person_id=person_id,participant_ids=ids,
            relationship_id=relationship_id,trip_id=context.trip.trip_id if memory_type=='trip' else None,
            destination=context.trip.destination if memory_type=='trip' else None,content=clause,structured_tags=tags,
            source_reference=source_reference,stable=True))
    return result[:8]

def same_scope(a,b):
    """人物、组合和原旅行分别判重，绝不跨scope覆盖。"""
    return (a.memory_type,a.person_id,sorted(a.participant_ids),a.relationship_id,a.trip_id)==(b.memory_type,b.person_id,sorted(b.participant_ids),b.relationship_id,b.trip_id)

class MemoryStore:
    """SQLite保存JSON向量，应用层余弦适合本地小规模；不是近似大规模向量索引。"""
    def __init__(self,path,embedding):self.path=path;self.embedding=embedding
    def write(self,candidates):
        """先过滤，向量成功后同事务判重/覆盖；失败不留下半条记忆。"""
        accepted=[]
        for candidate in candidates:
            c=MemoryCandidate.model_validate_json(candidate.model_dump_json())
            if not c.stable or re.search(TEMPORARY,c.content) or (c.source_type=='inferred' and c.observation_count<2):continue
            accepted.append(c)
        if len(accepted)>8:raise ValueError('单次最多8条候选记忆')
        if not accepted:return []
        vectors=validate_vectors(self.embedding.embed([c.content for c in accepted]),len(accepted))
        now=datetime.now(timezone.utc);stored=[]
        with connect(self.path) as db:
            initialize_memory(db)
            for c,vector in zip(accepted,vectors):
                old=[Memory.model_validate_json(row[0]) for row in db.execute('SELECT data FROM memories WHERE person_id=? AND active=1',(c.person_id,))]
                scoped=[m for m in old if same_scope(m,c)]
                duplicate=next((m for m in scoped if re.sub(r'\s','',m.content)==re.sub(r'\s','',c.content)),None)
                if duplicate:
                    duplicate.updated_at=now
                    if SOURCE_WEIGHT[c.source_type]>SOURCE_WEIGHT[duplicate.source_type]:
                        duplicate.source_type=c.source_type;duplicate.confidence=c.confidence;duplicate.source_reference=c.source_reference
                    if c.source_type=='confirmed':duplicate.last_confirmed_at=now
                    duplicate.embedding_model=self.embedding.model;duplicate.embedding_dimensions=len(vector)
                    db.execute('UPDATE memories SET updated_at=?,data=?,vector=? WHERE id=?',(now.isoformat(),duplicate.model_dump_json(),json.dumps(vector),duplicate.memory_id));stored.append(duplicate);continue
                mid='memory_'+str(uuid4())
                memory=Memory(**c.model_dump(),memory_id=mid,created_at=now,updated_at=now,last_confirmed_at=now if c.source_type=='confirmed' else None,
                    embedding_model=self.embedding.model,embedding_dimensions=len(vector),vector_id=mid)
                for m in scoped:
                    conflict=any(k in m.structured_tags and m.structured_tags[k]!=v for k,v in c.structured_tags.items())
                    if conflict and c.source_type!='inferred':
                        m.active=False;m.superseded_by=mid;m.updated_at=now
                        db.execute('UPDATE memories SET active=0,updated_at=?,data=? WHERE id=?',(now.isoformat(),m.model_dump_json(),m.memory_id))
                db.execute('INSERT INTO memories VALUES (?,?,?,?,?,?,?)',(mid,c.person_id,c.memory_type,1,now.isoformat(),memory.model_dump_json(),json.dumps(vector)))
                stored.append(memory)
        return stored
    def confirm(self,memory_ids,context):
        """只有明确提交ID才升级confirmed，不因重复检索或使用而确认。"""
        if len(memory_ids)>10:raise ValueError('单次最多确认10条')
        now=datetime.now(timezone.utc);confirmed=[]
        with connect(self.path) as db:
            initialize_memory(db)
            for mid in dict.fromkeys(memory_ids):
                row=db.execute('SELECT data FROM memories WHERE id=? AND active=1',(mid,)).fetchone()
                if row is None:raise ValueError('记忆不存在或不在本次范围')
                m=Memory.model_validate_json(row[0])
                rels={r.relationship_id:{r.person_a_id,r.person_b_id} for r in context.relationships}
                if m.person_id not in context.trip.participant_ids or not set(m.participant_ids)<=set(context.trip.participant_ids):raise ValueError('记忆不存在或不在本次范围')
                if m.memory_type=='relationship' and rels.get(m.relationship_id)!=set(m.participant_ids):raise ValueError('记忆不存在或不在本次范围')
                if m.memory_type=='trip' and (set(m.participant_ids)!=set(context.trip.participant_ids) or m.destination!=context.trip.destination):raise ValueError('记忆不存在或不在本次范围')
                m.source_type='confirmed';m.last_confirmed_at=now;m.updated_at=now
                db.execute('UPDATE memories SET updated_at=?,data=? WHERE id=?',(now.isoformat(),m.model_dump_json(),m.memory_id))
                confirmed.append(mid)
        return confirmed

    def retrieve(self,context,top_k=MEMORY_TOP_K):
        """SQL先按参与者隔离，组合/目的地再过滤，最后才计算语义相似度。"""
        if not 1<=top_k<=10:raise ValueError('TopK必须在1至10')
        ids=context.trip.participant_ids
        relationships={r.relationship_id:{r.person_a_id,r.person_b_id} for r in context.relationships}
        query=json.dumps({'destination':context.trip.destination,'context':context.trip.context.model_dump(),
            'participants':[{'id':p.person_id,'interests':p.interests,'food':p.food_preferences} for p in context.participants]},ensure_ascii=False)
        with connect(self.path) as db:
            initialize_memory(db)
            rows=db.execute('SELECT data,vector FROM memories WHERE active=1 AND person_id IN ('+','.join('?' for _ in ids)+') ORDER BY updated_at DESC,id',ids).fetchall()
        scoped=[]
        for raw,vector in rows:
            m=Memory.model_validate_json(raw)
            if m.memory_type=='relationship' and (m.relationship_id not in relationships or set(m.participant_ids)!=relationships[m.relationship_id] or not set(m.participant_ids)<=set(ids)):continue
            if m.memory_type=='trip' and (set(m.participant_ids)!=set(ids) or m.destination!=context.trip.destination):continue
            if m.embedding_model!=self.embedding.model:continue
            # 当前明确pace冲突的历史记录不入Prompt；未指定时才可作软参考。
            if context.trip.context.preferred_pace and m.structured_tags.get('preferred_pace') not in (None,context.trip.context.preferred_pace):continue
            scoped.append((m,json.loads(vector)))
            if len(scoped)>=MAX_SCOPED_MEMORIES:break
        if not scoped:return query,[]
        q=validate_vectors(self.embedding.embed([query]),1)[0]
        now=datetime.now(timezone.utc);ranked=[]
        for m,v in scoped:
            if len(v)!=len(q):continue
            v=validate_vectors([v],1)[0]
            similarity=sum(a*b for a,b in zip(q,v))/math.sqrt(sum(a*a for a in q)*sum(b*b for b in v))
            if similarity<0.15:continue
            age=max(0,(now-m.updated_at).total_seconds()/86400)
            recency=1/(1+age/90)
            score=0.6*similarity+SOURCE_WEIGHT[m.source_type]+0.08*m.confidence+0.05*recency+(0.03 if m.memory_type=='relationship' else 0)
            ranked.append(RetrievedMemory(memory_id=m.memory_id,memory_type=m.memory_type,person_id=m.person_id,content=m.content,
                structured_tags=m.structured_tags,source_type=m.source_type,confidence=m.confidence,source_reference=m.source_reference,score=score,similarity=similarity))
        return query,sorted(ranked,key=lambda x:(-x.score,x.memory_id))[:top_k]
