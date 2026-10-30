/* Same-origin UI. Credentials and knowledge are never stored in localStorage. */
'use strict';
const root=document.getElementById('app');
let me=null,page='overview',generation=0,activeRequest=null;
const labels={overview:'Overview',memories:'Knowledge',clients:'Clients & access',setup:'Setup assistant'};
const icons={overview:'▦',memories:'▤',clients:'◇',setup:'⚙'};
function el(tag,attrs={},...children){
  const node=document.createElement(tag);
  for(const [key,value] of Object.entries(attrs)){
    if(key.startsWith('on'))node.addEventListener(key.slice(2),value);
    else if(key==='class')node.className=value;
    else if(key==='value')node.value=value;
    else if(key==='checked'||key==='disabled')node[key]=value;
    else node.setAttribute(key,value);
  }
  for(const child of children.flat(Infinity))if(child!==null&&child!==undefined)node.append(child instanceof Node?child:document.createTextNode(String(child)));
  return node;
}
function button(text,fn,kind='secondary',attrs={}){return el('button',{type:'button',class:kind,onclick:fn,...attrs},text);}
function badge(text,kind=''){return el('span',{class:'badge '+kind},el('span',{class:'status-dot','aria-hidden':'true'}),text);}
function notice(text){document.getElementById('notice').textContent=text;}
function field(label,name,type='text',value='',hint=''){
  const id='f-'+name+'-'+Math.random().toString(36).slice(2);
  const input=type==='select'?el('select',{id,name}):el('input',{id,name,type,value,autocomplete:type==='password'?'current-password':'off'});
  return el('div',{class:'field'},el('label',{for:id},label),input,hint?el('small',{},hint):null);
}
function selectField(label,name,options,value){const f=field(label,name,'select');for(const [id,text] of options)f.querySelector('select').append(el('option',{value:id},text));f.querySelector('select').value=value;return f;}
function check(label,name,value=false){return el('label',{class:'check'},el('input',{type:'checkbox',name,checked:value}),label);}
function dataOf(form){return Object.fromEntries(new FormData(form).entries());}
function errorBox(error){return el('div',{class:'error',role:'alert'},error.message||String(error));}
function date(value){if(!value)return 'Never';const d=new Date(value);return Number.isNaN(d.valueOf())?'Unreported':d.toLocaleString();}
async function api(path,body,method=body===undefined?'GET':'POST'){
  const response=await fetch('/dashboard/api/'+path,{method,credentials:'same-origin',cache:'no-store',headers:body===undefined?{}:{'content-type':'application/json','x-rag-browser':'1',...(me?{'x-rag-csrf':me.csrf}:{})},...(body===undefined?{}:{body:JSON.stringify(body)})});
  const data=await response.json();
  if(!response.ok){
    if(response.status===401&&me){me=null;generation++;renderLogin(false,'Your session expired or access changed. Sign in again.');}
    const messages={invalid_credentials:'Sign-in failed or your session expired.',origin_denied:'This action requires the original dashboard address.',csrf_denied:'This page is out of date. Reload before trying again.',policy_revision_conflict:'Configuration changed. Reload and preview your change again.',last_administrator_required:'Keep at least one enabled administrator with a password.',policy_busy:'Another administrator is applying a change. Try again shortly.',setup_checks_incomplete:'Run all required checks successfully before completing setup.',existing_store_requires_upgrade:'Existing data was found. Choose the upgrade path to preserve it.',foreground_busy:'Current agent work has priority. Run this check again when the queue is quiet.',setup_probe_busy:'Another connectivity check is running. Wait before retrying.',administrator_required:'Your account cannot administer this service.',dashboard_capacity:'The dashboard is busy. Your data is safe; try again shortly.',policy_recovery_required:'An interrupted policy change conflicts with the current file. Ask the file owner to reconcile its audit before applying more changes.'};
    throw new Error(messages[data.error]||String(data.error||'Request failed').replaceAll('_',' '));
  }
  return data;
}
function header(title,description,extra){return el('div',{class:'page-head'},el('div',{},el('h1',{tabindex:'-1'},title),el('p',{},description)),extra||null);}
function brand(){return el('div',{class:'brand'},el('span',{class:'brand-mark','aria-hidden':'true'},'a'),el('span',{},'agentic-rag'));}
function renderLogin(bootstrap=false,message=''){
  const form=el('form',{class:'login-form'});
  form.append(el('span',{class:'eyebrow muted'},bootstrap?'FIRST ADMINISTRATOR':'YOUR KNOWLEDGE WORKSPACE'),el('h2',{class:'spaced'},bootstrap?'Set up secure access':'Welcome back'),el('p',{class:'muted'},bootstrap?'Use the one-time token created by the server operator. Existing stores are preserved.':'Sign in to search knowledge and manage your service within your permissions.'));
  if(message)form.append(errorBox(new Error(message)));
  if(bootstrap)form.append(field('One-time bootstrap token','token','password','','Created with rag service bootstrap.'));
  form.append(field('Username','username'),field(bootstrap?'New password':'Password','password','password','','At least 12 characters for a new account.'));
  for(const input of form.querySelectorAll('input'))input.required=true;
  form.querySelector('[name=username]').autocomplete='username';
  if(bootstrap)form.querySelector('[name=password]').autocomplete='new-password';
  const submit=el('button',{class:'primary',type:'submit'},bootstrap?'Create administrator':'Sign in');form.append(submit);
  form.addEventListener('submit',async event=>{
    event.preventDefault();form.querySelector('.error')?.remove();submit.disabled=true;
    try{await api(bootstrap?'bootstrap':'login',dataOf(form));form.reset();if(bootstrap){renderLogin(false,'Administrator created. Sign in to continue.');return;}me=await api('me');await navigate('overview');}
    catch(error){form.insertBefore(errorBox(error),submit);}
    finally{submit.disabled=false;}
  });
  root.replaceChildren(el('div',{class:'login-page'},el('section',{class:'login-story'},brand(),el('h1',{},'Shared knowledge.\nClear boundaries.'),el('p',{},'One place for your team’s memories, original sources and connected agents. Your permissions travel with every request.'),el('div',{class:'spaced'},badge('Private infrastructure','good'))),el('main',{id:'content',class:'login-panel'},form)));
}
function shell(){
  const nav=el('nav',{class:'nav','aria-label':'Main navigation'});
  for(const name of ['overview','memories',...(me.admin?['clients','setup']:[])])nav.append(button([icons[name]+'  ',labels[name]].join(''),()=>navigate(name),'',{'aria-current':page===name?'page':'false'}));
  const side=el('aside',{class:'sidebar'},brand(),el('div',{class:'eyebrow'},'Workspace'),nav,el('div',{class:'side-foot'},el('strong',{},me.admin?'Service administrator':'Knowledge member'),me.readonly?'Read-only knowledge access':'Scoped knowledge access',el('br'),el('small',{},'File-owned configuration · protocol 1')));
  const content=el('main',{id:'content',class:'content'});
  const wrap=el('div',{class:'shell'},side,el('div',{class:'workarea'},el('header',{class:'topbar'},button('☰',()=>{wrap.classList.toggle('menu-open');wrap.querySelector('.menu-toggle').setAttribute('aria-expanded',String(wrap.classList.contains('menu-open')));},'menu-toggle',{'aria-label':'Toggle navigation','aria-expanded':'false'}),el('div',{class:'breadcrumbs'},'Workspace  /  ',el('span',{},labels[page])),el('div',{class:'user'},el('span',{class:'avatar','aria-hidden':'true'},me.user.slice(0,2).toUpperCase()),el('span',{},me.user),button('Sign out',async()=>{try{await api('logout',{});me=null;generation++;renderLogin();}catch(e){notice(e.message);}},'quiet'))),content));
  root.replaceChildren(wrap);return content;
}
async function navigate(next){
  page=next;const epoch=++generation;activeRequest=null;notice('');const content=shell();
  content.append(header(labels[page],'Loading your workspace…'),el('div',{class:'pending',role:'status'},el('span',{class:'spinner','aria-hidden':'true'}),'Loading…'));
  try{const view=await ({overview:overviewPage,memories:memoryPage,clients:clientsPage,setup:setupPage}[page])();if(epoch!==generation)return;content.replaceChildren(...view);content.querySelector('h1')?.focus({preventScroll:true});}
  catch(error){if(epoch===generation)content.replaceChildren(header(labels[page],'The service could not complete this view.'),errorBox(error),button('Try again',()=>navigate(page)));}
}
function stat(label,value,note){return el('section',{class:'card'},el('div',{class:'stat-label'},label),el('div',{class:'stat-value'},value),el('div',{class:'stat-note'},note));}
function memoryRows(documents){
  if(!documents.length)return el('div',{class:'empty'},'No memories are visible in this scope.');
  return el('div',{},documents.map(doc=>el('article',{class:'row'},el('span',{class:'doc-icon','aria-hidden':'true'},'▤'),el('div',{class:'row-main'},button(doc.title,()=>showDocument(doc.id),'row-title'),el('p',{},doc.preview.slice(0,130)+(doc.preview.length>130?'…':'')),el('div',{class:'row-meta'},el('span',{},doc.domain),el('span',{},'·'),el('span',{},doc.project||'unknown'),el('span',{},'· '+date(doc.updated_at)))),badge(doc.review_state||doc.status,doc.review_state==='confirmed'?'good':doc.review_state==='unreviewed'?'warn':''))));
}
async function overviewPage(){
  const [overview,recent]=await Promise.all([api('overview'),api('memories?limit=5')]);
  const domains=el('section',{class:'card'},el('h2',{},'Knowledge domains'));
  for(const domain of overview.domains)domains.append(el('div',{class:'row'},el('div',{class:'row-main'},el('h3',{},domain.name),el('small',{},domain.memories+' memories visible to you'),el('div',{class:'domain-bar'},el('progress',{max:Math.max(1,overview.memories),value:domain.memories,'aria-label':domain.name+' share of visible knowledge'})))));
  if(!overview.domains.length)domains.append(el('p',{class:'muted'},'Your account has no visible knowledge yet. Ask an administrator to review its domain and project permissions.'));
  domains.append(el('div',{class:'callout spaced'},'Every count, search result and source below follows your current permissions. Administrator status does not expand knowledge access.'));
  return [header('Your knowledge, connected.','A shared memory for your team. Pick up from original sources, with access kept in scope.',badge('Scoped workspace','good')),el('div',{class:'grid stats'},stat('Visible memories',overview.memories,'Across your authorized domains and projects'),stat('Pending reviews',overview.pending_reviews,'Original-backed claims awaiting a decision'),stat('Service version',overview.version,'One engine for local and central use')),el('div',{class:'grid two-col'},el('section',{class:'card'},el('div',{class:'section-head'},el('h2',{},'Recently updated'),button('Browse knowledge →',()=>navigate('memories'),'quiet')),memoryRows(recent.documents)),el('div',{class:'grid'},domains,el('section',{class:'card'},el('h2',{},'Your access'),el('p',{class:'muted'},me.readonly?'You can browse and inspect sources. Knowledge changes are disabled.':'You can review knowledge within your writable scope.'),el('small',{},'Domains: '+me.permissions.read_domains.join(', ')),el('br'),el('small',{},'Projects: '+me.permissions.read_projects.join(', ')))))];
}
async function queueTool(tool,args,target){
  const epoch=generation;
  const submitted=await api('tools',{tool,arguments:args,idempotency_key:crypto.randomUUID(),created_at:new Date().toISOString()});
  activeRequest=submitted.request_id;
  const pending=el('div',{class:'pending',role:'status'},el('span',{class:'spinner','aria-hidden':'true'}),el('div',{},el('strong',{},'Waiting for the server'),el('br'),el('small',{},'Your request is queued. Current work takes priority over background extraction.')),button('Cancel',async()=>{try{await api('requests/'+submitted.request_id+'/cancel',{});notice('Cancellation requested.');}catch(e){notice(e.message);}},'quiet'));
  target.replaceChildren(pending);
  let result=submitted;
  for(let attempt=0;attempt<330;attempt++){
    if(epoch!==generation)return null;
    if(result.state==='completed'){activeRequest=null;return result.result;}
    if(['failed','cancelled','expired'].includes(result.state))throw new Error(String(result.code||result.state).replaceAll('_',' '));
    await new Promise(resolve=>setTimeout(resolve,1000));
    try{result=await api('requests/'+submitted.request_id);}catch(error){if(!me)throw error;if(attempt===329)throw error;}
  }
  throw new Error('The request is still waiting or its result expired. Retry explicitly when the service is available.');
}
async function memoryPage(){
  const controls=el('form',{class:'toolbar'},field('Search your knowledge','query','text','','Uses the shared server queue.'),field('Domain filter','domain'),field('Project filter','project','text','','Exact logical project, e.g. /projects/it'),check('Pending reviews only','pending'),el('button',{type:'submit',class:'primary'},'Search'));
  controls.firstChild.classList.add('grow');
  const queryInput=controls.querySelector('[name=query]');const pendingInput=controls.querySelector('[name=pending]');
  const syncPending=()=>{pendingInput.disabled=Boolean(queryInput.value.trim());if(pendingInput.disabled)pendingInput.checked=false;};
  queryInput.addEventListener('input',syncPending);
  controls.append(el('small',{class:'muted'},'Pending-only filtering applies to browsing. Text search clears this selection.'));
  const results=el('section',{class:'card'});
  const load=async(offset=0)=>{
    const values=dataOf(controls);const params=new URLSearchParams({limit:'25',offset:String(offset)});
    if(values.domain)params.set('domain',values.domain);if(values.project)params.set('project',values.project);if(values.pending)params.set('pending','1');
    const found=await api('memories?'+params);results.replaceChildren(el('div',{class:'section-head'},el('h2',{},'Memories'),el('small',{},found.total+' visible')),memoryRows(found.documents));
    if(offset||found.next_offset!==null)results.append(el('div',{class:'actions'},offset?button('Previous',()=>load(Math.max(0,offset-25))):null,found.next_offset!==null?button('Next',()=>load(found.next_offset)):null));
  };
  controls.addEventListener('submit',async event=>{
    event.preventDefault();try{
      syncPending();const values=dataOf(controls);if(!values.query.trim()){await load();return;}
      const result=await queueTool('memory_search',{query:values.query,k:25,strategy:'lexical',rerank:'off',...(values.domain?{domain:values.domain}:{}),...(values.project?{project:values.project}:{})},results);
      if(!result)return;
      results.replaceChildren(el('h2',{},'Search results'),memoryRows((result.results||[]).map(hit=>({id:hit.document_id||hit.doc_id||hit.id,slug:hit.slug,title:hit.title,preview:hit.snippet||hit.content||'',domain:hit.domain,project:hit.project_scope||hit.project,status:'match',updated_at:hit.verified_at}))));
    }catch(error){results.replaceChildren(errorBox(error));}
  });
  await load();return [header('Knowledge library','Browse memories in your scope, inspect their originals, and review claims with evidence.',badge(me.readonly?'Read-only':'Scoped access',me.readonly?'':'good')),controls,results];
}
async function showDocument(id){
  const content=root.querySelector('#content');if(!content)return;
  const epoch=++generation;content.replaceChildren(header('Memory details','Loading original-backed knowledge…'),button('← Back to knowledge',()=>navigate('memories'),'quiet'));
  const target=el('section',{class:'card spaced'});content.append(target);
  try{
    const result=await queueTool('memory_get',{id_or_slug:id},target);if(!result||epoch!==generation)return;
    if(!result.document){target.replaceChildren(el('div',{class:'empty'},'This memory is unavailable in your current scope.'));return;}
    const doc=result.document;
    content.querySelector('h1').textContent=doc.title;
    target.replaceChildren(el('div',{class:'detail-meta'},badge(doc.domain),badge(doc.project_scope||'unknown'),badge(doc.claim_evidence?.review_state||doc.status)),el('div',{class:'body-text'},doc.body),el('h2',{class:'spaced'},'Original sources & review'));
    const sources=doc.claim_sources||[];
    if(!sources.length)target.append(el('p',{class:'muted'},'No claim-source records. Inspect the original provenance below.'));
    for(const source of sources)target.append(el('article',{class:'source'},el('h3',{},source.source_id||source.source_key||'Source'),badge(source.state||'active'),el('p',{},source.quote||''),el('small',{},'Role: '+(source.role||'unknown')+' · '+(source.complete?'Complete quote':'Partial or unspecified quote')),source.reason?el('p',{},source.reason):null));
    target.append(el('details',{},el('summary',{},'Evidence, assertions and provenance'),el('pre',{},JSON.stringify({claim_evidence:doc.claim_evidence,assertion:doc.assertion,provenance:doc.provenance,edges_out:result.edges_out,edges_in:result.edges_in},null,2))));
    const writable=!me.readonly&&(me.permissions.write_domains.includes('*')||me.permissions.write_domains.includes(doc.domain))&&(me.permissions.write_projects.includes('*')||me.permissions.write_projects.includes(doc.project_scope));
    if(writable&&doc.claim_evidence?.review_state){
      const form=el('form',{class:'spaced'},el('h3',{},'Review this claim'),selectField('Review state','state',[['confirmed','Confirmed'],['unreviewed','Unreviewed'],['refuted','Refuted']],'confirmed'),field('Reason, grounded in the original sources','reason'),el('button',{type:'submit',class:'primary spaced'},'Apply audited review'));
      form.querySelector('[name=reason]').required=true;
      form.addEventListener('submit',async event=>{event.preventDefault();const values=dataOf(form);const box=el('div',{class:'spaced'});form.append(box);try{const saved=await queueTool('memory_review_claim',{id_or_slug:doc.id,state:values.state,reason:values.reason},box);if(saved){notice('Review saved through the audited gateway.');await showDocument(doc.id);}}catch(error){box.replaceChildren(errorBox(error));}});target.append(form);
    }
    target.querySelector('h2')?.focus();
  }catch(error){if(epoch===generation)target.replaceChildren(errorBox(error));}
}
function scopesText(row){return 'Read '+row.read_domains.join(', ')+' / '+row.read_projects.join(', ')+'\nWrite '+row.write_domains.join(', ')+' / '+row.write_projects.join(', ');}
async function clientsPage(){
  const admin=await api('admin');
  const list=el('section',{class:'card'},el('div',{class:'section-head'},el('h2',{},'Enrolled clients'),button('+ Enroll a VM',()=>editPrincipal(null,'machine'),'primary')));
  const table=el('table',{},el('thead',{},el('tr',{},['Client / owner','Access','Last connection','Permissions',''].map(x=>el('th',{scope:'col'},x)))));const rows=el('tbody');
  for(const row of admin.machines)rows.append(el('tr',{},el('td',{},el('strong',{},row.label),el('small',{},row.id+' · '+row.user),el('small',{},row.connection.reported_version?'Reported v'+row.connection.reported_version:'Version unreported'),el('small',{},row.connection.reported_capabilities?'Reported capabilities: '+row.connection.reported_capabilities:'Capabilities unreported')),el('td',{},badge(row.access_state,row.access_state==='enabled'?'good':'bad'),el('small',{},row.keys.map(k=>k.prefix+'••••').join(', ')||'No active keys')),el('td',{},badge(row.connection.freshness,row.connection.freshness==='online'?'good':''),el('small',{},date(row.connection.last_seen))),el('td',{},el('small',{},'Configured: '+scopesText(row)),el('small',{},'Effective: '+scopesText(row.effective_permissions.read_domains?row.effective_permissions:{read_domains:[],read_projects:[],write_domains:[],write_projects:[]})),el('small',{},'Configured teams: '+(row.session_teams.join(', ')||'none')),el('small',{},'Effective teams: '+((row.effective_permissions.session_teams||[]).join(', ')||'none'))),el('td',{},button('Manage',()=>editPrincipal(row,'machine'),'quiet'))));
  if(!admin.machines.length)list.append(el('div',{class:'empty'},'No clients enrolled. Add an owner user, enroll a VM, then generate its private credential.'));else{table.append(rows);list.append(el('div',{class:'table-wrap'},table));}
  list.append(el('div',{class:'callout spaced'},'Offline is not revoked. Freshness means authenticated activity in the last 5 minutes; it is not a continuous socket or a permission grant. Versions and capabilities are client-reported.'));
  const users=el('section',{class:'card spaced'},el('div',{class:'section-head'},el('h2',{},'People & service owners'),button('+ Add user',()=>editPrincipal(null,'user'))));
  for(const user of admin.users)users.append(el('div',{class:'row'},el('div',{class:'row-main'},el('h3',{},user.label),el('small',{},user.id+' · '+(user.admin?'Administrator':'Member')+' · '+(user.password_configured?'Browser login configured':'Machine owner only')),el('br'),el('small',{},scopesText(user)),el('br'),el('small',{},'Last observed: '+date(user.connection.last_seen)+' · '+user.connection.freshness)),badge(user.enabled?'Enabled':'Disabled',user.enabled?'good':'bad'),button('Manage',()=>editPrincipal(user,'user'),'quiet')));
  const health=el('section',{class:'card spaced'},el('h2',{},'Service health'),el('div',{class:'grid stats'},stat('Foreground queue',admin.foreground_queue.reduce((n,r)=>n+(r.state==='pending'||r.state==='running'?r.count:0),0),'Current interactive tool work'),stat('Source queue',admin.source_queue.reduce((n,r)=>n+(r.status==='pending'||r.status==='processing'?r.count:0),0),'Background extraction yields to foreground'),stat('Provider access',admin.provider_health.state,'Last explicit synthetic setup check')),el('small',{},'Model / embedding: '+admin.settings.model+' / '+admin.settings.embedding+' · file-owned, read-only'));
  const audit=el('section',{class:'card spaced'},el('h2',{},'Recent administrative changes'),admin.administrative_changes.length?el('div',{},admin.administrative_changes.map(row=>el('div',{class:'row'},el('div',{},el('strong',{},row.kind+' · '+row.subject),el('br'),el('small',{},row.actor+' · '+date(row.created_at))),badge(row.state,row.state==='applied'?'good':'warn')))):el('p',{class:'muted'},'No dashboard changes recorded. File configuration remains authoritative.'));
  return [header('Connected clients, controlled access.','Manage users, VM credentials and permissions through explicit, audited policy changes.',badge('File-owned policy')),list,users,health,audit];
}
async function policyChange(change,target){
  const policy=await api('policy');
  const preview=await api('policy/preview',{revision:policy.revision,change});
  target.replaceChildren(el('div',{class:'callout warn'},'Review this exact change. Applying it replaces the validated policy atomically; external file edits will cause a conflict.'),el('pre',{},JSON.stringify({...change,...('password' in change?{password:'[new password supplied]'}:{})},null,2)));
  const apply=button('Apply policy change',async()=>{
    apply.disabled=true;
    try{
      const saved=await api('policy/apply',{revision:preview.revision,change,operation_id:crypto.randomUUID()});
      // Drop the password from the JavaScript change object immediately after use.
      delete change.password;
      target.replaceChildren(el('div',{class:'callout'},'Change applied. New permissions take effect on the next authenticated request.'));
      if(saved.secret_once){
        const code=el('code',{},saved.secret_once);
        target.append(el('div',{class:'secret',role:'status'},el('strong',{},'Save this credential now — shown once'),code,el('p',{},'Store it in the client’s private token file. It will not appear again. A lost response requires a new rotation.'),button('Copy credential',async()=>{try{await navigator.clipboard.writeText(code.textContent);notice('Credential copied. Keep it private.');}catch{notice('Select the credential and copy it to a private file.');}},'secondary'),button('I saved it',()=>{code.textContent='';navigate('clients');},'quiet')));
      }else target.append(button('Return to clients',()=>navigate('clients'),'primary'));
    }catch(error){target.append(errorBox(error));apply.disabled=false;}
  },'primary');target.append(el('div',{class:'actions'},apply,button('Cancel',()=>navigate('clients'))));
}
function editPrincipal(row,kind){
  generation++;const content=root.querySelector('#content');content.replaceChildren(header(row?'Manage '+row.id:kind==='machine'?'Enroll a VM':'Add a user','Configuration remains file-owned. Preview and apply changes explicitly.'),button('← Back to clients',()=>navigate('clients'),'quiet'));
  const form=el('form',{class:'card spaced'});const grid=el('div',{class:'form-grid'});
  grid.append(field('Stable ID','id','text',row?.id||'','Letters, digits, underscores or hyphens.'),field('Display label','label','text',row?.label||''));
  grid.querySelector('[name=id]').required=true;if(row)grid.querySelector('[name=id]').readOnly=true;
  if(kind==='machine')grid.append(field('Owner user ID','user','text',row?.user||'','The VM’s effective rights are the intersection with its owner.'));
  else grid.append(field('New password (optional)','password','password','','Leave blank for unchanged password or a machine-only owner.'));
  for(const [name,label] of [['read_domains','Readable domains'],['write_domains','Writable domains'],['read_projects','Readable projects'],['write_projects','Writable projects'],['session_teams','Shared session-log teams']])grid.append(field(label,name,'text',(row?.[name]||[]).join(', '),'Comma-separated. Blank grants no access. * grants all; use deliberately.'));
  grid.append(check('Enabled','enabled',row?.enabled!==false));if(kind==='user')grid.append(check('Service administrator','admin',!!row?.admin));
  const target=el('div',{class:'spaced'});const submit=el('button',{type:'submit',class:'primary'},'Preview change');form.append(grid,el('div',{class:'actions'},submit),target);content.append(form);
  form.addEventListener('submit',async event=>{event.preventDefault();submit.disabled=true;try{
    const data=dataOf(form),fields={label:data.label||data.id,enabled:form.elements.enabled.checked};
    for(const key of ['read_domains','write_domains','read_projects','write_projects','session_teams'])fields[key]=data[key].split(',').map(x=>x.trim()).filter(Boolean);
    if(kind==='user')fields.admin=form.elements.admin.checked;
    const change={kind,id:data.id,fields,...(kind==='machine'?{user:data.user}:data.password?{password:data.password}:{})};
    await policyChange(change,target);form.querySelector('[name=password]')?.value&& (form.querySelector('[name=password]').value='');
  }catch(error){target.replaceChildren(errorBox(error));}finally{submit.disabled=false;}});
  if(kind==='machine'&&row){
    const credentials=el('section',{class:'card spaced'},el('h2',{},'API credentials'),el('p',{class:'muted'},'Rotating a key ID immediately invalidates its old credential, including pending jobs under that revision. Other key IDs remain enabled.'));
    for(const key of row.keys)credentials.append(el('div',{class:'row'},el('code',{},key.prefix+'••••'),button('Rotate',()=>credentialAction('rotate',row.id,key.id,credentials)),button('Revoke',()=>credentialAction('revoke',row.id,key.id,credentials),'danger')));
    const add=el('form',{class:'toolbar spaced'},field('New key ID','key_id'),el('button',{class:'secondary',type:'submit'},'Generate credential'));
    add.addEventListener('submit',event=>{event.preventDefault();credentialAction('rotate',row.id,dataOf(add).key_id,credentials);});credentials.append(add);content.append(credentials);
  }
}
async function credentialAction(kind,id,key,target){const box=el('div',{class:'spaced'});target.append(box);try{await policyChange({kind,id,key_id:key},box);}catch(error){box.replaceChildren(errorBox(error));}}
async function setupPage(){
  const state=await api('setup');const modeNames={'new-local':'New local installation','existing-local':'Upgrade an existing local store',central:'Central server setup',client:'Connect a client'};
  const choose=el('section',{class:'card'},el('h2',{},'1. Choose your installation path'),el('div',{class:'callout '+(state.discovery.existing_data?'warn':'')},state.discovery.existing_data?'Existing knowledge found. The upgrade path preserves it; fresh initialization is disabled.':'Initialized database detected. No stored knowledge found. The browser will never reset this store.'),el('p',{class:'muted spaced'},'PostgreSQL and the verified current schema are prerequisites. Migration, restore and service restarts remain explicit operator actions.'));
  const modes=el('div',{class:'mode-grid'});
  for(const mode of state.modes)modes.append(button('',async()=>{try{await api('setup',{mode:mode.id});await navigate('setup');}catch(error){notice(error.message);}},'mode',{'aria-pressed':String(state.mode===mode.id),disabled:!mode.allowed}));
  [...modes.children].forEach((node,index)=>node.append(el('strong',{},modeNames[state.modes[index].id]),el('small',{},state.modes[index].prerequisite)));choose.append(modes);
  const checks=el('section',{class:'card spaced'},el('h2',{},'2. Validate this configuration'),el('p',{class:'muted'},'Checks are saved and resume after restart. Model checks send only synthetic text, run one at a time and yield to agent work. They may use your configured provider account.'));
  for(const [key,title,explanation] of [['database','Database & schema','Verify the current schema and authorization protections.'],['permissions','Required permissions','Verify this live administrator and scoped reader/writer roles.'],['embedding','Embedding access','Verify local model identity, dimensions and an actual bounded embedding call.'],['provider','Provider access','Make one synthetic provider request; allow up to 40 seconds including Codex login preflight.'],['compatibility','Client / server compatibility','Authenticate to the file-configured target and verify protocol 1 and queued-tools capability 1.']]){
    const checkState=state.checks[key]||{state:'not-checked',code:'explicit_check_required'};
    const run=button('Run check',async()=>{run.disabled=true;run.textContent='Checking…';try{await api('setup/check',{check:key});await navigate('setup');}catch(error){notice(error.message);run.disabled=false;run.textContent='Run check';}},'secondary',{disabled:!state.mode});
    checks.append(el('div',{class:'check-row'},el('div',{},el('strong',{},title),el('small',{},explanation),el('small',{},checkState.code.replaceAll('_',' '))),badge(checkState.state,checkState.state==='verified'?'good':checkState.state==='unavailable'?'bad':''),run));
  }
  const finish=el('section',{class:'card spaced'},el('h2',{},'3. Review and finish'),el('p',{class:'muted'},'Runtime and model settings remain file-owned and read-only. Export an instruction plan, review it as the file owner, then apply any configuration or verified migration explicitly. Completing this assistant does not move data or restart services.'),el('div',{class:'actions'},button('Export setup plan',async()=>{try{const plan=await api('setup/export');const blob=new Blob([JSON.stringify(plan,null,2)+'\n'],{type:'application/json'});const url=URL.createObjectURL(blob);const a=el('a',{href:url,download:'agentic-rag-setup-plan.json'});a.click();URL.revokeObjectURL(url);notice('Plan exported. It contains placeholders and no credentials.');}catch(error){notice(error.message);}},'secondary',{disabled:!state.mode}),button(state.completed?'Setup complete':'Complete setup',async()=>{try{await api('setup/complete',{});notice('Setup checks complete. File changes and rollout remain explicit.');await navigate('setup');}catch(error){notice(error.message);}},'primary',{disabled:!state.mode||state.completed})),state.completed?el('div',{class:'callout spaced'},'Validated setup is complete. Repeating completion is idempotent. Configuration changes invalidate prior checks.'):null);
  return [header('Set up with confidence.','Choose a path, validate its prerequisites and resume whenever you need.',badge(state.completed?'Completed':'Resumable',state.completed?'good':'')),choose,checks,finish];
}
(async()=>{try{me=await api('me');await navigate('overview');}catch{try{const state=await api('bootstrap');renderLogin(state.available);}catch{renderLogin(false,'Dashboard unavailable. Check the private service URL and database/schema prerequisites.');}}})();
