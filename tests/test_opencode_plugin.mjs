import test from 'node:test';
import assert from 'node:assert/strict';
import { createPlugin, projectMessages } from '../agentic_rag/integrations/opencode/plugin.mjs';

const messages = [
 {info:{id:'msg_1',role:'user'},parts:[{type:'text',text:'actual user'},{type:'text',text:'injected',synthetic:true}]},
 {info:{id:'msg_2',role:'assistant',time:{completed:1}},parts:[{type:'reasoning',text:'private thoughts'},{type:'text',text:'actual answer'},{type:'tool',tool:'bash',state:{output:'private result',input:{command:'private command'}}}]},
 {info:{id:'msg_3',role:'assistant'},parts:[{type:'text',text:'unfinished'}]},
 {info:{id:'msg_4',role:'assistant',summary:true,time:{completed:1}},parts:[{type:'text',text:'summary not mined'}]},
];
function fixture(parent=false) {
 const calls=[];
 const client={session:{get:async()=>({data:{id:'ses_one',parentID:parent?'ses_parent':undefined}}),messages:async()=>({data:messages.filter(m=>!m.info.summary)})}};
 return {calls,client,invoke:async(event,payload)=>{calls.push({event,payload});return {ok:true,context:'fixture context',checkpoint_id:'fixture-checkpoint'};}};
}
test('projection omits reasoning, arguments, outputs, synthetic and partial messages',()=>{
 const value=projectMessages(messages);assert.equal(value.length,2);
 assert.deepEqual(value[1],{id:'msg_2',role:'assistant',text:'actual answer',tools:['bash']});
 assert.equal(value[0].text,'actual user');
 assert(!JSON.stringify(value).includes('private'));
});
test('main context transient, prompt invalidation and additive RO MCP',async()=>{
 const f=fixture();const h=await createPlugin({client:f.client,directory:'/private/tmp/fixture'},{python:'/fixture/python',invoke:f.invoke});
 const config={model:'keep/model',mcp:{other:{type:'local'}}};await h.config(config);
 assert.equal(config.model,'keep/model');assert(config.mcp.other);assert.equal(config.mcp['agentic-rag-ro'].environment.RAG_READONLY,'1');
 const out={system:['existing']};await h['experimental.chat.system.transform']({sessionID:'ses_one'},out);
 assert.deepEqual(out.system,['existing','fixture context']);
 await h['chat.message']({sessionID:'ses_one'},{parts:[{type:'text',text:'history question'}]});
 await h['experimental.chat.system.transform']({sessionID:'ses_one'},{system:[]});
 assert.equal(f.calls.filter(x=>x.event==='context').at(-1).payload.prompt,'history question');
 assert.equal(messages[0].parts.length,2);
});
test('child sessions never read transcript, inject or enqueue',async()=>{
 const f=fixture(true);f.client.session.messages=()=>{throw Error('must not read child')};
 const h=await createPlugin({client:f.client,directory:'/private/tmp/fixture'},{python:'/python',invoke:f.invoke});
 const out={system:[]};await h['experimental.chat.system.transform']({sessionID:'ses_child'},out);
 await h.event({event:{type:'session.idle',properties:{sessionID:'ses_child'}}});
 assert.deepEqual(f.calls,[]);assert.deepEqual(out.system,[]);
});
test('compaction reconciled before next context even without bus event',async()=>{
 const f=fixture();const rows=[...messages,{info:{id:'msg_5',role:'user'},parts:[{type:'compaction',auto:true}]}];
 f.client.session.messages=async()=>({data:rows});
 const h=await createPlugin({client:f.client,directory:'/private/tmp/fixture'},{python:'/python',invoke:f.invoke});
 const pre={context:['existing']};await h['experimental.session.compacting']({sessionID:'ses_one'},pre);
 assert.equal(f.calls.at(-1).payload.boundary_id,'msg_5');assert.equal(f.calls.at(-1).payload.trigger,'auto');
 rows.push({info:{id:'msg_6',role:'assistant',parentID:'msg_5',summary:true,time:{completed:1}},parts:[{type:'text',text:'actual summary'}]});
 await h['experimental.chat.system.transform']({sessionID:'ses_one'},{system:[]});
 const post=f.calls.findIndex(x=>x.event==='post-compact');const context=f.calls.findIndex(x=>x.event==='context');
 assert(post>=0&&post<context);assert.equal(f.calls[post].payload.summary,'actual summary');
});
test('SDK failure visible and fail-open',async()=>{
 const f=fixture();f.client.session.get=async()=>{throw Error('private provider detail')};
 const h=await createPlugin({client:f.client,directory:'/private/tmp/fixture'},{python:'/python',invoke:f.invoke});
 const out={system:[]};await h['experimental.chat.system.transform']({sessionID:'ses_one'},out);
 assert(out.system[0].includes('unavailable'));assert(!out.system[0].includes('private provider'));
});
test('concurrent idle callbacks serialize and unchanged projection is not enqueued twice',async()=>{
 const f=fixture();let active=0,max=0;
 const invoke=async(event,payload)=>{active++;max=Math.max(max,active);await new Promise(r=>setTimeout(r,5));f.calls.push({event,payload});active--;return {ok:true};};
 const h=await createPlugin({client:f.client,directory:'/private/tmp/fixture'},{python:'/python',invoke});
 await Promise.all([1,2].map(()=>h.event({event:{type:'session.idle',properties:{sessionID:'ses_one'}}})));
 assert.equal(max,1);assert.equal(f.calls.filter(x=>x.event==='idle').length,1);
});
test('real child-process failure is visible and existing RO MCP stays unchanged',async()=>{
 const f=fixture();const h=await createPlugin({client:f.client,directory:'/private/tmp/fixture'},{python:'/usr/bin/false'});
 const config={mcp:{'agentic-rag-ro':{enabled:false,custom:'preserve'}}};await h.config(config);
 assert.deepEqual(config.mcp['agentic-rag-ro'],{enabled:false,custom:'preserve'});
 const out={system:[]};await h['experimental.chat.system.transform']({sessionID:'ses_one'},out);
 assert(out.system.some(text=>text.includes('unavailable')));
});
