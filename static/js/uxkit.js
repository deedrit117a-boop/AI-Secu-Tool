// ---------- 화면 보강(UX): 진행 패널, 창 대기, 표 도구(정렬·찾기·더 보기), 테마·글자 크기, 처음 안내
// 다른 화면 코드는 이 파일의 함수만 부르고, 화면 상태(S)를 바꾸지 않는다.
const UX={job:null,waiting:[],open:false,atl:null};
const RPL=()=>S.rpLimit||400;     // 보고서 표에 한 번에 그리는 행 수 ('더 보기'로 늘어남)

// ---- 1) 진행 패널: 빠른 작업 진행 상황과 Atlantis 응답 대기를 어느 탭에서나 화면 아래에 보여 준다
const uxState=s=>/✅/.test(s)?'ok':/❌/.test(s)?'err':/🔄/.test(s)?'run':/⏸/.test(s)?'hold':'wait';
function jobSet(j){UX.job=j;clearTimeout(UX.jt);uxJobDraw()}
function jobEnd(ok){if(!UX.job)return;UX.job.done=true;UX.job.ok=ok;uxJobDraw();
  if(ok){clearTimeout(UX.jt);UX.jt=setTimeout(()=>{if(UX.job&&UX.job.done&&UX.job.ok){UX.job=null;uxJobDraw()}},9000)}}   // 성공하면 잠시 뒤 사라지고, 실패·보류는 닫을 때까지 남는다
function uxJobDraw(){let b=$('#jobbar');const polls=Object.keys(S.pollers||{}).length,j=UX.job,w=UX.waiting;
  const A=UX.atl&&UX.atl.show?UX.atl:null;
  if(!j&&!polls&&!w.length&&!A){if(b)b.style.display='none';return}
  if(!b){b=document.createElement('div');b.id='jobbar';b.setAttribute('role','status');b.setAttribute('aria-live','polite');document.body.appendChild(b)}
  const ic={wait:'○',run:'◔',ok:'✓',err:'✗',hold:'⏸'};
  const cur=j&&(j.steps.find(s=>s.state==='run')||j.steps.find(s=>s.state==='err'||s.state==='hold')||j.steps.filter(s=>s.state==='ok').slice(-1)[0]);
  const okN=j?j.steps.filter(s=>s.state==='ok').length:0;
  const head=j?`${j.done?(j.ok?'✅':'⚠️'):'⏳'} <b>${esc(j.title)}</b> — ${okN}/${j.steps.length} 단계${cur?` · ${esc(cur.label)}${cur.note?' ('+esc(String(cur.note).slice(0,60))+')':''}`:''}`:'';
  const extra=[polls?`Atlantis 응답 대기 ${polls}건`:'',...w.map(x=>'확인 대기: '+esc(x))].filter(Boolean).join(' · ');
  b.className=(j&&j.done&&!j.ok?'bad':'')+(UX.open?' open':'');b.style.display='block';
  b.innerHTML=`${head||extra?`<div class="jb-head"><button type="button" class="jb-t" aria-expanded="${!!UX.open}">${head}${head&&extra?' · ':''}${extra?`<span class="jb-x">${extra}</span>`:''}</button>${j&&j.done?'<button type="button" class="jb-c" aria-label="닫기">×</button>':''}</div>`:''}
    ${A?uxAtlHtml(A):''}
    ${UX.open&&j?`<ol class="jb-l">${j.steps.map(s=>`<li class="${s.state}"><span>${ic[s.state]||'○'}</span> ${esc(s.label)}${s.note?`<span class="mut"> — ${esc(String(s.note).slice(0,140))}</span>`:''}</li>`).join('')}</ol><div class="jb-f"><button type="button" class="jb-go">작업 탭으로</button></div>`:''}`;
  const tt=b.querySelector('.jb-t');if(tt)tt.onclick=()=>{UX.open=!UX.open;uxJobDraw()};
  const c=b.querySelector('.jb-c');if(c)c.onclick=()=>{UX.job=null;uxJobDraw()};
  const g=b.querySelector('.jb-go');if(g)g.onclick=()=>{S.tab='work';persist();render()};
  const ap=b.querySelector('.jb-apply');if(ap)ap.onclick=guard(()=>atlantisRunApply(A.iid,A.envId));
  const rp=b.querySelector('.jb-rep');if(rp)rp.onclick=()=>{S.tab='work';persist();render()};
  const pl=b.querySelector('.jb-plan');if(pl)pl.onclick=guard(()=>startPlan(A.iid,A.envId))}
// 진행 패널의 Atlantis 줄: MR 의 마지막 plan 결과와 apply 버튼
function uxAtlHtml(A){const ps=A.ps||{},n=ps.plan||{},lab={ok:'✅ plan 이상 없음',warn:'⚠️ plan 확인 필요',error:'❌ plan 실패',pending:'⏳ plan 대기 중'}[ps.state]||'plan 결과 없음';
  const num=n.add!=null?` · 추가 ${n.add} / 변경 ${n.change} / 삭제 ${n.destroy}${n.replace?` / 교체 ${n.replace}`:''}`:'';
  return `<div class="jb-atl"><span>MR !${esc(A.iid)} · ${lab}${num}</span> <button type="button" class="jb-apply ${ps.can_apply?'danger-fill':''}" ${ps.can_apply?'':'disabled'} title="${esc(ps.can_apply?'plan 결과를 확인한 뒤 apply 합니다':(ps.reason||'apply 할 수 없습니다'))}">apply 실행</button><button type="button" class="jb-plan">plan 다시</button><button type="button" class="jb-rep">결과 보기</button></div>`}

// ---- 2) 창 대기: 자동으로 뜨는 창(Jira 완료 처리, 엑셀 기록 등)은 먼저 열린 창이 닫힐 때까지 기다렸다가 이어서 연다
async function waitNoModal(label){
  if(!document.querySelector('.modal-ov'))return;
  UX.waiting.push(label);uxJobDraw();toast(`다른 창을 닫으면 "${label}" 창이 이어서 열립니다`,false,5000);
  while(document.querySelector('.modal-ov'))await new Promise(r=>setTimeout(r,400));
  UX.waiting=UX.waiting.filter(x=>x!==label);uxJobDraw()}

// ---- 3) 표 도구: 머리글을 눌러 정렬, 행이 많으면 '이 표에서 찾기', 잘린 표는 '더 보기'
function uxTable(t){if(t.dataset.ux||!t.tHead||!t.tBodies[0])return;t.dataset.ux='1';
  const body=t.tBodies[0],rows=()=>[...body.rows],ths=[...t.tHead.rows[0].cells];
  ths.forEach((th,i)=>{if(th.querySelector('input'))return;th.classList.add('srt');th.tabIndex=0;th.setAttribute('role','button');th.title='눌러서 정렬';
    const go=()=>{const asc=th.dataset.dir!=='asc';ths.forEach(x=>{delete x.dataset.dir;x.classList.remove('asc','desc')});th.dataset.dir=asc?'asc':'desc';th.classList.add(asc?'asc':'desc');
      const val=r=>{const c=r.cells[i];return c?c.innerText.trim():''},num=v=>/^-?\d+(\.\d+)?$/.test(v)?parseFloat(v):null;
      rows().sort((a,b)=>{const x=val(a),y=val(b),nx=num(x),ny=num(y);const c=(nx!==null&&ny!==null)?nx-ny:x.localeCompare(y,'ko',{numeric:true});return asc?c:-c}).forEach(r=>body.appendChild(r))};
    th.onclick=go;th.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();go()}}});
  if(rows().length>=8&&t.parentElement){const f=document.createElement('div');f.className='rp-find row';
    f.innerHTML='<input type="text" class="rp-q" placeholder="이 표에서 찾기" aria-label="이 표에서 찾기"><span class="mut rp-n"></span>';t.parentElement.insertBefore(f,t);
    const q=f.querySelector('.rp-q'),n=f.querySelector('.rp-n');
    const run=()=>{const w=q.value.trim().toLowerCase().split(/\s+/).filter(Boolean);let k=0;rows().forEach(r=>{const ok=!w.length||w.every(x=>r.innerText.toLowerCase().includes(x));r.style.display=ok?'':'none';if(ok)k++});n.textContent=w.length?`${k} / ${rows().length}건`:`${rows().length}건`};
    q.oninput=run;run()}}
function uxMore(root){root.querySelectorAll('.mut').forEach(m=>{if(m.dataset.more||!/건만 표시|일부만 불러옴/.test(m.textContent))return;m.dataset.more='1';
  const b=document.createElement('button');b.type='button';b.className='more';b.textContent='더 보기 (+400)';b.onclick=()=>{S.rpLimit=RPL()+400;if(root._rerender)root._rerender()};m.appendChild(b)})}
// 보고서 본문(root)에 새 표가 그려질 때마다 도구를 붙인다. rerender 는 '더 보기'가 현재 탭을 다시 그리는 함수
function uxObserveTables(root,rerender){root._rerender=rerender;if(root._uxo)return;
  root._uxo=new MutationObserver(()=>{clearTimeout(root._uxt);root._uxt=setTimeout(()=>{root.querySelectorAll('table.rp-t:not([data-ux])').forEach(uxTable);uxMore(root)},60)});
  root._uxo.observe(root,{childList:true,subtree:true})}

// ---- 4) 빠른 작업 진행 옵션 요약 (접힌 상태에서도 apply 가 켜졌는지 보이게)
function wzOptSum(){const c=$('#wz-optsum');if(!c||!$('#wz-plan'))return;const p=$('#wz-plan').checked,a=$('#wz-apply')&&$('#wz-apply').checked,j=$('#wz-jira')&&$('#wz-jira').checked;
  c.textContent=(p?'plan 까지':'plan 안 함')+(a?' + apply':'')+(j?' + Jira 기록':'');c.className='chip'+(a?' danger':'')}

// ---- 5) 처음 안내: 작업 탭 맨 위 한 줄 (닫으면 다시 나오지 않는다)
function workHint(){if(ls.get('hintWork',false))return'';
  return `<div class="card hintbar" id="wk-hint"><div class="row"><div><b>처음이라면</b> — <span class="stepr">① 저장소 받기</span> → <span class="stepr">② 브랜치 준비</span> → <span class="stepr">③ 규칙 수정 (접근제어 탭)</span> → <span class="stepr">④ Commit/Push</span> → <span class="stepr">⑤ MR</span> → <span class="stepr">⑥ plan / apply</span>
    <div class="mut" style="font-size:12px">익숙해지면 아래 ⚡ 빠른 작업이 ②~⑥ 을 한 번에 진행합니다. 각 카드 제목 옆 배지(✓ 완료 / ! 확인 / ✗ 실패)로 어디까지 했는지 볼 수 있습니다.</div></div><button type="button" id="wk-hint-x" style="margin-left:auto">다시 보지 않기</button></div></div>`}

// ---- 6) 화면 색상(자동/밝게/어둡게)과 글자 크기. 이 브라우저에만 기억한다
const UX_ZOOMS=[0.9,1,1.1,1.25,1.4],UX_THEMES=[['auto','🌓 자동'],['light','☀ 밝게'],['dark','🌙 어둡게']];
function uxApplyPrefs(){const th=ls.get('uxTheme','auto'),z=ls.get('uxZoom',1),r=document.documentElement;
  if(th==='auto')r.removeAttribute('data-theme');else r.dataset.theme=th;r.style.setProperty('--zoom',String(z));
  const b=$('#ux-th');if(b)b.textContent=(UX_THEMES.find(x=>x[0]===th)||UX_THEMES[0])[1];const zl=$('#ux-zl');if(zl)zl.textContent=Math.round(z*100)+'%'}
function uxInit(){uxApplyPrefs();const sb=document.querySelector('.sidebar');
  if(sb&&!$('#uxctl')){const d=document.createElement('div');d.id='uxctl';d.className='uxctl';
    d.innerHTML='<button type="button" id="ux-th" title="화면 색상 바꾸기 (자동 → 밝게 → 어둡게)"></button><span class="uxz"><button type="button" id="ux-zm" aria-label="글자 작게" title="글자 작게">A−</button><span id="ux-zl" class="mut"></span><button type="button" id="ux-zp" aria-label="글자 크게" title="글자 크게">A+</button></span>';
    sb.appendChild(d);
    $('#ux-th').onclick=()=>{const cur=ls.get('uxTheme','auto'),i=UX_THEMES.findIndex(x=>x[0]===cur);ls.set('uxTheme',UX_THEMES[(i+1)%UX_THEMES.length][0]);uxApplyPrefs()};
    const zs=dir=>{const cur=ls.get('uxZoom',1);let i=UX_ZOOMS.findIndex(x=>Math.abs(x-cur)<.01);if(i<0)i=1;i=Math.max(0,Math.min(UX_ZOOMS.length-1,i+dir));ls.set('uxZoom',UX_ZOOMS[i]);uxApplyPrefs()};
    $('#ux-zm').onclick=()=>zs(-1);$('#ux-zp').onclick=()=>zs(1);uxApplyPrefs()}}
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!document.querySelector('.modal-ov')){const t=$('#toast');if(t&&t.style.display==='block')t.style.display='none'}});   // Esc 로 알림 닫기
document.addEventListener('click',e=>{if(e.target&&e.target.id==='wk-hint-x'){ls.set('hintWork',true);const h=$('#wk-hint');if(h)h.remove()}});
uxInit();
