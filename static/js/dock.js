// ---------- 한 화면에서 끝내기 (v1.17): 작업 바, 진행 패널의 plan/apply, 슬라이드 패널(빠른 작업·SG 보기), 보고서 행 조치,
//            설정 바로가기, 명령 팔레트(Ctrl+K), 위치 복원·뒤로가기, 최근 칩
// 화면을 옮기지 않고도 규칙 수정 → Commit/Push → MR → plan → apply 까지 이어 가도록, 흩어져 있던 동작을 어느 탭에서나 부를 수 있게 모은다.
const DK={st:null,busy:false,tab:'',tm:0,atm:0};
const dkEnvLabel=id=>{const e=((S.cfg&&S.cfg.environments)||[]).find(x=>x.id===id);return e?[e.group,e.env,e.label].filter(Boolean).join(' · '):id};
const sgLink=x=>`<a href="#" class="sgl" data-e="${esc(x.env_id)}" data-s="${esc(x.sg)}" title="SG 규칙 보기·고치기">${esc(x.sg)}</a>`;

// ---- 환경 이동(탭은 그대로): 최근 칩, 팔레트, SG 패널이 함께 쓴다
async function dockGoEnv(envId,o={}){const e=S.cfg.environments.find(x=>x.id===envId);if(!e)return;
  if(S.envId!==envId){S.kind=e.kind;S.group=e.group;S.envId=envId;S.sg=null}
  if(o.tab)S.tab=o.tab;if(o.ticket!==undefined&&$('#ticket')){$('#ticket').value=o.ticket;$('#ticket').dispatchEvent(new Event('input'))}
  persist();renderPickers();await selectEnv();if(o.sg&&S.tab==='acl'&&(S.sgs||[]).some(x=>x.name===o.sg))await openSg(o.sg)}
const dockOpenSg=async(envId,sg)=>{await dockGoEnv(envId,{tab:'acl',sg});toast(`${dkEnvLabel(envId)} → ${sg}`)};

// ---- 1) 작업 바: 어느 탭에서나 브랜치·변경·Commit/Push·MR·plan
function dockBars(){let b=$('#actbar');if(!b){const tb=document.querySelector('.topbar');if(!tb)return null;b=document.createElement('div');b.id='actbar';b.className='actbar';tb.parentNode.insertBefore(b,tb.nextSibling);
    const r=document.createElement('div');r.id='recent';r.className='recent';b.parentNode.insertBefore(r,b.nextSibling)}return b}
const actbarSoon=()=>{clearTimeout(DK.tm);DK.tm=setTimeout(actbarRefresh,250)};
async function actbarRefresh(){const b=dockBars();if(!b)return;
  if(!S.cfg||!S.envId||S.tab==='cfg'||S.tab==='dist'){b.style.display='none';return}
  let st=null;try{st=await api('GET',`/api/env/${S.envId}/git/status`)}catch(e){st=null}
  if(!st||!b.isConnected)return;DK.st=st;const mr=S.mr[S.envId]||{},n=(st.files||[]).length;b.style.display='';
  b.innerHTML=!st.cloned?`<span class="mut">이 환경의 저장소를 아직 받지 않았습니다.</span><button type="button" class="blue" id="ab-dl">저장소 받기</button><span class="ab-r"><button type="button" id="ab-k" title="명령 팔레트">Ctrl+K</button></span>`
   :`<span class="ab-br" title="현재 브랜치">⎇ <b>${esc(st.branch)}</b></span>${st.on_default?'<span class="badge b-warn" title="규칙을 고치려면 작업 브랜치가 필요합니다">작업 브랜치 아님</span><button type="button" class="blue" id="ab-prep">브랜치 준비</button>':''}
     <span class="mut">변경 <b>${n}</b>개</span><button type="button" id="ab-undo" title="가장 최근 저장을 되돌립니다">↶ 되돌리기</button>
     <button type="button" class="blue" id="ab-push" ${n?'':'disabled'} title="변경 내용을 확인하고 Commit & Push">Commit/Push</button>
     ${mr.iid?`<a class="btn" href="${esc(mr.url||'#')}" target="_blank" rel="noopener" title="열려 있는 MR">MR !${esc(mr.iid)}</a>`:'<button type="button" id="ab-mr" title="Merge Request 만들기">MR 만들기</button>'}
     <button type="button" id="ab-plan" ${mr.iid?'':'disabled'} title="atlantis plan 실행">plan</button>
     <span class="ab-r"><button type="button" id="ab-wz" title="빠른 작업을 이 화면 옆 패널로 엽니다">⚡ 빠른 작업</button><button type="button" id="ab-rp" title="규칙 점검 보고서">📑 보고서</button>${S.sg&&S.tab==='acl'?'<button type="button" id="ab-sg" title="현재 SG 의 규칙·메타 데이터 패널">SG 패널</button>':''}<button type="button" id="ab-k" title="명령 팔레트 (Ctrl+K)">Ctrl+K</button></span>`;
  const on=(id,fn)=>{const x=$('#'+id);if(x)x.onclick=guard(fn)};
  on('ab-dl',async()=>{toast('저장소를 받는 중...',false,60000);await api('POST','/api/clone',{env_ids:[S.envId]});toast('저장소를 받았습니다');await selectEnv()});
  on('ab-prep',dockPrep);on('ab-undo',async()=>{const u=await api('GET',`/api/env/${S.envId}/undo`);if(!u.usable)return toast('되돌릴 변경이 없습니다');await undoLast(u)});
  on('ab-push',dockPush);on('ab-mr',dockMakeMr);on('ab-plan',async()=>{await startPlan(mr.iid,S.envId)});
  on('ab-wz',()=>openWizardDrawer());on('ab-rp',()=>openReports());on('ab-sg',()=>openSgPanel(S.envId,S.sg));on('ab-k',openPalette);
  dockRecentDraw()}

async function dockPrep(){let t=(($('#ticket')||{}).value||'').trim().toUpperCase();
  if(!/^[A-Z][A-Z0-9_]+-\d+$/.test(t)){const r=await showModal('브랜치 준비','<label class="f">티켓번호<input type="text" id="dk-t" size="18" placeholder="ISRIR-12345"></label><div class="mut" style="font-size:12px;margin-top:6px">브랜치 이름: 계정/날짜_티켓번호</div>','브랜치 만들기','취소',{collect:o=>({t:o.querySelector('#dk-t').value.trim().toUpperCase()})});
    if(!r)return;t=r.t;if(!/^[A-Z][A-Z0-9_]+-\d+$/.test(t))return toast('티켓번호 형식이 올바르지 않습니다 (예: ISRIR-12345)',true);if($('#ticket')){$('#ticket').value=t;$('#ticket').dispatchEvent(new Event('input'))}}
  toast('진행 중... (clone은 시간이 걸릴 수 있습니다)');const r=await api('POST',`/api/env/${S.envId}/git/prepare`,{ticket:t});
  addHist('브랜치 준비 → '+r.branch,r.log,{kind:'prep',headline:'✓ 브랜치 생성'});toast('브랜치 생성: '+r.branch);dockAfterChange(S.envId)}
async function dockPush(){try{await doPush()}catch(e){addHist('Commit & Push',e.message,{kind:'push',state:'error',headline:'❌ 실패'});throw e}dockAfterChange(S.envId)}
async function dockMakeMr(){const t=(($('#ticket')||{}).value||'').trim(),as=(S.pk&&S.pk.asg)||[],rv=(S.pk&&S.pk.rev)||[];
  const r=await showModal('MR 만들기',`<label class="f">Summary<input type="text" id="dk-s" size="44" value="${esc(t?t+' ':'')}"></label><div class="mut" style="font-size:12px;margin-top:6px">Assignees: ${esc(as.join(', ')||'-')} · Reviewers: ${esc(rv.join(', ')||'-')} (작업 탭 4번 카드의 선택값)</div>`,'MR 만들기','취소',{collect:o=>({s:o.querySelector('#dk-s').value.trim()})});
  if(!r)return;const m=await api('POST',`/api/env/${S.envId}/mr`,{summary:r.s,assignees:as,reviewers:rv});S.mr[S.envId]={iid:m.iid,url:m.url};ls.set('mr',S.mr);
  addHist(m.existing?`기존 MR 연결 → !${m.iid}`:`MR 생성 → !${m.iid}`,`${m.url}\nSummary: ${r.s}`,{kind:'mr',headline:(m.existing?'↺ 기존 MR !':'✓ MR !')+m.iid});toast(m.existing?`이미 열린 MR !${m.iid} 에 연결했습니다`:'MR 을 만들었습니다');dockAfterChange(S.envId)}
// 변경이 있은 뒤: 작업 바·진행 패널·(같은 환경이면) 접근제어 화면을 새로 맞춘다
function dockAfterChange(envId){actbarSoon();atlSoon();if(S.envId===envId&&typeof afterWorkChange==='function')afterWorkChange();dockPanelReload()}

// ---- 2) 진행 패널의 Atlantis: plan 결과와 apply 를 어느 탭에서나
const atlSoon=()=>{clearTimeout(DK.atm);DK.atm=setTimeout(atlRefresh,300)};
async function atlRefresh(){const m=S.mr[S.envId];
  if(!S.cfg||!S.envId||!m||!m.iid||S.tab==='cfg'){UX.atl=null;uxJobDraw();return}
  try{const ps=await api('GET',`/api/env/${S.envId}/atlantis/plan-status?iid=${encodeURIComponent(m.iid)}`);UX.atl={show:!!ps.exists&&!ps.applied,iid:m.iid,envId:S.envId,ps}}catch(e){UX.atl=null}
  uxJobDraw()}
async function atlantisRunApply(iid,envId){
  const ps=await api('GET',`/api/env/${envId}/atlantis/plan-status?iid=${encodeURIComponent(iid)}`);if(!ps.can_apply)throw new Error(ps.reason||'apply 할 수 없습니다');
  const n=ps.plan||{};
  if(!await showModal('atlantis apply 확인',`<div>plan 결과: ${ps.state==='ok'?'✅ 이상 없음':'⚠️ 확인 필요'} — 추가 <b>${n.add||0}</b> / 변경 <b>${n.change||0}</b> / 삭제 <b>${n.destroy||0}</b>${n.replace?` / 교체 <b>${n.replace}</b>`:''}</div>
    ${impactHtml(ps)}${ps.need_confirm?'<div class="warnbox danger" style="margin-top:8px">삭제 또는 교체(삭제 후 재생성)가 포함되어 있습니다. 실제 SG 규칙이 지워지거나 다시 만들어집니다.</div>':''}<div class="mut" style="margin-top:8px">MR !${esc(iid)}</div>`,'apply 실행',null,{danger:true}))return;
  const r=await api('POST',`/api/env/${envId}/atlantis`,{iid,action:'apply',confirm_destroy:!!ps.need_confirm}),key=histKey();
  const hid=addHist(`atlantis apply → MR !${iid}`,r.command,{kind:'apply',state:'pending',headline:'⏳ 응답 대기 중...',poll:{iid,since:r.note_id,action:'apply',envId}});
  pollOut(iid,r.note_id,'apply',hid,key,envId);atlSoon()}

// ---- 3) 슬라이드 패널: 화면을 옮기지 않고 빠른 작업·SG 보기를 연다
function openDrawer(title,html,onMount,key){let d=$('#drawer');
  if(!d){d=document.createElement('aside');d.id='drawer';d.setAttribute('role','dialog');document.body.appendChild(d);
    try{const w=ls.get('dwW',0);if(w>360)d.style.width=Math.min(w,innerWidth*.96)+'px'}catch(e){}}
  d.setAttribute('aria-label',title);d.dataset.key=key||'';
  d.innerHTML='<div class="dw-g" title="끌어서 너비 조절" aria-hidden="true"></div><div class="dw-h"><b class="dw-t"></b><button type="button" class="dw-x" aria-label="패널 닫기">×</button></div><div class="dw-b"></div>';
  d.querySelector('.dw-t').textContent=title;const body=d.querySelector('.dw-b');body.innerHTML=html;d.classList.add('open');d.querySelector('.dw-x').onclick=closeDrawer;
  const g=d.querySelector('.dw-g');g.onpointerdown=e=>{e.preventDefault();g.setPointerCapture(e.pointerId);const mv=ev=>{const w=Math.max(380,Math.min(innerWidth*.96,innerWidth-ev.clientX));d.style.width=w+'px'};
    const up=()=>{g.removeEventListener('pointermove',mv);g.removeEventListener('pointerup',up);ls.set('dwW',d.offsetWidth)};g.addEventListener('pointermove',mv);g.addEventListener('pointerup',up)};
  if(onMount)Promise.resolve(onMount(body,d)).catch(e=>toast(e.message,true));return d}
function closeDrawer(){const d=$('#drawer');if(!d)return;d.classList.remove('open');d.dataset.key='';setTimeout(()=>{if(!d.classList.contains('open'))d.innerHTML=''},220)}
async function openWizardDrawer(o={}){
  if(!S.envId)return toast('상단에서 환경을 먼저 선택하세요',true);
  if(S.tab==='work'&&$('#wzcard')){const c=$('#wzcard');c.open=true;S.wzOpen=true;
    if(o.sg){S.wzSel=new Set([o.sg]);document.querySelectorAll('#wz-sgs .wz-sg').forEach(i=>{i.checked=S.wzSel.has(i.value)});if($('#wz-ips'))$('#wz-ips').dispatchEvent(new Event('input'))}
    c.scrollIntoView({block:'start'});return}
  if(!(S.sgs||[]).length)await loadSgs();if(o.sg)S.wzSel=new Set([o.sg]);
  openDrawer('⚡ 빠른 작업',wizardCard(),async()=>{S.wzOpen=true;const c=$('#wzcard');if(c)c.open=true;await bindWizard()},'wizard')}

// SG 패널: 규칙 보기·삭제·만료 연장, 메타 데이터(별명·담당자·태그) 고치기, 이 SG 에 규칙 추가
async function openSgPanel(envId,sg){
  const r=await api('GET',`/api/env/${envId}/sg/${encodeURIComponent(sg)}/rules`);dockRecordSg(envId,sg);const td=new Date().toISOString().slice(0,10);
  const tags=(r.meta.tags||[]).map(t=>(t.type?t.type+':':'')+t.value).join(', ');
  const html=`<div class="mut">${esc(r.env)}${r.meta.sg_id?' · '+esc(r.meta.sg_id):''}</div>
    ${r.work_branch?'':`<div class="warnbox" style="margin:8px 0">현재 작업 브랜치가 아닙니다${r.branch?' ('+esc(r.branch)+')':''}. 삭제·만료 연장·규칙 추가에는 작업 브랜치가 필요합니다.<div class="row" style="margin-top:6px"><input type="text" id="sp-t" size="16" placeholder="티켓번호" value="${esc((($('#ticket')||{}).value||'').trim())}"><button type="button" class="blue" id="sp-prep">브랜치 준비</button></div></div>`}
    <div class="row" style="margin:8px 0"><button type="button" class="blue" id="sp-add">⚡ 이 SG 에 규칙 추가</button><button type="button" id="sp-open">접근제어 탭에서 열기</button></div>
    <details class="wz-adv"><summary>메타 데이터 (별명 · 담당자 · 태그)</summary><div class="row" style="margin-top:6px;align-items:flex-end"><label class="f">별명<input type="text" id="sp-al" size="18" value="${esc(r.meta.alias)}"></label><label class="f">담당자<input type="text" id="sp-ow" size="14" value="${esc(r.meta.owner)}"></label></div>
      <label class="f" style="margin-top:6px">태그 (유형:값, 쉼표 구분)<input type="text" id="sp-tg" value="${esc(tags)}"></label><div style="margin-top:6px"><button type="button" id="sp-ms">메타 데이터 저장</button></div></details>
    <div style="margin-top:10px"><b>규칙 ${r.rules.length}개</b></div>
    ${r.rules.length?`<table class="rp-t"><thead><tr><th>방향</th><th>프로토콜</th><th>포트</th><th>소스</th><th>설명</th><th>조치</th></tr></thead><tbody>${r.rules.map(x=>`<tr><td class="nw">${x.direction==='ingress'?'인':'아웃'}</td><td class="nw">${esc(x.protocol)}</td><td>${esc(x.port)}</td><td>${esc(x.source)}</td><td>${esc(x.description)}${x.expires?` <span class="badge ${x.expires<td?'b-chg':'b-warn'}">만료 ${esc(x.expires)}</span>`:''}</td>
      <td class="nw"><button type="button" class="sp-act" data-a="ext" data-d="${x.direction}" data-i="${x.idx}" data-g="${esc(x.sig)}">연장</button> <button type="button" class="sp-act danger" data-a="del" data-d="${x.direction}" data-i="${x.idx}" data-g="${esc(x.sig)}">삭제</button></td></tr>`).join('')}</tbody></table>`:'<div class="mut">규칙이 없습니다.</div>'}
    <div class="mut" style="font-size:12px;margin-top:8px">삭제·연장은 파일만 바꿉니다. 화면 위 작업 바의 Commit/Push 로 올리세요.</div>`;
  openDrawer(r.sg,html,body=>{
    uxObserveTables(body,()=>openSgPanel(envId,sg));
    const on=(id,fn)=>{const x=body.querySelector('#'+id);if(x)x.onclick=guard(fn)};
    on('sp-prep',async()=>{const t=body.querySelector('#sp-t').value.trim().toUpperCase();if(!/^[A-Z][A-Z0-9_]+-\d+$/.test(t))return toast('티켓번호 형식이 올바르지 않습니다 (예: ISRIR-12345)',true);
      toast('진행 중... (clone은 시간이 걸릴 수 있습니다)');const p=await api('POST',`/api/env/${envId}/git/prepare`,{ticket:t});addHist('브랜치 준비 → '+p.branch,p.log,{kind:'prep',headline:'✓ 브랜치 생성'});toast('브랜치 생성: '+p.branch);dockAfterChange(envId);openSgPanel(envId,sg)});
    on('sp-add',async()=>{closeDrawer();if(S.envId!==envId)await dockGoEnv(envId);await openWizardDrawer({sg})});
    on('sp-open',async()=>{closeDrawer();await dockOpenSg(envId,sg)});
    on('sp-ms',async()=>{const csv=s=>s.split(',').map(x=>x.trim()).filter(Boolean);
      const tg=csv(body.querySelector('#sp-tg').value).map(t=>{const i=t.indexOf(':');return i>0&&/[^\d.]/.test(t.slice(0,i))?{type:t.slice(0,i),value:t.slice(i+1)}:{type:'',value:t}});
      if(!S.meta.envs)S.meta.envs={};const em=(S.meta.envs[envId]=S.meta.envs[envId]||{});em.sgs=em.sgs||{};const old=em.sgs[sg]||{};
      em.sgs[sg]={...old,sg_id:old.sg_id||r.meta.sg_id||'',alias:body.querySelector('#sp-al').value.trim(),owner:body.querySelector('#sp-ow').value.trim(),tags:tg};
      await api('PUT','/api/meta',S.meta);toast('메타 데이터를 저장했습니다');if($('#sgl'))drawSgList&&drawSgList()});
    body.querySelectorAll('.sp-act').forEach(b=>b.onclick=guard(()=>ruleAction(b.dataset.a,{env_id:envId,sg,direction:b.dataset.d,idx:+b.dataset.i,sig:b.dataset.g})))},'sg:'+envId+'|'+sg)}
function dockPanelReload(){const d=$('#drawer');if(!d||!d.classList.contains('open'))return;const k=d.dataset.key||'';if(!k.startsWith('sg:'))return;const i=k.indexOf('|');openSgPanel(k.slice(3,i),k.slice(i+1)).catch(()=>{})}

// ---- 4) 규칙 한 건 삭제 / 만료 연장 (보고서 행, SG 패널이 함께 사용)
async function ruleAction(kind,o){
  if(kind==='del'){const it=[{env_id:o.env_id,sg:o.sg,direction:o.direction,idx:o.idx,sig:o.sig}],pv=await api('POST','/api/cleanup/apply',{items:it,dry_run:true});
    if(!pv.removed)return toast('그 사이 규칙이 바뀌었습니다. 화면을 새로 고친 뒤 다시 하세요',true);
    if(!await showModal('규칙 삭제',`<div><b>${esc(o.sg)}</b></div><ul>${pv.results.flatMap(x=>x.removed).map(t=>`<li>${esc(t)}</li>`).join('')}</ul><div class="mut">작업 브랜치의 파일만 바뀝니다. 올리려면 화면 위 작업 바의 Commit/Push 를 누르세요.</div>`,'삭제',null,{danger:true}))return;
    await api('POST','/api/cleanup/apply',{items:it,dry_run:false});toast('규칙을 삭제했습니다 (파일만 수정됨 — 위 작업 바에서 Commit/Push)',false,6000)}
  else{const def=new Date(Date.now()+90*864e5).toISOString().slice(0,10);
    const res=await showModal('만료일 연장',`<div><b>${esc(o.sg)}</b> 규칙의 설명에 적힌 만료일을 바꿉니다 (없으면 <code>만료:날짜</code> 를 덧붙입니다).</div><label class="f" style="margin-top:8px">새 만료일 (YYYY-MM-DD)<input type="text" id="ex-d" value="${def}" size="12"></label>`,'연장','취소',{collect:m=>({d:m.querySelector('#ex-d').value.trim()})});
    if(!res)return;const r=await api('POST','/api/rule/extend',{env_id:o.env_id,sg:o.sg,direction:o.direction,idx:o.idx,sig:o.sig,date:res.d});toast('만료일을 연장했습니다: '+r.new,false,6000)}
  dockAfterChange(o.env_id);const rb=$('#rp-body');if(rb&&rb._rerender)rb._rerender()}
document.addEventListener('click',e=>{
  const a=e.target.closest&&e.target.closest('a.sgl');if(a){e.preventDefault();openSgPanel(a.dataset.e,a.dataset.s).catch(x=>toast(x.message,true));return}
  const b=e.target.closest&&e.target.closest('button.rp-act');if(b)guard(()=>ruleAction(b.dataset.a,{env_id:b.dataset.e,sg:b.dataset.s,direction:b.dataset.d,idx:+b.dataset.i,sig:b.dataset.g}))()});

// ---- 5) 문제 해결 바로가기: 오류 알림에 '여기서 설정' 버튼을 붙인다 (탭을 옮기지 않고 작은 창에서 입력)
function uxFixButtons(t,m){const fx=[];
  if(/Jira.*(주소|토큰|API)/.test(m))fx.push(['Jira 설정',fixJira]);
  else if(/GitLab.*(토큰|인증)|토큰.*(입력|필요)|인증\/권한 오류\(40[13]\)/.test(m)&&!/Jira/.test(m))fx.push(['GitLab 토큰 입력',fixToken]);
  if(/AWS.*(로그인|인증)/.test(m)&&typeof awsPill!=='undefined')fx.push(['AWS 로그인 안내',()=>awsPill.click()]);
  if(/repo 로컬 경로|저장소 경로/.test(m))fx.push(['저장소 경로 설정',fixRepoPath]);
  if(/작업 브랜치가 아닙니다/.test(m)&&S.envId)fx.push(['브랜치 준비',dockPrep]);
  const sp=t.querySelector('.tbtn');if(!sp)return;
  fx.forEach(([lab,fn])=>{const b=document.createElement('button');b.type='button';b.className='tfix';b.textContent=lab;b.onclick=()=>{t.style.display='none';Promise.resolve().then(fn).catch(e=>toast(e.message,true))};sp.insertBefore(b,sp.firstChild)})}
async function fixJira(){const j=S.jira||{};
  const r=await showModal('Jira 설정',`<label class="f">Jira 주소<input type="text" id="fx-u" size="34" value="${esc(j.base_url||'https://jira.smilegate.net')}"></label><label class="f" style="margin-top:6px">API 키(토큰)<input type="password" id="fx-t" size="34" autocomplete="off"></label>
    <div class="mut" style="font-size:12px;margin-top:6px">API 키는 이 PC(data/local.json)에만 저장됩니다. 인증 방식·SSL 은 환경설정의 Jira 카드에서 바꿀 수 있습니다.</div>`,'저장','취소',{collect:o=>({u:o.querySelector('#fx-u').value.trim().replace(/\/+$/,''),t:o.querySelector('#fx-t').value})});
  if(!r)return;if(!r.t)return toast('API 키를 입력하세요',true);S.cfg.settings=S.cfg.settings||{};S.cfg.settings.jira_url=r.u;await api('PUT','/api/config',S.cfg);await api('PUT','/api/local',{jira:{token:r.t}});await reloadCfg();
  if(typeof checkTicket==='function')checkTicket();toast('Jira 설정을 저장했습니다')}
async function fixToken(){const kinds=Object.keys(S.cfg.sites||{});
  const r=await showModal('GitLab 토큰 입력',`<label class="f">대상<select id="fx-k">${kinds.map(k=>`<option value="${esc(k)}" ${k===S.kind?'selected':''}>${esc(KIND_LABEL(k))}</option>`).join('')}</select></label><label class="f" style="margin-top:6px">접근 토큰 (api 권한)<input type="password" id="fx-t" size="34" autocomplete="off"></label>
    ${S.account?'':'<label class="f" style="margin-top:6px">계정(브랜치 접두어)<input type="text" id="fx-a" size="18"></label>'}<div class="mut" style="font-size:12px;margin-top:6px">토큰은 이 PC(data/local.json)에만 저장됩니다.</div>`,'저장','취소',{collect:o=>({k:o.querySelector('#fx-k').value,t:o.querySelector('#fx-t').value.trim(),a:o.querySelector('#fx-a')?o.querySelector('#fx-a').value.trim():''})});
  if(!r)return;if(!r.t)return toast('토큰을 입력하세요',true);const body={tokens:{[r.k]:r.t}};if(r.a)body.account=r.a;await api('PUT','/api/local',body);await reloadCfg();toast('토큰을 저장했습니다')}
async function fixRepoPath(){const k=S.kind||Object.keys(S.cfg.sites||{})[0],cur=((S.cfg.defaults||{})[k]||{}).repo_dir||'';
  const r=await showModal('저장소 경로 설정',`<div>${esc(KIND_LABEL(k))} 환경의 저장소를 내려받을 폴더입니다.</div><label class="f" style="margin-top:6px">repo 로컬 경로<input type="text" id="fx-p" size="40" value="${esc(cur)}" placeholder="D:\\GIT\\Infra"></label>`,'저장','취소',{collect:o=>({p:o.querySelector('#fx-p').value.trim()})});
  if(!r)return;if(!r.p)return toast('경로를 입력하세요',true);S.cfg.defaults=S.cfg.defaults||{};(S.cfg.defaults[k]=S.cfg.defaults[k]||{}).repo_dir=r.p;await api('PUT','/api/config',S.cfg);await reloadCfg();toast('저장소 경로를 저장했습니다')}

// ---- 6) 명령 팔레트 (Ctrl+K)
function paletteCommands(){const C=[];const add=(g,t,fn,k)=>C.push({g,t,fn,k:(g+' '+t+' '+(k||'')).toLowerCase()});
  [['work','작업'],['acl','접근제어'],['meta','메타 데이터'],['dist','배포'],['cfg','환경설정']].forEach(([k,t])=>add('이동',t+' 탭',()=>{S.tab=k;persist();return S.envId&&!(S.sgs||[]).length?loadSgs().then(render):render()},'탭 이동 '+k));
  if(S.envId){
    add('작업','빠른 작업 열기 (옆 패널)',()=>openWizardDrawer(),'wizard 마법사 규칙 추가 apply');
    add('작업','Jira 티켓에서 채우기',async()=>{await openWizardDrawer();await ticketFillWizard(false)},'jira ticket 티켓 채우기');
    add('작업','여러 티켓 일괄 처리',async()=>{await openWizardDrawer();await openTicketQueue()},'jira 일괄 batch queue');
    add('작업','요청 양식 보기·복사',()=>openRequestTemplate(),'template 양식');
    add('작업','브랜치 준비',dockPrep,'branch');add('작업','Commit/Push',dockPush,'push commit');add('작업','되돌리기',async()=>{const u=await api('GET',`/api/env/${S.envId}/undo`);if(!u.usable)return toast('되돌릴 변경이 없습니다');await undoLast(u)},'undo');
    add('작업','MR 만들기',dockMakeMr,'merge request');
    const mr=S.mr[S.envId];if(mr&&mr.iid){add('작업',`plan 실행 (MR !${mr.iid})`,()=>startPlan(mr.iid,S.envId),'atlantis');add('작업',`apply 실행 (MR !${mr.iid})`,()=>atlantisRunApply(mr.iid,S.envId),'atlantis')}
    (S.sgs||[]).slice(0,800).forEach(s=>{add('SG','열기: '+s.name,()=>dockOpenSg(S.envId,s.name),'sg');add('SG','패널: '+s.name,()=>openSgPanel(S.envId,s.name),'sg 규칙 메타 담당자')})}
  [['expiry','만료 규칙'],['cleanup','정리 제안'],['reach','접근 경로(IP)'],['refs','SG 관계'],['score','기준 점검'],['ticket','티켓 찾기'],['owners','담당자별'],['audit','감사 보고서']].forEach(([k,t])=>add('보고서',t,()=>openReports(k),'report 보고서 점검'));
  add('도구','도메인 조회…',async()=>{const r=await showModal('도메인 조회','<label class="f">도메인<input type="text" id="pl-d" size="30" placeholder="game.example.com"></label>','조회','취소',{collect:o=>({d:o.querySelector('#pl-d').value.trim()})});if(r&&r.d)await openDomainLookup(r.d)},'domain dns');
  add('도구','서버 로그 보기',()=>showServerLog(),'log');add('도구','화면 색상 바꾸기',()=>{const b=$('#ux-th');if(b)b.click()},'theme dark 다크');
  ls.get('recentEnv',[]).forEach(x=>add('최근',`${dkEnvLabel(x.e)}${x.t?' · '+x.t:''}`,()=>dockGoEnv(x.e,{ticket:x.t||undefined}),'recent'));
  return C}
function openPalette(){if($('#palette')||!S.cfg)return;const o=document.createElement('div');o.id='palette';o.className='modal-ov';
  o.innerHTML='<div class="modal pal" role="dialog" aria-modal="true" aria-label="명령 팔레트"><input type="text" id="pal-q" placeholder="무엇을 할까요? 예) push · 만료 · SG 이름 · 티켓" aria-label="명령 검색" autocomplete="off"><div id="pal-l" class="pal-l" role="listbox"></div><div class="mut" style="font-size:12px;padding:6px 2px 0">↑↓ 선택 · Enter 실행 · Esc 닫기</div></div>';
  document.body.appendChild(o);const q=o.querySelector('#pal-q'),l=o.querySelector('#pal-l'),cmds=paletteCommands();let hit=[],sel=0;
  const draw=()=>{const w=q.value.trim().toLowerCase().split(/\s+/).filter(Boolean);hit=cmds.filter(c=>w.every(x=>c.k.includes(x))).slice(0,60);sel=Math.max(0,Math.min(sel,hit.length-1));
    l.innerHTML=hit.map((c,i)=>`<div role="option" class="pi ${i===sel?'on':''}" data-i="${i}" aria-selected="${i===sel}"><span class="badge b-pending">${esc(c.g)}</span> ${esc(c.t)}</div>`).join('')||'<div class="mut" style="padding:8px">일치하는 명령이 없습니다</div>';
    l.querySelectorAll('.pi').forEach(d=>{d.onclick=()=>run(+d.dataset.i)});const on=l.querySelector('.pi.on');if(on)on.scrollIntoView({block:'nearest'})};
  const close=()=>{o.remove();document.removeEventListener('keydown',kd,true)};
  const run=i=>{const c=hit[i];if(!c)return;close();Promise.resolve().then(()=>c.fn()).catch(e=>toast(e.message,true))};
  const kd=e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close()}else if(e.key==='ArrowDown'){e.preventDefault();sel=Math.min(sel+1,hit.length-1);draw()}else if(e.key==='ArrowUp'){e.preventDefault();sel=Math.max(sel-1,0);draw()}
    else if(e.key==='Enter'&&!e.isComposing){e.preventDefault();e.stopPropagation();run(sel)}};
  document.addEventListener('keydown',kd,true);o.onclick=e=>{if(e.target===o)close()};q.oninput=()=>{sel=0;draw()};draw();q.focus()}
document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&!e.shiftKey&&!e.altKey&&String(e.key).toLowerCase()==='k'){e.preventDefault();openPalette()}
  else if(e.key==='Escape'&&!document.querySelector('.modal-ov')&&$('#drawer')&&$('#drawer').classList.contains('open'))closeDrawer()});

// ---- 7) 위치 복원·뒤로가기: 탭·환경·SG 를 주소(#)에 담고, 탭마다 스크롤 위치를 기억한다
const dockHashStr=()=>'#'+[S.tab&&'tab='+S.tab,S.envId&&'env='+encodeURIComponent(S.envId),S.sg&&S.tab==='acl'&&'sg='+encodeURIComponent(S.sg)].filter(Boolean).join('&');
function dockHashWrite(){if(DK.busy||!S.cfg)return;const h=dockHashStr();if(h.length>1&&h!==location.hash){try{history.pushState(null,'',h)}catch(e){}}}
async function dockHashApply(){const m={};location.hash.replace(/^#/,'').split('&').filter(Boolean).forEach(x=>{const i=x.indexOf('=');if(i>0)m[x.slice(0,i)]=decodeURIComponent(x.slice(i+1))});if(!m.tab||!S.cfg)return;
  DK.busy=true;try{const e=m.env&&S.cfg.environments.find(x=>x.id===m.env);if(e){S.kind=e.kind;S.group=e.group;S.envId=e.id}
    if(['work','acl','meta','dist','cfg'].includes(m.tab))S.tab=m.tab;persist();renderPickers();await selectEnv();if(m.sg&&S.tab==='acl'&&(S.sgs||[]).some(x=>x.name===m.sg))await openSg(m.sg)}finally{DK.busy=false}}
window.addEventListener('popstate',()=>{dockHashApply().catch(()=>{})});
(function wrapRender(){const _r=render;render=function(){const prev=DK.tab;if(prev){try{sessionStorage.setItem('sc:'+prev,String(window.scrollY))}catch(e){}}
  _r.apply(this,arguments);DK.tab=S.tab;
  if(prev&&prev!==S.tab){let y=0;try{y=+sessionStorage.getItem('sc:'+S.tab)||0}catch(e){}setTimeout(()=>window.scrollTo(0,y),80)}
  dockHashWrite();actbarSoon();atlSoon();dockRecordEnv();if(S.tab==='work'&&$('#drawer')&&$('#drawer').dataset.key==='wizard')closeDrawer()};
  const _g=gitStatus;gitStatus=function(){const p=_g.apply(this,arguments);Promise.resolve(p).then(actbarSoon,()=>{});return p};
  const _d=drawDetail;drawDetail=function(){_d.apply(this,arguments);dockHashWrite();if(S.sg)dockRecordSg(S.envId,S.sg);actbarSoon()};
  const _p=refreshPlanStatus;refreshPlanStatus=function(){const p=_p.apply(this,arguments);Promise.resolve(p).then(atlSoon,()=>{});return p}})();

// ---- 8) 최근 칩: 최근에 쓴 환경(+티켓)과 SG 로 한 번에 돌아간다
const dkTicket=()=>{const t=(($('#ticket')||{}).value||'').trim().toUpperCase();return /^[A-Z][A-Z0-9_]+-\d+$/.test(t)?t:''};
function dockRecordEnv(){if(!S.cfg||!S.envId)return;const tk=dkTicket();let r=ls.get('recentEnv',[]).filter(x=>!(x.e===S.envId&&x.t===tk));r.unshift({e:S.envId,t:tk});ls.set('recentEnv',r.slice(0,6));dockRecentDraw()}
function dockRecordSg(e,sg){if(!e||!sg)return;let r=ls.get('recentSg',[]).filter(x=>!(x.e===e&&x.s===sg));r.unshift({e,s:sg});ls.set('recentSg',r.slice(0,6));dockRecentDraw()}
function dockRecentDraw(){const b=$('#recent');if(!b||!S.cfg)return;
  const env=ls.get('recentEnv',[]).filter(x=>S.cfg.environments.some(e=>e.id===x.e)),sg=ls.get('recentSg',[]).filter(x=>S.cfg.environments.some(e=>e.id===x.e));
  if((env.length<2&&!sg.length)||S.tab==='cfg'||S.tab==='dist'){b.style.display='none';return}b.style.display='';
  const cur=S.envId+'|'+dkTicket();
  b.innerHTML='<span class="mut">최근</span>'+env.map((x,i)=>`<button type="button" class="rc ${x.e+'|'+x.t===cur?'on':''}" data-k="e" data-i="${i}" title="이 환경${x.t?'과 티켓':''}으로 이동">${esc(dkEnvLabel(x.e))}${x.t?' · '+esc(x.t):''}</button>`).join('')
    +(sg.length?'<span class="mut">SG</span>':'')+sg.map((x,i)=>`<button type="button" class="rc" data-k="s" data-i="${i}" title="${esc(dkEnvLabel(x.e))}">${esc(x.s)}</button>`).join('');
  b.querySelectorAll('.rc').forEach(c=>{c.onclick=guard(async()=>{const x=(c.dataset.k==='e'?env:sg)[+c.dataset.i];if(c.dataset.k==='e')await dockGoEnv(x.e,{ticket:x.t});else await openSgPanel(x.e,x.s)})})}
document.addEventListener('input',e=>{if(e.target&&e.target.id==='ticket'){clearTimeout(DK.rt);DK.rt=setTimeout(dockRecordEnv,900)}});

// ---- 시작: 처음 한 번 작업 바를 만들고, 주소에 위치가 있으면 그 자리로 이동한다
(function dockInit(){dockBars();let n=0;const t=setInterval(()=>{n++;if(S.cfg){clearInterval(t);DK.tab=S.tab;
    if(location.hash.length>1)dockHashApply().catch(()=>{});else{try{history.replaceState(null,'',dockHashStr())}catch(e){}}actbarSoon();atlSoon()}else if(n>60)clearInterval(t)},250);
  setInterval(()=>{if(!document.hidden&&S.cfg&&S.envId&&S.tab!=='cfg'){actbarRefresh();atlRefresh()}},15000)})();
