// 검색 결과로 SG 를 열면 검색어를 규칙 필터에 넣어 일치하는 규칙만 보여준다. 그런데 검색어가 SG 의 별칭/태그/이름에서 찾아진 것이면
// 규칙 중에는 일치하는 것이 없어 표가 비어 보이므로, 일치하는 규칙이 하나도 없으면 필터를 비워 모든 규칙을 보여준다.
// 일치하는 규칙이 반대쪽 방향(인바운드/아웃바운드)에만 있으면 그 방향 탭으로 옮긴다.
function fitRuleFilter(){
  const ws=String(S.rf||'').trim().toLowerCase().split(/\s+/).filter(Boolean);
  if(!ws.length||!S.sgData)return;
  const text=r=>[ruleType(r),r.protocol,portStr(r),srcStr(r),r.description].join(' ').toLowerCase();
  const has=d=>(S.sgData[d]||[]).some(r=>ws.every(w=>text(r).includes(w)));
  if(has(S.dir))return;
  const other=S.dir==='ingress'?'egress':'ingress';
  if(has(other))S.dir=other;else S.rf='';
  drawDetail();
}
// ---------- 통합 검색 (최상단): IP / CIDR / 도메인 / 태그 / SG ID / SG명 / 서브넷 → 결과를 고르면 유형·종류·환경이 자동 반영
function initGlobalSearch(){
  const q=$('#gq'),box=$('#gres');let timer,items=[],sel=-1,seq=0,isIp=false;
  const mark=(t,w)=>{t=String(t);if(isIp||!w)return esc(t);const i=t.toLowerCase().indexOf(w.toLowerCase());
    return i<0?esc(t):esc(t.slice(0,i))+'<mark>'+esc(t.slice(i,i+w.length))+'</mark>'+esc(t.slice(i+w.length))};
  const hide=()=>{box.style.display='none';sel=-1};
  const draw=(msg)=>{const w=q.value.trim();
    box.innerHTML=(looksDomain(w)?`<div style="padding:8px 12px;border-bottom:1px solid var(--border)"><button id="gq-dom" title="DNS 결과와 메타 데이터(SG 태그·별명)를 비교하고, 메타 데이터가 있는 SG 의 태그에 도메인을 추가합니다">도메인 ${esc(w)} — 메타 데이터와 비교 / 태그 적용</button></div>`:'')+(msg?`<div class="mut" style="padding:10px 12px">${esc(msg)}</div>`:'')+items.slice(0,40).map((r,i)=>`<div class="gi ${i===sel?'on':''}" data-i="${i}">
      <div>${r.type==='sg'?`<button type="button" class="gi-pv" data-i="${i}" style="float:right" title="화면을 옮기지 않고 규칙·메타 데이터를 봅니다">미리보기</button>`:''}<b>${r.type==='env'?'환경 정보 (서브넷/NAT)':mark(r.name,w)}</b> <span class="badge b-pending">${esc(r.kind==='game'?'게임':'플랫폼')}</span>
        <span class="mut" style="font-size:12px">${esc(r.env_label)}</span></div>
      <div class="mut" style="font-size:12px">${r.hits.slice(0,2).map(h=>mark(h,w)).join('<br>')}${(r.total_hits||0)>2?` <span class="badge b-chg">+${r.total_hits-2}</span>`:''}</div></div>`).join('')
      +(items.length>40?`<div class="mut" style="padding:8px 12px">상위 40건만 표시 (전체 ${items.length}건) — 더 구체적으로 검색해 보세요</div>`:'');
    box.insertAdjacentHTML('beforeend',`<div style="padding:8px 12px;border-top:1px solid var(--border)"><button id="gq-rp">사용처 보고서 — 이 검색어가 쓰이는 모든 규칙 (CSV 내보내기)</button></div>`);
    const dmb=box.querySelector('#gq-dom');if(dmb)dmb.onmousedown=ev=>{ev.preventDefault();hide();openDomainLookup(q.value.trim()).catch(e=>toast(e.message,true))};
    const rpb=box.querySelector('#gq-rp');if(rpb)rpb.onmousedown=ev=>{ev.preventDefault();hide();showUsageReport(q.value.trim())};
    box.querySelectorAll('.gi-pv').forEach(b=>b.onmousedown=ev=>{ev.preventDefault();ev.stopPropagation();hide();const r=items[+b.dataset.i];openSgPanel(r.env_id,r.name).catch(e=>toast(e.message,true))});
    box.style.display='';
    box.querySelectorAll('.gi').forEach(d=>{d.onmousedown=ev=>{ev.preventDefault();go(items[+d.dataset.i])};d.onmouseenter=()=>{sel=+d.dataset.i;box.querySelectorAll('.gi').forEach(x=>x.classList.toggle('on',x===d))}})};
  const go=async r=>{if(!r)return;const e=S.cfg.environments.find(x=>x.id===r.env_id);if(!e)return;const w=q.value.trim();
    const cidr=(r.hits[0]||'').match(/\d+\.\d+\.\d+\.\d+(\/\d+)?/);
    S.kind=e.kind;S.group=e.group;S.envId=e.id;S.tab=r.type==='env'?'meta':'acl';S.rf=isIp?(cidr?cidr[0]:''):w;S.sgf='';S.sgm='';S.search='';S.mfq='';S.mfn=false;
    persist();hide();renderPickers();await selectEnv();
    if(r.type==='sg'){await openSg(r.name);fitRuleFilter()}
    toast(`${r.env_label}${r.name?' → '+r.name:''} 로 이동했습니다`)};
  const run=guard(async()=>{const w=q.value.trim();if(w.length<2){hide();return}const my=++seq;
    const res=await api('GET','/api/search?q='+encodeURIComponent(w));if(my!==seq)return;
    items=res.results;isIp=!!res.query_is_ip;sel=items.length?0:-1;
    draw(items.length?(isIp?`IP/대역 검색: 겹치는 규칙·서브넷 ${items.length}건 (좁은 대역 우선)`:`${items.length}건`):'검색 결과가 없습니다 (저장소를 아직 받지 않았다면 작업 탭에서 다운로드하세요)')});
  q.oninput=()=>{clearTimeout(timer);timer=setTimeout(run,300)};
  q.onfocus=()=>{if(items.length&&q.value.trim().length>=2)draw()};
  q.onblur=()=>setTimeout(hide,150);
  q.onkeydown=ev=>{if(ev.key==='ArrowDown'||ev.key==='ArrowUp'){ev.preventDefault();if(!items.length)return;sel=(sel+(ev.key==='ArrowDown'?1:-1)+Math.min(items.length,40))%Math.min(items.length,40);draw();
      box.querySelector('.gi.on')?.scrollIntoView({block:'nearest'})}
    else if(ev.key==='Enter'){ev.preventDefault();clearTimeout(timer);if(box.style.display==='none'||!items.length)run().then(()=>{if(items.length)go(items[0])});else go(items[Math.max(sel,0)])}
    else if(ev.key==='Escape'){hide();q.blur()}};
  document.addEventListener('keydown',ev=>{if(ev.key==='/'&&!/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)){ev.preventDefault();q.focus();q.select()}});
}
// ---------- 버전 / 서버 코드 변경 감지: 화면과 서버의 버전이 다르거나 서버 코드 파일이 시작 이후 바뀌면 재시작 안내
viewAcl=keepDraft(viewAcl,'acl');viewWork=keepDraft(viewWork,'work');
let _gsP=null,_gsT=0,_gsE='';
function gitStatus(force){force=force===true;const now=Date.now();
  if(!force&&_gsP&&_gsE===S.envId&&now-_gsT<400)return _gsP;     // 직전에 같은 환경으로 요청했다면 그 결과를 같이 쓴다
  _gsT=now;_gsE=S.envId;return _gsP=_gitStatusRun(force)}
const CLIENT_VERSION='1.17.0';
async function showServerLog(){
  try{const r=await api('GET','/api/log?lines=300');
    await showModal('서버 로그 (마지막 '+r.lines.length+'줄)',`<div class="mut" style="margin-bottom:6px">${esc(r.path||'')}</div><pre style="max-height:60vh;overflow:auto;white-space:pre-wrap;font-size:12px">${r.lines.length?esc(r.lines.join('\n')):'기록된 오류가 없습니다.'}</pre>`,'닫기','',{hideCancel:true})}
  catch(e){toast(e.message,true)}}
async function checkVersion(){
  const b=$('#vbanner'),f=$('#vfoot');let msg='',v=null;
  try{v=await api('GET','/api/version')}catch(e){msg='서버가 구버전이거나 응답하지 않습니다. run.bat 서버를 종료하고 다시 실행하세요.'}
  if(v){if(v.version!==CLIENT_VERSION)msg=`화면(v${CLIENT_VERSION})과 서버(v${v.version})의 버전이 다릅니다. run.bat 서버를 종료하고 다시 실행하세요.`;
    else if(v.stale)msg='서버 코드가 변경되었지만 서버가 아직 이전 코드로 실행 중입니다. run.bat 서버를 종료하고 다시 실행하세요.';
    if(f){f.innerHTML=`v${esc(v.version)} · 서버 시작 ${new Date(v.started*1000).toTimeString().slice(0,5)}<br><a href="#" id="vrs" style="color:var(--primary)">서버 재시작</a> · <a href="#" id="vlog" style="color:var(--primary)">서버 로그</a>`;$('#vrs').onclick=e=>{e.preventDefault();restartServer()};$('#vlog').onclick=e=>{e.preventDefault();showServerLog()}}}
  if(b){b.innerHTML=(v&&v.demo?'<div class="demobar" role="note"><b>시연 모드</b> — 가짜 저장소·가짜 GitLab/Jira/AWS 데이터로 동작합니다. 실제 시스템에는 아무것도 하지 않고, 이 창을 닫으면 만든 내용은 사라집니다.</div>':'')+
    (msg?`<div class="warnbox danger">🔄 <b>서버 재시작 필요</b> — ${esc(msg)} <button id="vrestart" style="margin-left:8px">지금 재시작</button></div>`:'');const rb=$('#vrestart');if(rb)rb.onclick=restartServer}}
