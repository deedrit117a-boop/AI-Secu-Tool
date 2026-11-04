// ---------- 정책 규칙(위험 기준·예외) 카드와 '규칙 점검 보고서'(만료 / 정리 제안 / 접근 경로), 변경 기록 파일
// 모두 읽기 전용이다. 정책은 config.json 의 policy 에 저장되어 팀이 같이 쓸 수 있고, 보고서는 바꾸는 일 없이 보여주기만 한다.
const PL_PORT_NAMES={22:'SSH',3389:'RDP',5985:'WinRM',5986:'WinRM(HTTPS)'};
function plEnvOptions(sel){return `<option value="">(모든 환경)</option>`+(S.cfg.environments||[]).map(e=>`<option value="${esc(e.id)}" ${sel===e.id?'selected':''}>${esc([e.group,e.env,e.label].filter(Boolean).join(' · ')||e.id)}</option>`).join('')}
const plRow=x=>`<tr class="plx"><td><input type="text" class="pl-n" style="width:100%" placeholder="예: 사무실 SSH" value="${esc(x.name||'')}"></td><td><input type="text" class="pl-c" style="width:100%" placeholder="211.34.57.0/24, 10.0.0.0/16" value="${esc((x.cidrs||[]).join(', '))}"></td><td style="width:140px"><input type="text" class="pl-p" style="width:100%" placeholder="22 또는 *" value="${esc(x.ports||'*')}"></td><td style="width:200px"><select class="pl-e" style="width:100%">${plEnvOptions(x.env||'')}</select></td><td style="width:70px"><button class="danger pl-d">삭제</button></td></tr>`;
async function drawPolicyCard(){
  const host=$('#policy-card');if(!host)return;
  let r;try{r=await api('GET','/api/policy')}catch(e){host.innerHTML=`<div class="card"><div class="warnbox danger">${esc(e.message)}</div></div>`;return}
  if(!$('#policy-card'))return;const p=r.policy;
  host.innerHTML=`<div class="card"><h3>정책 규칙 <span class="mut" style="font-weight:400">(위험 규칙으로 확인을 받을 기준 — config.json 공유)</span></h3>
    <div class="row" style="align-items:flex-end">
      <label class="f">관리 포트 (쉼표 구분)<input type="text" id="pl-mp" size="28" value="${esc(Object.keys(p.mgmt_ports).join(', '))}"></label>
      <label class="f">관리 포트는 /<input type="number" id="pl-mx" min="1" max="32" style="width:64px" value="${p.mgmt_max_prefix}"> 보다 넓은 대역에 열면 위험</label>
      <label class="f">광범위 대역 기준 /<input type="number" id="pl-wd" min="1" max="32" style="width:64px" value="${p.wide_prefix}"> 보다 넓으면 위험</label></div>
    <div style="margin-top:10px"><b>허용 예외</b> <span class="mut" style="font-size:12px">— 아래 소스 대역·포트에 해당하는 새 규칙은 위험으로 묻지 않습니다 (예: 우리 사무실 대역의 SSH)</span></div>
    <table><thead><tr><th style="width:200px">이름</th><th>소스 대역 (쉼표 구분, 이 안에 들어가면 예외)</th><th>포트</th><th>적용 환경</th><th></th></tr></thead><tbody id="pl-body">${p.exceptions.map(plRow).join('')}</tbody></table>
    <div class="row" style="margin-top:8px"><button id="pl-add">예외 추가</button><button class="pri" id="pl-save">정책 저장</button><button id="pl-reset" title="관리 포트·기준·예외를 처음 값으로 되돌립니다 (저장해야 반영)">기본값으로</button><span class="mut" id="pl-msg" role="status"></span></div>
    <div class="mut" style="font-size:12px;margin-top:6px">0.0.0.0/0 처럼 전체 개방은 예외에 그 대역을 직접 적어야 풀립니다. 포트는 <code>22</code>, <code>1000-2000</code>, <code>*</code>(전체) 형식입니다. 인바운드에 새로 넣는 규칙에만 적용됩니다.</div></div>`;
  const body=$('#pl-body');
  $('#pl-add').onclick=()=>{body.insertAdjacentHTML('beforeend',plRow({}))};
  body.onclick=e=>{if(e.target.classList.contains('pl-d'))e.target.closest('tr').remove()};
  $('#pl-reset').onclick=()=>{$('#pl-mp').value=Object.keys(r.defaults.mgmt_ports).join(', ');$('#pl-mx').value=r.defaults.mgmt_max_prefix;$('#pl-wd').value=r.defaults.wide_prefix;body.innerHTML='';$('#pl-msg').textContent='기본값을 채웠습니다. 저장을 눌러야 반영됩니다'};
  $('#pl-save').onclick=guard(async()=>{
    const exceptions=[...body.querySelectorAll('tr.plx')].map(tr=>({name:tr.querySelector('.pl-n').value.trim(),cidrs:tr.querySelector('.pl-c').value.trim(),ports:tr.querySelector('.pl-p').value.trim()||'*',env:tr.querySelector('.pl-e').value})).filter(x=>x.name||x.cidrs);
    const a=await api('PUT','/api/policy',{policy:{mgmt_ports:$('#pl-mp').value,mgmt_max_prefix:+$('#pl-mx').value,wide_prefix:+$('#pl-wd').value,exceptions}});
    await reloadCfg();$('#pl-msg').textContent=`저장했습니다 (관리 포트 ${Object.keys(a.policy.mgmt_ports).length}개, 예외 ${a.policy.exceptions.length}개)`;toast('정책 규칙을 저장했습니다')})}

// 접근 경로 토폴로지: 조회한 IP → 포트 → 환경(SG 수)을 선으로 이어 보여준다 (아웃바운드는 환경 → 포트 → IP).
// 노드를 누르면 그 포트/환경의 SG 만 아래 표에 남고, 다시 누르면 풀린다.
function tpDiagram(rows,q,rev,sel){
  const TOP=12,pc=new Map(),ec=new Map(),en0={};
  rows.forEach(x=>{en0[x.env_id]=x.env;ec.set(x.env_id,(ec.get(x.env_id)||0)+1);x.ports.forEach(p=>pc.set(p,(pc.get(p)||0)+1))});
  const top=m=>new Set([...m.entries()].sort((a,b)=>b[1]-a[1]).slice(0,TOP).map(e=>e[0]));
  const tp=top(pc),te=top(ec),pk=p=>tp.has(p)?p:'__o',ek=e=>te.has(e)?e:'__o';
  const pn=new Map(),en=new Map(),pe=new Map(),lab={__o:'기타'};
  rows.forEach(x=>{const e=ek(x.env_id);lab[e]=e==='__o'?'기타 환경':en0[x.env_id];en.set(e,(en.get(e)||0)+1);
    new Set(x.ports.map(pk)).forEach(p=>{lab[p]=p==='__o'?'기타 포트':p;pn.set(p,(pn.get(p)||0)+1);const k=p+'\u0001'+e;pe.set(k,(pe.get(k)||0)+1)})});
  const ord=m=>[...m.entries()].sort((a,b)=>(a[0]==='__o')-(b[0]==='__o')||b[1]-a[1]);
  const P=ord(pn),E=ord(en),n=Math.max(P.length,E.length,1),H=n*38+44,W=1000,NH=28;
  const A={x:10,w:230},B={x:390,w:220},C={x:760,w:230},y=i=>34+i*38;
  const cut=(s,k)=>s.length>k?s.slice(0,k-1)+'…':s;
  const col=['#2563eb','#7c3aed','#16a34a'];
  const mid=y((P.length-1)/2);
  const node=(c,x,w,yy,text,full,attrs,on)=>`<g class="tp-node${on?' sel':''}" ${attrs}><title>${esc(full)}</title><rect x="${x}" y="${yy}" width="${w}" height="${NH}" rx="6" style="stroke:${c}"/><text x="${x+10}" y="${yy+NH/2+4}">${esc(cut(text,w>225?30:26))}</text></g>`;
  const mx=Math.max(1,...pn.values(),...en.values());
  const link=(x1,y1,x2,y2,cnt,c,attrs,on,dim)=>{const mxx=(x1+x2)/2;return `<path class="tp-link${on?' sel':''}${dim?' tp-dim':''}" ${attrs} d="M${x1},${y1+NH/2} C${mxx},${y1+NH/2} ${mxx},${y2+NH/2} ${x2},${y2+NH/2}" stroke="${c}" stroke-width="${(1.5+8*cnt/mx).toFixed(1)}"/>`};
  const pi=new Map(P.map((e,i)=>[e[0],i])),ei=new Map(E.map((e,i)=>[e[0],i]));
  let links='',nodes='';
  // 가운데 열은 항상 포트. 왼쪽/오른쪽은 (조회 IP, 환경)이 방향에 따라 바뀐다
  const ipX=rev?C:A,envX=rev?A:C,ipSide=rev?'r':'l';
  P.forEach(([p,c],i)=>{const dim=sel.p&&sel.p!==p;
    links+=link(ipX.x+(rev?0:ipX.w),mid,B.x+(rev?B.w:0),y(i),c,col[0],`data-p="${esc(p)}"`,sel.p===p,dim);
    nodes+=node(col[1],B.x,B.w,y(i),`${lab[p]} (${c})`,`${lab[p]} — SG ${c}개`,`data-p="${esc(p)}"`,sel.p===p)});
  pe.forEach((c,k)=>{const [p,e]=k.split('\u0001'),on=sel.p===p&&sel.e===e,dim=(sel.p&&sel.p!==p)||(sel.e&&sel.e!==e);
    links+=link(rev?envX.x+envX.w:B.x+B.w,rev?y(ei.get(e)):y(pi.get(p)),rev?B.x:envX.x,rev?y(pi.get(p)):y(ei.get(e)),c,col[2],`data-p="${esc(p)}" data-e="${esc(e)}"`,on,dim)});
  E.forEach(([e,c],i)=>{nodes+=node(col[2],envX.x,envX.w,y(i),`${lab[e]} (${c})`,`${lab[e]} — SG ${c}개`,`data-e="${esc(e)}"`,sel.e===e)});
  nodes+=node(col[0],ipX.x,ipX.w,mid-0,`${q} (${rows.length})`,`${q} — SG ${rows.length}개`,'data-clear="1"',false);
  const h=rev?['환경 (SG 수)','포트','조회 IP']:['조회 IP','포트','환경 (SG 수)'],hx=[A.x,B.x,C.x],hc=rev?[col[2],col[1],col[0]]:[col[0],col[1],col[2]];
  const heads=h.map((t,i)=>`<text class="tp-col" x="${hx[i]}" y="16" style="fill:${hc[i]}">${esc(t)}</text>`).join('');
  return {svg:`<div class="tp-wrap"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="접근 경로 토폴로지">${heads}${links}${nodes}</svg></div>`,pk,ek,more:pc.size>TOP||ec.size>TOP}}

function dlFile(blob,name){const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),4000)}
const RP_KIND={duplicate:['중복','b-chg'],covered:['포함됨','b-warn']};
const RP_DIR=d=>d==='ingress'?'인바운드':'아웃바운드';
async function openReports(tab,ip){tab=tab||ls.get('rpTab','expiry');
  const csv=(u)=>`<a class="btn" style="text-decoration:none" href="${u}">CSV 다운로드</a>`;
  const tabs=[['expiry','만료 규칙'],['cleanup','정리 제안'],['reach','접근 경로(IP)'],['refs','SG 관계'],['score','기준 점검'],['ticket','티켓 찾기'],['owners','담당자별'],['audit','감사 보고서']];
  const html=`<div class="tabs" role="tablist" id="rp-tabs">${tabs.map(t=>`<button type="button" role="tab" data-t="${t[0]}" class="tab ${t[0]===(tab||'expiry')?'on':''}" aria-selected="${t[0]===(tab||'expiry')}">${t[1]}</button>`).join('')}</div><div id="rp-body" style="min-height:120px"></div>`;
  await showModal('규칙 점검 보고서',html,'닫기',null,{hideCancel:true,wide:'reports',onMount:o=>{
    const B=o.querySelector('#rp-body');let cur=tab||'expiry';
    const table=(head,rows)=>rows.length?`<div><table class="rp-t"><thead><tr>${head.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`:'';
    const bindCleanup=r=>{const rows=r.rows.slice(0,RPL()),all=B.querySelector('#cl-all');
      if(all)all.onchange=()=>B.querySelectorAll('.cl-ck').forEach(c=>c.checked=all.checked);
      const del=B.querySelector('#cl-del');if(!del)return;
      del.onclick=guard(async()=>{const sel=[...B.querySelectorAll('.cl-ck:checked')].map(c=>rows[+c.dataset.i]);if(!sel.length)return toast('삭제할 규칙을 먼저 선택하세요',true);
        const items=sel.map(x=>({env_id:x.env_id,sg:x.sg,direction:x.direction,idx:x.idx,sig:x.sig})),pv=await api('POST','/api/cleanup/apply',{items,dry_run:true});
        if(!pv.removed)return toast('삭제할 규칙이 없습니다 (그 사이 규칙이 바뀌었을 수 있습니다. 보고서를 다시 여세요)',true);
        if(!await showModal('선택한 규칙 삭제',`<div>선택한 규칙 <b>${pv.removed}</b>건을 파일에서 삭제합니다 (SG ${pv.results.filter(x=>x.removed.length).length}개).${pv.skipped?` 그 사이 바뀐 ${pv.skipped}건은 건너뜁니다.`:''}</div>
          <div style="max-height:40vh;overflow:auto;margin:8px 0">${pv.results.filter(x=>x.removed.length).map(x=>`<div><b>${esc(x.sg)}</b><ul>${x.removed.map(t=>`<li>${esc(t)}</li>`).join('')}</ul></div>`).join('')}</div>
          <div class="mut">작업 브랜치에서만 삭제할 수 있고 파일만 바뀝니다. 되돌리기는 작업 탭의 되돌리기를, 올리기는 작업 탭의 Commit/Push 를 쓰세요.</div>`,'삭제',null,{danger:true}))return;
        const r2=await api('POST','/api/cleanup/apply',{items,dry_run:false});toast(`규칙 ${r2.removed}건을 삭제했습니다 (파일만 수정됨 — Commit/Push 는 작업 탭에서)`,false,6000);tabs_.cleanup()})};
    const tabs_={
      ...reviewTabs({o,B,table,csv,ip}),
      async expiry(){const days=+(o.querySelector('#ex-days')?.value||30);B.innerHTML='<div class="mut">불러오는 중...</div>';
        const r=await api('GET','/api/report/expiry?days='+days),ow=(S.rpOwner||'').toLowerCase(),rows=r.rows.filter(x=>!ow||(x.owner||'').toLowerCase().includes(ow));
        B.innerHTML=`<div class="row" style="gap:10px;align-items:center"><label>앞으로 <input type="number" id="ex-days" min="0" max="3650" style="width:70px" value="${days}">일 안에 만료되는 규칙까지</label><button id="ex-go">다시 조회</button><input type="text" id="rp-ow" placeholder="담당자 필터" value="${esc(S.rpOwner||'')}" style="width:120px">${csv('/api/report/expiry?format=csv&days='+days)}</div>
          <div class="mut" style="margin:6px 0">만료일이 지난 규칙 <b>${r.expired}</b>건 · 임박 <b>${r.count-r.expired}</b>건 · 만료일이 적힌 규칙 전체 ${r.with_expiry}건</div>
          ${table(['환경','SG','담당자','방향','프로토콜','포트','소스','만료일','상태','설명','조치'],rows.slice(0,RPL()).map(x=>`<tr><td>${esc(x.env)}</td><td>${sgLink(x)}</td><td>${esc(x.owner||'')}</td><td>${RP_DIR(x.direction)}</td><td>${esc(x.protocol)}</td><td>${esc(x.port)}</td><td>${esc(x.source)}</td><td>${esc(x.expires)}</td><td><span class="badge ${x.status==='expired'?'b-chg':'b-warn'}">${x.status==='expired'?`지남 ${-x.days_left}일`:`D-${x.days_left}`}</span></td><td>${esc(x.description)}</td><td class="nw"><button type="button" class="rp-act" data-a="ext" data-e="${esc(x.env_id)}" data-s="${esc(x.sg)}" data-d="${x.direction}" data-i="${x.idx}" data-g="${esc(x.sig)}">연장</button> <button type="button" class="rp-act danger" data-a="del" data-e="${esc(x.env_id)}" data-s="${esc(x.sg)}" data-d="${x.direction}" data-i="${x.idx}" data-g="${esc(x.sig)}">삭제</button></td></tr>`))||'<div class="mut" style="padding:8px">해당하는 규칙이 없습니다.</div>'}
          <div class="mut" style="font-size:12px;margin-top:8px">규칙 설명에 <code>만료:2026-12-31</code> (또는 <code>expire=20261231</code>, <code>만료 261231</code>) 이라고 적어 두면 여기서 찾습니다. 도구는 규칙을 지우지 않으니, 확인한 뒤 접근제어에서 직접 삭제하세요.</div>`;
        o.querySelector('#ex-go').onclick=guard(tabs_.expiry);o.querySelector('#rp-ow').onchange=ev=>{S.rpOwner=ev.target.value.trim();tabs_.expiry()}},
      async cleanup(){B.innerHTML='<div class="mut">모든 환경을 살펴보는 중...</div>';
        const r=await api('GET','/api/report/cleanup'),ow=(S.rpOwner||'').toLowerCase(),rr={...r,rows:r.rows.filter(x=>!ow||(x.owner||'').toLowerCase().includes(ow))};
        B.innerHTML=`<div class="row" style="gap:10px;align-items:center">${Object.keys(RP_KIND).filter(k=>r.kinds[k]).map(k=>`<span><span class="badge ${RP_KIND[k][1]}">${RP_KIND[k][0]}</span> ${r.kinds[k]}</span>`).join('')||'<span>정리할 규칙이 없습니다</span>'}<span class="mut">SG ${r.sgs}개 검사</span><input type="text" id="rp-ow" placeholder="담당자 필터" value="${esc(S.rpOwner||'')}" style="width:120px">${csv('/api/report/cleanup?format=csv')}<button id="cl-del" class="danger" title="체크한 규칙을 파일에서 삭제합니다 (작업 브랜치에서만)">선택한 규칙 삭제</button></div>
          ${table(['<input type="checkbox" id="cl-all" title="전체 선택">','환경','SG','담당자','구분','방향','프로토콜','포트','소스','겹치는 규칙'],rr.rows.slice(0,RPL()).map((x,i)=>`<tr><td><input type="checkbox" class="cl-ck" data-i="${i}"></td><td>${esc(x.env)}</td><td>${sgLink(x)}</td><td>${esc(x.owner||'')}</td><td class="nw"><span class="badge ${RP_KIND[x.kind][1]}" title="${esc(x.note)}">${RP_KIND[x.kind][0]}</span></td><td class="nw">${RP_DIR(x.direction)}</td><td class="nw">${esc(x.protocol)}</td><td>${esc(x.port)}</td><td>${esc(x.source)}</td><td>${esc(x.by)}</td></tr>`))}
          ${rr.rows.length>RPL()?`<div class="mut">상위 ${RPL()}건만 표시했습니다. 전체는 CSV 로 받으세요.</div>`:''}
          <div class="mut" style="font-size:12px;margin-top:8px">제안만 하고 파일은 바꾸지 않습니다. 중복 = 같은 규칙이 이미 있음, 포함됨 = 더 넓은 규칙이 이미 허용함(지워도 접근 범위 같음). 아웃바운드 전체 허용에 포함되는 아웃바운드는 제외했습니다. 체크한 규칙은 위의 삭제 버튼으로 지울 수 있습니다(작업 브랜치에서만).</div>`;B.querySelector('#rp-ow').onchange=ev=>{S.rpOwner=ev.target.value.trim();tabs_.cleanup()};bindCleanup(rr)},
      async reach(){const q0=o.querySelector('#rc-q')?.value??(ip||'');
        B.innerHTML=`<div class="row" style="gap:8px"><input type="text" id="rc-q" style="flex:1" placeholder="IP 또는 대역 (예: 211.34.57.10, 10.0.0.0/24)" value="${esc(q0)}"><button class="blue" id="rc-go">조회</button><label style="white-space:nowrap" title="열린 SG 를 소스로 허용하는 다른 SG 도 (최대 2단계) 포함합니다"><input type="checkbox" id="rc-via"${o.querySelector('#rc-via')?.checked?' checked':''}> SG 경유(간접) 포함</label><span id="rc-dl"></span></div><div id="rc-res" style="margin-top:8px"></div>`;
        let dir='ingress',sel={p:null,e:null},res=null;
        const view=()=>{const R=o.querySelector('#rc-res'),all=res.rows.filter(x=>x.direction===dir),rev=dir==='egress';
          const d=tpDiagram(all,res.q,rev,sel),rows=all.filter(x=>(!sel.p||x.ports.some(p=>d.pk(p)===sel.p))&&(!sel.e||d.ek(x.env_id)===sel.e));
          const ni=res.ingress,ne=res.count-res.ingress;
          R.innerHTML=`<div class="row" style="gap:8px;align-items:center;margin-bottom:6px"><b>${esc(res.q)}</b> 이(가) 열려 있는 SG
            <button type="button" data-d="ingress" class="${dir==='ingress'?'blue':''}">인바운드 ${ni}</button><button type="button" data-d="egress" class="${dir==='egress'?'blue':''}">아웃바운드 ${ne}</button>
            ${sel.p||sel.e?'<button type="button" id="rc-clr">선택 해제</button>':''}</div>
            ${all.length?d.svg+`<div class="mut" style="font-size:12px;margin:2px 0 8px">포트나 환경 상자, 선을 누르면 아래 표에 그 SG 만 남습니다. 선이 굵을수록 SG 가 많습니다.${d.more?' 가장 많은 12개만 그리고 나머지는 "기타"로 묶었습니다 (표에는 모두 나옵니다).':''}</div>`:''}
            ${table(['환경','SG','별명','태그','범위','열린 포트'],rows.slice(0,RPL()).map(x=>`<tr><td>${esc(x.env)}</td><td>${sgLink(x)}${x.sg_id?`<div class="mut" style="font-size:11px">${esc(x.sg_id)}</div>`:''}</td><td>${esc(x.alias)}</td><td>${esc(x.tags)}</td><td class="nw">${rcBadge(x)}</td><td>${x.ports.map(esc).join(', ')}</td></tr>`))||'<div class="mut" style="padding:8px">이 주소가 열려 있는 SG 가 없습니다.</div>'}
            ${rows.length>RPL()?`<div class="mut">상위 ${RPL()}건만 표시했습니다. 전체는 CSV 로 받으세요.</div>`:''}
            <div class="mut" style="font-size:12px;margin-top:8px"><b>전체</b> = 입력한 주소 전체가 규칙의 대역 안에 있음 / <b>일부 대역만</b> = 입력한 대역과 일부만 겹침. <b>SG 경유</b> = 'SG 경유(간접) 포함'을 켰을 때만 나오며, 열린 SG 를 소스로 허용하는 다른 SG(최대 2단계)입니다.</div>`;
          R.querySelectorAll('[data-d]').forEach(b=>b.onclick=()=>{dir=b.dataset.d;sel={p:null,e:null};view()});
          const c=R.querySelector('#rc-clr');if(c)c.onclick=()=>{sel={p:null,e:null};view()};
          const sv=R.querySelector('svg');if(sv)sv.onclick=ev=>{const t=ev.target.closest('[data-p],[data-e],[data-clear]');if(!t)return;
            if(t.dataset.clear){sel={p:null,e:null}}
            else if(t.dataset.p!==undefined&&t.dataset.e!==undefined){const same=sel.p===t.dataset.p&&sel.e===t.dataset.e;sel=same?{p:null,e:null}:{p:t.dataset.p,e:t.dataset.e}}
            else if(t.dataset.p!==undefined)sel={p:sel.p===t.dataset.p?null:t.dataset.p,e:sel.e};
            else sel={p:sel.p,e:sel.e===t.dataset.e?null:t.dataset.e};
            view()}};
        const run=guard(async()=>{const q=o.querySelector('#rc-q').value.trim();if(!q)return;const R=o.querySelector('#rc-res');R.innerHTML='<div class="mut">찾는 중...</div>';
          const vq=o.querySelector('#rc-via').checked?'&via=1':'';res=await api('GET','/api/report/reach?q='+encodeURIComponent(q)+vq);o.querySelector('#rc-dl').innerHTML=csv('/api/report/reach?format=csv&q='+encodeURIComponent(q)+vq);
          sel={p:null,e:null};dir=res.ingress||!(res.count-res.ingress)?'ingress':'egress';view()});
        o.querySelector('#rc-go').onclick=run;o.querySelector('#rc-via').onchange=()=>{if(res)run()};o.querySelector('#rc-q').onkeydown=e=>{if(e.key==='Enter')run()};if(q0)run()}};
    const go=t=>{cur=t;ls.set('rpTab',t);uxObserveTables(B,()=>go(t));o.querySelectorAll('#rp-tabs button').forEach(b=>{const on=b.dataset.t===t;b.className='tab'+(on?' on':'');b.setAttribute('aria-selected',on)});
      Promise.resolve(tabs_[t]()).catch(e=>{B.innerHTML=`<div class="warnbox danger">${esc(e.message)}</div>`})};
    o.querySelectorAll('#rp-tabs button').forEach(b=>b.onclick=()=>go(b.dataset.t));go(cur)}})}

// 변경 요약 보고서의 '변경 기록 파일' 버튼에서 부른다: 티켓·작성자·변경 내용·위험·MR·plan 결과를 한 장(.md)으로 저장
async function saveChangeRecord(){
  const tk=($('#ticket')||{}).value||'';
  const r=await fetch(`/api/env/${S.envId}/report/audit?download=1&ticket=${encodeURIComponent(tk.trim())}`);
  if(!r.ok){let m='변경 기록을 만들지 못했습니다';try{m=(await r.json()).error||m}catch{}throw new Error(m)}
  const cd=r.headers.get('Content-Disposition')||'',m=/filename="([^"]+)"/.exec(cd);
  dlFile(await r.blob(),m?m[1]:'sg-change-record.md');toast('변경 기록 파일을 저장했습니다 (다운로드 폴더)')}
