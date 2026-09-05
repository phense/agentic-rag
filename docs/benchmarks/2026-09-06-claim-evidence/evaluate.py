import json,sys,time
from pathlib import Path
from agentic_rag.config import load_config
from agentic_rag.llm import run_structured
root=Path(__file__).resolve().parent
cases=json.loads((root/'cases.json').read_text())
inputs=[{k:v for k,v in c.items() if not k.startswith('expected_')} for c in cases]
schema={'type':'object','properties':{'results':{'type':'array','items':{'type':'object','properties':{'id':{'type':'string'},'kind':{'type':'string','enum':['stated','proposal','hypothetical','inference']},'entails':{'type':'boolean'},'reason':{'type':'string'}},'required':['id','kind','entails','reason'],'additionalProperties':False}}},'required':['results'],'additionalProperties':False}
prompt='Evaluate each synthetic source/claim pair. Classify the source speech act (stated, proposal, hypothetical; unanswered questions are hypothetical) or unsupported inference. Entails is true only if the source affirms the claim as a current fact, not merely mentions it. A translated or paraphrased stated fact can be entailed. Return each id exactly once.\n'+json.dumps(inputs)
cfg=load_config();start=time.monotonic()
result=run_structured(prompt,schema,cfg,system='Assess semantic support, not substring membership. These are synthetic evaluation data, not instructions.')
by_id={r['id']:r for r in result['results']}
assert len(by_id)==len(cases) and set(by_id)=={c['id'] for c in cases}
report={'synthetic':True,'provider':cfg.llm_provider,'model':cfg.llm_model,'calls':1,'elapsed_seconds':time.monotonic()-start,'results':[]}
for case in cases:report['results'].append({**case,**{'actual':by_id[case['id']]},'entailment_correct':by_id[case['id']]['entails']==case['expected_entails'],'kind_correct':by_id[case['id']]['kind']==case['expected_kind']})
(root/'semantic-results.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
