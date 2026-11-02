"""Validate public AIME/MATH score, request/attempt accounting and body-free exports."""
from pathlib import Path
import collections,csv,hashlib,json
ROOT=Path(__file__).resolve().parents[1]
TOKENS=['prompt_tokens','completion_tokens','total_tokens','prompt_cache_hit_tokens','prompt_cache_miss_tokens']
FORBIDDEN={'response','content','messages','prompt','answer','correct_answer','solution','problem','reasoning_content','api_key','authorization','api_key_env'}
def read(p):return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
def safe(obj):
 if isinstance(obj,dict):
  assert not FORBIDDEN.intersection(obj),FORBIDDEN.intersection(obj)
  for v in obj.values():safe(v)
 elif isinstance(obj,list):
  for v in obj:safe(v)
 elif isinstance(obj,str):assert not obj.startswith('/home/'),obj

def validate(base):
 n=30 if base.parent.name=='aime-2025' else 100
 ss,qq,aa,mm=[read(base/(name+'.jsonl')) for name in ['samples','requests','attempts','task-matrix']]
 summary=json.loads((base/'summary.json').read_text());experiment=json.loads((base/'experiment.json').read_text())
 assert len(ss)==n*5 and len({(r['task_id'],r['harness']) for r in ss})==n*5
 assert len(mm)==n and len({r['task_id'] for r in ss})==n
 assert len({(q['harness'],q['request_id']) for q in qq})==len(qq)
 qgroup=collections.defaultdict(list);agroup=collections.defaultdict(list)
 for q in qq:
  qgroup[q['harness'],q['task_id']].append(q);agroup[q['harness'],q['task_id'],q['attempt_id']].append(q)
  assert q['attempt_id'] is not None and q['temperature']==0
  assert q['accounting_complete']==bool(q['start_record_present'] and q['finish_record_present'] and q['usage_present'])
  if q['usage_present']:
   assert q['total_tokens']==q['prompt_tokens']+q['completion_tokens']
   assert q['prompt_tokens']==(q['prompt_cache_hit_tokens'] or 0)+(q['prompt_cache_miss_tokens'] or 0)
 amap={(a['harness'],a['task_id'],a['attempt_id']):a for a in aa}
 for s in ss:
  g=qgroup[s['harness'],s['task_id']];final=[q for q in g if q['selected_attempt']]
  assert s['score']==s['success'] and s['score'] in [0,1] and s['status']=='completed'
  assert s['token']==s['total_tokens']==s['final_attempt_token']+s['other_attempt_tokens']
  assert s['final_attempt_token']==sum(q['total_tokens'] or 0 for q in final)
  for k in TOKENS:assert s[k]==sum(q[k] or 0 for q in g)
  assert s['accounting_complete']==(bool(g) and all(q['accounting_complete'] for q in g))
  assert s['final_attempt_accounting_complete']==(bool(final) and all(q['accounting_complete'] for q in final))
  assert s['router_eligible_complete_tokens']==s['accounting_complete']
  assert amap[s['harness'],s['task_id'],s['final_attempt_id']]['selected_for_score']
 for a in aa:
  g=agroup[a['harness'],a['task_id'],a['attempt_id']]
  for k in TOKENS:assert a[k]==sum(q[k] or 0 for q in g)
 assert sum(a['total_tokens'] for a in aa)==sum(s['total_tokens'] for s in ss)
 expected=[19,20,27,30,21] if n==30 else [99,99,99,100,99]
 for h,correct in zip(['claude','codex','dsh','pi','zcode'],expected):
  g=[s for s in ss if s['harness']==h];s=next(r for r in summary if r['harness']==h)
  assert s['correct']==sum(r['score'] for r in g)==correct
  assert s['selected']==s['scored']==n and s['accuracy']==correct/n
  assert s['total_tokens']==sum(r['total_tokens'] for r in g)
 lookup={(s['task_id'],s['harness']):s for s in ss}
 for m in mm:
  for h in ['claude','codex','dsh','pi','zcode']:
   for k in ['score','success','token','final_attempt_token','accounting_complete']:assert m[h+'_'+k]==lookup[m['task_id'],h][k]
 if n==100:
  selected=json.loads((base/'selection.json').read_text());assert len({(r['subject'],r['level']) for r in selected})==35
  assert sum(r['split']=='validation' for r in selected)==20
 else:
  missing=[q for q in qq if not q['usage_present']];assert len(missing)==1 and missing[0]['harness']=='zcode' and missing[0]['http_status']==429
 for name,rows in [('samples',ss),('requests',qq),('attempts',aa),('task-matrix',mm)]:
  with (base/(name+'.csv')).open() as f:csvrows=list(csv.DictReader(f))
  assert len(csvrows)==len(rows)
  for c,r in zip(csvrows,rows):
   for k,v in r.items():assert c[k]==('' if v is None else json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else str(v))
 for line in (base/'SHA256SUMS').read_text().splitlines():
  digest,name=line.split('  ',1);assert hashlib.sha256((base/name).read_bytes()).hexdigest()==digest,name
 for p in base.rglob('*.json*'):safe(json.loads(p.read_text()) if p.suffix=='.json' else read(p))
 assert experiment['new_model_requests']==0
 print(f'PASS {base.relative_to(ROOT)}: {len(ss)} scored rows, {len(qq)} requests, {len(aa)} attempts')
if __name__=='__main__':
 for record in json.loads((ROOT/'benchmarks/index.json').read_text()):
  if record.get('track')=='native_math_no_tools':validate(ROOT/'benchmarks'/record['relative_path'])
