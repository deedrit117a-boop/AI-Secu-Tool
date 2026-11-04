// ---------- 검토 도구(화면): 위험 규칙 승인 사유, 서비스 사전, 규칙 점검 보고서의 'SG 관계 / 기준 점검 / 티켓 찾기' 탭
// 승인 사유와 서비스 사전만 값을 저장한다. 나머지는 읽기 전용 조회다.

// 위험 규칙 확인 창 + 승인 사유(필수). 사유 문자열을 돌려주고, 취소하면 null. 저장이 끝난 뒤 recordRisk 로 기록한다
async function askRisk(risks,o){o=o||{};let why='';
  for(;;){
    const r=await showModal(o.title||'⚠ 위험 규칙 확인',`<div>${o.intro||'접근 범위가 넓은 규칙이 포함되어 있습니다. 그대로 진행할까요?'}</div><ul>${risks.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>
      <label class="f" style="margin-top:8px">승인 사유 (필수 — 변경 기록 파일과 MR 본문에 남습니다)<input type="text" id="rk-why" maxlength="300" style="width:100%" placeholder="예: ISRIR-12345 사무실 이전, 팀장 승인" value="${esc(why)}"></label>`,o.ok||'그대로 진행',null,
      {collect:m=>({why:m.querySelector('#rk-why').value.trim()})});
    if(!r)return null;why=r.why;if(why.length>=2)return why;toast('승인 사유를 2자 이상 적어 주세요',true)}}
async function recordRisk(envId,sg,risks,why){try{await api('POST',`/api/env/${envId}/risk-approval`,{sg,risks,reason:why})}catch(e){toast('승인 사유를 기록하지 못했습니다: '+e.message,true)}}
async function recordRiskAll(results,why){for(const x of results.filter(x=>x.risks&&x.risks.length))await recordRisk(x.env_id||S.envId,x.name,x.risks,why)}

// 서비스 사전 (환경설정 카드): 자주 쓰는 프로토콜·포트에 이름을 붙여 마법사에서 고른다. 주소 묶음은 위의 '프리셋'을 쓴다
const svRow=x=>`<tr class="svx"><td><input type="text" class="sv-n" style="width:100%" placeholder="예: 웹(HTTPS)" value="${esc(x.name||'')}"></td><td style="width:110px"><select class="sv-p"><option ${x.protocol==='UDP'?'':'selected'}>TCP</option><option ${x.protocol==='UDP'?'selected':''}>UDP</option></select></td><td style="width:170px"><input type="text" class="sv-t" style="width:100%" placeholder="443 또는 1000-2000" value="${esc(x.ports||'')}"></td><td style="width:70px"><button class="danger sv-d">삭제</button></td></tr>`;
async function drawServiceCard(){
  const host=$('#service-card');if(!host)return;
  let r;try{r=await api('GET','/api/services')}catch(e){host.innerHTML=`<div class="card"><div class="warnbox danger">${esc(e.message)}</div></div>`;return}
  if(!$('#service-card'))return;
  host.innerHTML=`<div class="card"><h3>서비스 사전 <span class="mut" style="font-weight:400">(빠른 작업에서 이름으로 고르는 프로토콜·포트 — config.json 공유)</span></h3>
    <table><thead><tr><th>이름</th><th>프로토콜</th><th>포트</th><th></th></tr></thead><tbody id="sv-body">${r.services.map(svRow).join('')}</tbody></table>
    <div class="row" style="margin-top:8px"><button id="sv-add">서비스 추가</button><button id="sv-ex" title="HTTPS/HTTP/SSH 예시를 채웁니다 (저장해야 반영)">예시 채우기</button><button class="pri" id="sv-save">저장</button><span class="mut" id="sv-msg" role="status"></span></div>
    <div class="mut" style="font-size:12px;margin-top:6px">포트는 한 개(443) 또는 범위(1000-2000)입니다. 여러 포트는 서비스를 나눠 등록하세요. 위 <b>프리셋</b>(자주 쓰는 IP 묶음)은 IP 입력칸에 <code>@프리셋이름</code> 으로도 쓸 수 있습니다.</div></div>`;
  const body=$('#sv-body');
  $('#sv-add').onclick=()=>body.insertAdjacentHTML('beforeend',svRow({}));
  $('#sv-ex').onclick=()=>{body.innerHTML=r.examples.map(svRow).join('');$('#sv-msg').textContent='예시를 채웠습니다. 저장을 눌러야 반영됩니다'};
  body.onclick=e=>{if(e.target.classList.contains('sv-d'))e.target.closest('tr').remove()};
  $('#sv-save').onclick=guard(async()=>{
    const services=[...body.querySelectorAll('tr.svx')].map(tr=>({name:tr.querySelector('.sv-n').value.trim(),protocol:tr.querySelector('.sv-p').value,ports:tr.querySelector('.sv-t').value.trim()})).filter(x=>x.name||x.ports);
    const a=await api('PUT','/api/services',{services});S.services=a.services;$('#sv-msg').textContent=`저장했습니다 (서비스 ${a.services.length}개)`;toast('서비스 사전을 저장했습니다')})}
function svcPicker(){const sv=S.services||[];return sv.length?`<select id="wz-svc" title="환경설정의 서비스 사전"><option value="">서비스 불러오기...</option>${sv.map((s,i)=>`<option value="${i}">${esc(s.name)} (${esc(s.protocol)} ${esc(s.ports)})</option>`).join('')}</select>`:''}

// 접근 경로 표의 '범위' 뱃지
const rcBadge=x=>x.access==='full'?'<span class="badge b-chg">전체</span>':x.access==='via'?`<span class="badge b-pending">SG 경유</span><div class="mut" style="font-size:11px">${esc(x.via||'')}</div>`:'<span class="badge b-warn">일부 대역만</span>';

// SG 관계 그림: 왼쪽 = 이 SG 가 소스로 받는 SG, 가운데 = 조회한 SG, 오른쪽 = 이 SG 를 소스로 허용하는 SG (1단계만 그리고 더 깊은 단계는 표로)
function refDiagram(s){
  const ups=[...new Map(s.up.filter(e=>e.depth===1).map(e=>[e.from.sg_id||e.from.name,e])).values()].slice(0,14);
  const dns=[...new Map(s.down.filter(e=>e.depth===1).map(e=>[e.to.env+'/'+e.to.name,e])).values()].slice(0,14);
  const n=Math.max(ups.length,dns.length,1),H=n*38+44,W=1000,NH=28,A={x:10,w:300},B={x:350,w:300},C={x:690,w:300},y=i=>34+i*38,mid=y((n-1)/2);
  const cut=(t,k)=>t.length>k?t.slice(0,k-1)+'…':t,col=['#2563eb','#7c3aed','#16a34a'];
  const node=(c,x,w,yy,t,full)=>`<g class="tp-node"><title>${esc(full)}</title><rect x="${x}" y="${yy}" width="${w}" height="${NH}" rx="6" style="stroke:${c}"/><text x="${x+10}" y="${yy+NH/2+4}">${esc(cut(t,40))}</text></g>`;
  const link=(x1,y1,x2,y2,c,t)=>{const m=(x1+x2)/2;return `<path class="tp-link" d="M${x1},${y1+NH/2} C${m},${y1+NH/2} ${m},${y2+NH/2} ${x2},${y2+NH/2}" stroke="${c}" stroke-width="3"><title>${esc(t)}</title></path>`};
  let g='';
  ups.forEach((e,i)=>{g+=link(A.x+A.w,y(i),B.x,mid,col[0],e.ports.join(', '))+node(col[0],A.x,A.w,y(i),e.from.name,`${e.from.name} ${e.from.sg_id||''}`)});
  dns.forEach((e,i)=>{g+=link(B.x+B.w,mid,C.x,y(i),col[2],e.ports.join(', '))+node(col[2],C.x,C.w,y(i),e.to.name,`${e.to.name} (${e.to.env}) ${e.ports.join(', ')}`)});
  g+=node(col[1],B.x,B.w,mid,s.sg.name,`${s.sg.name} ${s.sg.sg_id||''}`);
  const heads=[['이 SG 로 들어올 수 있는 SG',A.x,col[0]],['조회한 SG',B.x,col[1]],['이 SG 를 거쳐 갈 수 있는 SG',C.x,col[2]]].map(h=>`<text class="tp-col" x="${h[1]}" y="16" style="fill:${h[2]}">${esc(h[0])}</text>`).join('');
  return `<div class="tp-wrap"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="SG 참조 관계">${heads}${g}</svg></div>`}

// 규칙 점검 보고서의 추가 탭. c = {o, B, table, csv, ip} (openReports 의 도구들)
function reviewTabs(c){
  const {o,B,table,csv}=c;
  const bad=g=>({A:'b-pending',B:'b-pending',C:'b-warn',D:'b-chg'}[g]||'b-warn');
  return{
    async refs(){const q0=o.querySelector('#sr-q')?.value??'',d0=o.querySelector('#sr-d')?.value??'2';
      B.innerHTML=`<div class="row" style="gap:8px"><input type="text" id="sr-q" style="flex:1" placeholder="SG 이름, SG ID(sg-…), 별명" value="${esc(q0)}"><label>단계 <select id="sr-d">${[1,2,3].map(n=>`<option ${String(n)===d0?'selected':''}>${n}</option>`).join('')}</select></label><button class="blue" id="sr-go">조회</button><span id="sr-dl"></span></div><div id="sr-res" style="margin-top:8px"></div>`;
      const run=guard(async()=>{const q=o.querySelector('#sr-q').value.trim(),d=o.querySelector('#sr-d').value;if(!q)return;const R=o.querySelector('#sr-res');R.innerHTML='<div class="mut">찾는 중...</div>';
        const r=await api('GET',`/api/report/sgrefs?q=${encodeURIComponent(q)}&depth=${d}`);o.querySelector('#sr-dl').innerHTML=csv(`/api/report/sgrefs?format=csv&q=${encodeURIComponent(q)}&depth=${d}`);
        const row=(e,k)=>`<tr><td class="nw">${'└ '.repeat(0)}${e.depth}단계</td><td>${esc(e.from.name)}${e.from.sg_id?`<div class="mut" style="font-size:11px">${esc(e.from.sg_id)}</div>`:''}</td><td>${esc(e.to.name)}</td><td>${esc(e.to.env)}</td><td>${e.ports.map(esc).join(', ')}</td></tr>`;
        R.innerHTML=r.starts.map(s=>`<div style="margin-bottom:14px"><div><b>${esc(s.sg.name)}</b> <span class="mut">${esc(s.sg.env)}${s.sg.sg_id?' · '+esc(s.sg.sg_id):''}${s.sg.alias?' · '+esc(s.sg.alias):''}</span></div>
          ${s.no_sg_id?'<div class="warnbox" style="margin:4px 0">이 SG 의 SG ID 가 메타 데이터에 없어 \'이 SG 를 소스로 허용하는 SG\'는 찾을 수 없습니다. 메타 데이터에서 AWS 가져오기를 먼저 하세요.</div>':''}
          ${s.up.length||s.down.length?refDiagram(s):'<div class="mut" style="margin:6px 0">SG 를 소스로 지정한 규칙이 이 SG 와 이어져 있지 않습니다.</div>'}
          ${table(['단계','소스 SG','규칙을 가진 SG','환경','포트'],s.down.map(e=>row(e)))?`<div style="margin:6px 0 2px"><b>이 SG 를 소스로 허용하는 SG</b> (이 SG 의 서버에서 이어질 수 있음)</div>`+table(['단계','소스 SG','규칙을 가진 SG','환경','포트'],s.down.map(e=>row(e))):''}
          ${table(['단계','소스 SG','규칙을 가진 SG','환경','포트'],s.up.map(e=>row(e)))?`<div style="margin:6px 0 2px"><b>이 SG 가 소스로 허용하는 SG</b> (이 SG 로 들어올 수 있음)</div>`+table(['단계','소스 SG','규칙을 가진 SG','환경','포트'],s.up.map(e=>row(e))):''}</div>`).join('')+
          `<div class="mut" style="font-size:12px">인바운드 규칙의 소스가 SG 인 것만 따라갑니다. 그림은 1단계만, 표에는 선택한 단계까지 나옵니다. 받아 둔 파일과 메타 데이터의 SG ID 기준입니다.</div>`});
      o.querySelector('#sr-go').onclick=run;o.querySelector('#sr-q').onkeydown=e=>{if(e.key==='Enter')run()};if(q0)run()},
    async score(){B.innerHTML='<div class="mut">모든 환경을 살펴보는 중...</div>';
      const r=await api('GET','/api/report/score'),K=r.kinds,keys=Object.keys(K);let envSel='',kindSel='';
      const draw=()=>{const rows=r.rows.filter(x=>(!envSel||x.env_id===envSel)&&(!kindSel||x.kind===kindSel)).slice(0,RPL());
        B.innerHTML=`<div class="row" style="gap:10px;align-items:center"><b>환경별 점수</b><span class="mut" style="font-size:12px">100점에서 항목마다 감점합니다. 환경 줄을 누르면 아래 목록이 그 환경만 남습니다.</span>${csv('/api/report/score?format=csv')}</div>
          ${table(['환경','SG','규칙','점수',...keys.map(k=>esc(K[k].label))],r.envs.map(e=>`<tr class="sc-env" data-e="${esc(e.env_id)}" style="cursor:pointer;${envSel===e.env_id?'background:var(--primary-bg)':''}"><td>${esc(e.env)}</td><td>${e.sgs}</td><td>${e.rules}</td><td class="nw"><span class="badge ${bad(e.grade)}">${e.score}점 ${e.grade}</span></td>${keys.map(k=>`<td>${e.counts[k]||'-'}</td>`).join('')}</tr>`))||'<div class="mut" style="padding:8px">환경이 없습니다.</div>'}
          <div class="row" style="margin-top:10px;gap:8px;align-items:center"><b>걸린 규칙</b><select id="sc-kind"><option value="">(모든 항목)</option>${keys.map(k=>`<option value="${k}" ${kindSel===k?'selected':''}>${esc(K[k].label)}</option>`).join('')}</select><span class="mut">${rows.length}건 표시${r.count>r.rows.length?' (일부만 불러옴 — 전체는 CSV)':''}</span></div>
          ${table(['환경','SG','담당자','항목','방향','프로토콜','포트','소스','설명'],rows.map(x=>`<tr><td>${esc(x.env)}</td><td>${sgLink(x)}</td><td>${esc(x.owner||'')}</td><td class="nw">${esc(K[x.kind].label)}</td><td class="nw">${RP_DIR(x.direction)}</td><td class="nw">${esc(x.protocol)}</td><td>${esc(x.port)}</td><td>${esc(x.source)}</td><td>${esc(x.description)}</td></tr>`))||'<div class="mut" style="padding:8px">해당하는 규칙이 없습니다.</div>'}
          <div class="mut" style="font-size:12px;margin-top:8px">감점 = 항목 가중치 × 건수(항목마다 상한 있음): ${keys.map(k=>`${esc(K[k].label)} ${K[k].weight}점(최대 ${K[k].weight*K[k].cap}점)`).join(' · ')}. 등급 A 90↑ / B 75↑ / C 60↑ / D. 정책 규칙의 허용 예외에 해당하는 규칙은 세지 않습니다. 읽기 전용이며 받아 둔 파일 기준입니다.</div>`;
        B.querySelectorAll('.sc-env').forEach(tr=>tr.onclick=()=>{envSel=envSel===tr.dataset.e?'':tr.dataset.e;draw()});
        B.querySelector('#sc-kind').onchange=e=>{kindSel=e.target.value;draw()}};
      draw()},
    async owners(){const days=+(o.querySelector('#ow-days')?.value||30);B.innerHTML='<div class="mut">모든 환경을 살펴보는 중...</div>';
      const r=await api('GET','/api/report/owners?days='+days);
      B.innerHTML=`<div class="row" style="gap:10px;align-items:center"><label>만료 임박 기준 <input type="number" id="ow-days" min="0" max="3650" style="width:70px" value="${days}">일</label><button id="ow-go">다시 조회</button>${csv('/api/report/owners?format=csv&days='+days)}<span class="mut">담당자 미지정 SG ${r.unassigned}개</span></div>
        ${table(['담당자','SG','만료 지남','만료 임박','정리 제안','기준 점검 항목'],r.owners.map(x=>`<tr><td>${esc(x.owner)}</td><td>${x.sgs}</td><td>${x.expired||'-'}</td><td>${x.soon||'-'}</td><td>${x.cleanup||'-'}</td><td>${x.issues||'-'}</td></tr>`))||'<div class="mut" style="padding:8px">SG 가 없습니다.</div>'}
        <div class="mut" style="font-size:12px;margin-top:8px">담당자는 메타 데이터 화면의 SG별 <b>담당자</b> 칸에 적습니다(CSV 에도 owner 열이 있습니다). 만료·정리 제안·기준 점검 탭에서 담당자로 걸러 볼 수 있습니다.</div>`;
      o.querySelector('#ow-go').onclick=guard(()=>this.owners())},
    async audit(){const t=new Date(),iso=d=>d.toISOString().slice(0,10),f0=o.querySelector('#au-from')?.value||iso(new Date(t.getTime()-90*864e5)),t0=o.querySelector('#au-to')?.value||iso(t),d0=o.querySelector('#au-days')?.value||'30';
      B.innerHTML=`<div class="row" style="gap:10px;align-items:center;flex-wrap:wrap"><label>기간 <input type="date" id="au-from" value="${esc(f0)}"> ~ <input type="date" id="au-to" value="${esc(t0)}"></label><label>만료 임박 기준 <input type="number" id="au-days" min="0" max="3650" style="width:70px" value="${esc(d0)}">일</label><a class="btn blue" id="au-dl" style="text-decoration:none" href="#">Excel 로 내려받기 (.xlsx)</a></div>
        <div class="mut" style="margin:8px 0">한 파일에 시트로 담깁니다: <b>요약</b>(환경별 점수 포함) · <b>변경 이력</b>(규칙·push·MR·plan·apply, 기간 내) · <b>위험 규칙 승인</b>(사유 포함) · <b>만료 규칙</b> · <b>정리 제안</b> · <b>기준 점검</b> · <b>담당자별</b>.</div>
        <div class="mut" style="font-size:12px">받아 둔 파일과 도구의 기록(작업 이력, 승인 기록)을 모은 읽기 전용 보고서입니다. 작업 이력은 이 도구로 한 작업만 들어 있습니다.</div>`;
      const link=()=>{o.querySelector('#au-dl').href=`/api/report/audit-xlsx?from=${encodeURIComponent(o.querySelector('#au-from').value)}&to=${encodeURIComponent(o.querySelector('#au-to').value)}&days=${encodeURIComponent(o.querySelector('#au-days').value)}`};
      ['#au-from','#au-to','#au-days'].forEach(s=>o.querySelector(s).onchange=link);link()},
    async ticket(){const q0=o.querySelector('#tk-q')?.value??((($('#ticket')||{}).value)||'');
      B.innerHTML=`<div class="row" style="gap:8px"><input type="text" id="tk-q" style="flex:1;max-width:280px" placeholder="티켓 번호 (예: ISRIR-12345)" value="${esc(q0.trim())}"><button class="blue" id="tk-go">찾기</button><span class="mut" style="font-size:12px">설명에 번호가 들어간 규칙 · 이름에 들어간 브랜치 · 제목/설명에 들어간 MR 을 모든 환경에서 찾습니다</span></div><div id="tk-res" style="margin-top:8px"></div>`;
      const run=guard(async()=>{const q=o.querySelector('#tk-q').value.trim();if(!q)return;const R=o.querySelector('#tk-res');R.innerHTML='<div class="mut">찾는 중... (MR 은 GitLab 에서 조회합니다)</div>';
        const r=await api('GET','/api/ticket/'+encodeURIComponent(q));
        const link=x=>/^https?:\/\//.test(x.url||'')?`<a href="${esc(x.url)}" target="_blank" rel="noopener">!${esc(x.iid)}</a>`:`!${esc(x.iid)}`;
        R.innerHTML=`<div class="mut"><b>${esc(r.ticket)}</b> — 규칙 <b>${r.rule_count}</b>건 · 브랜치 <b>${r.branches.length}</b>개 · MR <b>${r.mrs.length}</b>건</div>
          <div style="margin:8px 0 2px"><b>규칙</b></div>${table(['환경','SG','방향','프로토콜','포트','소스','설명'],r.rules.map(x=>`<tr><td>${esc(x.env)}</td><td>${esc(x.sg)}</td><td class="nw">${RP_DIR(x.direction)}</td><td class="nw">${esc(x.protocol)}</td><td>${esc(x.port)}</td><td>${esc(x.source)}</td><td>${esc(x.description)}</td></tr>`))||'<div class="mut">설명에 이 번호가 들어간 규칙이 없습니다.</div>'}
          <div style="margin:10px 0 2px"><b>브랜치</b></div>${table(['브랜치','환경','마지막 커밋','위치','제목'],r.branches.map(x=>`<tr><td>${esc(x.branch)}</td><td>${esc(x.env)}</td><td class="nw">${esc(x.date)}</td><td class="nw">${x.local?'내 PC':''}${x.local&&x.remote?' + ':''}${x.remote?'GitLab':''}</td><td>${esc(x.subject)}</td></tr>`))||'<div class="mut">이름에 이 번호가 들어간 브랜치가 없습니다.</div>'}
          <div style="margin:10px 0 2px"><b>MR</b></div>${table(['MR','환경','상태','제목','브랜치'],r.mrs.map(x=>`<tr><td class="nw">${link(x)}</td><td>${esc(x.env)}</td><td class="nw">${esc(x.state)}</td><td>${esc(x.title)}</td><td>${esc(x.branch)}</td></tr>`))||'<div class="mut">찾은 MR 이 없습니다.</div>'}
          ${r.mr_errors.length?`<div class="mut" style="font-size:12px;margin-top:6px">MR 조회 건너뜀: ${esc(r.mr_errors.join(' / '))}</div>`:''}`});
      o.querySelector('#tk-go').onclick=run;o.querySelector('#tk-q').onkeydown=e=>{if(e.key==='Enter')run()};if(q0.trim())run()}}}
