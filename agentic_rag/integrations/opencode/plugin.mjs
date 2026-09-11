import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { dirname, resolve, delimiter } from 'node:path';
import { fileURLToPath } from 'node:url';
const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');

const UNAVAILABLE = 'agentic-rag unavailable: OpenCode lifecycle adapter failed; see the local hook log.';
const disabled = () => Boolean(process.env.AGENTIC_RAG_HOOKS_DISABLE?.trim());

function invokePython(python, event, payload) {
  if (disabled()) return Promise.resolve({ok:true});
  return new Promise(resolve => {
    let done = false, size = 0, chunks = [];
    const child = spawn(python, ['-m', 'agentic_rag.integrations.opencode.hooks', event], {
      stdio: ['pipe', 'pipe', 'ignore'], detached: true,
      env: {...process.env, PYTHONPATH:[packageRoot,process.env.PYTHONPATH].filter(Boolean).join(delimiter)},
    });
    const stop = () => { try { process.kill(-child.pid, 'SIGKILL'); } catch {} };
    const finish = value => {
      if (done) return;
      done = true; clearTimeout(timer); resolve(value);
    };
    const timer = setTimeout(() => { stop(); finish({ok:false,context:UNAVAILABLE}); }, 15000);
    child.on('error', () => finish({ok:false,context:UNAVAILABLE}));
    child.stdin.on('error', () => {});
    child.stdout.on('data', chunk => {
      size += chunk.length;
      if (size > 262144) { stop(); finish({ok:false,context:UNAVAILABLE}); }
      else chunks.push(chunk);
    });
    child.on('close', code => {
      if (done) return;
      try {
        const result = JSON.parse(Buffer.concat(chunks).toString());
        if (code !== 0 || typeof result?.ok !== 'boolean') throw new Error();
        finish(result);
      } catch { finish({ok:false,context:UNAVAILABLE}); }
    });
    const data = JSON.stringify(payload);
    if (Buffer.byteLength(data) > 4 * 1024 * 1024) { stop(); finish({ok:false,context:UNAVAILABLE}); }
    else child.stdin.end(data);
  });
}

export function projectMessages(messages) {
  return messages.filter(({info}) => info && !info.summary &&
    (info.role === 'user' || (info.role === 'assistant' && info.time?.completed)))
    .map(({info,parts}) => ({
      id: info.id, role: info.role,
      text: parts.filter(p => p.type === 'text' && !p.synthetic && !p.ignored)
        .map(p => p.text || '').join('\n').slice(0,16000),
      tools: parts.filter(p => p.type === 'tool').map(p => p.tool).slice(0,100),
    })).filter(m => m.text || m.tools.length);
}

export async function createPlugin({client,directory}, {python,invoke} = {}) {
  const call = invoke ?? ((event,payload) => invokePython(python,event,payload));
  const states = new Map();
  function state(id) {
    if (!states.has(id)) states.set(id,{queue:Promise.resolve(),prompt:'',context:null,main:null,summary:null,idle:null});
    return states.get(id);
  }
  async function serial(id, action) {
    const s=state(id);
    const next=s.queue.then(() => action(s));
    s.queue=next.catch(() => {});
    return next;
  }
  async function main(id,s) {
    if (s.main !== null) return s.main;
    const result=await client.session.get({path:{id},query:{directory},signal:AbortSignal.timeout(5000)});
    if (result.error || !result.data?.id) throw new Error('session identity unavailable');
    s.main=!result.data.parentID;
    return s.main;
  }
  async function history(id) {
    const result=await client.session.messages({path:{id},query:{directory,limit:200},signal:AbortSignal.timeout(5000)});
    if (result.error || !Array.isArray(result.data)) throw new Error('session messages unavailable');
    return result.data.slice(-200).sort((a,b) => a.info.id.localeCompare(b.info.id));
  }
  const payload=(id,rows,extra={}) => ({session_id:id,cwd:directory,messages:projectMessages(rows),...extra});
  function boundary(rows,id) {
    const request=id ? rows.find(m=>m.info.id===id) : [...rows].reverse().find(m=>m.parts.some(p=>p.type==='compaction'));
    const part=request?.parts.find(p=>p.type==='compaction');
    if (!part) return null;
    return {boundary_id:request.info.id,trigger:part.auto?'auto':'manual'};
  }
  async function reconcile(id,s,rows) {
    const summary=[...rows].reverse().find(m=>m.info.role==='assistant'&&m.info.summary&&m.info.time?.completed&&!m.info.error);
    if (!summary || s.summary===summary.info.id) return;
    const b=boundary(rows,summary.info.parentID);
    if (!b) { s.warning=UNAVAILABLE; return; }
    const text=summary.parts.filter(p=>p.type==='text').map(p=>p.text||'').join('\n').slice(0,32000);
    const result=await call('post-compact',payload(id,rows,{...b,summary:text}));
    if (!result.ok) s.warning=result.context||UNAVAILABLE;
    else {s.summary=summary.info.id;s.context=null;}
  }
  async function guarded(id,action,onError) {
    if (!id || disabled()) return;
    try { return await serial(id,async s=>{if(await main(id,s)) return action(s);}); }
    catch { onError?.(); }
  }
  return {
    async config(config) {
      config.mcp ??= {};
      if (!Object.hasOwn(config.mcp,'agentic-rag-ro')) config.mcp['agentic-rag-ro']={
        type:'local',command:[python,'-m','agentic_rag.mcp_server'],environment:{RAG_READONLY:'1'},enabled:true,
      };
    },
    async 'chat.message'(input,output) {
      await guarded(input.sessionID,async s=>{
        s.prompt=output.parts.filter(p=>p.type==='text'&&!p.synthetic&&!p.ignored).map(p=>p.text||'').join('\n').slice(0,12000);
        s.context=null;
      },()=>{state(input.sessionID).warning=UNAVAILABLE;});
    },
    async 'experimental.chat.system.transform'(input,output) {
      await guarded(input.sessionID,async s=>{
        // Reconcile on the awaited model path too: event bus ordering is not a barrier.
        const rows=await history(input.sessionID);
        await reconcile(input.sessionID,s,rows);
        if (s.context===null) {
          const result=await call('context',payload(input.sessionID,rows,{source:'resume',prompt:s.prompt}));
          s.context=result.context||'';
        }
        if (s.context) output.system.push(s.context);
        if (s.warning) {output.system.push(s.warning);s.warning=null;}
      },()=>output.system.push(UNAVAILABLE));
    },
    async 'experimental.session.compacting'(input,output) {
      await guarded(input.sessionID,async s=>{
        const rows=await history(input.sessionID), b=boundary(rows);
        if (!b) throw new Error('compaction boundary unavailable');
        const result=await call('pre-compact',payload(input.sessionID,rows,b));
        output.context.push(result.context||UNAVAILABLE);
        s.context=null;
      },()=>output.context.push(UNAVAILABLE));
    },
    async event({event}) {
      const id=event.properties?.sessionID;
      if (event.type==='session.deleted') {states.delete(event.properties?.info?.id);return;}
      const idle=event.type==='session.idle'||(event.type==='session.status'&&event.properties?.status?.type==='idle');
      if (!idle && event.type!=='session.compacted') return;
      await guarded(id,async s=>{
        const rows=await history(id);
        if (event.type==='session.compacted') {s.context=null;await reconcile(id,s,rows);return;}
        await reconcile(id,s,rows);
        const data=payload(id,rows);
        const fingerprint=createHash('sha256').update(JSON.stringify(data.messages)).digest('hex');
        if (fingerprint===s.idle || !data.messages.length) return;
        const result=await call('idle',data);
        if (result.ok) s.idle=fingerprint; else s.warning=result.context||UNAVAILABLE;
      },()=>{if(id) state(id).warning=UNAVAILABLE;});
    },
  };
}
