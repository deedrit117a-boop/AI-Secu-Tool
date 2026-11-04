const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ls={get:(k,d)=>{try{return JSON.parse(localStorage.getItem(k))??d}catch{return d}},set:(k,v)=>{try{localStorage.setItem(k,JSON.stringify(v))}catch{}}};
async function api(method,url,body,isForm){
  const o={method,headers:{}};
  if(S.allowMain)o.headers['X-Allow-Main']='1';
  if(method==='PUT'&&url==='/api/config'&&S.cfgRev)o.headers['X-Rev']=S.cfgRev;
  if(method==='PUT'&&url==='/api/meta'&&S.metaRev)o.headers['X-Rev']=S.metaRev;
  if(body&&isForm)o.body=body;else if(body){o.body=JSON.stringify(body);o.headers['Content-Type']='application/json'}
  const r=await fetch(url,o);let d;const t=await r.text();try{d=JSON.parse(t)}catch{d=t}
  if(!r.ok){
    if(r.status===409&&d&&d.conflict&&(url==='/api/config'||url==='/api/meta')){   // 다른 화면/서버 작업으로 먼저 바뀐 경우: 최신 내용으로 다시 불러온다
      try{await reloadCfg();S.meta=await api('GET','/api/meta');if(!S.meta.envs)S.meta.envs={}}catch{}
    }
    const err=new Error(d.error||t);err.data=d;throw err}
  if(d&&typeof d==='object'){
    if(url==='/api/config'&&d.rev)S.cfgRev=d.rev;
    if(url==='/api/meta'){if(method==='GET'&&d._rev)S.metaRev=d._rev;else if(d.rev)S.metaRev=d.rev}
    if(d.today)S.today=d.today;
    if(method==='POST'&&/\/discover$|\/config\/repair$|\/meta\/(env\/)?csv|\/meta\/env-csv/.test(url)&&!(d&&d.dry_run))refreshRevs();   // 서버가 직접 바꾼 경우 내 화면의 기준을 갱신
  }
  return d;
}
async function refreshRevs(){try{const c=await fetch('/api/config').then(r=>r.json());S.cfgRev=c.rev;const m=await fetch('/api/meta').then(r=>r.json());S.metaRev=m._rev}catch{}}
function toast(m,err,ms){const t=$('#toast');t.setAttribute('role',err?'alert':'status');t.className=err?'err':'';
  t.innerHTML='<span class="tmsg"></span>'+(err?'<span class="tbtn"><button type="button" class="tcp" title="메시지 복사">복사</button><button type="button" class="tx" aria-label="닫기">×</button></span>':'');
  t.querySelector('.tmsg').textContent=m;t.style.display='block';clearTimeout(t._h);const hide=()=>{t.style.display='none'};if(err&&typeof uxFixButtons==='function')uxFixButtons(t,m);
  if(err){t.querySelector('.tx').onclick=hide;t.querySelector('.tcp').onclick=async()=>{try{await navigator.clipboard.writeText(m);t.querySelector('.tcp').textContent='복사됨'}catch{}};
    const arm=()=>{clearTimeout(t._h);t._h=setTimeout(hide,ms||20000)};t.onmouseenter=()=>clearTimeout(t._h);t.onmouseleave=arm;arm()}   // 오류는 오래 두고, 마우스를 올려 두면 계속 보인다 (Esc 또는 × 로 닫음)
  else{t.onmouseenter=t.onmouseleave=null;t._h=setTimeout(hide,ms||3000)}}

// ---------- 확인 모달 / diff 색상
// opts: {onMount(o), collect(o)->값, hideCancel}. 확인하면 {ok:true, ...collect()} 를, 취소하면 false 를 돌려준다
function showModal(title,html,okText,cancelText,opts){
  opts=opts||{};
  return new Promise(res=>{const o=document.createElement('div');o.className='modal-ov';
    const tid='mt'+Math.random().toString(36).slice(2,7);o.innerHTML=`<div class="modal${opts.wide?' rz':''}" role="dialog" aria-modal="true" aria-labelledby="${tid}"><h3 id="${tid}">${esc(title)}</h3><div class="mbody">${html}</div><div class="row" style="justify-content:flex-end;margin-top:12px">${opts.hideCancel?'':`<button class="mc">${esc(cancelText||'취소')}</button>`}<button class="blue mo${opts.danger?' danger-fill':''}">${esc(okText||'확인')}</button></div></div>`;
    const prevFocus=document.activeElement;document.body.appendChild(o);
    const kd=e=>{if(e.key==='Escape'){done(false);return}
      if(e.key==='Enter'&&!e.isComposing&&!e.defaultPrevented&&!opts.hideCancel&&!opts.noEnter&&e.target&&e.target.matches&&e.target.matches('input[type=text],input[type=number]')&&o.contains(e.target)){e.preventDefault();o.querySelector('.mo').click();return}   // 글자 입력칸에서 Enter = 확인 (한글 조합 중에는 제외)
      if(e.key==='Tab'){const f=[...o.querySelectorAll('button,input,select,textarea,a[href],summary,[tabindex="0"]')].filter(x=>!x.disabled&&x.offsetParent!==null);   // Tab 이 대화상자 밖으로 나가지 않게
        if(!f.length)return;const first=f[0],last=f[f.length-1];
        if(e.shiftKey&&(document.activeElement===first||!o.contains(document.activeElement))){e.preventDefault();last.focus()}
        else if(!e.shiftKey&&(document.activeElement===last||!o.contains(document.activeElement))){e.preventDefault();first.focus()}}};
    const done=v=>{o.remove();document.removeEventListener('keydown',kd);try{if(prevFocus&&prevFocus.isConnected)prevFocus.focus()}catch{}res(v)};document.addEventListener('keydown',kd);
    o.querySelector('.mc')?.addEventListener('click',()=>done(false));
    o.querySelector('.mo').onclick=()=>done({ok:true,...(opts.collect?opts.collect(o):{})});
    o.onclick=e=>{if(e.target===o)done(false)};if(opts.wide)modalResizable(o.querySelector('.modal'),opts.wide);if(opts.onMount)opts.onMount(o);(opts.danger&&o.querySelector('.mc')?o.querySelector('.mc'):o.querySelector('.mo')).focus()})}   // 위험한 작업은 처음 포커스를 취소에 둔다
// 넓은 대화상자: 처음부터 넉넉한 크기로 열고, 오른쪽 아래 모서리를 끌어 크기를 바꿀 수 있다. 바꾼 크기는 이 브라우저에 기억한다
function modalResizable(m,key){const k='tfa.modal.'+(typeof key==='string'?key:'wide');let sz=null;try{sz=JSON.parse(localStorage.getItem(k)||'null')}catch{}
  if(sz&&sz.w>320&&sz.h>240){m.style.width=Math.min(sz.w,innerWidth*.98)+'px';m.style.height=Math.min(sz.h,innerHeight*.96)+'px'}
  const g=document.createElement('div');g.className='rz-grip';g.title='끌어서 크기 조절 (더블클릭: 기본 크기)';g.setAttribute('aria-hidden','true');m.appendChild(g);
  const save=()=>{try{localStorage.setItem(k,JSON.stringify({w:m.offsetWidth,h:m.offsetHeight}))}catch{}};
  g.addEventListener('dblclick',()=>{m.style.width='';m.style.height='';try{localStorage.removeItem(k)}catch{}});
  g.addEventListener('pointerdown',e=>{e.preventDefault();const x0=e.clientX,y0=e.clientY,w0=m.offsetWidth,h0=m.offsetHeight;g.setPointerCapture(e.pointerId);
    // 대화상자가 가운데 정렬이라 너비·높이가 늘어난 만큼 양쪽으로 커지므로, 움직인 거리의 2배를 더한다 (마우스가 모서리를 따라가게)
    const mv=ev=>{m.style.width=Math.max(360,Math.min(innerWidth*.98,w0+(ev.clientX-x0)*2))+'px';m.style.height=Math.max(260,Math.min(innerHeight*.96,h0+(ev.clientY-y0)*2))+'px'};
    const up=()=>{g.removeEventListener('pointermove',mv);g.removeEventListener('pointerup',up);save()};g.addEventListener('pointermove',mv);g.addEventListener('pointerup',up)})}
function colorizeDiff(text){
  return String(text).split('\n').map(l=>{let c='';
    if(/^(\+\+\+|---) /.test(l)||/^(diff --git|index )/.test(l))c='sum';else if(l.startsWith('+'))c='add';else if(l.startsWith('-'))c='del';else if(l.startsWith('@@'))c='chg';
    return `<span class="ln ${c}">${esc(l)||' '}</span>`}).join('')}
const guard=fn=>async(...a)=>{try{return await fn(...a)}catch(e){toast(e.message,true)}};

// IP 목록 입력(줄바꿈/쉼표/공백 구분, /32 생략 가능) → {ok:[CIDR...], bad:[잘못된 입력...]} (중복 제거). 마법사와 일괄 적용이 함께 사용
const parseIps=txt=>{const raw=txt.split(/[\s,;]+/).filter(Boolean).flatMap(x=>{if(x[0]!=='@')return[x];const p=((S.cfg&&S.cfg.presets)||[]).find(q=>q.name===x.slice(1));return p?p.ips:[x]}),seen=new Set(),ok=[],bad=[];
  raw.forEach(x=>{const c=/\/\d+$/.test(x)?x:x+'/32';if(!/^\d+\.\d+\.\d+\.\d+\/\d+$/.test(c)||c.split('/')[0].split('.').some(o=>+o>255)||+c.split('/')[1]>32){bad.push(x);return}if(!seen.has(c)){seen.add(c);ok.push(c)}});return{ok,bad}};

// 브랜치 이름 뒤에 붙일 문자: 서버(clean_branch_suffix)와 같은 규칙으로 미리 보여준다
const branchSuffix=t=>{let s=String(t||'').trim().replace(/\s+/g,'_').replace(/[^\p{L}\p{N}_.\-]/gu,'').replace(/\.{2,}/g,'.').replace(/^[._-]+|[._-]+$/g,'');return s.slice(0,40)};
// ---------- 처음 시작하기 안내: 계정/토큰/환경이 준비되지 않았을 때 해야 할 일을 순서대로 보여준다
function onboardSteps(){const toks=Object.values(S.tokenSet||{}).some(Boolean);
  return[{ok:!!S.account,t:'계정 입력',d:'GitLab 사용자명 (브랜치 이름과 Assignee 기본값에 사용)',go:'cfg'},
    {ok:toks,t:'GitLab 토큰 입력',d:'플랫폼은 필수, 게임환경은 저장소 받기에는 없어도 되지만 MR/plan 에는 필요 (api 권한)',go:'cfg'},
    {ok:(S.cfg.environments||[]).length>0,t:'환경 등록',d:'GitLab 프로젝트와 sg_rule 폴더 경로로 환경을 추가하세요. 한 환경을 등록해 저장소를 받으면 [환경 검색] 으로 나머지를 자동 등록할 수 있습니다',go:'cfg',add:true},
    {ok:false,t:'저장소 다운로드 → 작업 시작',d:'작업 탭에서 저장소를 받고, 티켓번호를 넣고 브랜치를 준비하세요',go:'work',last:true}];}
function onboardHtml(){const st=onboardSteps();if(st.slice(0,3).every(x=>x.ok))return'';
  return`<div class="card" id="onboard"><h3>시작하기</h3><div class="mut" style="margin-bottom:8px">처음 사용하시는 경우 아래 순서대로 진행하세요.</div>
    <ol style="padding-left:20px;margin:0">${st.map((x,i)=>`<li style="margin:6px 0"><b>${x.ok?'✓ ':''}${esc(x.t)}</b>${x.ok?'':` <button class="ob-go" data-go="${x.go}" data-add="${x.add?1:''}">${x.go==='work'?'작업 탭으로':(x.add?'환경 추가하기':'환경설정으로')}</button>`}<div class="mut" style="font-size:12px">${esc(x.d)}</div></li>`).join('')}</ol></div>`}
function bindOnboard(){document.querySelectorAll('.ob-go').forEach(b=>b.onclick=()=>{S.tab=b.dataset.go;persist();render();if(b.dataset.add&&typeof envForm==='function'){envForm(null);const f=$('#eform');if(f&&f.scrollIntoView)f.scrollIntoView({block:'center'})}})}

// ---------- 상태
const S={cfg:null,account:'',tokenSet:{},paths:{},meta:{envs:{}},kind:ls.get('kind',''),group:ls.get('group',''),envId:ls.get('envId',''),
  tab:ls.get('tab','work'),sg:null,sgs:[],sgData:null,dir:'ingress',edit:null,search:'',results:null,mr:ls.get('mr',{}),gitst:null,outp:null};
const env=()=>S.cfg.environments.find(e=>e.id===S.envId);
const KIND_LABEL=k=>S.cfg.sites[k]?.label||k;
const today=()=>{if(S.today)return S.today;const d=new Date();return String(d.getFullYear()%100).padStart(2,'0')+String(d.getMonth()+1).padStart(2,'0')+String(d.getDate()).padStart(2,'0')};

// ---------- 검색형 드롭다운
function combo(el,label,items,cur,onPick){
  el.innerHTML=`<button aria-haspopup="listbox" aria-expanded="false">${esc(label)}: ${esc(cur?(items.find(i=>i.v===cur)?.t||cur):'선택')} ▾</button>`;
  const btn=el.firstChild;
  btn.onclick=ev=>{ev.stopPropagation();closePanels();btn.setAttribute('aria-expanded','true');
    const p=document.createElement('div');p.className='panel';
    p.innerHTML=`<input type="text" placeholder="검색..." aria-label="${esc(label)} 검색" role="combobox" aria-expanded="true" aria-autocomplete="list">`+'<div class="list" role="listbox"></div>';el.appendChild(p);
    const inp=p.querySelector('input'),list=p.querySelector('.list');let act=-1;
    const opts=()=>[...list.querySelectorAll('[role=option]')];
    const mark=n=>{const o=opts();if(!o.length)return;act=(n+o.length)%o.length;o.forEach((x,i)=>{x.classList.toggle('act',i===act);x.setAttribute('aria-selected',i===act?'true':'false')});o[act].scrollIntoView({block:'nearest'});inp.setAttribute('aria-activedescendant',o[act].id)};
    const draw=()=>{const q=inp.value.toLowerCase();list.innerHTML='';act=-1;
      items.filter(i=>i.t.toLowerCase().includes(q)).forEach((i,n)=>{const d=document.createElement('div');d.textContent=i.t;d.setAttribute('role','option');d.id=el.id+'-o'+n;d.setAttribute('aria-selected','false');if(i.v===cur)d.className='sel';d.onclick=()=>{closePanels();onPick(i.v)};list.appendChild(d)});
      if(!list.children.length)list.innerHTML='<div class="mut">결과 없음</div>'};
    inp.oninput=draw;inp.onclick=e=>e.stopPropagation();
    inp.onkeydown=e=>{if(e.key==='ArrowDown'){e.preventDefault();mark(act+1)}else if(e.key==='ArrowUp'){e.preventDefault();mark(act<0?-1:act-1)}
      else if(e.key==='Enter'){e.preventDefault();const o=opts();(o[act>=0?act:(o.length===1?0:-1)]||{click(){}}).click()}
      else if(e.key==='Escape'){e.stopPropagation();closePanels();btn.focus()}};
    draw();inp.focus()};
}
const closePanels=()=>{document.querySelectorAll('.panel').forEach(p=>p.remove());document.querySelectorAll('.combo > button[aria-expanded]').forEach(b=>b.setAttribute('aria-expanded','false'))};
document.addEventListener('click',closePanels);

function renderPickers(){
  const kinds=Object.keys(S.cfg.sites).map(k=>({v:k,t:KIND_LABEL(k)}));
  const groups=[...new Set(S.cfg.environments.filter(e=>e.kind===S.kind).map(e=>e.group))].map(g=>({v:g,t:g}));
  const inGroup=S.cfg.environments.filter(e=>e.kind===S.kind&&e.group===S.group);
  const envNames=[...new Set(inGroup.map(e=>e.env))].map(n=>({v:n,t:n}));
  const cur=inGroup.find(e=>e.id===S.envId);
  const variants=cur?inGroup.filter(e=>e.env===cur.env).map(e=>({v:e.id,t:e.label||'(기본)'})):[];
  combo($('#c1'),'1.유형',kinds,S.kind,k=>{S.kind=k;S.group='';S.envId='';persist();renderPickers();selectEnv()});
  combo($('#c2'),S.kind==='game'?'2.게임':'2.플랫폼',groups,S.group,g=>{S.group=g;S.envId='';persist();renderPickers();selectEnv()});
  combo($('#c3'),'3.환경',envNames,cur?cur.env:'',n=>{const f=inGroup.find(e=>e.env===n);S.envId=f.id;persist();renderPickers();selectEnv()});
  combo($('#c4'),'4.리전/티어',variants,S.envId,id=>{S.envId=id;persist();renderPickers();selectEnv()});
  $('#c4').parentElement.style.display=variants.length>1?'':'none';
}
const persist=()=>{ls.set('kind',S.kind);ls.set('group',S.group);ls.set('envId',S.envId);ls.set('tab',S.tab)};

async function selectEnv(){
  S.dl=null;S.sg=null;S.sgData=null;S.sgs=[];S.edit=null;S.results=null;S.gitst=null;S.outp=null;
  if(S.envId&&S.tab!=='cfg'){await loadSgs()}
  render();
}
const loadSgs=guard(async()=>{const r=await api('GET',`/api/env/${S.envId}/sgs`);S.sgs=r.sgs;S.sgPath=r.path;S.sgExists=r.exists});

// ---------- 탭
const ICONS={'work': '<path d="M17 1l4 4-4 4"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><path d="M7 23l-4-4 4-4"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/>', 'acl': '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>', 'meta': '<path d="M20.6 13.4l-7.2 7.2a2 2 0 0 1-2.8 0L2 12V2h10l8.6 8.6a2 2 0 0 1 0 2.8z"/><circle cx="7" cy="7" r="1.5"/>', 'cfg': '<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>'};
ICONS.dist='<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/>';
const TABS=[['work','작업 (Git/MR/Atlantis)'],['acl','접근제어'],['meta','메타 데이터'],['dist','배포'],['cfg','환경설정']];
const platWork=()=>S.tab==='work'&&S.kind==='platform';
function render(){
  renderPickers();
  document.body.dataset.tab=S.tab;
  $('#tabs').innerHTML='<div class="sidebar-section-label">메뉴</div>'+TABS.map(([k,t])=>`<button class="tab-btn ${S.tab===k?'active':''}" data-k="${k}" ${S.tab===k?'aria-current="page"':''}><span class="nav-icon" aria-hidden="true"><svg viewBox="0 0 24 24">${ICONS[k]}</svg></span>${t}</button>`).join('');
  document.querySelectorAll('.tab-btn').forEach(t=>t.onclick=async()=>{S.tab=t.dataset.k;persist();if(S.envId&&!S.sgs.length)await loadSgs();render()});
  if(S.tab!=='cfg'&&S.tab!=='dist'&&!S.envId&&!(S.tab==='work'&&S.kind)){$('#view').innerHTML=onboardHtml()+'<div class="card mut">상단에서 유형 → 게임/플랫폼 → 환경을 선택하세요. 목록이 없으면 [환경설정] 탭에서 추가하세요.</div>';bindOnboard();return}
  if(S.tab!=='acl'&&S.tab!=='work')S._drawn=S.tab;
  ({acl:viewAcl,work:viewWork,meta:viewMeta,cfg:viewCfg,dist:viewDist})[S.tab]();
}

// 화면이 다시 그려져도(MR 생성 후 등) 사용자가 직접 바꾼 입력칸은 유지한다.
// 처음 그려질 때의 값(defaultValue)과 다른 칸만 저장했다가, 같은 id 의 칸에 되돌린다 (비밀번호/파일 칸 제외)
function snapDraft(){const m={};document.querySelectorAll('#view input[id],#view textarea[id],#view select[id]').forEach(el=>{
  if(el.type==='password'||el.type==='file'||el.type==='button')return;
  if(el.type==='checkbox'||el.type==='radio'){if(el.checked!==el.defaultChecked)m[el.id]={c:el.checked}}
  else if(el.tagName==='SELECT'){const d=[...el.options].findIndex(o=>o.defaultSelected);if(el.selectedIndex!==Math.max(d,0))m[el.id]={v:el.value}}
  else if(el.value!==el.defaultValue)m[el.id]={v:el.value}});return m}
function restoreDraft(m){Object.keys(m||{}).forEach(id=>{const el=document.getElementById(id);if(!el||el.type==='password'||el.type==='file')return;
  const x=m[id];if('c' in x)el.checked=x.c;else if(el.tagName==='SELECT'){if([...el.options].some(o=>o.value===x.v))el.value=x.v}else el.value=x.v})}
function keepDraft(fn,tab){return function(...a){const same=S._drawn===tab,snap=same?snapDraft():{},y=same?window.scrollY:0;
  const r=fn.apply(this,a);S._drawn=tab;if(same){restoreDraft(snap);window.scrollTo(0,y)}return r}}

