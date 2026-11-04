// ---------- 작업 (Git/MR/Atlantis)
function viewWork(){
  const e=env();
  if(!e){$('#view').innerHTML='<div class="card" id="repos"></div><div class="card mut">상단에서 유형 → 종류 → 환경을 선택하면 브랜치 / Commit·Push / MR / Atlantis 단계가 활성화됩니다. (저장소 다운로드는 위에서 바로 가능)</div><div class="card" id="hist"></div>';drawRepos();drawHist();loadHist(histKey());return}
  const mr=S.mr[S.envId]||{};
  $('#view').innerHTML=`
  <div class="card" id="repos"></div>
  ${workHint()}
  ${wizardCard()}
  <div class="wgrid">
    <div class="card"><h3>2. 브랜치 준비 <span id="st-prep"></span></h3>
      <div class="mut" style="margin-bottom:8px">clone → ${esc(e.target_branch||'main')} 최신화 → <code>계정/${today()}_티켓[_입력문자]</code> 브랜치 생성</div>
      <div class="row"><button class="blue" id="prep">clone / 브랜치 생성</button><input type="text" id="bsuf" size="22" maxlength="40" placeholder="브랜치 뒤에 붙일 문자 (선택)" aria-label="브랜치 이름 뒤에 붙일 문자" title="예: 입력하면 heejim/261023_ISRIR-69431_입력문자 로 생성됩니다. 비우면 붙이지 않습니다"><button id="gst">상태 새로고침</button></div>
      <div class="mut" style="font-size:12px;margin-top:4px">생성될 브랜치: <code id="bpv"></code></div>
      <div class="mut" style="font-size:12px;margin-top:6px">${esc(e.repo_dir)}</div><div id="gs" style="margin-top:8px"></div></div>
    <div class="card"><h3>3. 파일 수정 후 Commit / Push <span id="st-push"></span></h3>
      <div class="mut">접근제어 탭에서 수정 → <code>git add -A</code> → <code>git commit -m [브랜치]</code> → <code>git push origin --set-upstream [브랜치]</code></div>
      <div style="margin-top:10px" class="row"><button class="blue" id="push">Commit &amp; Push</button><button id="rpt" title="이번 작업의 변경 규칙·영향 SG·위험 규칙 요약 (MR/Jira 에 붙이기)">변경 요약 보고서</button><button id="xls" title="이번 작업의 변경 규칙을 엑셀 ACL 적용내역 시트에 한 건당 한 줄로 기록합니다">엑셀 기록</button></div></div>
  </div>
  <div class="wgrid">
    <div class="card"><h3>4. Merge Request 생성 <span id="st-mr"></span> <span class="mut" style="font-weight:400">(${esc(e.project||'프로젝트 미설정')})</span></h3>
      <div class="row" style="align-items:flex-start;gap:20px"><div class="f" style="min-width:240px;flex:1">Assignees<div class="pk" id="pk-asg"></div></div>
        <div class="f" style="min-width:240px;flex:1">Reviewers<div class="pk" id="pk-rev"></div></div></div>
      <label class="f" style="margin-top:8px">MR Type (고정)<input type="text" id="mrt" value="SG 정책 추가/변경/삭제" readonly style="background:var(--bg)"></label>
      <div id="mrex" class="mut" style="font-size:12.5px;margin-top:8px"></div>
      <label class="f" style="margin-top:8px">Summary (실제 작업 내용 요약)<textarea id="sum" placeholder="예: match3 서버에서 ar-tsv 6001 포트 접근 허용"></textarea></label>
      <div style="margin-top:8px" class="row"><button class="blue" id="mkmr">MR 생성</button>${S.jira&&S.jira.enabled?'<button id="jsum" title="Jira 이슈 제목을 Summary 로 채움">Jira 제목으로 채우기</button>':''}<span id="mrinfo">${mr.url?`<a href="${esc(mr.url)}" target="_blank">MR !${mr.iid}</a>`:''}</span>
        <span class="mut">기존 MR iid:</span><input type="text" id="iid" size="6" value="${esc(mr.iid||'')}"></div></div>
    <div class="card"><h3>5. Atlantis <span id="st-atl"></span></h3>
      <div class="row"><label class="f" style="flex-direction:row;align-items:center;gap:6px">-d <select id="atenv">${S.cfg.environments.filter(x=>x.kind===S.kind&&(S.kind==='platform'||x.group===S.group)).map(x=>`<option value="${esc(x.id)}" ${x.id===S.envId?'selected':''}>${esc(atDir(x))}</option>`).join('')}</select></label></div>
      <div class="row" style="margin-top:10px"><button class="blue" id="plan">atlantis plan</button><button class="pri" id="apply">atlantis apply</button></div>
      <div id="plst" class="mut" style="font-size:12.5px;margin-top:8px"></div>
      <div class="mut" style="font-size:12px;margin-top:4px">apply 는 같은 MR 커밋에서 성공한 plan 이 있을 때만 가능하며, 삭제/교체가 있으면 한 번 더 확인합니다. 결과(Show Output)는 아래 <b>작업 이력</b>에 표시됩니다.</div></div>
  </div>
  <div class="card" id="hist"></div>`;
  // 실행 + 결과/오류를 작업 이력에 기록
  const track=(step,kind,fn)=>guard(async()=>{try{return await fn()}catch(err){addHist(step,err.message,{kind,state:'error',headline:'❌ 실패'});throw err}});
  const bprev=()=>{const el=$('#bpv');if(!el)return;const t=($('#ticket')||{}).value?.trim()||'티켓',s=branchSuffix($('#bsuf').value);el.textContent=`${S.account||'계정'}/${today()}_${t}${s?'_'+s:''}`};
  $('#bsuf').oninput=bprev;$('#ticket').addEventListener('input',bprev);bprev();
  $('#prep').onclick=track('브랜치 준비','prep',async()=>{const t=$('#ticket').value.trim();if(!t)return toast('상단에 티켓번호를 입력하세요',true);
    toast('진행 중... (clone은 시간이 걸릴 수 있습니다)');const r=await api('POST',`/api/env/${S.envId}/git/prepare`,{ticket:t,suffix:$('#bsuf').value});$('#bsuf').value='';bprev();
    addHist('브랜치 준비 → '+r.branch,r.log,{kind:'prep',headline:'✓ 브랜치 생성'});toast('브랜치 생성: '+r.branch);gitStatus(true)});
  $('#gst').onclick=()=>gitStatus(true);
  $('#xls').onclick=()=>excelRecordModal(S.envId,false);
  $('#push').onclick=track('Commit & Push','push',doPush);
  $('#rpt').onclick=guard(showChangeReport);
  peoplePicker('pk-asg','asg');peoplePicker('pk-rev','rev');
  $('#jsum')&&($('#jsum').onclick=guard(()=>jiraFill('#sum')));
  $('#mkmr').onclick=track('MR 생성','mr',async()=>{const r=await api('POST',`/api/env/${S.envId}/mr`,{summary:$('#sum').value,assignees:S.pk.asg,reviewers:S.pk.rev});
    S.mr[S.envId]={iid:r.iid,url:r.url};ls.set('mr',S.mr);
    if(r.existing){addHist(`기존 MR 연결 → !${r.iid}`,`${r.url}\n같은 브랜치로 이미 열린 MR 이 있어 새로 만들지 않았습니다 (기존 MR 은 변경하지 않음)`,{kind:'mr',headline:'↺ 기존 MR !'+r.iid+' 사용'});toast(`이미 열린 MR !${r.iid} 이 있어 새로 만들지 않고 연결했습니다`,false,6000)}
    else{addHist(`MR 생성 → !${r.iid}`,`${r.url}\nAssignees: ${S.pk.asg.join(', ')||'-'}\nReviewers: ${S.pk.rev.join(', ')||'-'}\nSummary: ${$('#sum').value.trim()}`,{kind:'mr',headline:'✓ MR !'+r.iid});toast('MR 생성됨')}
    viewWork()});
  $('#iid').onchange=ev=>{S.mr[S.envId]={iid:ev.target.value.trim()};ls.set('mr',S.mr);refreshPlanStatus()};
  $('#atenv').onchange=refreshPlanStatus;
  const run=a=>track('atlantis '+a,a,async()=>{const iid=$('#iid').value.trim();if(!iid)return toast('MR iid가 필요합니다',true);
    S.atEnv=$('#atenv')?$('#atenv').value:S.envId;let confirmDestroy=false;
    if(a==='apply'){
      const ps=await api('GET',`/api/env/${S.atEnv}/atlantis/plan-status?iid=${encodeURIComponent(iid)}`);
      if(!ps.can_apply)throw new Error(ps.reason||'apply 할 수 없습니다');
      const n=ps.plan||{};
      if(!await showModal('atlantis apply 확인',`<div>plan 결과: ${ps.state==='ok'?'✅ 이상 없음':'⚠️ 확인 필요'} — 추가 <b>${n.add||0}</b> / 변경 <b>${n.change||0}</b> / 삭제 <b>${n.destroy||0}</b>${n.replace?` / 교체 <b>${n.replace}</b>`:''}</div>
        ${impactHtml(ps)}${ps.need_confirm?'<div class="warnbox danger" style="margin-top:8px">삭제 또는 교체(삭제 후 재생성)가 포함되어 있습니다. 실제 SG 규칙이 지워지거나 다시 만들어집니다.</div>':''}
        <div class="mut" style="margin-top:8px">MR !${esc(iid)} · -d ${esc(atDir(S.cfg.environments.find(x=>x.id===S.atEnv)))}</div>`,'apply 실행',null,{danger:true}))return;
      confirmDestroy=ps.need_confirm;
    }
    const r=await api('POST',`/api/env/${S.atEnv}/atlantis`,{iid,action:a,confirm_destroy:confirmDestroy});
    const key=histKey(),hid=addHist(`atlantis ${a} → MR !${iid}`,r.command,{kind:a,state:'pending',headline:'⏳ 응답 대기 중...',poll:{iid,since:r.note_id,action:a,envId:S.atEnv}});
    pollOut(iid,r.note_id,a,hid,key,S.atEnv);refreshPlanStatus()});
  $('#plan').onclick=run('plan');$('#apply').onclick=run('apply');
  gitStatus();drawRepos();drawHist();loadHist(histKey());refreshPlanStatus();refreshExistingMr();bindWizard();
}
// 이 작업 브랜치로 이미 열린 MR 이 있으면 안내하고 MR iid 를 자동으로 연결 (중복 MR 방지: 서버도 중복 생성을 막음)
async function refreshExistingMr(){const el=$('#mrex');if(!el||!S.envId)return;
  try{const r=await api('GET',`/api/env/${S.envId}/mr/existing`);if(!$('#mrex'))return;
    if(!r.exists){el.innerHTML='';const b=$('#mkmr');if(b)b.textContent='MR 생성';return}
    S.mr[S.envId]={iid:r.iid,url:r.url};ls.set('mr',S.mr);const i=$('#iid');if(i&&i.value!==String(r.iid)){i.value=r.iid;refreshPlanStatus()}
    el.innerHTML=`ℹ️ 이 브랜치(<b>${esc(r.branch)}</b>)로 이미 열린 MR <a href="${esc(r.url)}" target="_blank">!${r.iid}</a> 이 있습니다. 새로 만들지 않고 이 MR 을 사용합니다 (생성 버튼을 눌러도 중복 생성되지 않습니다).`;
    const b=$('#mkmr');if(b)b.textContent='기존 MR 연결'}catch(e){/* 토큰 없음/네트워크 오류는 무시 */}}
// ---------- 저장소 다운로드: 플랫폼은 단일 저장소, 게임은 상단에서 고른 게임의 저장소(전체 게임 보기로 여러 개 선택)
const repoOf=e=>{const project=e.project||S.cfg.defaults[e.kind]?.project||'';   // 경로를 비우면 서버가 repos/<프로젝트> 를 쓰므로 같은 기준으로 비교한다
  return{id:e.id,group:e.group,label:e.label||e.env,dir:e.repo_dir||S.cfg.defaults[e.kind]?.repo_dir||(project?'repos/'+project.replace(/^\/+|\/+$/g,'').replace(/\//g,'__'):''),project}};
async function drawRepos(){
  const box=$('#repos');if(!box)return;
  const seen=new Set(),list=[];
  S.cfg.environments.filter(e=>e.kind===S.kind&&(S.kind!=='game'||S.repoAll||!S.group||e.group===S.group)).forEach(e=>{const r=repoOf(e);const k=(r.dir||r.id).toLowerCase();if(!seen.has(k)){seen.add(k);list.push(r)}});
  const rows=S.kind==='platform'?list.slice(0,1):list;
  const st={};await Promise.all(rows.map(async r=>{try{st[r.id]=(await api('GET',`/api/env/${r.id}/git/status`)).cloned}catch{st[r.id]=false}}));
  const multi=S.kind==='game';
  if($('#repos')!==box)return;
  box.innerHTML=`<h3>1. 저장소 다운로드 <span id="st-dl"></span> <span class="mut" style="font-weight:400">(${multi?'게임: 여러 저장소 선택 가능':'플랫폼: 일괄 다운로드 (종류/환경 선택 불필요)'})</span></h3>
    ${multi?`<div class="row" style="margin-bottom:8px"><input type="text" id="rpq" style="flex:1" placeholder="저장소 필터 (게임/프로젝트/경로)" value="${esc(S.rpq||'')}">
      <label><input type="checkbox" id="rpall" ${S.repoAll?'checked':''}> 전체 게임 저장소 보기</label></div>
    <div class="mut" style="font-size:12px;margin-bottom:6px">${S.repoAll||!S.group?'모든 게임의 저장소를 표시합니다.':`상단에서 선택한 게임(<b>${esc(S.group)}</b>)의 저장소만 표시합니다. 다른 게임도 받으려면 "전체 게임 저장소 보기"를 체크하세요.`}</div>`:''}
    <table><tbody>${rows.map(r=>`<tr class="rprow" data-t="${esc([r.group,r.project,r.dir].join(' ').toLowerCase())}">${multi?`<td style="width:30px"><input type="checkbox" class="rp" value="${esc(r.id)}" ${(!S.repoAll&&S.group)||r.id===S.envId?'checked':''}></td>`:''}
      <td><b>${esc(multi?r.group:KIND_LABEL(S.kind))}</b><br><span class="mut" style="font-size:12px">${esc(r.project||'프로젝트 미설정')}</span></td>
      <td class="mut">${esc(r.dir)}</td><td>${st[r.id]?'<span class="badge b-ok">다운로드됨</span>':'<span class="badge b-pending">없음</span>'}</td></tr>`).join('')||'<tr><td class="mut">등록된 환경이 없습니다 (환경설정)</td></tr>'}</tbody></table>
    <div style="margin-top:8px" class="row"><button class="blue" id="dl">${multi?'선택 항목 다운로드/업데이트':'다운로드/업데이트'}</button><label class="f" style="flex-direction:row;align-items:center;gap:6px">기존 폴더가 있을 때
        <select id="fmode"><option value="keep">유지 (최신 정보만 가져오기)</option><option value="backup">백업 후 새로 받기</option><option value="delete">삭제 후 새로 받기 (복구 불가)</option></select></label><span class="mut" id="dlmsg"></span></div>`;
  if(multi){const rpf=()=>{S.rpq=$('#rpq').value;const ws=S.rpq.trim().toLowerCase().split(/\s+/).filter(Boolean);
    box.querySelectorAll('.rprow').forEach(r=>r.style.display=ws.every(w=>r.dataset.t.includes(w))?'':'none')};$('#rpq').oninput=rpf;rpf();
    $('#rpall').onchange=e=>{S.repoAll=e.target.checked;drawRepos()}}
  $('#dl').onclick=guard(async()=>{const ids=multi?[...box.querySelectorAll('.rprow:not([style*="none"]) .rp:checked')].map(c=>c.value):rows.map(r=>r.id);
    if(!ids.length)return toast('다운로드할 저장소를 선택하세요',true);
    const mode=$('#fmode').value,dirs=rows.filter(r=>ids.includes(r.id)).map(r=>r.dir).join('\n');
    let confirmTxt;
    if(mode==='backup'&&!confirm('기존 폴더를 삭제하지 않고 이름을 "_backup_날짜시간" 으로 바꾼 뒤 새로 받습니다.\n(커밋하지 않은 변경도 백업 폴더에 그대로 남습니다)\n\n대상 폴더:\n'+dirs+'\n\n진행할까요?'))return;
    if(mode==='delete')confirmTxt='delete';  // 선택 자체가 확인: 별도 확인창 없이 바로 진행
    $('#dlmsg').textContent='진행 중... (clone은 시간이 걸릴 수 있습니다)';
    let r;try{r=await api('POST','/api/clone',{env_ids:ids,mode,confirm:confirmTxt})}catch(err){addHist('저장소 다운로드',err.message,{kind:'dl',state:'error',headline:'❌ 실패'});throw err}
    const bad=r.results.filter(x=>x.error),bk=r.results.filter(x=>x.backup).map(x=>'백업('+(x.backup_mode==='copied'?'폴더 사용 중이라 복사 후 원격 기준으로 초기화':'폴더 이름 변경')+'): '+x.backup);
    if(bad.length)toast(bad.map(b=>b.project+': '+b.error).join('\n'),true);else toast('완료: '+r.results.map(x=>x.result).join(', ')+(bk.length?'\n'+bk.join('\n'):''));
    addHist('저장소 다운로드 ('+({keep:'유지',backup:'백업 후 새로 받기',delete:'삭제 후 새로 받기'})[mode]+')',r.results.map(x=>(x.error?'❌ ':'✓ ')+x.project+' → '+(x.error||x.result)+(x.backup?'\n   백업: '+x.backup:'')).join('\n'),{kind:'dl',state:bad.length?'error':'ok',headline:bad.length?'❌ 일부 실패':'✓ '+r.results.map(x=>x.result).join(', ')});
    drawRepos()});
}
// ---------- Assignees / Reviewers 선택: 프로젝트 멤버 검색 후 여러 명 추가 (선택값은 브라우저에 기억)
S.pk=S.pk||ls.get('pk',null)||{asg:[],rev:[]};
function peoplePicker(id,key){
  const box=$('#'+id);if(!box)return;
  if(key==='asg'&&!S.pk.asg.length&&!S.pk.asgInit&&S.account){S.pk.asg=[S.account];S.pk.asgInit=true}
  const save=()=>ls.set('pk',S.pk);
  const draw=()=>{
    box.innerHTML=`<div style="margin:2px 0">${S.pk[key].map((u,i)=>`<span class="tag" style="font-size:12.5px">@${esc(u)} <a data-x="${i}" style="cursor:pointer" title="제거">✕</a></span>`).join('')||'<span class="mut" style="font-weight:400">선택 없음</span>'}</div>
      <div style="position:relative"><input type="text" class="pq" style="width:100%" placeholder="이름 / ID 검색 (Enter: 입력한 ID 추가)"><div class="pkp" style="display:none"><div class="list"></div></div></div>`;
    box.querySelectorAll('[data-x]').forEach(a=>a.onclick=()=>{S.pk[key].splice(+a.dataset.x,1);save();draw()});
    const q=box.querySelector('.pq'),pop=box.querySelector('.pkp'),list=pop.querySelector('.list');let timer;
    const add=u=>{u=String(u).trim().replace(/^@/,'');if(u&&!S.pk[key].includes(u)){S.pk[key].push(u);save()}draw()};
    q.oninput=()=>{clearTimeout(timer);const t=q.value.trim();if(!t){pop.style.display='none';return}
      timer=setTimeout(async()=>{try{const us=await api('GET',`/api/env/${S.envId}/assignees?q=${encodeURIComponent(t)}`);
        list.innerHTML='';us.filter(u=>!S.pk[key].includes(u.username)).forEach(u=>{const d=document.createElement('div');d.textContent=`${u.name} (@${u.username})`;d.onmousedown=e=>{e.preventDefault();add(u.username)};list.appendChild(d)});
        if(!list.children.length)list.innerHTML='<div class="mut">검색 결과 없음 (Enter로 직접 추가)</div>';pop.style.display=''}
        catch(e){list.innerHTML=`<div class="mut">검색 실패: ${esc(e.message).slice(0,80)} (Enter로 직접 추가)</div>`;pop.style.display=''}},250)};
    q.onkeydown=e=>{if(e.key==='Enter'&&q.value.trim()){e.preventDefault();add(q.value)}};
    q.onblur=()=>setTimeout(()=>pop.style.display='none',150);
  };
  draw();
}
const atDir=e=>e.atlantis_dir||e.sg_dir.replace(/\/[^/]*$/,'');
// 작업 이력: 서버(data/history.json)에 보관 → 새로고침/다른 브라우저·PC에서도 유지. 키는 GitLab 프로젝트 경로(저장소 단위)
const histKey=()=>{const e=env();if(!e)return 'kind:'+(S.kind||'')+':'+(S.group||'');const r=repoOf(e);return (r.project||r.dir).toLowerCase()};
const HK={dl:'저장소 다운로드',prep:'브랜치 준비',rule:'규칙 추가/수정',push:'Commit/Push',mr:'MR 생성',plan:'Atlantis plan',apply:'Atlantis apply',unlock:'Atlantis unlock'};
const histKind=x=>x.kind||(String(x.step).startsWith('브랜치')?'prep':String(x.step).startsWith('Commit')?'push':'');
S.hist=S.hist||{};S.pollers=S.pollers||{};
const histLoad=k=>S.hist[k]||[];
const histFail=e=>toast('작업 이력을 서버에 저장하지 못했습니다: '+e.message,true);
async function loadHist(k){
  try{await Promise.allSettled(S.hq||[]);S.hq=[];   // 방금 추가한 항목의 저장이 끝난 뒤에 읽어서 덮어쓰지 않도록
    const r=await api('GET','/api/history?key='+encodeURIComponent(k));let list=r.entries;
    if(!list.length){   // 예전 버전(브라우저 저장) 이력이 있으면 한 번만 서버로 옮긴다
      const all=ls.get('gitHist',{}),e=env(),old=(all[k]||(e?all[repoOf(e).dir.toLowerCase()]:null)||[]).map((x,i)=>({...x,id:x.id||'old'+i+'_'+(x.t||'')}));
      if(old.length){await api('POST','/api/history/import',{key:k,entries:old});list=old}}
    S.hist[k]=list}catch(e){/* 서버를 읽지 못하면 화면의 임시 목록 유지 */}
  if(k===histKey()){drawHist();resumePolls(k)}}
function addHist(step,text,o={}){
  const k=o.key||histKey(),id='h'+Date.now()+Math.random().toString(36).slice(2,6);
  const x={id,ts:Date.now(),t:new Date().toLocaleString('ko-KR',{hour12:false}),step,kind:o.kind||'',state:o.state||'ok',headline:o.headline||'',text:String(text||'').trim().slice(0,80000),user:S.account||''};
  if(o.poll)x.poll=o.poll;if(o.meta)x.meta=o.meta;
  (S.hist[k]=S.hist[k]||[]).push(x);S.hist[k]=S.hist[k].slice(-200);S.hopen=S.hopen||{};S.hopen[id]=true;drawHist();
  (S.hq=S.hq||[]).push(api('POST','/api/history',{key:k,entry:x}).catch(histFail));return id}
function updateHist(k,id,patch){const x=histLoad(k).find(i=>i.id===id);if(!x)return;
  if(patch.text!=null)patch.text=String(patch.text).slice(0,80000);Object.assign(x,patch);if(k===histKey())drawHist();
  const send={...patch};delete send.id;(S.hq=S.hq||[]).push(api('PATCH','/api/history/'+encodeURIComponent(id),{key:k,patch:send}).catch(histFail))}
function drawChips(){const list=histLoad(histKey());
  [['st-dl',['dl']],['st-prep',['prep']],['st-push',['push']],['st-mr',['mr']],['st-atl',['plan','apply']]].forEach(([id,kinds])=>{const el=document.getElementById(id);if(!el)return;
    const x=[...list].reverse().find(i=>kinds.includes(histKind(i)));
    el.className='badge '+(x?'b-'+(x.state==='pending'?'pending':x.state):'');
    el.textContent=x?`${x.state==='ok'?'✓':x.state==='error'?'✗':x.state==='warn'?'!':'…'} ${x.ts?new Date(x.ts).toTimeString().slice(0,5):''}`:''})}
function drawHist(){
  drawChips();const box=$('#hist');if(!box)return;
  const k=histKey(),all=[...histLoad(k)].reverse(),f=S.hf||'';
  const list=all.filter(x=>!f||histKind(x)===f);
  box.innerHTML=`<div class="row"><h3 style="margin:0">작업 이력</h3><span class="mut">${list.length} / ${all.length}건 · 최신순 · 서버에 저장되어 다른 PC/브라우저에서도 보입니다</span>
    <span style="margin-left:auto" class="row"><select id="hf"><option value="">전체</option>${Object.entries(HK).map(([v,t])=>`<option value="${v}" ${f===v?'selected':''}>${t}</option>`).join('')}</select>
      <button id="hclr">이력 지우기</button></span></div>
    <div id="hl" style="margin-top:10px">${list.map((x,i)=>{const kd=histKind(x),plan=kd==='plan'||kd==='apply',st=x.state||'ok',open=(S.hopen||{})[x.id]??(i===0);
      return `<details class="he" data-id="${x.id}" ${open?'open':''}><summary><span class="mut">[${esc(x.t)}]</span> <b>${esc(x.step)}</b>${x.user?` <span class="mut" style="font-size:12px">@${esc(x.user)}</span>`:''}
        <span class="badge b-${st==='pending'?'pending':st}">${esc(x.headline||({ok:'완료',error:'실패',warn:'확인 필요',pending:'진행 중'})[st]||st)}</span></summary>
        ${(x.hint&&(x.state==='error'||x.state==='warn'))?hintBox(x):''}${x.meta&&x.meta.wz?`<div style="margin-bottom:6px"><button class="wzc" data-id="${x.id}">마법사로 복제</button></div>`:''}${(S.jira&&S.jira.enabled&&['mr','plan','apply','push'].includes(kd))?`<div style="margin-bottom:6px"><button class="jc" data-id="${x.id}">Jira 코멘트</button></div>`:''}${x.text?(plan?`<pre class="plan">${colorizePlan(x.text)}</pre>`:`<pre>${esc(x.text)}</pre>`):''}</details>`}).join('')||'<div class="mut">아직 이력이 없습니다. 위 단계를 실행하면 결과가 여기에 쌓입니다.</div>'}</div>`;
  $('#hf').onchange=e=>{S.hf=e.target.value;drawHist()};
  $('#hclr').onclick=guard(async()=>{if(!confirm('이 저장소의 작업 이력을 모두 지울까요? (서버에서 삭제됩니다)'))return;
    await api('DELETE','/api/history?key='+encodeURIComponent(k));S.hist[k]=[];drawHist()});
  box.querySelectorAll('details.he').forEach(d=>d.ontoggle=()=>{S.hopen=S.hopen||{};S.hopen[d.dataset.id]=d.open});
  const ent=b=>histLoad(k).find(e=>e.id===b.dataset.id);
  box.querySelectorAll('.jc').forEach(b=>b.onclick=guard(()=>jiraComment(ent(b))));
  box.querySelectorAll('.wzc').forEach(b=>b.onclick=()=>fillWizard(ent(b).meta.wz));
  box.querySelectorAll('.hb-retry').forEach(b=>b.onclick=guard(()=>startPlan(ent(b).poll.iid,ent(b).poll.envId)));
  box.querySelectorAll('.hb-push').forEach(b=>b.onclick=()=>{const t=$('#push');if(t){t.scrollIntoView({block:'center'});t.focus()}});
  box.querySelectorAll('.hb-unlock').forEach(b=>b.onclick=guard(()=>unlockMr(ent(b).poll.iid,ent(b).poll.envId)))}
const hintBox=x=>`<div class="warnbox ${x.state==='error'?'danger':''}" style="margin-bottom:6px">💡 ${esc(x.hint)}<div class="row" style="margin-top:6px">${x.poll?`<button class="hb-retry" data-id="${x.id}">plan 다시 실행</button>`:''}${['branch_missing','tf_error'].includes(x.ekind)?`<button class="hb-push" data-id="${x.id}">Commit/Push 로 이동</button>`:''}${x.ekind==='lock'&&x.poll?`<button class="danger hb-unlock" data-id="${x.id}">atlantis unlock...</button>`:''}</div></div>`;
// 새로고침으로 끊긴 Atlantis 조회를 이어서 한다 (이력의 pending 항목 + 조회 정보 사용)
function resumePolls(k){histLoad(k).filter(x=>x.state==='pending'&&x.poll&&!S.pollers[x.id]).forEach(x=>{
  if(Date.now()-(x.ts||0)>15*60*1000)updateHist(k,x.id,{state:'warn',headline:'⏳ 응답 없음 (시간 초과)'});
  else pollOut(x.poll.iid,x.poll.since,x.poll.action,x.id,k,x.poll.envId)})}
const _gitStatusRun=guard(async(force)=>{const s=await api('GET',`/api/env/${S.envId}/git/status${force?'?fresh=1':''}`);const g=$('#gs');if(!g)return;
  g.innerHTML=!s.cloned?'<span class="mut">아직 clone 되지 않음</span>':`브랜치: <b>${esc(s.branch)}</b> · 변경 ${s.files.length}개${s.files.length?(s.is_new?' <span class="badge b-warn">신규 파일 포함</span>':' <span class="badge b-ok">기존 파일 수정</span>'):''}
    ${s.files.map(f=>`<div class="mut">${esc(f.state)} — ${esc(f.path)}${(s.out_of_scope||[]).some(o=>o.path===f.path)?' <span class="badge b-pending">커밋 제외 (SG 폴더 밖)</span>':''}</div>`).join('')}${s.on_default?'<div class="warnbox danger" style="margin-top:6px">현재 기본 브랜치입니다. 브랜치 준비 후 수정하세요.</div>':''}<div class="row" id="wtools-work" style="margin-top:8px"></div>`;if(s.cloned)drawWorkTools(g.querySelector('#wtools-work'))});
async function refreshPlanStatus(){const el=$('#plst'),iid=($('#iid')||{}).value;if(!el)return;
  if(!iid||!iid.trim()){el.textContent='';return}
  try{const e=$('#atenv')?$('#atenv').value:S.envId;const ps=await api('GET',`/api/env/${e}/atlantis/plan-status?iid=${encodeURIComponent(iid.trim())}`);if(!$('#plst'))return;
    const n=ps.plan||{};el.innerHTML=!ps.exists?'마지막 plan: 없음 → apply 불가 (먼저 atlantis plan)':
      `마지막 plan: ${({ok:'✅ 이상 없음',warn:'⚠️ 확인 필요',error:'❌ 실패',pending:'⏳ 대기 중'})[ps.state]||ps.state}${n.add!=null?` (추가 ${n.add} / 변경 ${n.change} / 삭제 ${n.destroy}${n.replace?` / 교체 ${n.replace}`:''})`:''} · `+
      (ps.can_apply?(ps.need_confirm?'<b>apply 가능 (삭제/교체 확인 필요)</b>':'<b>apply 가능</b>'):`<span style="color:var(--err)">apply 불가 — ${esc(ps.reason||'')}</span>`)}
  catch(e){const el2=$('#plst');if(el2)el2.textContent=''}}
// Atlantis 응답을 4초마다 조회해서 작업 이력 항목(hid)을 갱신 (여러 건 동시 가능, 15분 후 시간 초과)
function pollOut(iid,since,action,hid,key,envId){
  if(S.pollers[hid])return;
  const stop=()=>{clearInterval(S.pollers[hid]);delete S.pollers[hid];uxJobDraw()};
  const tick=async()=>{const e=histLoad(key).find(x=>x.id===hid);if(!e){stop();return}
    try{const r=await api('GET',`/api/env/${envId}/atlantis/output?iid=${iid}&since=${since}&action=${action}`);
      if(r.state!=='pending'){stop();updateHist(key,hid,{state:r.state,headline:r.headline,text:r.body,ekind:r.kind||'',hint:r.hint||''});refreshPlanStatus();
        if(action==='apply'&&r.state==='ok'&&/apply complete/i.test(r.body||''))S.finishing=finishAfterApply(envId)}
      else if(r.busy&&e.headline!==r.headline){updateHist(key,hid,{headline:r.headline})}
      else if(Date.now()-(e.ts||Date.now())>15*60*1000){stop();updateHist(key,hid,{state:'warn',headline:'⏳ 응답 없음 (시간 초과)'})}}
    catch(err){stop();updateHist(key,hid,{state:'error',headline:'❌ 조회 실패',text:err.message})}};
  S.pollers[hid]=setInterval(tick,4000);uxJobDraw();
}
// Atlantis apply 가 끝나면: 변경이 반영되었으므로 대상 브랜치(main)로 돌아가 최신화하고, 접근제어의 변경 음영/표시를 지운다
const finishAfterApply=async envId=>{
  await waitNoModal('apply 후 정리(엑셀 기록·Jira)');
  let brTicket='';try{const st=await api('GET',`/api/env/${envId}/git/status`);const m=/_([A-Z][A-Z0-9_]+-\d+)(?:_|$)/.exec(st.branch||'');brTicket=m?m[1]:''}catch(e){/* 브랜치를 못 읽어도 정리는 계속 */}
  try{await excelRecordModal(envId,true)}catch(e){/* 엑셀 기록 실패가 main 전환을 막지 않도록 */}   // 브랜치를 떠나기 전에 변경 내용을 엑셀에 기록할지 묻는다
  try{const r=await api('POST',`/api/env/${envId}/git/finish`);
    addHist(`Apply 완료 → ${r.branch} 브랜치로 전환`,r.log||'',{kind:'prep',headline:'✓ '+r.branch+' 로 전환'+(r.pulled?'':' (최신화 실패)')});
    toast(`Apply 완료 — ${r.branch} 브랜치로 전환했고 접근제어 변경 표시를 해제했습니다`+(r.pulled?'':'\n(최신화는 실패했습니다: 네트워크/토큰 확인)'),!r.pulled,7000);
    S.sg='';S.sgData=null;S.chg=null;await loadSgs();render()}
  catch(e){addHist('Apply 완료 후 정리 안 됨',e.message,{kind:'prep',state:'warn',headline:'⚠ main 전환 안 됨'});toast('Apply 는 완료되었지만 '+e.message,true,9000)}
  try{await jiraFinishFlow(envId,brTicket)}catch(e){addHist('Jira 완료 처리 안 됨',e.message,{kind:'apply',state:'warn',headline:'⚠ Jira 완료 처리 안 됨'});toast('Jira 완료 처리를 하지 못했습니다: '+e.message,true,9000)}};
// Atlantis 출력 색상: 줄 맨 앞의 - / -/+ 는 빨강(삭제·교체), + 는 초록(추가), ~ 는 주황(변경). 들여쓴 속성 줄은 글자색만.
function colorizePlan(text){
  return String(text).split('\n').filter(l=>!/^\s*```/.test(l)).map(l=>{
    l=l.replace(/<\/?details[^>]*>/gi,'').replace(/<summary>(.*?)<\/summary>/gi,'$1').replace(/<br\s*\/?>/gi,'');
    let c='';
    if(/^(-\/\+|\+\/-)\s/.test(l)||/^-\s/.test(l))c='del';
    else if(/^\+\s/.test(l))c='add';
    else if(/^~\s/.test(l))c='chg';
    else if(/^\s+(-\/\+|\+\/-)\s/.test(l)||/^\s+-\s/.test(l))c='del-t';
    else if(/^\s+\+\s/.test(l))c='add-t';
    else if(/^\s+~\s/.test(l))c='chg-t';
    else if(/^(Plan:|Apply complete|Error:)/.test(l))c='sum';
    return `<span class="ln ${c}">${esc(l)||' '}</span>`}).join('')}

// Commit & Push (변경 내용 확인 창 → push). 작업 카드와 화면 위 작업 바가 함께 쓴다
async function doPush(){
    const df=await api('GET',`/api/env/${S.envId}/git/diff`);
    if(!df.files.length)return toast('커밋할 SG 파일 변경이 없습니다'+(df.skipped.length?` (SG 폴더 밖 변경 ${df.skipped.length}개는 제외됨)`:''),true);
    const html=`<div class="mut" style="margin-bottom:6px">브랜치 <b>${esc(df.branch)}</b> · 커밋 대상 <b>${df.files.length}</b>개 (SG 폴더의 파일만 add/commit 합니다)</div>
      ${df.files.map(f=>`<div>${f.state==='new'?'🆕 신규':f.state==='deleted'?'🗑 삭제':'✏️ 수정'} <code>${esc(f.path)}</code></div>`).join('')}
      ${df.skipped.length?`<div class="warnbox" style="margin-top:8px">커밋되지 않는 파일 ${df.skipped.length}개 (SG 폴더 밖): ${df.skipped.map(f=>`<code>${esc(f.path)}</code>`).join(', ')}</div>`:''}
      <pre class="plan" style="margin-top:10px">${colorizeDiff(df.diff)}</pre>`;
    const fr=df.freshness||{};let warn='',needAck=false;
    if(fr.checked===false)warn+=`<div class="warnbox">원격 최신 여부를 확인하지 못했습니다 (${esc(fr.error||'')}). 그대로 진행할 수 있습니다.</div>`;
    if(fr.behind>0){const ov=fr.overlap&&fr.overlap.length;needAck=!!ov;warn+=`<div class="warnbox ${ov?'danger':''}">대상 브랜치(<b>${esc(fr.target)}</b>)에 내 브랜치에 없는 커밋이 <b>${fr.behind}</b>개 있습니다. ${ov?`<b>같은 SG 파일이 대상 브랜치에서도 바뀌었습니다 (충돌 가능)</b>: ${fr.overlap.map(f=>`<code>${esc(f)}</code>`).join(', ')}`:'(같은 SG 파일은 겹치지 않아 대체로 문제 없습니다)'}</div>`}
    if(fr.remote_ahead>0)warn+=`<div class="warnbox danger">원격 작업 브랜치에 내 PC에 없는 커밋이 ${fr.remote_ahead}개 있습니다. push 가 거부됩니다 — 먼저 가져오기(pull)로 합쳐야 합니다.</div>`;
    const res=await showModal('Commit & Push 확인',warn+html+(needAck?'<label style="display:block;margin-top:8px"><input type="checkbox" id="fr-ack"> 충돌 가능성을 확인했습니다</label>':''),'Commit & Push',null,{collect:o=>({ack:!!o.querySelector('#fr-ack')?.checked})});
    if(!res)return;if(needAck&&!res.ack)return toast('충돌 가능성 확인란을 체크해야 진행할 수 있습니다',true);
    const r=await api('POST',`/api/env/${S.envId}/git/push`,{});
    addHist(`Commit & Push → ${r.branch}`,r.files.map(f=>f.state+' '+f.path).join('\n')+(r.skipped&&r.skipped.length?'\n(커밋 제외 - SG 폴더 밖 '+r.skipped.length+'개: '+r.skipped.map(f=>f.path).join(', ')+')':'')+'\n'+r.log,{kind:'push',headline:r.is_new?'✓ push (신규 파일 포함)':'✓ push (기존 파일 수정)'});
    toast(`push 완료 (${r.is_new?'신규 파일 포함':'기존 파일 수정'})`);gitStatus(true);refreshExistingMr()}
