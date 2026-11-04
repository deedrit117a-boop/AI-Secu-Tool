// ---------- Jira 연동 (선택): 티켓번호 확인 / Summary 채우기 / 결과를 코멘트로 남기기 (코멘트는 확인창에서 누른 경우에만 작성)
const ticketKey=()=>{const t=($('#ticket')||{value:''}).value.trim().toUpperCase();return /^[A-Z][A-Z0-9_]+-\d+$/.test(t)?t:''};
let tkTimer;
async function checkTicket(){const el=$('#tkinfo');if(!el)return;const k=ticketKey();S.tinfo=null;
  if(!k||!(S.jira&&S.jira.enabled)){el.textContent='';return}
  el.textContent='Jira 확인 중...';
  try{const d=await api('GET','/api/jira/issue?key='+encodeURIComponent(k));S.tinfo=d;
    el.innerHTML=`✓ <a href="${esc(d.url)}" target="_blank">${esc(d.key)}</a> ${esc(d.summary).slice(0,60)} <span class="badge b-pending">${esc(d.status)}</span>`}
  catch(e){el.innerHTML=`<span style="color:var(--warn)">⚠ Jira 확인 실패: ${esc(e.message).slice(0,70)}</span>`}}
async function jiraFill(sel){const k=ticketKey();if(!k)return toast('상단에 티켓번호를 입력하세요',true);
  const d=(S.tinfo&&S.tinfo.key===k)?S.tinfo:await api('GET','/api/jira/issue?key='+encodeURIComponent(k));
  const el=$(sel);if(el.value.trim()&&!confirm('입력된 Summary 를 Jira 제목으로 바꿀까요?'))return;el.value=d.summary}
function jiraCommentText(x){const kd=histKind(x),lines=(x.text||'').split('\n');
  if(kd==='plan'||kd==='apply'){const sum=lines.find(l=>/^(Plan:|Apply complete)/.test(l));return `[Traform ACL] ${x.step}\n${x.headline||''}${sum?'\n'+sum:''}`}
  return `[Traform ACL] ${x.step}\n${x.headline||''}\n${lines.slice(0,8).join('\n')}`}
async function jiraComment(x){return jiraCommentModal(jiraCommentText(x))}
async function jiraCommentModal(text){
  const res=await showModal('Jira에 코멘트 남기기',`<label class="f">티켓<input type="text" id="jc-key" value="${esc(ticketKey())}"></label>
    <label class="f" style="margin-top:8px">코멘트 (수정 가능)<textarea id="jc-body" style="min-height:150px">${esc(text)}</textarea></label>
    <div class="warnbox" style="margin-top:8px">'Jira에 작성'을 누르면 Jira 이슈에 코멘트가 실제로 등록됩니다.</div>`,'Jira에 작성',null,
    {collect:o=>({key:o.querySelector('#jc-key').value.trim().toUpperCase(),body:o.querySelector('#jc-body').value})});
  if(!res)return;await api('POST','/api/jira/comment',{key:res.key,body:res.body});toast('Jira 코멘트를 작성했습니다: '+res.key)}

// ---------- 서버 재시작 (화면에서): 새 프로세스를 띄우고 이 프로세스는 종료 → 응답이 돌아오면 자동 새로고침
async function restartServer(){
  if(!confirm('서버를 다시 시작합니다. 진행 중인 작업이 있으면 중단됩니다. 계속할까요?'))return;
  try{await api('POST','/api/restart',{confirm:true})}
  catch(e){return toast('이 서버는 화면에서 재시작할 수 없습니다 (구버전). run.bat 서버를 종료하고 다시 실행하세요.',true,10000)}
  const ov=document.createElement('div');ov.className='modal-ov';
  ov.innerHTML='<div class="modal" style="width:min(460px,92vw)"><h3>서버를 다시 시작하는 중...</h3><div class="mut" id="rs-msg">잠시 후 화면이 자동으로 새로고침됩니다 (최대 45초). 새 콘솔 창이 열립니다.</div></div>';document.body.appendChild(ov);
  const t0=Date.now();await new Promise(r=>setTimeout(r,2800));
  while(Date.now()-t0<45000){try{const v=await fetch('/api/version',{cache:'no-store'}).then(r=>r.json());if(v&&v.version){location.reload();return}}catch(e){}await new Promise(r=>setTimeout(r,1200))}
  $('#rs-msg').textContent='응답이 없습니다. run.bat 으로 직접 시작해 주세요.'}

// ---------- IP/대역으로 규칙 일괄 삭제 (현재 SG / 환경 / 같은 저장소): 미리보기 → 삭제 실행
async function ipDeleteModal(){
  const html=`<div class="mut" style="margin-bottom:8px">입력한 IP/대역이 소스인 규칙을 찾아 삭제합니다. 규칙 하나에 CIDR 이 여러 개면 일치하는 것만 빼고, 모두 빠지면 규칙을 삭제합니다. SG ID 소스 규칙은 건드리지 않습니다. 삭제는 작업 브랜치에서만 가능합니다.</div>
    <label class="f">IP / 대역 (줄바꿈·쉼표 구분) ${presetPicker('#bd-ips')}<textarea id="bd-ips" placeholder="10.0.0.1&#10;10.1.0.0/24"></textarea></label>
    <div class="row" style="margin-top:8px"><label class="f">범위<select id="bd-scope"><option value="sg">현재 SG (${esc(S.sg||'선택 없음')})</option><option value="env">현재 환경의 모든 SG</option><option value="repo">같은 저장소의 모든 환경</option></select></label>
      <label class="f">일치 방식<select id="bd-match"><option value="exact">정확히 일치</option><option value="overlap">포함/겹침</option></select></label>
      <div class="f">방향<span class="row"><label><input type="checkbox" id="bd-in" checked> 인바운드</label><label><input type="checkbox" id="bd-out" checked> 아웃바운드</label></span></div></div>
    <div class="row" style="margin-top:8px"><button id="bd-prev">미리보기</button><button class="danger" id="bd-run" disabled>삭제 실행</button><span class="mut" id="bd-msg"></span></div><div id="bd-res" style="margin-top:8px"></div>`;
  await showModal('IP로 규칙 삭제',html,'닫기',null,{hideCancel:true,onMount:o=>{
    bindPresetPickers(o,null);const q=s=>o.querySelector(s);let last=null;
    const params=dry=>({env_id:S.envId,name:S.sg||'',scope:q('#bd-scope').value,ips:q('#bd-ips').value.split(/[\s,;]+/).filter(Boolean),match:q('#bd-match').value,
      directions:['ingress','egress'].filter(d=>d==='ingress'?q('#bd-in').checked:q('#bd-out').checked),dry_run:dry});
    q('#bd-ips').oninput=()=>{q('#bd-run').disabled=true};
    q('#bd-prev').onclick=async()=>{if(q('#bd-scope').value==='sg'&&!S.sg)return toast('먼저 SG를 선택하세요 (또는 범위를 바꾸세요)',true);
      try{last=await api('POST','/api/bulk-delete',params(true));
        q('#bd-res').innerHTML=last.results.length?`<table><thead><tr><th>환경</th><th>SG</th><th>삭제될 규칙</th><th>일부 IP만 제거</th></tr></thead><tbody class="plan">${last.results.map(x=>`<tr class="del"><td>${esc((S.cfg.environments.find(e=>e.id===x.env_id)||{}).env||x.env_id)}</td><td>${esc(x.name)}</td>
          <td>${x.removed.map(r=>esc(r.direction+' '+r.protocol+' '+portStr(r)+' '+srcStr(r))).join('<br>')||'-'}</td><td>${x.modified.map(r=>esc(portStr(r)+' : '+r.removed_cidrs.join(', '))).join('<br>')||'-'}</td></tr>`).join('')}</tbody></table>`:'<div class="mut">일치하는 규칙이 없습니다.</div>';
        q('#bd-msg').textContent=`삭제 ${last.total_removed}건 · 일부 제거 ${last.total_modified}건 · SG ${last.results.length}개`;q('#bd-run').disabled=!(last.total_removed||last.total_modified)}
      catch(err){toast(err.message,true)}};
    q('#bd-run').onclick=async()=>{if(!last||!confirm(`${last.results.length}개 SG 에서 규칙 ${last.total_removed}건 삭제, ${last.total_modified}건에서 일부 IP 를 제거합니다. 실행할까요?`))return;
      try{const r=await api('POST','/api/bulk-delete',params(false));
        addHist(`규칙 삭제(IP 기준) → SG ${r.results.length}개`,r.results.map(x=>`${x.name}: 삭제 ${x.removed.length} / 일부 제거 ${x.modified.length}`).join('\n'),{kind:'rule',headline:`✓ 삭제 ${r.total_removed}건 · 수정 ${r.total_modified}건`});
        toast(`삭제 ${r.total_removed}건, 일부 제거 ${r.total_modified}건 (파일만 수정됨 — Commit/Push 는 작업 탭에서)`,false,6000);
        await loadSgs();await loadChg();drawSgList();if(S.sg)await openSg(S.sg);q('.mo')&&o.querySelector('.mo').click()}
      catch(err){toast(err.message,true,10000)}}}})}

// ---------- 영향 분석 보고서
async function showChangeReport(){
  const r=await api('GET',`/api/env/${S.envId}/report/changes`);
  const rows=(items,cls,label)=>items.map(x=>`<tr class="${cls}"><td>${label}</td><td>${x.direction==='ingress'?'인':'아웃'}바운드</td><td>${esc(x.protocol)}</td><td>${esc(portStr(x))}</td><td>${esc(srcStr(x))}</td><td>${esc(x.description)}</td></tr>`).join('');
  const html=`<div class="mut">브랜치 <b>${esc(r.branch)}</b> (기준 <code>${esc(String(r.base).slice(0,10))}</code>) · 변경 SG <b>${r.totals.sgs}</b>개 · 규칙 추가 <b>${r.totals.added}</b> / 삭제 <b>${r.totals.removed}</b> · 위험 <b>${r.totals.risks}</b></div>
    ${r.sgs.map(s=>`<div style="margin-top:10px"><b>${esc(s.name)}</b> <span class="mut" style="font-size:12px">${esc(s.env)}</span>
      <table><thead><tr><th></th><th>방향</th><th>프로토콜</th><th>포트</th><th>소스</th><th>설명</th></tr></thead><tbody class="plan">${rows(s.added,'add','➕')}${rows(s.removed,'del','➖')}</tbody></table></div>`).join('')||'<div class="mut" style="margin-top:8px">기준 브랜치 대비 변경된 SG 규칙이 없습니다.</div>'}
    ${r.risks.length?`<div class="warnbox danger" style="margin-top:10px"><b>⚠ 위험 규칙</b><ul>${r.risks.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div>`:''}
    <div class="row" style="margin-top:10px"><button id="rp-copy">마크다운 복사 (MR/Jira 설명용)</button><button id="rp-audit" title="티켓·작성자·변경 내용·위험·MR·plan 결과를 한 장의 .md 파일로 저장합니다">변경 기록 파일 저장 (.md)</button>${S.jira&&S.jira.enabled?'<button id="rp-jira">Jira 코멘트로 남기기</button>':''}</div>`;
  await showModal('변경 요약 보고서 (영향 분석)',html,'닫기',null,{hideCancel:true,onMount:o=>{
    o.querySelector('#rp-copy').onclick=async()=>{try{await navigator.clipboard.writeText(r.markdown);toast('마크다운을 복사했습니다')}catch(e){prompt('아래 내용을 복사하세요',r.markdown)}};
    o.querySelector('#rp-audit').onclick=guard(saveChangeRecord);
    o.querySelector('#rp-jira')&&(o.querySelector('#rp-jira').onclick=guard(()=>jiraCommentModal('[Traform ACL] SG 변경 요약\n'+r.markdown)))}})}
async function showUsageReport(q){
  const r=await api('GET','/api/report/usage?q='+encodeURIComponent(q));
  const url=f=>'/api/report/usage?q='+encodeURIComponent(q)+'&format='+f;
  const html=`<div class="mut">검색어 <b>${esc(q)}</b> — 이 값이 쓰이는 규칙 <b>${r.count}</b>건 (IP/대역은 겹침 포함, SG 이름·ID 는 참조 관계 포함)</div>
    <div class="row" style="margin:8px 0"><a class="btn" style="text-decoration:none" href="${url('csv')}">CSV 다운로드</a><button id="us-md">마크다운 복사</button></div>
    ${r.rows.length?`<div style="max-height:46vh;overflow:auto"><table><thead><tr><th>환경</th><th>SG</th><th>방향</th><th>프로토콜</th><th>포트</th><th>소스</th><th>설명</th><th>일치</th></tr></thead><tbody>${r.rows.slice(0,300).map(x=>`<tr><td>${esc(x.env)}</td><td>${esc(x.sg)}</td><td>${x.direction==='ingress'?'인':'아웃'}</td><td>${esc(x.protocol)}</td><td>${esc(x.port)}</td><td>${esc(x.source)}</td><td>${esc(x.description)}</td><td>${esc(x.match)}</td></tr>`).join('')}</tbody></table></div>${r.rows.length>300?'<div class="mut">상위 300건만 표시 — 전체는 CSV 로 받으세요</div>':''}`:'<div class="mut">쓰이는 규칙이 없습니다.</div>'}`;
  await showModal('사용처 보고서',html,'닫기',null,{hideCancel:true,onMount:o=>{o.querySelector('#us-md').onclick=async()=>{try{const t=await fetch(url('md')).then(x=>x.text());await navigator.clipboard.writeText(t);toast('마크다운을 복사했습니다')}catch(e){toast('복사하지 못했습니다: '+e.message,true)}}}})}

// ---------- Atlantis 이어서 하기: plan 다시 실행 / 잠금 해제(확인 필수)
async function startPlan(iid,envId){
  const r=await api('POST',`/api/env/${envId}/atlantis`,{iid,action:'plan'});const key=histKey();
  const hid=addHist(`atlantis plan → MR !${iid}`,r.command,{kind:'plan',state:'pending',headline:'⏳ 응답 대기 중...',poll:{iid,since:r.note_id,action:'plan',envId}});
  pollOut(iid,r.note_id,'plan',hid,key,envId);refreshPlanStatus();return hid}
async function unlockMr(iid,envId){
  if(!await showModal('atlantis unlock 확인',`<div>MR !${esc(iid)} 에 <code>atlantis unlock</code> 코멘트를 남겨 이 MR 이 잡고 있는 plan 잠금을 해제합니다.</div><div class="warnbox" style="margin-top:8px">다른 사람의 plan 에는 영향이 없지만, 이 MR 의 저장된 plan 이 삭제되므로 이후 plan 을 다시 실행해야 합니다. 잠금을 잡고 있는 MR 이 따로 있다면 그 MR 에서 해제해야 할 수 있습니다.</div>`,'unlock 실행',null,{danger:true}))return;
  const r=await api('POST',`/api/env/${envId}/atlantis`,{iid,action:'unlock',confirm_unlock:true});
  addHist(`atlantis unlock → MR !${iid}`,r.command+'\n(Atlantis 가 MR 코멘트로 결과를 답합니다. 잠금이 풀리면 plan 을 다시 실행하세요)',{kind:'unlock',headline:'✓ unlock 요청'});
  toast('unlock 을 요청했습니다. 잠시 후 plan 을 다시 실행하세요',false,6000)}

const presetRow=p=>`<tr class="pr"><td><input type="text" class="pr-n" style="width:100%" placeholder="예: SGP Office" value="${esc(p.name||'')}"></td><td><textarea class="pr-i" style="min-height:44px" placeholder="211.34.57.0/24">${esc((p.ips||[]).join('\n'))}</textarea></td><td style="width:70px"><button class="danger pr-d">삭제</button></td></tr>`;

async function reloadCfg(){const r=await api('GET','/api/config');S.cfg=r.config;S.account=r.account;S.tokenSet=r.token_set;S.paths=r.paths;S.jira=r.jira;
  try{S.services=(await api('GET','/api/services')).services}catch{S.services=S.services||[]}}
(async()=>{
  try{await reloadCfg();S.meta=await api('GET','/api/meta');if(!S.meta.envs)S.meta.envs={}}catch(e){toast(e.message,true);return}
  $('#ticket').value=ls.get('ticket','');$('#ticket').oninput=e=>{ls.set('ticket',e.target.value);clearTimeout(tkTimer);tkTimer=setTimeout(checkTicket,600)};
  {const e0=S.cfg.environments.find(e=>e.id===S.envId);if(e0){S.kind=e0.kind;S.group=e0.group}else S.envId=''}
  renderPickers();if(S.envId)await loadSgs();render();initGlobalSearch();checkTicket();checkVersion();awsPill.init();backupNudge();setInterval(checkVersion,30000);window.addEventListener('focus',checkVersion);
})();
