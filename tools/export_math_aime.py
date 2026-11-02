"""Export AIME25 and MATH-500 measurement metadata; no API calls or task text."""
from __future__ import annotations
import argparse,bisect,collections,csv,hashlib,json
from pathlib import Path

HARNESSES=['claude','codex','dsh','pi','zcode']
TOKENS=['prompt_tokens','completion_tokens','total_tokens','prompt_cache_hit_tokens','prompt_cache_miss_tokens']
COHORTS={
 'aime-2025':('aime25-agentplan2-dsv41flash-economy-t0-thinkmax-r1-native-v1','dsv41flash-economy-t0-thinkmax-native-agentplan2-r1-v1',30),
 'math-500':('math500-subset100-s20261102-agentplan2-dsv41flash-economy-t0-thinkmax-r1-native-v1','dsv41flash-economy-t0-thinkmax-native-stratified100-s20261102-agentplan2-r1-v1',100)}

def sha(path):
 with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def dump(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def tables(base,name,rows):
 (base/(name+'.jsonl')).write_text(''.join(json.dumps(r,ensure_ascii=False,allow_nan=False)+'\n' for r in rows))
 keys=list(dict.fromkeys(k for r in rows for k in r))
 with (base/(name+'.csv')).open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=keys,lineterminator='\n');w.writeheader()
  for r in rows:w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in r.items()})
class Source:
 def __init__(self,root):self.root=root;self.hashes={}
 def read(self,p):self.hashes[str(p.relative_to(self.root))]=sha(p);return json.loads(p.read_text())
 def lines(self,p):self.hashes[str(p.relative_to(self.root))]=sha(p);return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]

def selected_attempt(source,p,row):
 value=(row.get('recovery') or {}).get('source_attempt') or row.get('attempt')
 if value:
  a=Path(value);return a if a.is_absolute() else source.root/a
 return sorted((p.parent/'attempts').glob('[0-9]*'))[-1]

def aggregate(requests):
 return {**{k:sum(r[k] or 0 for r in requests) for k in TOKENS},'accounting_complete':bool(requests) and all(r['accounting_complete'] for r in requests),'model_requests':len(requests),'accounting_gaps':sum(not r['finish_record_present'] for r in requests),'usage_missing_requests':sum(not r['usage_present'] for r in requests)}

def export(root,out,benchmark):
 prefix,release,n=COHORTS[benchmark];base=out/'benchmarks'/benchmark/release
 if base.exists():raise ValueError('Refuse to overwrite release: '+str(base))
 src=Source(root);samples=[];requests=[];attempts=[];experiments={};selected=[]
 if benchmark=='math-500':
  manifest=src.read(root/'runs'/prefix/'selection.json')
  selected=[{k:r[k] for k in ['sample_id','unique_id','source_row','subject','level','stratum','split','problem_sha256','execution_order']} for r in manifest['selection']]
  sampling=manifest['sampling']
 else:
  selected=src.read(root/'runs'/(prefix+'-claude')/'selection.json');sampling={'method':'all_30_AIME2025_questions','size':30}
 selection_by_id={r['sample_id']:r for r in selected}
 for h in HARNESSES:
  run=root/'runs'/(prefix+'-'+h);exp=src.read(run/'experiment.json')
  fields=['model','temperature','thinking','reasoning_effort','max_output_tokens','timeout','n_repeats','tools','compression_policy','cli_version','harness','dataset_sha256']
  experiments[h]={k:exp[k] for k in fields if k in exp}
  events=src.lines(run/'requests.jsonl');starts={r['request_id']:r for r in events if r['event']=='start'};finishes={r['request_id']:r for r in events if r['event']=='finish'}
  foldermap={p.parent.name:p for p in (run/'samples').glob('*/result.json')}
  for sid,p in sorted(foldermap.items()):
   row=src.read(p);apaths=sorted((p.parent/'attempts').glob('[0-9]*'));atimes=[int(a.name)/1e9 for a in apaths]
   chosen=selected_attempt(src,p,row).name;group=[]
   for rid in sorted(starts.keys()|finishes.keys()):
    start=starts.get(rid,{});finish=finishes.get(rid,{})
    if start.get('sample_id',finish.get('sample_id'))!=sid:continue
    usage=finish.get('usage') or {};present=all(isinstance(usage.get(k),(int,float)) for k in ['prompt_tokens','completion_tokens','total_tokens'])
    i=bisect.bisect_right(atimes,start.get('time',0))-1;aid=apaths[i].name if i>=0 else None
    q={'benchmark':benchmark,'task_id':sid,'harness':h,'request_id':rid,'attempt_id':aid,'selected_attempt':aid==chosen,'started_at':start.get('time'),'finished_at':finish.get('time'),'start_record_present':bool(start),'finish_record_present':bool(finish),'http_status':finish.get('http_status'),'finish_reason':finish.get('finish_reason'),'error_type':finish.get('error_type'),'model':exp['model'],'temperature':start.get('temperature',exp['temperature']),'usage_present':present,'accounting_complete':bool(start) and bool(finish) and present,**{k:usage.get(k) for k in TOKENS},'reasoning_tokens':(usage.get('completion_tokens_details') or {}).get('reasoning_tokens')}
    group.append(q)
   requests.extend(group);allcost=aggregate(group);finalcost=aggregate([q for q in group if q['selected_attempt']])
   for a in apaths:
    aa=aggregate([q for q in group if q['attempt_id']==a.name]);execution=a/'execution.json';rc=src.read(execution).get('returncode') if execution.exists() else None
    attempts.append({'benchmark':benchmark,'task_id':sid,'harness':h,'attempt_id':a.name,'selected_for_score':a.name==chosen,'native_returncode':rc,**aa})
   score=row.get('score');sel=selection_by_id[sid]
   public={'benchmark':benchmark,'task_id':sid,'harness':h,'status':row['status'],'score':score,'success':score,'label':'correct' if score==1 else 'incorrect' if score==0 else 'unscored',**allcost,'token':allcost['total_tokens'],'final_attempt_id':chosen,'final_attempt_token':finalcost['total_tokens'],'other_attempt_tokens':allcost['total_tokens']-finalcost['total_tokens'],'final_attempt_accounting_complete':finalcost['accounting_complete'],'native_returncode':row.get('native_returncode'),'answer_source':row.get('answer_source'),'restored_from_saved_native_attempt':bool(row.get('recovery')),'output_truncated':row.get('output_truncated',False),'compression_policy':'native_defaults_no_acon','native_compaction_count':len(row.get('native_compactions') or []),'router_eligible_label':score in [0,1],'router_eligible_complete_tokens':score in [0,1] and allcost['accounting_complete'],'source_result_sha256':src.hashes[str(p.relative_to(root))]}
   for k in ['source_row','subject','level','stratum','problem_sha256']:
    if k in sel:public[k]=sel[k]
   samples.append(public)
 if len(samples)!=n*5:raise ValueError('Unexpected cohort size')
 summary=[]
 for h in HARNESSES:
  rows=[r for r in samples if r['harness']==h];done=[r for r in rows if r['score'] is not None]
  summary.append({'harness':h,'selected':n,'scored':len(done),'correct':sum(r['score'] for r in done),'accuracy':sum(r['score'] for r in done)/len(done),'model_requests':sum(r['model_requests'] for r in rows),'samples_with_complete_tokens':sum(r['accounting_complete'] for r in rows),**{k:sum(r[k] for r in rows) for k in TOKENS},'selected_attempt_tokens':sum(r['final_attempt_token'] for r in rows)})
 matrix=[];index={(r['task_id'],r['harness']):r for r in samples}
 for sid in sorted(selection_by_id):
  item={'task_id':sid}
  for h in HARNESSES:
   r=index[sid,h]
   for k in ['score','success','token','final_attempt_token','accounting_complete']:item[h+'_'+k]=r[k]
  matrix.append(item)
 base.mkdir(parents=True);tables(base,'samples',samples);tables(base,'requests',requests);tables(base,'attempts',attempts);tables(base,'task-matrix',matrix)
 dump(base/'summary.json',summary);dump(base/'selection.json',selected);dump(base/'provenance/source-files.json',src.hashes)
 dump(base/'experiment.json',{'benchmark':benchmark,'release_id':release,'harnesses':HARNESSES,'experiments':experiments,'sampling':sampling,'track':'native_math_no_tools','provider':'Ark Agent Plan 2','tools':False,'compression':'native_defaults_no_acon','scoring':'last boxed answer + math-verify 0.9.0 mathematical equivalence' if benchmark=='math-500' else 'recorded AIME integer grading, no model judge','token_scope':'all recorded attempts; final_attempt follows chosen score source, including explicit recovery.source_attempt; prompt includes cache hits; reasoning is already included in completion; missing usage stays unknown','body_policy':'No task text, reference answer, model response, reasoning transcript, credentials or raw settings exported','new_model_requests':0})
 text=f'# {"AIME 2025" if benchmark=="aime-2025" else "MATH-500 分层100题"}：五组原生 harness\n\n{n}题 × 5组，全部评分完成。DeepSeek V4.1 Flash Economy，Agent Plan 2，temperature=0、thinking enabled、reasoning effort=max，每请求最多131072输出 tokens，每题 CLI 超时1800秒。无工具，各 harness 原生默认上下文管理，没有统一压缩阈值。\n\n'
 text+='| Harness | 正确 / 已评分 | 正确率 | 所有尝试已观测 token | 采纳 attempt token | 用量完整题数 |\n|---|---:|---:|---:|---:|---:|\n'
 for s in summary:text+=f"| {s['harness']} | {s['correct']}/{s['scored']} | {s['accuracy']:.2%} | {s['total_tokens']:,} | {s['selected_attempt_tokens']:,} | {s['samples_with_complete_tokens']}/{n} |\n"
 text+='\n输入 token 已包含缓存命中，不重复相加；completion 已包含 reasoning，不重复加。总量包含失败和重试的已记录用量；缺 usage 不推算，因此总量可能是已知下界。final_attempt 指最终评分实际采用的 attempt，按恢复指针定位，未必是时间最新的一次。未将套餐消耗换算成实际账单。\n\n'
 if benchmark=='aime-2025':text+='DSH 早期非流式传输超时产生多次重试；后续流式适配修复后的原生输出与历史账本保留。两条结果从已有原生 attempt 对齐恢复，均不冒充新调用。ZCode 有1次 HTTP429 未返回 usage，明确保留缺失标记。DSML-only 原生最终文本按无可解析答案记0，不筛选掉错误结果。\n'
 else:text+='从 MATH-500 按 subject×level 比例分层抽100题，seed=20261102，覆盖35层，每层至少1题。原始题集附带80 train /20 validation 的历史划分；此处发布的是原评测采样记录，后续 router 可另冻结新的 train/dev/test manifest。最后一个完整 boxed 答案用 math-verify 0.9.0 做等价判定。8题含原始 Asymptote 文本，没有渲染图片。\n'
 text+='\n`samples` 为逐题分数和 token，`requests` 为全部原始请求的数值账本，`attempts` 为全部尝试及被采纳标记，`task-matrix` 为同题五路矩阵。每表均有 CSV/JSONL。`selection.json` 不含题目和答案；`experiment.json` 保存白名单参数及 harness 版本；来源哈希在 `provenance/source-files.json`。\n\n没有新增 API 调用，没有发布题目正文、标准答案、模型输出、原始失败轨迹或凭证。\n'
 (base/'README.md').write_text(text)
 for relative,expected in src.hashes.items():
  if sha(root/relative)!=expected:raise ValueError('Source changed during export')
 (base/'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.relative_to(base)}\n' for p in sorted(base.rglob('*')) if p.is_file() and p.name!='SHA256SUMS'))
 return {'benchmark':benchmark,'release_id':release,'relative_path':f'{benchmark}/{release}','model':'deepseek-v4.1-flash-economy','tasks':n,'harnesses':HARNESSES,'rows':n*5,'scored_rows':n*5,'status':'finished_with_accounting_markers','track':'native_math_no_tools','primary_metric':'accuracy'}

def main():
 p=argparse.ArgumentParser();p.add_argument('--source-root',type=Path,required=True);p.add_argument('--output-root',type=Path,default=Path(__file__).resolve().parents[1]);args=p.parse_args()
 index_path=args.output_root/'benchmarks/index.json';index=json.loads(index_path.read_text())
 for benchmark in COHORTS:
  record=export(args.source_root.resolve(),args.output_root.resolve(),benchmark);index.append(record);print(record['relative_path'])
 dump(index_path,index)
if __name__=='__main__':main()
