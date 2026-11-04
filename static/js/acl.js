// ---------- 접근제어
function sgMeta(name){return S.meta.envs?.[S.envId]?.sgs?.[name]||{}}
function viewAcl(){
  const v=$('#view');
  v.innerHTML=`<div id="bbanner"></div><div class="grid"><div>
    <div class="card"><div class="row"><input type="text" id="q" style="flex:1" placeholder="도메인/SG명/태그/IP 검색 후 Enter" value="${esc(S.search)}">
      <label><input type="checkbox" id="qall"> 전체환경</label></div>
      <div class="row" style="margin-top:8px"><input type="text" id="sgf" style="flex:1;min-width:120px" placeholder="목록 필터 (입력 즉시)" value="${esc(S.sgf||'')}">
        <select id="sgm"><option value="">전체</option><option value="chg">변경/신규만</option><option value="notag">태그 없음</option></select></div>
      <div class="mut" style="font-size:12px;margin-top:4px">${esc(S.sgPath||'')}${S.sgExists===false?' <b style="color:var(--err)">(경로 없음 - clone 필요)</b>':''}</div>
      <div class="row" style="margin-top:6px;gap:6px"><button id="hyg" title="만료된 규칙, 정리할 만한 규칙, 특정 IP 가 열려 있는 SG 를 모든 환경에서 찾아 보여줍니다 (읽기 전용)">규칙 점검 보고서</button><button id="awscmp" title="이 환경의 SG 마다 AWS 에 실제로 열려 있는 규칙과 저장소 파일의 규칙을 비교합니다 (읽기 전용, AWS 로그인 필요)">AWS 규칙 비교 보고서</button></div></div>
    <div class="card sglist" id="sgl"></div>
    <div class="card"><h3>새 SG 파일</h3><div class="row"><input type="text" id="newres" style="flex:1" placeholder="${env().kind==='game'?'리소스 (예: auto-scaler-lambda)':'리소스 (예: sip-docdb)'}">
      <button id="newbtn">생성</button></div>
      <div class="mut" style="font-size:12px;margin-top:4px">${env().kind==='game'?`파일: <code>${esc(env().file_prefix||'')}[리소스]-sg-ingress/egress-rules.json</code> (접두어 = 게임명-환경)`:'파일: <code>[리소스].json</code>'}</div>
      ${env().kind==='game'?'<label><input type="checkbox" id="eg" checked> egress 기본 allow-all</label>':''}</div>
  </div><div id="detail"></div></div>`;
  $('#q').onkeydown=e=>{if(e.key==='Enter'){S.search=e.target.value;doSearch($('#qall').checked)}};
  $('#awscmp').onclick=guard(awsCompareReport);$('#hyg').onclick=guard(()=>openReports());
  $('#newbtn').onclick=guard(async()=>{const r=await api('POST',`/api/env/${S.envId}/sgs`,{resource:$('#newres').value,egress_allow_all:$('#eg')?.checked});
    toast('생성: '+r.name);await loadSgs();S.sg=r.name;await openSg(r.name)});
  $('#sgf').oninput=e=>{S.sgf=e.target.value;drawSgList()};$('#sgm').value=S.sgm||'';$('#sgm').onchange=e=>{S.sgm=e.target.value;drawSgList()};
  drawSgList();drawDetail();drawBranchBanner();
}
function drawSgList(){
  const l=$('#sgl');if(!l)return;
  let items=S.results?S.results.map(r=>({env_id:r.env_id,name:r.name,sub:r.env_label+' — '+r.hits.join(' | ')})):S.sgs.map(s=>({env_id:S.envId,name:s.name,change:s.change,sub:`in ${s.ingress} / out ${s.egress}`+(sgMeta(s.name).alias?' · '+sgMeta(s.name).alias:'')}));
  const sgIdOf=i=>S.meta.envs?.[i.env_id]?.sgs?.[i.name]?.sg_id||'';   // 메타 데이터에 SG ID 가 있으면 이름 옆에 함께 표시
  const fw=(S.sgf||'').trim().toLowerCase().split(/\s+/).filter(Boolean);
  items=items.filter(i=>(!fw.length||fw.every(w=>(i.name+' '+sgIdOf(i)+' '+(i.sub||'')).toLowerCase().includes(w)))&&
    (!S.sgm||(S.sgm==='chg'?!!i.change:!((S.meta.envs?.[i.env_id]?.sgs?.[i.name]?.tags||[]).length))));
  l.innerHTML=(S.results?`<div class="mut" onclick="S.results=null;drawSgList()">검색 결과 ${items.length}건 (클릭하면 전체 목록)</div>`:'')+
    (items.map((i,n)=>`<div data-n="${n}" class="${i.name===S.sg&&i.env_id===S.envId?'on':''}${i.change?' chg':''}"><b>${esc(i.name)}</b>${sgIdOf(i)?`<span class="mut sgid">(${esc(sgIdOf(i))})</span>`:''}${i.change?` <span class="badge b-chg">${i.change==='new'?'신규':'변경'}</span>`:''}<br><span class="mut" style="font-size:12px">${esc(i.sub)}</span></div>`).join('')||'<div class="mut">SG 파일이 없습니다</div>');
  l.querySelectorAll('[data-n]').forEach(d=>d.onclick=guard(async()=>{const i=items[d.dataset.n];
    if(i.env_id!==S.envId){const e=S.cfg.environments.find(x=>x.id===i.env_id);S.kind=e.kind;S.group=e.group;S.envId=e.id;persist();renderPickers();await loadSgs();S.results=null;S.search='';viewAcl()}
    await openSg(i.name)}));
}
const doSearch=guard(async all=>{const r=await api('GET',`/api/search?q=${encodeURIComponent(S.search)}${all?'':'&env_id='+S.envId}`);S.results=S.search?r.results:null;drawSgList()});
// ---------- 작업 브랜치 배너: main/기본 브랜치에서는 규칙 수정이 서버에서 차단되므로 미리 안내
S.allowMain=S.allowMain||(()=>{try{return sessionStorage.getItem('allowMain')==='1'}catch{return false}})();
const drawBranchBanner=guard(async()=>{const b=$('#bbanner');if(!b||!S.envId)return;
  const s=await api('GET',`/api/env/${S.envId}/git/status`);if(!$('#bbanner'))return;
  if(!s.cloned){b.innerHTML='<div class="warnbox">저장소가 아직 없습니다. <button id="bgo">작업 탭에서 다운로드</button></div>'}
  else if(s.on_default&&!S.allowMain){b.innerHTML=`<div class="warnbox danger">⚠ 현재 <b>${esc(s.branch)}</b> 브랜치입니다. 규칙 수정은 <b>작업 브랜치</b>에서만 할 수 있습니다.
    <button id="bgo" class="blue">작업 탭에서 브랜치 준비</button> <button id="ballow">이 세션에서는 그대로 수정</button></div>`}
  else if(s.on_default){b.innerHTML=`<div class="warnbox danger">⚠ <b>${esc(s.branch)}</b> 브랜치를 직접 수정하는 중입니다 (이 세션에서 허용함). <button id="bgo">브랜치 준비로 이동</button></div>`}
  else{b.innerHTML=`<div class="mut" style="font-size:12px;margin-bottom:10px">작업 브랜치 <b>${esc(s.branch)}</b> · 변경 ${s.files.length}개${s.out_of_scope&&s.out_of_scope.length?` · <span style="color:var(--warn)">SG 폴더 밖 변경 ${s.out_of_scope.length}개는 커밋되지 않음</span>`:''}</div><div class="row" id="wtools-acl" style="margin-bottom:10px"></div>`;drawWorkTools(b.querySelector('#wtools-acl'))}
  b.querySelector('#bgo')?.addEventListener('click',()=>{S.tab='work';persist();render()});
  b.querySelector('#ballow')?.addEventListener('click',()=>{S.allowMain=true;try{sessionStorage.setItem('allowMain','1')}catch{}drawBranchBanner()})});
const openSg=guard(async name=>{S.sg=name;S.edit=null;S.bulk=false;S.warns=[];S.sgData=await api('GET',`/api/env/${S.envId}/sg/${name}`);await loadChg();drawSgList();drawDetail()});
const loadChg=async()=>{try{S.chg=await api('GET',`/api/env/${S.envId}/sg/${S.sg}/changes`)}catch{S.chg={ingress:[],egress:[]}}};
const saveSg=guard(async()=>{
  const undo=async()=>{S.edit=null;await openSg(S.sg)};
  const v=await api('POST',`/api/env/${S.envId}/sg/${S.sg}/validate`,S.sgData);
  if(v.errors.length){toast('저장할 수 없습니다:\n'+v.errors.join('\n'),true,12000);await undo();return false}
  let why=null;
  if(v.risks.length){why=await askRisk(v.risks,{intro:'접근 범위가 넓은 규칙이 새로 추가/변경됩니다. 그대로 저장할까요?',ok:'그대로 저장'});if(!why){await undo();return false}}
  if((v.already||[]).length&&!await showModal('이미 열려 있는 규칙',`<div>새로 넣는 규칙을 이미 허용하는 규칙이 있습니다. 불필요한 규칙일 수 있습니다. 그래도 저장할까요?</div><ul>${v.already.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`,'그래도 저장')){await undo();return false}
  try{await api('PUT',`/api/env/${S.envId}/sg/${S.sg}`,S.sgData)}catch(e){await undo();throw e}
  if(why)await recordRisk(S.envId,S.sg,v.risks,why);
  const warns=[...v.warnings,...(v.others||[]).map(x=>'참고: '+x)];
  S.warns=warns;toast('파일 저장됨'+(warns.length?`\n참고 ${warns.length}건 (규칙 표 위에 표시)`:''),false,warns.length?5000:3000);
  await loadSgs();await loadChg();drawSgList();return true});

function ruleType(r){if(r.protocol==='-1')return'All traffic';const p=String(r.protocol).toLowerCase();
  const wk={22:'SSH',80:'HTTP',443:'HTTPS',3306:'MySQL/Aurora',5432:'PostgreSQL',3389:'RDP',6379:'Redis',27017:'MongoDB'};
  if(p==='icmp')return'ICMP';return (r.from_port===r.to_port&&wk[r.from_port])?wk[r.from_port]:'Custom '+p.toUpperCase()}
const portStr=r=>r.protocol==='-1'?'All':(r.from_port===r.to_port?r.from_port:r.from_port+' - '+r.to_port);
const srcStr=r=>r.security_groups?r.security_groups:(r.cidr_blocks.join(', ')||'-');

function drawDetail(){
  const d=$('#detail');if(!d)return;
  if(!S.sg||!S.sgData){d.innerHTML='<div class="card mut">왼쪽에서 SG를 선택하세요.</div>';return}
  const m=sgMeta(S.sg);
  const rules=S.sgData[S.dir];
  d.innerHTML=`<div class="card"><div class="row"><h3 style="margin:0">${esc(S.sg)}</h3>
      ${m.sg_id?`<span class="tag">${esc(m.sg_id)}</span>`:''}${m.alias?`<span class="mut">${esc(m.alias)}</span>`:''}${(m.tags||[]).map(t=>`<span class="tag">${esc(t.type?t.type+': ':'')}${esc(t.value)}</span>`).join('')}
      <span style="margin-left:auto" class="row"><a class="btn" style="text-decoration:none;padding:4px 12px;border:1px solid var(--mut)" href="/api/env/${S.envId}/sg/${S.sg}/csv">CSV 다운로드</a>
      ${(S.sgs||[]).some(x=>x.name===S.sg&&x.change)?'<button id="rvsg" title="이 SG 의 Commit 하지 않은 변경을 취소합니다">이 SG 변경 취소</button>':''}<button id="dv">변경 내용 보기</button><button id="up">CSV 업로드</button><input type="file" id="upf" accept=".csv" hidden></span></div></div>
    <div class="card">${S.warns?.length?`<div class="warnbox">참고 ${S.warns.length}건 <button class="wclr" style="float:right;padding:0 8px">닫기</button><ul>${S.warns.slice(0,8).map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div>`:''}<div class="tabs"><div class="tab ${S.dir==='ingress'?'on':''}" data-d="ingress">인바운드 규칙 (${S.sgData.ingress.length})</div>
      <div class="tab ${S.dir==='egress'?'on':''}" data-d="egress">아웃바운드 규칙 (${S.sgData.egress.length})</div></div>
      <div class="mut" style="font-size:12px;margin-bottom:6px"><span class="legend"></span> 음영 = Commit 전 (신규/변경, Commit/Push 후에는 해제)${S.chg?.is_new?' · <b>신규 SG 파일</b>':''}
        <input type="text" id="rf" placeholder="규칙 필터 (IP/포트/설명)" style="float:right;width:260px;margin-top:-4px" value="${esc(S.rf||'')}"></div>
      <table><thead><tr><th style="width:28px"><input type="checkbox" id="selall" title="전체 선택"></th><th>유형</th><th>프로토콜</th><th>포트 범위</th><th>${S.dir==='ingress'?'소스':'대상'}</th><th>설명</th><th style="width:130px"></th></tr></thead>
      <tbody>${rules.map((r,i)=>S.edit&&S.edit.i===i?editRow(r):`<tr class="${(S.chg?.[S.dir]||[]).includes(i)?'chg':''}"><td><input type="checkbox" class="rsel" data-i="${i}"></td><td>${esc(ruleType(r))}</td><td>${esc(r.protocol)}</td><td>${esc(portStr(r))}</td><td>${esc(srcStr(r))}</td><td>${esc(r.description)}</td>
        <td><button data-e="${i}">수정</button> <button class="danger" data-x="${i}">삭제</button></td></tr>`).join('')}
        ${S.edit&&S.edit.i===-1?editRow({protocol:env().kind==='game'?'TCP':'tcp',from_port:'',to_port:'',cidr_blocks:[],security_groups:'',description:''}):''}</tbody></table>
      <div style="margin-top:8px" class="row"><button class="blue" id="add" ${S.edit?'disabled':''}>규칙 추가</button>
        <button id="cp" title="체크한 규칙과 동일한 규칙을 새로 만듭니다">선택 복사</button>
        <button id="bsg" title="체크한 규칙을 다른 SG(같은 저장소의 다른 환경 포함)에도 추가">다른 SG에 적용</button>
        <button id="bdel" class="danger" title="체크한 규칙을 삭제">선택 삭제</button><button id="bipd" title="IP/대역이 소스인 규칙을 찾아 삭제 (SG/환경/저장소 범위)">IP로 규칙 삭제</button>
        <button id="bulk" title="체크한 규칙을 기준으로 IP만 바꿔 여러 개 추가">여러 IP 일괄 추가</button></div></div>
    ${bulkCard()}`;
  d.querySelectorAll('[data-d]').forEach(t=>t.onclick=()=>{S.dir=t.dataset.d;S.edit=null;S.bulk=false;drawDetail()});
  d.querySelectorAll('[data-e]').forEach(b=>b.onclick=()=>{S.edit={i:+b.dataset.e};drawDetail()});
  d.querySelectorAll('[data-x]').forEach(b=>b.onclick=async()=>{const r=rules[+b.dataset.x];if(!confirm(`삭제할까요?\n${srcStr(r)} ${portStr(r)}\n${r.description}`))return;rules.splice(+b.dataset.x,1);await saveSg();drawDetail()});
  const rfilter=()=>{S.rf=$('#rf').value;const ws=S.rf.trim().toLowerCase().split(/\s+/).filter(Boolean);
    d.querySelectorAll('tbody tr:not(.edit)').forEach(tr=>{const t=tr.innerText.toLowerCase();tr.style.display=ws.every(w=>t.includes(w))?'':'none'})};
  $('#rf').oninput=rfilter;rfilter();
  d.querySelector('.wclr')?.addEventListener('click',()=>{S.warns=[];drawDetail()});
  $('#add').onclick=()=>{S.edit={i:-1};drawDetail()};
  $('#selall').onchange=e=>d.querySelectorAll('.rsel').forEach(c=>c.checked=e.target.checked);
  const checked=()=>[...d.querySelectorAll('.rsel:checked')].map(c=>+c.dataset.i);
  $('#cp').onclick=guard(async()=>{const idx=checked();if(!idx.length)return toast('복사할 규칙을 체크하세요',true);
    const first=rules.length;[...idx].sort((x,y)=>x-y).forEach(i=>rules.push(JSON.parse(JSON.stringify(rules[i]))));   // 새 규칙은 항상 맨 아래에 추가
    await saveSg();S.edit={i:first};toast(`${idx.length}개 규칙을 동일하게 복사해 맨 아래에 추가했습니다. 첫 번째 복사본을 수정하세요`);drawDetail()});
  $('#bsg').onclick=guard(async()=>{const idx=checked();if(!idx.length)return toast('적용할 규칙을 체크하세요',true);await applyToOtherSgs(idx.map(i=>({direction:S.dir,...JSON.parse(JSON.stringify(rules[i]))})))});
  $('#bdel').onclick=guard(async()=>{const idx=checked();if(!idx.length)return toast('삭제할 규칙을 체크하세요',true);
    const html=`<div>${S.dir==='ingress'?'인바운드':'아웃바운드'} 규칙 <b>${idx.length}</b>개를 삭제합니다. 파일에 바로 저장되며 Commit 전에는 git 으로 되돌릴 수 있습니다.</div><table style="margin-top:8px"><tbody class="plan">${idx.map(i=>`<tr class="del"><td>${esc(rules[i].protocol)}</td><td>${esc(portStr(rules[i]))}</td><td>${esc(srcStr(rules[i]))}</td><td>${esc(rules[i].description)}</td></tr>`).join('')}</tbody></table>`;
    if(!await showModal('선택한 규칙 삭제',html,'삭제',null,{danger:true}))return;
    const keep=rules.filter((_,i)=>!idx.includes(i));rules.length=0;rules.push(...keep);
    const ok=await saveSg();if(ok!==false)addHist(`규칙 삭제 → ${S.sg}`,`${idx.length}건 삭제`,{kind:'rule',headline:`✓ ${idx.length}건 삭제`});drawDetail()});
  $('#bipd').onclick=guard(()=>ipDeleteModal());
  $('#bulk').onclick=()=>{S.bulk=!S.bulk;$('#bulkcard').style.display=S.bulk?'':'none'};
  bindBulk(d,rules,checked);
  $('#up').onclick=()=>$('#upf').click();
  // 변경 내용 보기: 마지막 커밋 대비 이 SG 파일의 diff (읽기 전용)
  if($('#rvsg'))$('#rvsg').onclick=()=>revertSg(S.sg);
  $('#dv').onclick=guard(async()=>{const r=await api('GET',`/api/env/${S.envId}/sg/${S.sg}/diff`);
    await showModal('변경 내용 — '+S.sg,r.diff.trim()?`<div class="mut" style="margin-bottom:6px">마지막 커밋 대비${r.new_file?' · <b>신규 파일</b>':''}. <span style="color:var(--ok)">초록</span>=추가, <span style="color:var(--err)">빨강</span>=삭제</div><pre class="plan">${colorizeDiff(r.diff)}</pre>`:'<div class="mut">변경 사항이 없습니다 (마지막 커밋과 동일).</div>','닫기',null,{hideCancel:true})});
  // CSV 업로드: 적용 전에 추가/제거될 규칙·오류·위험을 미리 보고(추가 / 전체 교체 중 선택) 확인 후 적용
  $('#upf').onchange=guard(async e=>{const f=e.target.files[0];if(!f)return;e.target.value='';
    const send=extra=>{const fd=new FormData();fd.append('file',f);Object.entries(extra).forEach(([k,v])=>fd.append(k,v));return api('POST',`/api/env/${S.envId}/sg/${S.sg}/csv`,fd,true)};
    const pv=(await send({dry_run:'1'})).preview;
    const rows=(list,cls)=>list.map(r=>`<tr class="${cls}"><td>${r.direction==='ingress'?'인바운드':'아웃바운드'}</td><td>${esc(r.protocol)}</td><td>${esc(portStr(r))}</td><td>${esc(srcStr(r))}</td><td>${esc(r.description)}</td></tr>`).join('');
    const ul=(items,cls,title)=>items.length?`<div class="warnbox ${cls}"><b>${title}</b><ul>${items.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div>`:'';
    const panel=m=>{const x=pv[m];return `<div class="pv" data-m="${m}" style="${m==='append'?'':'display:none'}">
      ${ul(x.errors,'danger','적용할 수 없습니다 (아래 오류를 CSV에서 고쳐 주세요)')}${ul(x.risks,'danger','위험 규칙 (적용하면 접근 범위가 넓어집니다)')}${ul(x.warnings.slice(0,6),'','참고')}
      <div style="margin:6px 0">추가 <b>${x.added.length}</b>건${m==='replace'?` · 제거 <b>${x.removed.length}</b>건`:''}</div>
      <table><thead><tr><th>구분</th><th>프로토콜</th><th>포트</th><th>소스</th><th>설명</th></tr></thead><tbody class="plan">${rows(x.added,'add')}${rows(x.removed,'del')}</tbody></table>
      ${(x.added.length||x.removed.length)?'':'<div class="mut" style="margin-top:6px">변경되는 내용이 없습니다 (모두 이미 있는 규칙).</div>'}</div>`};
    const res=await showModal('CSV 적용 미리보기 — '+S.sg,`<div class="row" style="margin-bottom:8px"><label><input type="radio" name="csvm" value="append" checked> 추가 (중복 제외)</label><label><input type="radio" name="csvm" value="replace"> 전체 교체 (기존 규칙을 CSV로 대체)</label></div>${panel('append')}${panel('replace')}`,'적용',null,
      {onMount:o=>o.querySelectorAll('input[name=csvm]').forEach(r=>r.onchange=()=>{const m=o.querySelector('input[name=csvm]:checked').value;o.querySelectorAll('.pv').forEach(p=>p.style.display=p.dataset.m===m?'':'none')}),
       collect:o=>({mode:o.querySelector('input[name=csvm]:checked').value})});
    if(!res)return;const x=pv[res.mode];
    if(x.errors.length)return toast('오류가 있어 적용하지 않았습니다:\n'+x.errors.join('\n'),true,12000);
    let why=null;if(x.risks.length){why=await askRisk(x.risks,{intro:'CSV 적용으로 접근 범위가 넓은 규칙이 추가/변경됩니다. 그대로 적용할까요?',ok:'그대로 적용'});if(!why)return}
    const r=await send({mode:res.mode,...(x.risks.length?{confirm_risk:'1'}:{})});if(why)await recordRisk(S.envId,S.sg,x.risks,why);
    S.warns=r.warnings||[];toast(`적용됨 (in ${r.ingress} / out ${r.egress})`+(S.warns.length?`\n참고 ${S.warns.length}건`:''));await openSg(S.sg);S.warns=r.warnings||[];drawDetail()});
  const ed=d.querySelector('#ed-save');if(ed){
    ed.onclick=async()=>{const g=id=>d.querySelector('#ed-'+id).value.trim();
      const proto=g('proto');const all=proto==='-1';
      const r={protocol:proto,from_port:all?0:+g('from'),to_port:all?0:(g('to')===''?+g('from'):+g('to')),description:g('desc'),prefix_list_ids:[],cidr_blocks:[],security_groups:''};
      if(!all&&(isNaN(r.from_port)||isNaN(r.to_port)||g('from')===''))return toast('포트를 입력하세요',true);
      if(g('stype')==='sg'){r.security_groups=g('src');if(!/^sg-[0-9a-f]+$/.test(r.security_groups))return toast('SG ID 형식이 아닙니다 (sg-xxxx)',true)}
      else{r.cidr_blocks=g('src').split(/[,\s;]+/).filter(Boolean);if(!r.cidr_blocks.length)return toast('IP/CIDR를 입력하세요',true);
        r.cidr_blocks=r.cidr_blocks.map(c=>/\/\d+$/.test(c)?c:c+'/32');
        if(r.cidr_blocks.some(c=>!/^\d+\.\d+\.\d+\.\d+\/\d+$/.test(c)))return toast('CIDR 형식 오류',true)}
      if(!r.description)return toast('설명을 입력하세요',true);
      if(S.edit.i===-1)rules.push(r);else rules[S.edit.i]=r;
      S.edit=null;await saveSg();drawDetail()};
    d.querySelector('#ed-cancel').onclick=()=>{S.edit=null;drawDetail()};
    d.querySelector('#ed-auto').onclick=()=>{const t=$('#ticket').value.trim();if(!t)return toast('상단에 티켓번호를 입력하세요',true);
      const vals=d.querySelector('#ed-src').value.split(/[\s,;]+/).filter(Boolean),found=vals.map(resolveSource).filter(Boolean);
      let s;if(vals.length&&found.length===vals.length)s=[...new Set(found)].join(',');
      else{s=prompt('출발지 정보 (태그/SG ID에서 찾지 못했습니다)',found[0]||'');if(!s)return}
      const o=selfName();
      d.querySelector('#ed-desc').value=`tf_${today()}_${t}_${s} to ${o} Connection`};
  }
}
// SG 짧은 이름 (게임: 접두어/-sg 제거한 리소스명, 플랫폼: SG 이름)
const shortName=(e,name)=>{let n=name||'';if(e.kind==='game'){const p=e.file_prefix||'';if(p&&n.startsWith(p))n=n.slice(p.length);n=n.replace(/-sg$/,'')}return n};
const selfName=()=>shortName(env(),S.sg);  // 설명의 목적지 = 현재 SG 자신
// 출발지(IP 또는 SG ID)가 메타의 태그 값/SG ID와 일치하면 해당 SG의 리소스명(별명 우선)을 반환
const normSrc=x=>String(x).trim().replace(/\/32$/,'').toLowerCase();
function resolveSource(v){
  const n=normSrc(v);if(!n)return null;const envs=S.meta.envs||{};
  for(const eid of [S.envId,...Object.keys(envs).filter(k=>k!==S.envId)]){
    const e=S.cfg.environments.find(x=>x.id===eid);if(!e)continue;
    for(const [name,m] of Object.entries(envs[eid]?.sgs||{})){
      if((m.sg_id&&normSrc(m.sg_id)===n)||(m.tags||[]).some(t=>normSrc(t.value)===n))return m.alias||shortName(e,name)}}
  return null;
}
const ruleKey=r=>[String(r.protocol).toLowerCase(),+r.from_port,+r.to_port,r.security_groups||'',(r.cidr_blocks||[]).join(',')].join('|');
function bulkCard(){
  return `<div class="card" id="bulkcard" style="display:${S.bulk?'':'none'}"><h3>여러 IP 일괄 추가</h3>
    <div class="mut" style="margin-bottom:8px">위 표에서 기준이 될 규칙을 <b>체크</b>하고, 아래에 IP를 입력하세요. 체크한 규칙과 <b>동일한 정책(프로토콜/포트/설명)</b>으로 IP만 바꿔 IP마다 규칙을 추가합니다. (체크한 규칙이 여러 개면 규칙 x IP 만큼 추가)</div>
    <label class="f">IP 목록 (줄바꿈 / 쉼표 / 공백 구분, /32 생략 가능) ${presetPicker('#bk-ips')}<textarea id="bk-ips" placeholder="10.0.0.1&#10;10.0.0.2/32&#10;10.0.1.0/24"></textarea></label>
    <div class="row" style="margin-top:8px"><label class="f" style="flex:1">설명 변경 (비우면 체크한 규칙의 설명 유지. 단 IP가 태그/SG ID로 인식되고 티켓번호가 있으면 출발지 자동 적용. <code>{ip}</code>=IP, <code>{src}</code>=인식된 출발지 리소스)<input type="text" id="bk-desc"></label><button id="bk-auto" style="align-self:end">설명 자동생성</button></div>
    <div class="row" style="margin-top:8px"><button class="pri" id="bk-apply">체크한 규칙에 IP 적용</button><button id="bk-close">닫기</button><span class="mut" id="bk-info"></span></div></div>`;
}
function bindBulk(d,rules,checked){
  const $$=id=>d.querySelector('#bk-'+id);bindPresetPickers(d.querySelector('#bulkcard'),null);
  $$('auto').onclick=()=>{const t=$('#ticket').value.trim();if(!t)return toast('상단에 티켓번호를 입력하세요',true);
    $$('desc').value=`tf_${today()}_${t}_{src} to ${selfName()} Connection`};
  $$('close').onclick=()=>{S.bulk=false;$('#bulkcard').style.display='none'};
  const parse=()=>parseIps($$('ips').value);
  $$('ips').oninput=()=>{const r=parse();const hit=r.ok.map(ip=>resolveSource(ip)?ip.replace(/\/32$/,'')+'→'+resolveSource(ip):'').filter(Boolean);
    $$('info').textContent=`유효 IP ${r.ok.length}개`+(r.bad.length?` / 형식 오류 ${r.bad.length}개`:'')+(hit.length?` / 출발지 인식: ${hit.join(', ')}`:'')};
  $$('apply').onclick=guard(async()=>{const idx=checked();if(!idx.length)return toast('위 표에서 기준 규칙을 먼저 체크하세요',true);
    const {ok,bad}=parse();if(bad.length)return toast('형식 오류: '+bad.join(', '),true);if(!ok.length)return toast('IP를 입력하세요',true);
    const desc=$$('desc').value.trim(),have=new Set(rules.map(ruleKey));let n=0,skip=0;const add=[];
    idx.forEach(i=>ok.forEach(ip=>{const t=rules[i];const r={...JSON.parse(JSON.stringify(t)),cidr_blocks:[ip],security_groups:''};
      const ipn=ip.replace(/\/32$/,''),src=resolveSource(ip),tk=$('#ticket').value.trim();
      r.description=(desc||(src&&tk?`tf_${today()}_${tk}_{src} to ${selfName()} Connection`:t.description)).replace(/\{ip\}/g,ipn).replace(/\{src\}/g,src||ipn);
      if(have.has(ruleKey(r))){skip++;return}have.add(ruleKey(r));add.push(r);n++}));
    rules.push(...add);if(n)await saveSg();S.bulk=false;toast(`${n}개 규칙 추가${skip?`, 이미 있는 ${skip}개 제외`:''}`);drawDetail()});
}
function editRow(r){
  const sg=!!r.security_groups;
  return `<tr class="edit"><td></td><td>-</td><td><select id="ed-proto">${['TCP','UDP','ICMP','-1'].map(p=>{const v=p==='-1'||env().kind==='game'?p:p.toLowerCase();return`<option value="${v}" ${String(r.protocol).toLowerCase()===p.toLowerCase()?'selected':''}>${p==='-1'?'All (-1)':p}</option>`}).join('')}</select></td>
    <td><input type="text" id="ed-from" size="5" value="${esc(r.from_port)}" placeholder="from"> - <input type="text" id="ed-to" size="5" value="${esc(r.to_port)}" placeholder="to"></td>
    <td><select id="ed-stype"><option value="cidr" ${sg?'':'selected'}>IP/CIDR</option><option value="sg" ${sg?'selected':''}>SG ID</option></select>
      <input type="text" id="ed-src" style="width:100%;margin-top:2px" value="${esc(sg?r.security_groups:r.cidr_blocks.join(', '))}" placeholder="10.0.0.1/32 (여러 개는 쉼표) 또는 sg-xxxx"></td>
    <td><input type="text" id="ed-desc" style="width:100%" value="${esc(r.description)}"><button id="ed-auto" style="margin-top:2px">설명 자동생성</button></td>
    <td><button class="pri" id="ed-save">저장</button> <button id="ed-cancel">취소</button></td></tr>`;
}

