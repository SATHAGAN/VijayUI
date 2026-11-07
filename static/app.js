const $=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
let MODS={},B=null,INS=null,DEC={},FILTER='all',EDIT=null;
async function api(u,o){const r=await fetch(u,o);if(!r.ok){let d;try{d=(await r.json()).detail}catch{d=r.statusText}throw{status:r.status,detail:d}}
 return (r.headers.get('content-type')||'').includes('json')?r.json():r}
const jp=(u,b,m='POST')=>api(u,{method:m,headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});
const msg=e=>Array.isArray(e.detail)?e.detail.join('; '):(e.detail&&e.detail.message)||e.detail||e.message;
const month=()=>$('#gm').value,loc=()=>$('#gl').value.trim();
function opts(sel,items,blank){sel.innerHTML=(blank?`<option value="">${blank}</option>`:'')+items.map(([v,l])=>`<option value="${esc(v)}">${esc(l)}</option>`).join('')}

// ---------- tabs ----------
$('#nav').onclick=e=>{const t=e.target.dataset.t;if(!t)return;document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('on',b===e.target));
 document.querySelectorAll('section').forEach(s=>s.classList.toggle('on',s.id==='t-'+t));({dash:loadDash,rec:loadRecs,his:loadHist,imp:loadMaps})[t]?.()};
$('#gm').onchange=$('#gl').onchange=()=>{loadDash();if($('#t-rec').classList.contains('on'))loadRecs()};

// ---------- dashboard ----------
async function loadDash(){if(!month())return;const d=await api(`/api/dashboard?month=${month()}&location=${encodeURIComponent(loc())}`);
 $('#dnote').textContent=(d.drafts_excluded?`${d.drafts_excluded} draft record(s) excluded. `:'')+(d.missing_modules.length?`No data yet for: ${d.missing_modules.join(', ')}`:'');
 $('#dash').innerHTML='<div class="grid">'+Object.entries(d.kpis).map(([m,v])=>`<div class="card"><h3 style="margin:0 0 8px">${esc(v.label)}</h3>`+
  Object.entries(v.metrics).map(([k,x])=>`<div class="kpi"><span>${esc(k)}</span><b>${x??'–'}</b></div>`).join('')+
  Object.entries(v.tables||{}).map(([t,o])=>`<div class="mut" style="margin-top:8px">${esc(t)}</div>`+Object.entries(o).map(([k,x])=>`<div class="kpi"><span>${esc(k)}</span><b>${x}</b></div>`).join('')).join('')+
  `<div class="mut" style="margin-top:8px">Sources: ${Object.entries(d.sources[m]).map(([s,n])=>`${s} ${n}`).join(', ')||'–'}</div></div>`).join('')+'</div>'}
$('#dl').onclick=()=>{location.href=`/api/report.xlsx?month=${month()}&location=${encodeURIComponent(loc())}`};

// ---------- import ----------
async function loadMaps(){const m=$('#im').value;const l=await api('/api/mappings?module='+m);opts($('#isv'),l.map(x=>[x.name,x.name]),'(none)')}
$('#im').onchange=loadMaps;
function fd(extra={}){const f=new FormData();f.append('module',$('#im').value);if($('#if').files[0])f.append('file',$('#if').files[0]);else f.append('text',$('#it').value);
 f.append('header_row',$('#ih').value||0);Object.entries(extra).forEach(([k,v])=>f.append(k,v));return f}
$('#ins').onclick=async()=>{try{if(!$('#if').files[0]&&!$('#it').value.trim())throw{detail:'Choose a file or paste data first'};
 INS=await api('/api/import/inspect',{method:'POST',body:fd({mapping_name:$('#isv').value})});drawMap()}catch(e){alert(msg(e))}};
function drawMap(){const fields=MODS[$('#im').value].fields,c=$('#mapc');c.style.display='block';
 const hs=[...new Set(INS.sheets.flatMap(s=>s.headers))];
 c.innerHTML=`<h3 style="margin-top:0">2. Select sheets &amp; map columns <span class="pill">${esc(INS.source)}</span></h3>`+
 `<div class="row">${INS.sheets.map(s=>`<label style="font-size:13px;color:var(--tx)"><input type="checkbox" class="sh" value="${esc(s.name)}" checked> ${esc(s.name)} <span class="mut">(${s.rows} rows)</span></label>`).join('')}</div>`+
 `<div class="tw"><table><tr><th>Source column</th><th>Maps to field</th></tr>${hs.map(h=>`<tr><td>${esc(h)}</td><td><select class="mp" data-h="${esc(h)}"><option value="">(ignore)</option>${fields.map(f=>`<option value="${f.name}" ${INS.mapping[h]===f.name?'selected':''}>${esc(f.label)}${f.required?' *':''}</option>`).join('')}</select></td></tr>`).join('')}</table></div>`+
 `<div class="row" style="margin-top:10px"><div><label>Save this mapping as</label><input id="mname"></div><button id="msave">Save mapping</button><button class="p" id="pv">Preview records →</button></div>`;
 const map=()=>Object.fromEntries([...document.querySelectorAll('.mp')].map(s=>[s.dataset.h,s.value]).filter(x=>x[1]));
 $('#msave').onclick=async()=>{if(!$('#mname').value)return alert('Enter a name');await jp('/api/mappings',{module:$('#im').value,name:$('#mname').value,mapping:map()});loadMaps();alert('Mapping saved')};
 $('#pv').onclick=async()=>{try{B=await api('/api/import/stage',{method:'POST',body:fd({sheets:[...document.querySelectorAll('.sh:checked')].map(x=>x.value).join('|'),mapping:JSON.stringify(map()),
  default_location:$('#idl').value,default_month:$('#idm').value,sheet_as_location:$('#isl').checked})});DEC={};FILTER='all';drawBatch()}catch(e){alert(msg(e))}}}

function drawBatch(){const c=$('#prev'),fields=MODS[B.module].fields,k=B.counts;c.style.display='block';
 const miss=Object.entries(B.missing||{}).map(([s,m])=>`<div class="err">Missing required columns in “${esc(s)}”: ${m.join(', ')}</div>`).join('');
 const rows=B.rows.filter(r=>FILTER==='all'||r.status===FILTER).slice(0,500);
 c.innerHTML=`<h3 style="margin-top:0">3. Review before importing <span class="pill">${esc(B.source)}${B.file_name?' · '+esc(B.file_name):''}</span></h3>${miss}`+
 (B.requires_verification?`<div class="err">PDF extraction can be wrong. Check every value against the source document; corrected rows are re-validated.</div>`:'')+
 `<div class="row"><select id="flt">${['all','valid','invalid','duplicate'].map(f=>`<option ${f===FILTER?'selected':''} value="${f}">${f==='all'?`All (${k.total})`:`${f[0].toUpperCase()+f.slice(1)} (${k[f]})`}</option>`).join('')}</select>
 <div><label>Duplicates default action</label><select id="dact"><option value="skip">Skip duplicate</option><option value="update">Update existing record</option><option value="keep">Keep existing record</option><option value="review">Review manually later</option></select></div>
 ${B.requires_verification?'<label style="font-size:13px;color:var(--tx)"><input type="checkbox" id="ver"> I verified the extracted values</label>':''}
 <button class="p" id="cm">Import ${k.valid} valid record(s)</button><a href="/api/import/${B.id}/rejected.csv"><button>Download rejected (.csv)</button></a><button class="d" id="dc">Discard</button></div>
 <div class="mut">Invalid rows are never imported unless corrected. Edit any cell and tab out to re-validate.${B.rows.length>500?' Showing first 500 of the filtered rows.':''}</div>
 <div class="tw"><table><tr><th>Sheet / row</th><th>Status</th>${fields.map(f=>`<th>${esc(f.label)}</th>`).join('')}<th>Details</th></tr>`+
 rows.map(r=>{const done=r.result;return `<tr class="${r.status}"><td>${esc(r.sheet)} #${r.row_number}</td><td>${done?esc(done):r.status}</td>`+
  fields.map(f=>`<td>${done?esc(r.mapped[f.name]):f.choices?`<select data-i="${r.idx}" data-f="${f.name}"><option value=""></option>${f.choices.map(c=>`<option ${(r.data[f.name]||r.mapped[f.name])===c?'selected':''}>${c}</option>`).join('')}</select>`:`<input data-i="${r.idx}" data-f="${f.name}" value="${esc(r.mapped[f.name])}">`}</td>`).join('')+
  `<td class="err">${(r.errors||[]).map(esc).join('<br>')}${r.status==='duplicate'&&!done?`${{exact:'Identical record already saved',conflict:'Conflicts with saved record #'+r.existing_id,in_file:'Repeated in this file'}[r.dup_type]}<br><select data-d="${r.idx}">${['','skip','update','keep','review'].map(a=>`<option value="${a}" ${DEC[r.idx]===a?'selected':''}>${a||'(default action)'}</option>`).join('')}</select>${r.dup_type==='conflict'?`<div class="mut">Saved: ${esc(JSON.stringify(r.existing_data))}</div>`:''}`:''}</td></tr>`}).join('')+'</table></div>';
 $('#flt').onchange=e=>{FILTER=e.target.value;drawBatch()};
 c.querySelectorAll('[data-d]').forEach(s=>s.onchange=()=>{DEC[s.dataset.d]=s.value});
 c.querySelectorAll('[data-i]').forEach(i=>i.onchange=async()=>{const r=B.rows[i.dataset.i],m={...r.mapped,[i.dataset.f]:i.value};
  try{B=await jp(`/api/import/${B.id}/rows/${r.idx}`,{mapped:m},'PUT');drawBatch()}catch(e){alert(msg(e))}});
 $('#dc').onclick=async()=>{if(confirm('Discard this import?')){await api('/api/import/'+B.id,{method:'DELETE'});c.style.display='none'}};
 $('#cm').onclick=async()=>{const d=Object.fromEntries(Object.entries(DEC).filter(x=>x[1]));
  if(!confirm(`Import ${k.valid} new record(s) and apply the chosen action to ${k.duplicate} duplicate(s)?`))return;
  try{B=await jp(`/api/import/${B.id}/commit`,{default_action:$('#dact').value,decisions:d,verified:!!$('#ver')?.checked});
   const n=B.counts;alert(`Done: ${n.inserted} inserted, ${n.updated} updated, ${n.skipped} skipped, ${n.invalid} rejected, ${n.pending} pending review.`);
   if(B.status==='partial')drawBatch();else{$('#prev').style.display='none';loadDash()}}catch(e){alert(msg(e))}}}

// ---------- manual entry ----------
function drawForm(rec){const fs=MODS[$('#mm').value].fields;EDIT=rec?rec.id:null;$('#medit').style.display=rec?'inline':'none';$('#medit').textContent='Editing record #'+(rec?rec.id:'');$('#mmsg').textContent='';
 $('#mf').innerHTML=fs.map(f=>{const v=rec?rec.data[f.name]??'':'';const t={date:'date',month:'month',int:'number',float:'number'}[f.type]||'text';
  return `<div><label>${esc(f.label)}${f.required?' *':''}</label>`+(f.choices?`<select data-f="${f.name}"><option value=""></option>${f.choices.map(c=>`<option ${v===c?'selected':''}>${c}</option>`).join('')}</select>`:`<input type="${t}" ${t==='number'?'min="0"':''} data-f="${f.name}" value="${esc(v)}"></div>`)+(f.choices?'</div>':'')}).join('');
 if(!rec&&loc())$('#mf [data-f=location]').value=loc()}
$('#mm').onchange=()=>drawForm();$('#mc').onclick=()=>drawForm();
async function saveRec(status){const data={};document.querySelectorAll('#mf [data-f]').forEach(i=>{if(i.value!=='')data[i.dataset.f]=i.value});const body={module:$('#mm').value,data,status};
 try{try{await (EDIT?jp('/api/records/'+EDIT,body,'PUT'):jp('/api/records',body))}
  catch(e){if(e.status!==409)throw e;const x=e.detail.existing;if(EDIT)throw e;
   if(confirm(`${e.detail.message}.\nExisting (${x.source}, ${x.status}): ${JSON.stringify(x.data)}\n\nOK = update the existing record with these values\nCancel = keep the existing record`))await jp('/api/records',{...body,action:'update'});else{$('#mmsg').textContent='Kept existing record; nothing changed.';return}}
  $('#mmsg').textContent=status==='draft'?'Draft saved.':'Submitted.';drawForm();loadDash()}catch(e){$('#mmsg').textContent=msg(e)}}
$('#md').onclick=()=>saveRec('draft');$('#ms').onclick=()=>saveRec('submitted');

// ---------- records ----------
async function loadRecs(){const p=new URLSearchParams({module:$('#rm').value,status:$('#rs').value,source:$('#rsrc').value,q:$('#rq').value,location:loc()});if(!$('#rall').checked)p.set('month',month());
 [...p].forEach(([k,v])=>{if(!v)p.delete(k)});const L=await api('/api/records?'+p);
 $('#rt').innerHTML=`<table><tr><th>ID</th><th>Module</th><th>Month</th><th>Location</th><th>Data</th><th>Source</th><th>Status</th><th>Modified</th><th></th></tr>`+L.map(r=>`<tr><td>${r.id}</td><td>${esc(MODS[r.module].label)}</td><td>${r.reporting_month}</td><td>${esc(r.location)}</td>
 <td style="white-space:normal;max-width:380px">${esc(Object.entries(r.data).filter(([k])=>k!=='location').map(([k,v])=>k+': '+v).join(' · '))}</td><td>${r.source}${r.source_file?' · '+esc(r.source_file):''}</td><td>${r.status}</td><td>${r.updated_at.slice(0,16).replace('T',' ')}</td>
 <td><button data-e="${r.id}">Edit</button> <button class="d" data-x="${r.id}">Delete</button></td></tr>`).join('')+'</table>';
 document.querySelectorAll('[data-e]').forEach(b=>b.onclick=()=>{const r=L.find(x=>x.id==b.dataset.e);$('#mm').value=r.module;drawForm(r);document.querySelector('[data-t=man]').click()});
 document.querySelectorAll('[data-x]').forEach(b=>b.onclick=async()=>{if(confirm('Delete this record permanently? This is written to the audit trail.')){await api('/api/records/'+b.dataset.x,{method:'DELETE'});loadRecs();loadDash()}})}
$('#rgo').onclick=loadRecs;

// ---------- history ----------
async function loadHist(){const [h,a]=await Promise.all([api('/api/imports'),api('/api/audit')]);
 $('#hb').innerHTML='<table><tr><th>Batch</th><th>When</th><th>Module</th><th>Source</th><th>File</th><th>Status</th><th>Rows</th><th>Inserted</th><th>Updated</th><th>Skipped</th><th>Rejected</th></tr>'+h.map(b=>{const c=b.counts||{};return `<tr><td>${b.id.slice(0,8)}</td><td>${b.created_at.slice(0,16).replace('T',' ')}</td><td>${esc(MODS[b.module].label)}</td><td>${b.source}</td><td>${esc(b.file_name||'')}</td><td>${b.status}</td><td>${c.total??''}</td><td>${c.inserted||0}</td><td>${c.updated||0}</td><td>${c.skipped||0}</td><td>${c.invalid||0}</td></tr>`}).join('')+'</table>';
 $('#ha').innerHTML='<table><tr><th>Time (UTC)</th><th>Entity</th><th>ID</th><th>Action</th><th>Detail</th></tr>'+a.map(x=>`<tr><td>${x.ts.replace('T',' ')}</td><td>${x.entity}</td><td>${esc(x.entity_id.slice(0,8))}</td><td>${x.action}</td><td style="white-space:normal;max-width:600px">${esc(JSON.stringify(x.detail)).slice(0,300)}</td></tr>`).join('')+'</table>'}

// ---------- init ----------
(async()=>{MODS=await api('/api/modules');const ml=Object.entries(MODS).map(([k,v])=>[k,v.label]);['#im','#mm'].forEach(s=>opts($(s),ml));opts($('#rm'),ml,'All');
 const d=new Date();d.setMonth(d.getMonth()-1);$('#gm').value=d.toISOString().slice(0,7);
 api('/api/locations').then(l=>$('#locs').innerHTML=l.map(x=>`<option value="${esc(x)}">`).join(''));drawForm();loadDash();loadMaps()})();
