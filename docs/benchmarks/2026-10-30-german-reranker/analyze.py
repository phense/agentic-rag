import json,math,statistics,sys
from pathlib import Path
out=Path(sys.argv[1])
j=json.loads((out/'results.json').read_text());rows=j['rows']
assert len(rows)==96*len(j['evaluated_models'])
summary={}
for model in j['evaluated_models']:
 summary[model]={}
 for language in ['de','en']:
  raw=[r for r in rows if r['model']==model and r['language']==language and r['mode']=='semantic30s']
  first=[r for r in raw if r['permutation']==0];assert len(first)==16 and len(raw)==32
  second={r['case_id']:r for r in raw if r['permutation']==1}
  summary[model][language]=dict(questions=16,families=8,expected_source_occurrences=17,
   top1=sum(r['metrics']['top1'] for r in first),all_sources3=sum(r['metrics']['all_sources3'] for r in first),
   recall3=statistics.mean(r['metrics']['recall3'] for r in first),ndcg3=statistics.mean(r['metrics']['ndcg3'] for r in first),
   failures=[dict(case=r['case_id'],first=r['order'][0],expected=r['expected'],ranked=r['order']) for r in first if not r['metrics']['top1']],
   second_top1=sum(r['metrics']['top1'] for r in second.values()),position_top1_changes=sum(r['order'][0]!=second[r['case_id']]['order'][0] for r in first),
   raw_scoring_errors=sum(r['error'] is not None for r in raw),
   production_range_incompatible=sum(not r['production_score_range_compatible'] for r in raw),
   raw_p50_ms=statistics.median(r['elapsed_ms'] for r in raw),raw_p95_ms=sorted(r['elapsed_ms'] for r in raw)[math.ceil(.95*len(raw))-1])
  live=[r for r in rows if r['model']==model and r['mode']=='adapter1.5s' and r['language']==language];assert len(live)==16
  summary[model][language]['adapter']=dict(observations=16,top1=sum(r['metrics']['top1'] for r in live),all_sources3=sum(r['metrics']['all_sources3'] for r in live),outcomes={o:sum(r['diagnostics']['outcome']==o for r in live) for o in set(r['diagnostics']['outcome'] for r in live)},p50_ms=statistics.median(r['elapsed_ms'] for r in live),p95_ms=sorted(r['elapsed_ms'] for r in live)[15])
 de,en=summary[model]['de'],summary[model]['en']
 critical=[r['case_id'] for r in rows if r['model']==model and r['mode']=='semantic30s' and r['language']=='de' and r['permutation']==0 and r['family'] in ('access-negation','subject-object') and not r['metrics']['top1']]
 summary[model]['decision']=dict(two_or_more_DE_top1_misses=16-de['top1']>=2,critical_DE_top1_misses=critical,DE_trails_EN_more_than_10pp=(en['top1']-de['top1'])/16>.1)
 summary[model]['decision']['reject_blanket_german_recommendation']=summary[model]['decision']['two_or_more_DE_top1_misses'] or bool(critical) or summary[model]['decision']['DE_trails_EN_more_than_10pp']
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
