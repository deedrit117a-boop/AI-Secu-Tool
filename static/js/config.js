// ---------- 환경설정
function viewCfg(){
  const c=S.cfg;
  $('#view').innerHTML=`${(c.environments||[]).length?'':onboardHtml()}<div class="card"><h3>개인 설정 <span class="mut" style="font-weight:400">(local.json — 공유 금지)</span></h3><div class="row">
    <label class="f">계정 (branch 접두어 / 기본 Assignee)<input type="text" id="acct" value="${esc(S.account)}"></label>
    ${Object.keys(c.sites).map(k=>`<label class="f">${esc(KIND_LABEL(k))} GitLab 토큰 ${S.tokenSet[k]?'<b style="color:var(--ok)">(설정됨)</b>':''}<input type="password" class="tok" data-k="${k}" placeholder="${S.tokenSet[k]?'변경 시에만 입력':'api scope 토큰'}" autocomplete="off"></label>`).join('')}
    <button class="pri" id="lsave" style="align-self:end">저장</button></div>
    <div class="mut" style="font-size:12px;margin-top:4px">토큰은 서버의 ${esc(S.paths.local)} 에만 저장되며 화면에는 다시 표시되지 않습니다.</div></div>
  <div class="card"><h3>Jira 연동 <span class="mut" style="font-weight:400">(주소는 config.json 공유 / API 키는 local.json 개인 — 공유 금지)</span></h3>
    <div class="row" style="align-items:flex-end">
      <label class="f">Jira 주소<input type="text" id="jr-url" size="30" value="${esc((S.jira||{}).base_url||'https://jira.smilegate.net')}"></label>
      <label class="f">인증 방식<select id="jr-auth"><option value="bearer" ${(S.jira||{}).auth!=='basic'?'selected':''}>Bearer (개인 액세스 토큰, PAT)</option><option value="basic" ${(S.jira||{}).auth==='basic'?'selected':''}>Basic (사용자 + API 토큰)</option></select></label>
      <label class="f">사용자 (Basic 일 때)<input type="text" id="jr-user" size="16" value="${esc((S.jira||{}).user||'')}"></label>
      <label class="f">Jira API 키 ${(S.jira||{}).token_set?'<b style="color:var(--ok)">(설정됨)</b>':''}<input type="password" id="jr-tok" size="26" autocomplete="off" placeholder="${(S.jira||{}).token_set?'변경 시에만 입력':'API 키 / 개인 액세스 토큰'}"></label>
      <label style="align-self:center"><input type="checkbox" id="jr-ssl" ${(S.jira||{}).ssl_verify===false?'':'checked'}> SSL 인증서 검증</label>
      <button class="pri" id="jr-save">저장</button><button id="jr-test">연결 테스트</button>${(S.jira||{}).token_set?'<button class="danger" id="jr-clear">API 키 삭제</button>':''}</div>
    <div class="mut" id="jr-msg" style="font-size:12px;margin-top:8px">연결 테스트는 읽기 전용입니다(내 계정 정보만 조회). API 키는 화면에 다시 표시되지 않습니다. 사내 Jira(Server/Data Center)는 보통 <b>프로필 → 개인 액세스 토큰</b>을 Bearer 방식으로 사용합니다.</div></div>
  <div id="excel-card"></div>
  <div id="policy-card"></div>
  <div id="service-card"></div>
  <div id="backup-card"></div>
  <div id="selfcheck-card"></div>
  <div class="card"><h3>자주 쓰는 소스 프리셋 <span class="mut" style="font-weight:400">(config.json 공유 — 사무실/VPN 등 자주 쓰는 IP. 마법사·일괄 추가·IP 삭제에서 불러오면 이름이 출발지 정보로 쓰입니다)</span></h3>
    <table><thead><tr><th style="width:240px">이름</th><th>IP / 대역 (줄바꿈·쉼표 구분)</th><th></th></tr></thead><tbody id="pr-body">${(c.presets||[]).map(presetRow).join('')}</tbody></table>
    <div class="row" style="margin-top:8px"><button id="pr-add">프리셋 추가</button><button class="pri" id="pr-save">프리셋 저장</button><span class="mut" id="pr-msg"></span></div></div>
  <div class="card"><h3>유형별 기본값 <span class="mut" style="font-weight:400">(동일 유형의 모든 환경에 적용, 환경에서 비우면 이 값 사용)</span></h3>
    ${Object.keys(c.sites).map(k=>`<div class="row" style="margin-bottom:6px"><b style="width:90px">${esc(KIND_LABEL(k))}</b>
      <label class="f">GitLab URL<input type="text" data-s="${k}" data-f="base_url" size="34" value="${esc(c.sites[k].base_url)}"></label>
      <label class="f">프로젝트 경로<input type="text" data-d="${k}" data-f="project" size="34" value="${esc(c.defaults[k]?.project||'')}"></label>
      <label class="f">repo 로컬 경로 (기본)<input type="text" data-d="${k}" data-f="repo_dir" size="34" value="${esc(c.defaults[k]?.repo_dir||'')}"></label>
      <label class="f">대상 브랜치<input type="text" data-d="${k}" data-f="target_branch" size="10" value="${esc(c.defaults[k]?.target_branch||'main')}"></label>
</div>`).join('')}
    <label><input type="checkbox" id="ssl" ${c.settings.ssl_verify?'checked':''}> SSL 인증서 검증 (사내 인증서 오류 시 해제)</label>
    <div style="margin-top:8px"><button class="pri" id="dsave">기본값 저장</button></div></div>
  <div class="card"><div class="row"><h3 style="margin:0">환경 목록 <span class="mut" style="font-weight:400">(config.json — 공유 가능)</span></h3><span style="margin-left:auto" class="row"><button id="erepair" title="중복 환경 ID 와 저장소에 폴더가 없는 환경을 점검/정리 (적용 전 data/backup 에 백업)">환경 점검/정리</button><button class="blue" id="eadd">환경 추가</button></span></div>
    ${(()=>{const n={};c.environments.forEach(e=>n[e.id]=(n[e.id]||0)+1);const d=Object.values(n).filter(v=>v>1).length;
      return d?`<div class="warnbox danger" style="margin-top:8px">⚠ <b>환경 ID가 중복된 항목이 ${d}종류</b> 있습니다. 같은 ID의 환경은 첫 번째 것만 선택되어 잘못된 경로가 열립니다. <button id="erepair2">지금 정리</button></div>`:''})()}
    <div class="row" style="margin:10px 0"><input type="text" id="efq" style="flex:1;min-width:200px" placeholder="환경 검색 (그룹/환경/경로/프로젝트/접두어)" value="${esc(S.cfgq||'')}">
      <button id="efx">필터 초기화</button><span class="mut" id="efc"></span></div>
    <table><thead><tr><th style="position:relative;white-space:nowrap">유형<span class="fi" data-col="k" title="필터"><svg viewBox="0 0 24 24" width="14" height="14"><path d="M22 3H2l8 9.46V19l4 2v-8.54z"/></svg></span></th><th style="position:relative;white-space:nowrap">그룹<span class="fi" data-col="g" title="필터"><svg viewBox="0 0 24 24" width="14" height="14"><path d="M22 3H2l8 9.46V19l4 2v-8.54z"/></svg></span></th><th style="position:relative;white-space:nowrap">환경<span class="fi" data-col="e" title="필터"><svg viewBox="0 0 24 24" width="14" height="14"><path d="M22 3H2l8 9.46V19l4 2v-8.54z"/></svg></span></th><th style="position:relative;white-space:nowrap">repo 로컬 경로<span class="fi" data-col="r" title="필터"><svg viewBox="0 0 24 24" width="14" height="14"><path d="M22 3H2l8 9.46V19l4 2v-8.54z"/></svg></span></th><th style="position:relative;white-space:nowrap">sg_rule 상대경로<span class="fi" data-col="s" title="필터"><svg viewBox="0 0 24 24" width="14" height="14"><path d="M22 3H2l8 9.46V19l4 2v-8.54z"/></svg></span></th><th></th></tr></thead><tbody>
    ${c.environments.map((e,i)=>`<tr class="erow" data-i="${i}" data-k="${esc(e.kind)}" data-g="${esc(e.group)}" data-e="${esc(e.env)}" data-r="${esc((e.repo_dir||'').toLowerCase())}" data-s="${esc((e.sg_dir||'').toLowerCase())}" data-t="${esc([e.group,e.env,e.label,e.sg_dir,e.repo_dir,e.project,e.file_prefix].join(' ').toLowerCase())}"><td>${esc(KIND_LABEL(e.kind))}</td><td>${esc(e.group)}</td><td>${esc(e.env)}</td><td>${esc(e.repo_dir)}</td><td>${esc(e.sg_dir)}</td>
      <td><button data-ed="${i}" title="저장소 안의 sg_rule 폴더를 찾아 환경으로 자동 등록">환경 검색</button> <button data-ee="${i}">수정</button> <button class="danger" data-ex="${i}">삭제</button></td></tr>`).join('')}</tbody></table>
    <div id="eform"></div>
    <div class="mut" style="font-size:12px;margin-top:6px">공유 파일: ${esc(S.paths.config)}<br>${esc(S.paths.meta)}</div></div>`;
  $('#lsave').onclick=guard(async()=>{const tokens={};document.querySelectorAll('.tok').forEach(t=>{if(t.value)tokens[t.dataset.k]=t.value});
    await api('PUT','/api/local',{account:$('#acct').value,tokens});await reloadCfg();toast('저장됨');viewCfg()});
  const prBind=tr=>tr.querySelector('.pr-d').onclick=()=>tr.remove();$('#pr-body').querySelectorAll('tr').forEach(prBind);
  $('#pr-add').onclick=()=>{$('#pr-body').insertAdjacentHTML('beforeend',presetRow({}));prBind($('#pr-body').lastElementChild)};
  $('#pr-save').onclick=guard(async()=>{c.presets=[...$('#pr-body').querySelectorAll('tr')].map(tr=>({name:tr.querySelector('.pr-n').value.trim(),ips:tr.querySelector('.pr-i').value.split(/[\s,;]+/).filter(Boolean).map(x=>/\/\d+$/.test(x)?x:x+'/32')})).filter(p=>p.name||p.ips.length);
    await api('PUT','/api/config',c);await reloadCfg();toast(`프리셋 ${c.presets.length}개를 저장했습니다`);viewCfg()});
  const saveJira=async()=>{c.settings=c.settings||{};c.settings.jira_url=$('#jr-url').value.trim().replace(/\/+$/,'');
    await api('PUT','/api/config',c);   // 주소: config.json (공유)
    await api('PUT','/api/local',{jira:{auth:$('#jr-auth').value,user:$('#jr-user').value,ssl_verify:$('#jr-ssl').checked,token:$('#jr-tok').value}});   // API 키: local.json (개인)
    await reloadCfg()};
  $('#jr-save').onclick=guard(async()=>{await saveJira();checkTicket();toast('Jira 설정을 저장했습니다');viewCfg()});
  $('#jr-test').onclick=guard(async()=>{const m=$('#jr-msg');m.textContent='연결 확인 중...';
    try{await saveJira();const r=await api('GET','/api/jira/test');
      m.innerHTML=`<span style="color:var(--ok)">✓ 연결 성공</span> — ${esc(r.displayName||r.name)}${r.email?' ('+esc(r.email)+')':''} · ${esc(r.base_url)}`;checkTicket()}
    catch(e){m.innerHTML=`<span style="color:var(--err)">✗ 연결 실패: ${esc(e.message)}</span>`}});
  $('#jr-clear')&&($('#jr-clear').onclick=guard(async()=>{if(!confirm('저장된 Jira API 키를 삭제할까요?'))return;await api('PUT','/api/local',{jira:{token:'__clear__'}});await reloadCfg();checkTicket();viewCfg()}));
  $('#dsave').onclick=guard(async()=>{document.querySelectorAll('[data-s]').forEach(i=>c.sites[i.dataset.s][i.dataset.f]=i.value.trim());
    document.querySelectorAll('[data-d]').forEach(i=>{(c.defaults[i.dataset.d]=c.defaults[i.dataset.d]||{})[i.dataset.f]=i.value.trim()});
    c.settings.ssl_verify=$('#ssl').checked;await api('PUT','/api/config',c);toast('저장됨')});
  // 열 머리글 깔때기 필터 (엑셀 방식): 조건 입력(포함) + 값별 체크박스 다중 선택
  const CF=S.cf=S.cf||{k:null,g:null,e:null,r:null,s:null};   // {text, sel:null|[값]}
  const colVal=(e,col)=>({k:e.kind,g:e.group,e:e.env,r:e.repo_dir||'',s:e.sg_dir||''})[col]||'';
  const colLabel=(col,v)=>col==='k'?KIND_LABEL(v):v;
  const active=f=>!!f&&(!!f.text||!!f.sel);
  const match=(col,f,val)=>!active(f)||((!f.text||(val+' '+colLabel(col,val)).toLowerCase().includes(f.text.toLowerCase()))&&(!f.sel||f.sel.includes(val)));
  const passOthers=(e,except)=>Object.keys(CF).every(k=>k===except||match(k,CF[k],colVal(e,k)));
  const filt=()=>{
    S.cfgq=$('#efq').value;const q=S.cfgq.trim().toLowerCase().split(/\s+/).filter(Boolean);let n=0;
    document.querySelectorAll('.erow').forEach(r=>{const d=r.dataset,e=c.environments[+d.i];
      const ok=passOthers(e,'')&&q.every(w=>d.t.includes(w)||(d.k+' '+r.children[0].textContent).toLowerCase().includes(w));r.style.display=ok?'':'none';if(ok)n++});
    document.querySelectorAll('.fi').forEach(i=>i.classList.toggle('on',active(CF[i.dataset.col])));
    $('#efc').textContent=`${n} / ${c.environments.length}개`};
  document.querySelectorAll('.fi').forEach(ic=>ic.onclick=ev=>{ev.stopPropagation();const col=ic.dataset.col,th=ic.parentElement;
    const had=th.querySelector('.panel');closePanels();if(had)return;
    const pop=document.createElement('div');pop.className='panel';pop.style.cssText='min-width:260px;font-weight:400;text-transform:none;letter-spacing:0;white-space:normal';
    pop.innerHTML=`<input type="text" placeholder="조건 입력 (포함)" value="${esc(CF[col]?.text||'')}">
      <label class="chk" style="border-bottom:1px solid var(--border);font-weight:700"><input type="checkbox" class="all"> 전체 선택</label><div class="list" style="max-height:220px;overflow:auto"></div>
      <div style="padding:6px 10px;border-top:1px solid var(--border);display:flex;gap:6px;justify-content:space-between"><button class="clr">필터 해제</button><button class="cls blue">닫기</button></div>`;
    th.appendChild(pop);pop.onclick=e=>e.stopPropagation();
    const inp=pop.querySelector('input[type=text]'),list=pop.querySelector('.list'),all=pop.querySelector('.all');
    const listed=()=>{const t=inp.value.trim().toLowerCase();return[...new Set(c.environments.filter(e=>passOthers(e,col)).map(e=>colVal(e,col)))].sort()
      .filter(v=>!t||(v+' '+colLabel(col,v)).toLowerCase().includes(t))};
    const apply=()=>{const vals=listed(),chk=[...list.querySelectorAll('input:checked')].map(i=>i.value);
      CF[col]={text:inp.value.trim(),sel:chk.length===vals.length?null:chk};if(!active(CF[col]))CF[col]=null;
      all.checked=chk.length===vals.length;all.indeterminate=chk.length>0&&chk.length<vals.length;filt()};
    const draw=()=>{const vals=listed(),sel=CF[col]?.sel;list.innerHTML='';
      vals.forEach(v=>{const l=document.createElement('label');l.className='chk';l.innerHTML=`<input type="checkbox" value="${esc(v)}" ${!sel||sel.includes(v)?'checked':''}> ${esc(colLabel(col,v))}`;
        l.querySelector('input').onchange=apply;list.appendChild(l)});
      if(!vals.length)list.innerHTML='<div class="mut" style="padding:7px 12px">결과 없음</div>';
      const n=list.querySelectorAll('input:checked').length;all.checked=vals.length>0&&n===vals.length;all.indeterminate=n>0&&n<vals.length};
    all.onchange=()=>{list.querySelectorAll('input').forEach(i=>i.checked=all.checked);apply()};
    inp.oninput=()=>{CF[col]=inp.value.trim()?{text:inp.value.trim(),sel:null}:null;draw();filt()};
    pop.querySelector('.clr').onclick=()=>{CF[col]=null;inp.value='';draw();filt()};pop.querySelector('.cls').onclick=()=>closePanels();
    draw();inp.focus()});
  $('#efq').oninput=filt;
  $('#efx').onclick=()=>{Object.keys(CF).forEach(k=>CF[k]=null);$('#efq').value='';S.cfgq='';filt()};
  filt();
  const repairFlow=guard(async()=>{
    const r=await api('POST','/api/config/repair',{dry_run:true,remove_stale:false});
    const none=!r.changes.length&&!r.stale.length&&!r.meta_ambiguous.length&&!r.meta_rekey.length&&!r.meta_orphans.length;
    const html=none?'<div style="color:var(--ok)">✓ 이상 없음 — 중복된 환경 ID, 폴더가 없는 환경, 연결이 끊긴 메타 데이터가 없습니다.</div>':
      `<div class="mut" style="margin-bottom:8px">적용하기 전에 <code>data/backup/날짜_시간/</code> 에 config.json, meta.json 을 백업합니다 (최근 20개 유지).</div>
       ${r.changes.length?`<div><b>중복 환경 ID ${r.duplicate_ids.length}종류 → ${r.changes.length}개 환경에 새 ID 부여</b> (각 ID의 첫 번째 환경은 그대로 유지)</div>
         <table style="margin:6px 0"><thead><tr><th>기존 ID</th><th>새 ID</th><th>경로</th></tr></thead><tbody>${r.changes.map(x=>`<tr><td><code>${esc(x.old)}</code></td><td><code>${esc(x.new)}</code></td><td>${esc(x.sg_dir)}</td></tr>`).join('')}</tbody></table>`:''}
       ${r.meta_moved.length?`<div>메타 데이터(SG 별명/태그) <b>${r.meta_moved.length}건</b>을 SG 파일이 실제로 있는 환경으로 이동: ${r.meta_moved.slice(0,8).map(x=>esc(x.sg)).join(', ')}${r.meta_moved.length>8?' …':''}</div>`:''}
       ${r.meta_rekey.length?`<div style="margin-top:6px">환경 ID가 바뀐 메타 <b>${r.meta_rekey.length}건</b>을 같은 경로의 환경으로 다시 연결: ${r.meta_rekey.map(x=>`<code>${esc(x.from)}</code> → <code>${esc(x.to)}</code>`).join(', ')}</div>`:''}
       ${r.meta_ambiguous.length?`<div class="warnbox" style="margin-top:6px">어느 환경 것인지 알 수 없어 <b>그대로 둔</b> 메타: ${r.meta_ambiguous.map(x=>esc(x.sg)).join(', ')} (첫 번째 환경에 남음 — 필요하면 직접 옮기세요)</div>`:''}
       ${r.meta_orphans.length?`<div class="warnbox" style="margin-top:6px"><b>연결할 환경이 없는 메타 ${r.meta_orphans.length}건</b> (환경이 삭제되었거나 ID가 바뀜):<ul style="margin:4px 0 4px 18px">${r.meta_orphans.map(x=>`<li><code>${esc(x.id)}</code> ${esc(x.label||x.sg_dir||'')} — SG ${x.sgs}개${x.subnets?`, 서브넷 ${x.subnets}행`:''}</li>`).join('')}</ul>
         <label><input type="checkbox" id="rp-orphan"> 이 메타 데이터를 삭제 (백업에는 남습니다)</label></div>`:''}
       ${r.stale.length?`<div style="margin-top:8px"><b>저장소에 폴더가 없는 환경 ${r.stale.length}개</b> (저장소를 받았는데 sg_rule 경로가 없음)<ul style="margin:4px 0 4px 18px">${r.stale.map(x=>`<li>${esc(x.group)} · ${esc(x.env)} <span class="mut">${esc(x.sg_dir)}</span></li>`).join('')}</ul>
         <label><input type="checkbox" id="rp-stale" checked> 이 환경들을 목록에서 제거</label></div>`:''}`;
    const res=await showModal('환경 점검 / 정리',html,none?'닫기':'정리 적용',null,{hideCancel:none,collect:o=>({stale:!!o.querySelector('#rp-stale')?.checked,orphan:!!o.querySelector('#rp-orphan')?.checked})});
    if(!res||none)return;
    const a=await api('POST','/api/config/repair',{dry_run:false,remove_stale:res.stale,remove_orphans:res.orphan});
    await reloadCfg();if(!S.cfg.environments.find(e=>e.id===S.envId)){S.envId='';S.sg=null}persist();renderPickers();
    toast(a.backup?`정리했습니다. 백업: ${a.backup}`:'변경할 내용이 없습니다',false,8000);S.meta=await api('GET','/api/meta');viewCfg()});
  $('#erepair').onclick=repairFlow;$('#erepair2')&&($('#erepair2').onclick=repairFlow);
  $('#eadd').onclick=()=>envForm(null);bindOnboard();drawExcelCard();drawPolicyCard();drawServiceCard();drawBackupCard();drawSelfcheckCard();
  document.querySelectorAll('[data-ed]').forEach(b=>b.onclick=guard(async()=>{const e=c.environments[+b.dataset.ed];
    const r=await api('POST',`/api/env/${e.id}/discover`);await reloadCfg();renderPickers();
    toast(r.added.length?`환경 ${r.added.length}개 추가: `+r.added.join(', '):'새로 추가할 환경이 없습니다 (이미 모두 등록됨)');viewCfg()}));
  document.querySelectorAll('[data-ee]').forEach(b=>b.onclick=()=>envForm(+b.dataset.ee));
  document.querySelectorAll('[data-ex]').forEach(b=>b.onclick=guard(async()=>{const e=c.environments[+b.dataset.ex];if(!confirm(`'${e.group}/${e.env}' 환경을 목록에서 삭제할까요? (파일은 삭제되지 않음)`))return;
    c.environments.splice(+b.dataset.ex,1);await api('PUT','/api/config',c);if(S.envId===e.id){S.envId=''}renderPickers();viewCfg()}));
}
function envForm(i){
  const c=S.cfg,e=i===null?{kind:S.kind||'platform',group:'',env:'',label:'',repo_dir:'',sg_dir:'',file_prefix:'',project:'',target_branch:'',atlantis_dir:''}:c.environments[i];
  const f=(k,l,sz=30,ph='')=>`<label class="f">${l}<input type="text" id="f-${k}" size="${sz}" value="${esc(e[k]||'')}" placeholder="${esc(ph)}"></label>`;
  $('#eform').innerHTML=`<div class="card" style="margin-top:8px"><h3>${i===null?'환경 추가':'환경 수정'}</h3>${i===null?'':`<div class="mut" style="font-size:12px;margin-bottom:6px">환경 ID: <code>${esc(e.id)}</code> — 변경할 수 없습니다 (메타 데이터가 이 ID에 연결됩니다). 이름·경로는 아래에서 자유롭게 수정할 수 있습니다.</div>`}<div class="row">
    <label class="f">유형<select id="f-kind">${Object.keys(c.sites).map(k=>`<option value="${k}" ${e.kind===k?'selected':''}>${esc(KIND_LABEL(k))}</option>`).join('')}</select></label>
    ${f('group','2단계: 게임/플랫폼 종류',18,'eclipse / megaport-sip')}${f('env','3단계: 환경',10,'qa / live / re')}${f('label','표시 이름',26)}</div>
    <div class="row" style="margin-top:6px">${f('repo_dir','repo 로컬 경로 (비우면 유형 기본값)',44,'D:\\GIT\\Infra\\cloud-multiverse')}${f('sg_dir','sg_rule 폴더 (repo 기준 상대경로)',50,'aws/megaport-sip-dev/apne2/dev/sg/sg_rule')}</div>
    <div class="row" style="margin-top:6px">${f('file_prefix','신규 파일 접두어 (게임: 게임명-환경)',22,'l-sg-bbz-')}${f('project','GitLab 프로젝트 (비우면 기본값)',34,'sgp-infra/eclipse/infra-deploy')}${f('target_branch','대상 브랜치',10)}${f('atlantis_dir','atlantis -d 경로 (비우면 sg_rule 상위)',34)}</div>
    <div style="margin-top:8px"><button class="pri" id="esave">저장</button> <button id="ecancel">취소</button></div></div>`;
  $('#ecancel').onclick=()=>$('#eform').innerHTML='';
  $('#esave').onclick=guard(async()=>{const n={...e};['kind','group','env','label','repo_dir','sg_dir','file_prefix','project','target_branch','atlantis_dir'].forEach(k=>n[k]=$('#f-'+k).value.trim());
    n.sg_dir=n.sg_dir.replace(/\\/g,'/').replace(/^\/|\/$/g,'');
    if(!n.group||!n.env||!n.sg_dir)return toast('그룹/환경/sg_rule 경로는 필수입니다',true);
    if(!n.repo_dir&&!c.defaults[n.kind]?.repo_dir)return toast('repo 로컬 경로 또는 유형별 기본 repo 경로가 필요합니다',true);
    n.id=e.id||(n.kind+'-'+n.group+'-'+n.env+'-'+Date.now().toString(36)).replace(/[^A-Za-z0-9_-]/g,'-');
    if(i===null)c.environments.push(n);else c.environments[i]=n;
    await api('PUT','/api/config',c);renderPickers();toast('저장됨');viewCfg()});
}

