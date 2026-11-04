// ---------- ⚡ 빠른 작업 마법사: 규칙 추가 / 규칙 삭제(IP 기준) / 새 SG 만들고 규칙 추가 — 여러 SG 선택 가능
// 티켓·대상·IP/포트 입력 → 전체 내용을 한 번 확인 → 브랜치 → 규칙 변경 → Commit/Push → MR → (선택) plan. apply 는 자동으로 하지 않습니다.
// 자주 쓰는 소스 프리셋(환경설정에서 등록): 선택하면 IP 목록에 추가하고, 출발지 정보가 비어 있으면 프리셋 이름을 넣는다
function presetPicker(target){const ps=S.cfg.presets||[];return ps.length?`<select class="presetpick" data-for="${target}" title="환경설정에 등록한 자주 쓰는 IP"><option value="">프리셋 불러오기...</option>${ps.map((p,i)=>`<option value="${i}">${esc(p.name)} (${p.ips.length}개)</option>`).join('')}</select>`:''}
function bindPresetPickers(root,srcSel){root.querySelectorAll('.presetpick').forEach(sel=>sel.onchange=()=>{const p=(S.cfg.presets||[])[+sel.value];if(!p)return;
  const ta=root.querySelector(sel.dataset.for);ta.value=(ta.value.trim()?ta.value.trim()+'\n':'')+p.ips.join('\n');ta.dispatchEvent(new Event('input'));
  const src=srcSel&&root.querySelector(srcSel);if(src&&!src.value.trim()){src.value=p.name;src.dispatchEvent(new Event('input'))}sel.value=''})}
const sgFileName=(e,res)=>e.kind==='game'?(e.file_prefix||'')+res+'-sg':res;
function wizardCard(){
  return `<details class="card wz" id="wzcard" ${S.wzOpen?'open':''}><summary><b>⚡ 빠른 작업 (마법사)</b> <span class="mut" style="font-weight:400">티켓·대상·IP/포트만 입력하면 브랜치 → 규칙 변경 → Commit/Push → MR → plan 까지 이어서 진행 (apply 는 선택 시에만)</span></summary>
    <div class="wz-start"><b>시작하기</b><span class="row">${S.jira&&S.jira.enabled?'<button type="button" id="wz-tk" title="Jira 티켓(읽기 전용)에서 출발지 IP·포트·대상 SG 후보를 읽어 아래 칸을 채웁니다">Jira 티켓에서 채우기</button><button type="button" id="wz-tkgo" class="blue" title="채운 뒤 바로 실행 확인 창을 엽니다 (확인해야 실행됩니다)">채우고 실행 확인</button><button type="button" id="wz-tkq" title="티켓 여러 개를 차례로 처리합니다 (티켓마다 실행 확인)">여러 티켓 일괄</button>':''}<button type="button" id="wz-tpl" title="요청자가 티켓 설명에 붙여 넣는 표준 요청 양식(표)을 보여 주고 복사합니다">요청 양식</button></span><span class="mut" style="font-size:12px">${S.jira&&S.jira.enabled?'티켓번호를 입력하고 버튼을 누르면 티켓 내용으로 아래 칸이 채워집니다':'아래 칸에 직접 입력하세요 (Jira 연동을 켜면 티켓에서 채울 수 있습니다)'}</span></div>
    <div class="row" style="align-items:flex-start;gap:14px;margin-top:10px">
      <label class="f">작업 종류<select id="wz-act"><option value="add">규칙 추가</option><option value="del">규칙 삭제 (IP 기준)</option><option value="newsg">새 SG 만들고 규칙 추가</option></select></label>
      <label class="f">티켓번호<input type="text" id="wz-ticket" size="14" placeholder="ISRIR-12345"></label>

      <label class="f" id="wz-dirw">방향<select id="wz-dir"><option value="ingress">인바운드</option><option value="egress">아웃바운드</option></select></label>
      <label class="f wz-addf">프로토콜<select id="wz-proto"><option value="TCP">TCP</option><option value="UDP">UDP</option></select></label>
      <label class="f wz-addf">포트 (From - To, 여러 개는 From 칸에 쉼표로)<span class="row"><input type="text" id="wz-from" size="6" placeholder="6001"><input type="text" id="wz-to" size="6" placeholder="(같으면 생략)">${svcPicker()}</span></label>
      <div class="f wz-delf" style="display:none">삭제 대상 방향<span class="row"><label><input type="checkbox" id="wz-din" checked> 인바운드</label><label><input type="checkbox" id="wz-dout" checked> 아웃바운드</label></span></div>
      <label class="f wz-delf" style="display:none">IP 일치 방식<select id="wz-match"><option value="exact">정확히 일치</option><option value="overlap">포함/겹침</option></select></label></div>
    <div class="row" style="align-items:flex-start;gap:14px;margin-top:8px">
      <div class="f" id="wz-sgbox" style="min-width:300px;flex:1">대상 SG (여러 개 선택 가능)<input type="text" id="wz-sgq" placeholder="SG 필터"><div id="wz-sgs" class="dlbox" style="max-height:170px;width:100%"></div></div>
      <div class="f" id="wz-newbox" style="min-width:300px;flex:1;display:none">새 SG 리소스명<input type="text" id="wz-new" placeholder="${env().kind==='game'?'예: auto-scaler-lambda':'예: sip-docdb'}">
        <span class="mut" style="font-weight:400">파일 이름: <code id="wz-newname"></code></span>${env().kind==='game'?'<label style="font-weight:400"><input type="checkbox" id="wz-eg" checked> egress 기본 allow-all</label>':''}</div>
      <div style="flex:1;min-width:280px"><label class="f">IP 목록 (줄바꿈/쉼표 구분, /32 생략 가능, @프리셋이름 가능) ${presetPicker('#wz-ips')}<textarea id="wz-ips" placeholder="10.0.0.1&#10;10.0.0.2/32"></textarea></label>
        <label class="f wz-addf" style="margin-top:8px">출발지 정보 (비우면 태그/SG ID로 자동 인식, 없으면 IP)<input type="text" id="wz-src" placeholder="예: match3"></label>
        <label class="f" style="margin-top:8px">Summary (MR 요약, 비우면 자동 생성)<input type="text" id="wz-sum"></label>${S.jira&&S.jira.enabled?'<button id="wz-jsum" style="margin-top:4px">Jira 제목으로 채우기</button>':''}
        <div class="mut" id="wz-prev" style="font-size:12px;margin-top:6px"></div></div></div>
    <details class="wz-adv" id="wz-adv"><summary>진행 옵션 <span id="wz-optsum" class="chip">plan 까지</span></summary><div class="row" style="margin-top:6px"><label><input type="checkbox" id="wz-plan" checked> MR 생성 후 atlantis plan 실행</label>
      <label title="체크하면 plan 이 이상 없을 때(삭제·교체 없음, 대상 SG 안의 변경만, 위험 규칙 없음) apply 까지 자동으로 진행합니다. 체크하지 않으면 apply 는 직접 합니다. 규칙 삭제 작업은 자동 apply 하지 않습니다."><input type="checkbox" id="wz-apply"> plan 이 이상 없으면 <b>apply 까지</b> 진행</label>
      ${S.jira&&S.jira.enabled?'<label title="apply 까지 끝나면 Jira 에 코멘트를 남기고 상태를 전환합니다 (처음 한 번 전환할 상태를 고르면 기억합니다)"><input type="checkbox" id="wz-jira" checked> 완료 시 Jira 코멘트·상태 전환</label>':''}
    </div></details><div class="row" style="margin-top:8px"><span class="mut" style="font-size:12px">Assignees/Reviewers 는 4번 카드의 선택값을 사용합니다.</span><span style="margin-left:auto" class="row"><button class="blue" id="wz-run">검토 후 실행</button></span></div>
    <div id="wzs" style="margin-top:10px"></div></details>`}
async function bindWizard(){
  const c=$('#wzcard');if(!c)return;c.addEventListener('toggle',()=>{S.wzOpen=c.open});
  $('#wz-ticket').value=$('#ticket').value;
  if(!S.sgs.length)await loadSgs();if(!$('#wz-sgs'))return;
  const e=env();S.wzSel=S.wzSel||new Set();
  const drawSgs=()=>{const q=$('#wz-sgq').value.trim().toLowerCase();
    $('#wz-sgs').innerHTML=S.sgs.filter(x=>!q||x.name.toLowerCase().includes(q)).map(x=>`<label class="chk"><input type="checkbox" class="wz-sg" value="${esc(x.name)}" ${S.wzSel.has(x.name)?'checked':''}> ${esc(x.name)}</label>`).join('')||'<div class="mut" style="padding:6px">SG 없음</div>';
    $('#wz-sgs').querySelectorAll('.wz-sg').forEach(i=>i.onchange=()=>{i.checked?S.wzSel.add(i.value):S.wzSel.delete(i.value);upd()})};
  const upd=()=>{const act=$('#wz-act').value,t=$('#wz-ticket').value.trim(),ips=parseIps($('#wz-ips').value),f=$('#wz-from').value.trim(),n=S.wzSel.size;
    document.querySelectorAll('.wz-addf').forEach(x=>x.style.display=act==='del'?'none':'');document.querySelectorAll('.wz-delf').forEach(x=>x.style.display=act==='del'?'':'none');
    $('#wz-dirw').style.display=act==='del'?'none':'';$('#wz-sgbox').style.display=act==='newsg'?'none':'';$('#wz-newbox').style.display=act==='newsg'?'':'none';
    $('#wz-newname').textContent=$('#wz-new').value.trim()?sgFileName(e,$('#wz-new').value.trim()):'';
    const dst=act==='newsg'?$('#wz-new').value.trim():(n?shortName(e,[...S.wzSel][0]):'');
    $('#wz-prev').textContent=(t&&dst&&act!=='del'?`설명 예: tf_${today()}_${t}_${$('#wz-src').value.trim()||'[출발지]'} to ${dst} Connection · `:'')+`SG ${act==='newsg'?($('#wz-new').value.trim()?1:0):n}개 · IP ${ips.ok.length}개${ips.bad.length?` (형식 오류 ${ips.bad.length})`:''}${f&&act!=='del'?` · 포트 ${f}${$('#wz-to').value.trim()&&$('#wz-to').value.trim()!==f?'-'+$('#wz-to').value.trim():''}`:''}`};
  ['#wz-act','#wz-ticket','#wz-ips','#wz-src','#wz-from','#wz-to','#wz-new'].forEach(s=>$(s).addEventListener('input',upd));$('#wz-act').addEventListener('change',upd);
  $('#wz-sgq').oninput=drawSgs;bindPresetPickers($('#wzcard'),'#wz-src');
  $('#wz-svc')&&($('#wz-svc').onchange=()=>{const s=(S.services||[])[+$('#wz-svc').value];if(!s)return;$('#wz-proto').value=s.protocol;const pp=s.ports.split('-');$('#wz-from').value=pp[0];$('#wz-to').value=pp[1]||'';upd();$('#wz-svc').value=''});
  $('#wz-jsum')&&($('#wz-jsum').onclick=guard(()=>jiraFill('#wz-sum')));
  $('#wz-tk')&&($('#wz-tk').onclick=guard(()=>ticketFillWizard(false)));$('#wz-tkgo')&&($('#wz-tkgo').onclick=guard(()=>ticketFillWizard(true)));
  $('#wz-tkq')&&($('#wz-tkq').onclick=guard(openTicketQueue));$('#wz-tpl').onclick=guard(openRequestTemplate);
  const syncApply=()=>{const ap=$('#wz-apply');if(!ap)return;const ok=$('#wz-plan').checked&&$('#wz-act').value!=='del';ap.disabled=!ok;if(!ok)ap.checked=false;ap.parentElement.style.opacity=ok?'':'.5'};
  $('#wz-plan').addEventListener('change',syncApply);$('#wz-act').addEventListener('change',syncApply);syncApply();['#wz-plan','#wz-apply','#wz-jira'].forEach(q=>{const x=$(q);if(x)x.addEventListener('change',wzOptSum)});wzOptSum();
  $('#wz-run').onclick=guard(runWizard);drawSgs();upd();if(S.wzPending){fillWizard(S.wzPending);S.wzPending=null}}
// plan 결과가 나올 때까지 기다린다 (자동 apply 조건 검사 결과 포함). 최대 15분
async function waitPlanResult(iid,envId,targets,expect){
  const q=`iid=${encodeURIComponent(iid)}&targets=${encodeURIComponent(targets.join(','))}&expect=${expect}`;
  for(let i=0;i<225;i++){await new Promise(r=>setTimeout(r,i?4000:1500));
    const ps=await api('GET',`/api/env/${envId}/atlantis/plan-status?${q}`);if(ps.exists&&ps.state&&ps.state!=='pending')return ps}
  throw new Error('plan 결과를 15분 안에 받지 못했습니다 — apply 하지 않았습니다')}
// apply 를 요청하고 결과가 나올 때까지 기다린다. 끝난 뒤 정리(엑셀 기록·main 전환·Jira 완료 처리)는 pollOut 이 이어서 한다
async function applyAndWait(iid,envId){
  const r=await api('POST',`/api/env/${envId}/atlantis`,{iid,action:'apply',confirm_destroy:false}),key=histKey();
  const hid=addHist(`atlantis apply → MR !${iid}`,r.command+'\n(빠른 작업에서 "apply 까지 진행"을 선택해 자동으로 요청했습니다)',{kind:'apply',state:'pending',headline:'⏳ 응답 대기 중...',poll:{iid,since:r.note_id,action:'apply',envId}});
  pollOut(iid,r.note_id,'apply',hid,key,envId);
  for(let i=0;i<225;i++){await new Promise(r2=>setTimeout(r2,4000));const e=histLoad(key).find(x=>x.id===hid);if(e&&e.state!=='pending'){if(e.state!=='ok')throw new Error('apply 결과: '+(e.headline||e.state));return}}
  throw new Error('apply 결과를 15분 안에 받지 못했습니다 — 작업 이력을 확인하세요')}
// 이전 작업(작업 이력)의 설정으로 마법사 채우기
function fillWizard(m){const c=$('#wzcard');if(!c||!$('#wz-act')){S.wzPending=m;return}
  c.open=true;S.wzOpen=true;$('#wz-act').value=m.act||'add';$('#wz-dir').value=m.dir||'ingress';$('#wz-proto').value=m.proto||'TCP';
  $('#wz-from').value=m.from??'';$('#wz-to').value=(m.to!=null&&m.to!==m.from)?m.to:'';$('#wz-ips').value=(m.ips||[]).join('\n');$('#wz-src').value=m.src||'';$('#wz-sum').value=m.summary||'';
  $('#wz-new').value=m.newRes||'';$('#wz-din').checked=m.dirs?m.dirs.includes('ingress'):true;$('#wz-dout').checked=m.dirs?m.dirs.includes('egress'):true;$('#wz-match').value=m.match||'exact';
  S.wzSel=new Set((m.targets||[]).filter(n=>S.sgs.some(x=>x.name===n)));$('#wz-sgq').value='';
  $('#wz-act').dispatchEvent(new Event('change'));$('#wz-sgs').querySelectorAll('.wz-sg').forEach(i=>i.checked=S.wzSel.has(i.value));
  $('#wz-ticket').value='';$('#wz-ticket').focus();c.scrollIntoView({block:'start'});toast('이전 작업 설정을 불러왔습니다. 티켓번호를 입력하고 확인 후 실행하세요')}
async function runWizard(){
  const e=env(),g=id=>$('#wz-'+id).value.trim(),act=g('act'),ticket=g('ticket').toUpperCase();
  if(!/^[A-Z][A-Z0-9_]+-\d+$/.test(ticket))return toast('티켓번호 형식이 올바르지 않습니다 (예: ISRIR-12345)',true);
  const ips=parseIps($('#wz-ips').value);if(ips.bad.length)return toast('IP 형식 오류: '+ips.bad.join(', '),true);if(!ips.ok.length)return toast('IP를 입력하세요',true);
  let targets=[...S.wzSel],newRes='';
  if(act==='newsg'){newRes=g('new');if(!/^[A-Za-z0-9_.\-]+$/.test(newRes))return toast('새 SG 리소스명을 영문/숫자/-/_ 로 입력하세요',true);targets=[sgFileName(e,newRes)];
    if(S.sgs.some(x=>x.name===targets[0]))return toast('이미 있는 SG 입니다: '+targets[0],true)}
  else if(!targets.length)return toast('대상 SG를 선택하세요',true);
  const dir=g('dir'),proto=g('proto'),pl=act==='del'?[]:parsePortList(g('from'),g('to')),from=pl&&pl[0]?pl[0][0]:NaN,to=pl&&pl[0]?pl[0][1]:NaN,srcIn=g('src'),match=g('match');
  const dirs=['ingress','egress'].filter(d=>d==='ingress'?$('#wz-din').checked:$('#wz-dout').checked);
  if(act!=='del'&&(!pl||!pl.length))return toast('포트를 입력하세요 (예: 443 또는 443, 8080-8090)',true);
  if(act==='del'&&!dirs.length)return toast('삭제할 방향을 선택하세요',true);
  const port=act==='del'?'':pl.map(r=>r[0]===r[1]?String(r[0]):r[0]+'-'+r[1]).join(', '),dst0=shortName(e,targets[0]);
  const rules=act==='del'?[]:ips.ok.flatMap(ip=>{const ipn=ip.replace(/\/32$/,''),src=srcIn||resolveSource(ip)||ipn;
    return pl.map(([a,b])=>({direction:dir,protocol:proto,from_port:a,to_port:b,cidr_blocks:[ip],security_groups:'',prefix_list_ids:[],description:`tf_${today()}_${ticket}_${src} to ${dst0} Connection`}))});
  if(rules.length>50)return toast(`규칙이 ${rules.length}개라 한 번에 처리할 수 없습니다 (IP × 포트 50개까지). 나눠서 실행하세요`,true);
  const more=targets.length>1?` 외 ${targets.length-1}개 SG`:'';
  const summary=g('sum')||(act==='del'?`${dst0}${more} ${ips.ok.join(', ')} 접근제어 삭제`:act==='newsg'?`${dst0} SG 신규 생성 및 ${port} 접근제어 추가 (${ips.ok.length}개 IP)`:`${dst0}${more} ${port} ${dir==='ingress'?'접근제어':'아웃바운드'} 추가 (${ips.ok.length}개 IP)`);
  const doPlan=$('#wz-plan').checked,tg=targets.map(n=>({env_id:S.envId,name:n}));
  const doApply=!!($('#wz-apply')&&$('#wz-apply').checked)&&doPlan&&act!=='del',wantJira=!!($('#wz-jira')&&$('#wz-jira').checked);let riskUsed=false;
  // 미리보기 (저장하지 않음): 중복/오류/삭제 대상 확인
  let pv=null;
  if(act==='add')pv=await api('POST','/api/bulk-apply',{rules,targets:tg,retarget_desc:true,dry_run:true});
  if(act==='del')pv=await api('POST','/api/bulk-delete',{env_id:S.envId,targets:tg,ips:ips.ok,match,directions:dirs,dry_run:true});
  if(pv&&act==='add'){const errs=pv.results.flatMap(x=>x.errors.map(k=>`${x.name}: ${k}`));if(errs.length)return toast('검증 오류로 시작하지 않았습니다:\n'+errs.join('\n'),true,12000);
    if(!pv.results.some(x=>x.added))return toast('추가할 규칙이 없습니다 (이미 모두 있음)',true)}
  if(pv&&act==='del'&&!pv.total_removed&&!pv.total_modified)return toast('삭제할 규칙을 찾지 못했습니다 (IP/일치 방식 확인)',true);
  const st0=await api('GET',`/api/env/${S.envId}/git/status`),reuse=st0.cloned&&!st0.on_default&&st0.branch.includes(ticket);
  const body=act==='del'?`<table><thead><tr><th>SG</th><th>삭제</th><th>일부 IP 제거</th></tr></thead><tbody class="plan">${pv.results.map(x=>`<tr class="del"><td>${esc(x.name)}</td><td>${x.removed.map(r=>esc(r.direction+' '+portStr(r)+' '+srcStr(r))).join('<br>')||'-'}</td><td>${x.modified.map(r=>esc(portStr(r)+' : '+r.removed_cidrs.join(', '))).join('<br>')||'-'}</td></tr>`).join('')}</tbody></table>`
    :`<table><thead><tr><th>SG</th><th>방향</th><th>프로토콜</th><th>포트</th><th>소스</th><th>설명</th></tr></thead><tbody class="plan">${targets.slice(0,6).flatMap(n=>rules.map(r=>`<tr class="add"><td>${esc(n)}${act==='newsg'?' <b>(새 SG)</b>':''}</td><td>${r.direction==='ingress'?'인':'아웃'}바운드</td><td>${esc(r.protocol)}</td><td>${esc(port)}</td><td>${esc(r.cidr_blocks[0])}</td><td>${esc(r.description)}</td></tr>`)).join('')}</tbody></table>${targets.length>6?`<div class="mut">… 외 ${targets.length-6}개 SG 동일 적용 (설명의 목적지는 각 SG 이름으로 변경)</div>`:''}${pv?`<div class="mut" style="margin-top:4px">이미 있어 건너뛰는 규칙: ${pv.results.reduce((a,x)=>a+x.skipped,0)}건</div>`:''}${pv&&pv.results.some(x=>(x.already||[]).length)?`<div class="warnbox" style="margin-top:6px"><b>이미 열려 있는 규칙이 있습니다 (불필요한 규칙일 수 있음)</b><ul>${pv.results.flatMap(x=>(x.already||[]).map(k=>`<li>${esc(x.name)}: ${esc(k)}</li>`)).slice(0,8).join('')}</ul></div>`:''}`;
  const html=`<div class="sumline"><span class="chip">${esc(e.env)}${e.label?' · '+esc(e.label):''}</span><span class="chip">${{add:'규칙 추가',del:'규칙 삭제',newsg:'새 SG 생성 + 규칙 추가'}[act]}</span><span class="chip">SG ${targets.length}개</span><span class="chip">IP ${ips.ok.length}개</span>${act==='del'?'':`<span class="chip">규칙 ${rules.length*targets.length}건</span>`}${doApply?'<span class="chip danger">apply 까지 진행 ⚠</span>':''}${wantJira?'<span class="chip">Jira 기록</span>':''}</div>
    <details style="margin:8px 0" ${doApply?'open':''}><summary>진행 단계 보기</summary><ol style="margin:8px 0;padding-left:18px"><li>브랜치 ${reuse?`<b>${esc(st0.branch)}</b> 사용 (이미 작업 브랜치)`:`<code>${esc(S.account||'계정')}/${today()}_${esc(ticket)}</code> 새로 생성 (${esc(e.target_branch||'main')} 최신화)`}</li>
      <li>${act==='del'?'규칙 삭제':act==='newsg'?'SG 파일 생성 후 규칙 추가':'규칙 추가'} 후 파일 저장 (검증 오류는 중단, 위험 규칙은 별도 확인)</li><li>SG 폴더의 변경 파일만 Commit &amp; Push</li>
      <li>MR 생성 (이미 열린 MR 이 있으면 재사용) — Assignees ${esc(S.pk.asg.join(', ')||'-')} / Reviewers ${esc(S.pk.rev.join(', ')||'-')}</li><li>${doPlan?'atlantis plan 실행 (결과는 작업 이력)':'(plan 은 실행하지 않음)'}</li>${doApply?'<li><b>plan 이 이상 없으면 atlantis apply 까지 진행</b> — 삭제·교체 0건, 변경이 대상 SG 안에서만, 위험 규칙 승인 없음일 때만 (아니면 apply 하지 않고 멈춤)</li>':'<li>apply 는 직접 합니다 (5번 카드)</li>'}${wantJira?`<li>${doApply?'apply 가 끝나면':'apply 를 마치면'} Jira ${esc(ticket)} 에 코멘트를 남기고 상태를 전환합니다</li>`:''}</ol></details>${body}
    <div class="mut" style="margin-top:8px">MR Summary: ${esc(summary)}</div><div class="warnbox ${doApply?'danger':''}" style="margin-top:8px">${doApply?'<b>실행하면 plan 이 이상 없을 때 apply 까지 자동으로 진행되어 실제 SG 규칙이 바로 바뀝니다.</b> 브랜치 생성/수정, push, MR 생성도 실제로 진행됩니다.':'실행하면 저장소 브랜치 생성/수정, push, MR 생성이 실제로 진행됩니다.'}</div>`;
  if(!await showModal('빠른 작업 실행 확인',html,doApply?'apply 까지 실행':act==='del'?'삭제 실행':'실행',null,{danger:doApply||act==='del'}))return;
  const steps=['브랜치 준비','규칙 변경','Commit & Push','MR 생성','atlantis plan','plan 결과 확인','atlantis apply'].filter((_,i)=>i<4||(i===4&&doPlan)||(i>4&&doApply));
  const box=$('#wzs'),state=steps.map(()=>['⏳ 대기','']);
  const draw=()=>{box.innerHTML=steps.map((s,i)=>`<div>${state[i][0]} <b>${i+1}. ${esc(s)}</b> <span class="mut">${esc(state[i][1])}</span></div>`).join('');jobSet({title:`${ticket} · ${dst0}${more}`,steps:steps.map((n,i)=>({label:n,state:uxState(state[i][0]),note:state[i][1]})),done:false})};
  const run=async(i,fn)=>{state[i]=['🔄 진행 중',''];draw();try{const note=await fn();state[i]=['✅ 완료',note||''];draw()}catch(err){state[i]=['❌ 실패',err.message.split('\n')[0]];draw();addHist('마법사: '+steps[i],err.message,{kind:['prep','rule','push','mr','plan','plan','apply'][i],state:'error',headline:'❌ 실패'});throw err}};
  draw();let mr=null;
  const meta={wz:{act,dir,proto,from:pl&&pl.length>1?g('from'):from,to:pl&&pl.length>1?'':to,ips:ips.ok,src:srcIn,summary:g('sum'),targets,newRes,dirs,match}};
  try{
    await run(0,async()=>{if(reuse)return '기존 작업 브랜치 사용: '+st0.branch;
      const r=await api('POST',`/api/env/${S.envId}/git/prepare`,{ticket});addHist('브랜치 준비 → '+r.branch,r.log,{kind:'prep',headline:'✓ 브랜치 생성'});return r.branch});
    await run(1,async()=>{
      if(act==='newsg'){const r=await api('POST',`/api/env/${S.envId}/sgs`,{resource:newRes,egress_allow_all:$('#wz-eg')?!!$('#wz-eg').checked:false});targets=[r.name];tg[0].name=r.name}
      if(act==='del'){const r=await api('POST','/api/bulk-delete',{env_id:S.envId,targets:tg,ips:ips.ok,match,directions:dirs,dry_run:false});
        addHist(`규칙 삭제 → SG ${r.results.length}개`,r.results.map(x=>`${x.name}: 삭제 ${x.removed.length} / 일부 IP 제거 ${x.modified.length}`).join('\n'),{kind:'rule',headline:`✓ 삭제 ${r.total_removed}건 · 수정 ${r.total_modified}건`,meta});
        return `삭제 ${r.total_removed}건 / 일부 제거 ${r.total_modified}건`}
      const call=conf=>api('POST','/api/bulk-apply',{rules,targets:tg,retarget_desc:true,confirm_risk:conf});let r;
      try{r=await call(false)}catch(err){
        if(err.data&&err.data.need_confirm){const risks=err.data.results.filter(x=>x.risks.length).flatMap(x=>x.risks.map(k=>`${x.name}: ${k}`));
          const why=await askRisk(risks,{intro:'접근 범위가 넓은 규칙이 포함되어 있습니다. 계속할까요?'});if(!why)throw new Error('위험 규칙 확인에서 중단했습니다');riskUsed=true;r=await call(true);await recordRiskAll(err.data.results,why)}
        else if(err.data&&err.data.results){throw new Error('검증 오류:\n'+err.data.results.flatMap(x=>x.errors.map(k=>`${x.name}: ${k}`)).join('\n'))}else throw err}
      const n=r.results.reduce((a,x)=>a+x.added,0);if(!n)throw new Error('추가할 규칙이 없습니다 (이미 모두 있음)');
      addHist(`규칙 추가 → SG ${r.results.length}개`,r.results.map(x=>`${x.name}: +${x.added}${x.skipped?` (중복 ${x.skipped})`:''}`).join('\n')+'\n'+rules.map(x=>`${x.direction} ${x.protocol} ${port} ${x.cidr_blocks[0]}  ${x.description}`).join('\n'),{kind:'rule',headline:`✓ ${n}건 추가${act==='newsg'?' (새 SG)':''}`,meta});return `${n}건 추가`});
    await run(2,async()=>{const r=await api('POST',`/api/env/${S.envId}/git/push`,{});
      addHist(`Commit & Push → ${r.branch}`,r.files.map(f=>f.state+' '+f.path).join('\n')+(r.skipped&&r.skipped.length?'\n(커밋 제외 - SG 폴더 밖 '+r.skipped.length+'개)':'')+'\n'+r.log,{kind:'push',headline:r.is_new?'✓ push (신규 파일 포함)':'✓ push (기존 파일 수정)'});return r.branch});
    await run(3,async()=>{mr=await api('POST',`/api/env/${S.envId}/mr`,{summary,assignees:S.pk.asg,reviewers:S.pk.rev});S.mr[S.envId]={iid:mr.iid,url:mr.url};ls.set('mr',S.mr);
      if(mr.existing){addHist(`기존 MR 연결 → !${mr.iid}`,`${mr.url}\n같은 브랜치로 이미 열린 MR 이 있어 새로 만들지 않았습니다 (기존 MR 은 변경하지 않음)`,{kind:'mr',headline:'↺ 기존 MR !'+mr.iid+' 사용'});return '기존 MR !'+mr.iid+' 사용 (새로 만들지 않음)'}
      addHist(`MR 생성 → !${mr.iid}`,`${mr.url}\nAssignees: ${S.pk.asg.join(', ')||'-'}\nReviewers: ${S.pk.rev.join(', ')||'-'}\nSummary: ${summary}`,{kind:'mr',headline:'✓ MR !'+mr.iid});return '!'+mr.iid});
    S.jiraCtx=S.jiraCtx||{};S.jiraCtx[S.envId]={ticket,iid:mr.iid,url:mr.url,summary,on:wantJira,purpose:(S.wzJira&&S.wzJira.key===ticket)?S.wzJira.purpose:''};
    if(doPlan)await run(4,async()=>{S.atEnv=S.envId;await startPlan(mr.iid,S.atEnv);return '요청됨 — 결과는 작업 이력'});
    let held='',applied=false;
    if(doApply){
      await run(5,async()=>{const ps=await waitPlanResult(mr.iid,S.atEnv,targets,rules.length*targets.length);
        if(ps.state==='error')throw new Error('plan 이 실패했습니다. 오류를 확인하세요 — apply 하지 않았습니다');
        if(riskUsed)held='위험 규칙 승인이 필요한 변경이라 자동 apply 하지 않습니다';else if(!ps.auto_ok)held=ps.auto_reason||'plan 결과가 조건을 만족하지 않습니다';
        return held?'보류 — '+held:ps.checks.map(c=>`${c.ok?'✓':c.block?'✗':'△'} ${c.label}${c.detail?` (${c.detail})`:''}`).join(' · ')});
      if(held){state[6]=['⏸ 보류',held];draw();addHist('apply 보류 → MR !'+mr.iid,held+'\n5번 카드에서 plan 결과를 확인한 뒤 직접 apply 하세요',{kind:'apply',state:'warn',headline:'⏸ 자동 apply 보류'})}
      else{await run(6,async()=>{await applyAndWait(mr.iid,S.atEnv);applied=true;return '완료'});await S.finishing}}
    toast(applied?'빠른 작업을 apply 까지 마쳤습니다':held?'plan 결과가 조건을 만족하지 않아 apply 하지 않았습니다: '+held+' — 5번 카드에서 확인 후 직접 apply 하세요':'빠른 작업을 마쳤습니다. plan 결과를 확인한 뒤 5번 카드에서 apply 하세요',!!held,applied?5000:8000);
    jobEnd(!held);return{ok:true,mr,applied,held};
  }catch(err){toast('마법사가 중단되었습니다: '+err.message.split('\n')[0],true,10000);jobEnd(false);return{ok:false,error:err.message}}
  finally{gitStatus(true);drawHist();const i=$('#iid');if(i&&mr)i.value=mr.iid;refreshPlanStatus();refreshExistingMr()}}

// ---------- 같은 규칙을 다른 SG(같은 저장소의 다른 환경 포함)에 한 번에 적용
async function applyToOtherSgs(rulesSel){
  const here=repoOf(env()).dir.toLowerCase();
  const sameEnvs=S.cfg.environments.filter(e=>e.id!==S.envId&&repoOf(e).dir.toLowerCase()===here);
  const lists={[S.envId]:S.sgs.filter(x=>x.name!==S.sg).map(x=>x.name)};
  const envLabel=id=>{const e=S.cfg.environments.find(x=>x.id===id);return `${e.group} · ${e.env}${e.label?' · '+e.label:''}`};
  const picked=new Set();const key=(e,n)=>e+'|'+n;
  const html=`<div class="mut" style="margin-bottom:6px">체크한 규칙 <b>${rulesSel.length}</b>개를 아래 SG에 추가합니다. 같은 규칙(프로토콜/포트/소스)이 이미 있으면 건너뜁니다.</div>
    <table style="margin-bottom:8px"><tbody class="plan">${rulesSel.map(r=>`<tr class="add"><td>${r.direction==='ingress'?'인바운드':'아웃바운드'}</td><td>${esc(r.protocol)}</td><td>${esc(portStr(r))}</td><td>${esc(srcStr(r))}</td><td>${esc(r.description)}</td></tr>`).join('')}</tbody></table>
    <div class="row"><input type="text" id="bs-q" style="flex:1" placeholder="SG 필터">${sameEnvs.length?`<label><input type="checkbox" id="bs-oth"> 같은 저장소의 다른 환경도 보기 (${sameEnvs.length}개)</label>`:''}<label><input type="checkbox" id="bs-all"> 보이는 것 전체 선택</label></div>
    <div id="bs-list" class="dlbox" style="max-height:260px;margin-top:6px;width:100%"></div>
    <label style="display:block;margin-top:8px"><input type="checkbox" id="bs-rt" checked> 설명의 목적지를 대상 SG 이름으로 변경 (<code>tf_..._출발지 to 대상 Connection</code>)</label>
    <div class="row" style="margin-top:8px"><button id="bs-prev">미리보기</button><span class="mut" id="bs-cnt"></span></div><div id="bs-res" style="margin-top:8px"></div>`;
  const targetsOf=()=>[...picked].map(k=>{const i=k.indexOf('|');return{env_id:k.slice(0,i),name:k.slice(i+1)}});
  const res=await showModal('다른 SG에 규칙 적용 — '+S.sg,html,'적용',null,{
    onMount:o=>{
      const list=o.querySelector('#bs-list'),cnt=()=>o.querySelector('#bs-cnt').textContent=`선택 ${picked.size}개 SG`;
      const draw=()=>{const q=o.querySelector('#bs-q').value.trim().toLowerCase(),oth=o.querySelector('#bs-oth')?.checked;
        const ids=[S.envId,...(oth?sameEnvs.map(e=>e.id):[])];
        list.innerHTML=ids.map(id=>{const names=(lists[id]||[]).filter(n=>!q||n.toLowerCase().includes(q));
          return `<div class="mut" style="padding:4px 6px;font-weight:700">${esc(envLabel(id))}${lists[id]?'':' (불러오는 중...)'}</div>`+names.map(n=>`<label class="chk"><input type="checkbox" class="bt" data-e="${esc(id)}" value="${esc(n)}" ${picked.has(key(id,n))?'checked':''}> ${esc(n)}</label>`).join('')}).join('');
        list.querySelectorAll('.bt').forEach(c=>c.onchange=()=>{c.checked?picked.add(key(c.dataset.e,c.value)):picked.delete(key(c.dataset.e,c.value));cnt()});cnt()};
      const loadOther=async()=>{await Promise.all(sameEnvs.filter(e=>!lists[e.id]).map(async e=>{try{lists[e.id]=(await api('GET',`/api/env/${e.id}/sgs`)).sgs.map(x=>x.name)}catch{lists[e.id]=[]}}));draw()};
      o.querySelector('#bs-q').oninput=draw;
      o.querySelector('#bs-oth')?.addEventListener('change',async()=>{draw();if(o.querySelector('#bs-oth').checked)await loadOther()});
      o.querySelector('#bs-all').onchange=ev=>{list.querySelectorAll('.bt').forEach(c=>{c.checked=ev.target.checked;ev.target.checked?picked.add(key(c.dataset.e,c.value)):picked.delete(key(c.dataset.e,c.value))});cnt()};
      o.querySelector('#bs-prev').onclick=async()=>{const t=targetsOf();if(!t.length)return toast('대상 SG를 선택하세요',true);
        try{const r=await api('POST','/api/bulk-apply',{rules:rulesSel,targets:t,retarget_desc:o.querySelector('#bs-rt').checked,dry_run:true});
          o.querySelector('#bs-res').innerHTML=`<table><thead><tr><th>SG</th><th>추가</th><th>중복(건너뜀)</th><th>검증</th></tr></thead><tbody>${r.results.map(x=>`<tr><td>${esc(x.name)}</td><td><b>${x.added}</b></td><td>${x.skipped}</td>
            <td>${x.errors.length?`<span style="color:var(--err)">${esc(x.errors.join(' / '))}</span>`:x.risks.length?`<span style="color:var(--warn)">위험: ${esc(x.risks.join(' / '))}</span>`:'<span style="color:var(--ok)">이상 없음</span>'}</td></tr>`).join('')}</tbody></table>`}
        catch(err){toast(err.message,true)}};
      draw()},
    collect:o=>({targets:targetsOf(),retarget:o.querySelector('#bs-rt').checked})});
  if(!res)return;if(!res.targets.length)return toast('대상 SG를 선택하세요',true);
  const call=confirm=>api('POST','/api/bulk-apply',{rules:rulesSel,targets:res.targets,retarget_desc:res.retarget,confirm_risk:confirm});
  let r;try{r=await call(false)}catch(err){
    if(err.data&&err.data.need_confirm){const risks=err.data.results.filter(x=>x.risks.length).flatMap(x=>x.risks.map(k=>`${x.name}: ${k}`));
      const why=await askRisk(risks,{intro:'접근 범위가 넓은 규칙이 포함되어 있습니다. 그대로 적용할까요?',ok:'그대로 적용'});if(!why)return;r=await call(true);await recordRiskAll(err.data.results,why)}
    else if(err.data&&err.data.results){const errs=err.data.results.filter(x=>x.errors.length).flatMap(x=>x.errors.map(k=>`${x.name}: ${k}`));throw new Error('검증 오류로 아무것도 저장하지 않았습니다:\n'+errs.join('\n'))}
    else throw err}
  const total=r.results.reduce((a,x)=>a+x.added,0);
  addHist(`규칙 일괄 적용 → SG ${r.results.length}개`,r.results.map(x=>`${x.name}: +${x.added}${x.skipped?` (중복 ${x.skipped})`:''}`).join('\n'),{kind:'rule',headline:`✓ ${total}건 추가`});
  toast(`${r.results.length}개 SG에 ${total}건 추가했습니다 (파일만 수정됨 — Commit/Push 는 작업 탭에서)`,false,6000);
  await loadSgs();await loadChg();drawSgList()}

