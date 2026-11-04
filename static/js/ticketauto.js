// ---------- Jira 티켓으로 빠른 작업 채우기(+바로 실행 확인), 여러 티켓 일괄, 요청 양식, 완료 처리(코멘트·상태 전환), 도메인 조회(메타 데이터 비교 / 태그 적용)
// 티켓은 읽기만 한다. 읽은 값은 화면에서 확인·수정한 뒤에 빠른 작업(마법사)에 채워지고, 규칙은 마법사의 '실행' 확인을 거쳐서만 바뀐다.
// Jira 에 쓰는 것은 '완료 처리'(코멘트 + 상태 전환) 하나뿐이고, apply 가 끝난 뒤 화면 확인(또는 위저드에서 옵션을 켠 경우)에서만 일어난다.

// 진행 단계: 앞의 5개는 항상, apply 와 Jira 완료 처리는 빠른 작업 카드의 체크박스(opt)를 켰을 때만 한다.
const AUTO_STEPS=[
  {id:'prep',label:'브랜치 준비',on:true},{id:'rules',label:'규칙 추가',on:true},{id:'push',label:'Commit & Push',on:true},{id:'mr',label:'MR 생성',on:true},{id:'plan',label:'atlantis plan',on:true},
  {id:'apply',label:'plan 이상 없으면 apply',opt:'#wz-apply'},{id:'jira',label:'완료 시 Jira 코멘트·상태 전환',opt:'#wz-jira'}];

// '443, 8080-8090' → [[443,443],[8080,8090]]. 끝 포트 칸(to)이 있으면 from-to 한 범위. 형식이 틀리면 null
function parsePortList(fromStr,toStr){fromStr=String(fromStr||'').trim();toStr=String(toStr||'').trim();
  const ok=(a,b)=>Number.isInteger(a)&&Number.isInteger(b)&&a>=0&&b<=65535&&a<=b;
  if(toStr!==''){const a=parseInt(fromStr),b=parseInt(toStr);return ok(a,b)&&/^\d+$/.test(fromStr)&&/^\d+$/.test(toStr)?[[a,b]]:null}
  if(!fromStr)return [];const out=[];
  for(const t of fromStr.split(/[,\s;]+/).filter(Boolean)){const m=/^(\d{1,5})(?:-(\d{1,5}))?$/.exec(t);if(!m)return null;const a=+m[1],b=+(m[2]||m[1]);if(!ok(a,b))return null;if(!out.some(r=>r[0]===a&&r[1]===b))out.push([a,b])}
  return out}

// 티켓 한 건(또는 그 안의 한 묶음)을 읽어 빠른 작업을 채운다. o = {key, group}. 반환: 취소 null / 채우기만 {ok:true,filled:true} / 실행했으면 runWizard 의 결과
async function ticketFillWizard(runNow,o={}){
  if(!S.envId)return toast('환경을 먼저 선택하세요',true);
  const wk=(o.key||$('#wz-ticket').value||'').trim().toUpperCase(),k=/^[A-Z][A-Z0-9_]+-\d+$/.test(wk)?wk:(typeof ticketKey==='function'?ticketKey():'');
  if(!k)return toast('티켓번호를 먼저 입력하세요 (예: ISRIR-12345)',true);
  toast('Jira 티켓을 읽는 중...',false,20000);
  let p;try{p=await api('GET',`/api/jira/plan?key=${encodeURIComponent(k)}&env_id=${encodeURIComponent(S.envId)}`)}finally{$('#toast').style.display='none'}
  const q=p.parsed;
  const G=(q.groups&&q.groups.length)?q.groups:[{action:'add',ips:q.ips,dst_ips:q.dst_ips,ports:q.ports,protocol:q.protocol,targets:p.targets,suggested:p.suggested,purpose:'',period:'',expires:'',project:p.project||'',src_env:'',dst_env:'',rows:[]}];
  const gi0=Math.min(Math.max(o.group||0,0),G.length-1);
  const portTxt=g=>g.ports.map(r=>r.from===r.to?String(r.from):r.from+'-'+r.to).join(', ');
  const gname=(g,i)=>`묶음 ${i+1}: ${g.action==='del'?'[삭제] ':''}${(g.dst_ips||[]).map(x=>x.replace(/\/32$/,'')).join(', ')||'목적지 미상'} · ${g.protocol} ${portTxt(g)} · 출발지 ${g.ips.length}개`;
  const sgHtml=g=>{const opts=S.sgs.map(x=>{const t=(g.targets||[]).find(y=>y.name===x.name);return{name:x.name,reason:t?t.reason:'',on:(g.suggested||[]).includes(x.name)}});
    opts.sort((a,b)=>(!!b.reason)-(!!a.reason));
    return opts.map(x=>`<label class="chk"><input type="checkbox" class="tk-sg" value="${esc(x.name)}" ${x.on?'checked':''}> ${esc(x.name)}${x.reason?` <span class="mut" style="font-size:12px">— ${esc(x.reason)}</span>`:''}</label>`).join('')||'<div class="mut" style="padding:6px">SG 없음</div>'};
  const infoHtml=g=>{const bits=[g.project&&`프로젝트 <b>${esc(g.project)}</b>`,(g.src_env||g.dst_env)&&`환경 ${esc(g.src_env||'-')} → ${esc(g.dst_env||'-')}`,g.purpose&&`용도 ${esc(g.purpose)}`,g.period&&`사용 기간 ${esc(g.period)}${g.expires?` (만료 ${esc(g.expires)})`:''}`,(g.dst_ips||[]).length&&`목적지 ${g.dst_ips.map(x=>esc(x.replace(/\/32$/,''))).join(', ')}`,(g.rows||[]).length&&`표 행 ${g.rows.map(esc).join(', ')}`].filter(Boolean);
    return bits.length?`<div class="mut" style="font-size:12px;margin-top:6px">${bits.join(' · ')}</div>`:''};
  const g0=G[gi0];
  const dom=p.domains.map(d=>`<li><b>${esc(d.domain)}</b> — ${d.registered.length?`메타 데이터에 등록됨 (${d.registered.slice(0,3).map(r=>esc(r.sg)).join(', ')})`:d.candidates.length?`후보 SG ${d.candidates.length}곳 (태그 추가 가능)`:'메타 데이터에서 찾지 못함'} <button type="button" class="tk-dom" data-d="${esc(d.domain)}">도메인 조회</button></li>`).join('');
  const stepBadge=s=>{const on=s.on||(s.opt&&$(s.opt)&&$(s.opt).checked);return `<span class="badge ${on?'b-chg':'b-pending'}" style="${on?'':'opacity:.55'}">${on?'✓ ':''}${esc(s.label)}${s.opt?(on?' (선택됨)':' (끔)'):''}</span>`};
  const html=`<div><b>${esc(p.key)}</b> ${esc(p.summary)} <span class="badge b-pending">${esc(p.status||'-')}</span> <a href="${esc(p.url)}" target="_blank" rel="noopener">Jira 에서 열기</a></div>
    ${q.warnings.length?`<div class="warnbox" style="margin:8px 0"><b>확인하세요</b><ul>${q.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul></div>`:''}
    ${G.length>1?`<div style="margin-top:8px"><label class="f">요청 묶음 (한 번에 한 묶음씩 처리합니다)<select id="tk-grp">${G.map((g,i)=>`<option value="${i}" ${i===gi0?'selected':''}>${esc(gname(g,i))}</option>`).join('')}</select></label></div>`:''}
    <div id="tk-info">${infoHtml(g0)}</div>
    <div class="row" style="align-items:flex-start;gap:14px;margin-top:8px">
      <label class="f" style="flex:1;min-width:230px">출발지 IP (줄바꿈/쉼표)<textarea id="tk-ips" rows="5">${esc(g0.ips.join('\n'))}</textarea></label>
      <div style="flex:1;min-width:230px"><label class="f">포트 (예: 443, 8080-8090)<input type="text" id="tk-ports" value="${esc(portTxt(g0))}"></label>
        <div class="row" style="margin-top:8px"><label class="f">작업<select id="tk-act"><option value="add" ${g0.action!=='del'?'selected':''}>규칙 추가</option><option value="del" ${g0.action==='del'?'selected':''}>규칙 삭제 (IP 기준)</option></select></label>
        <label class="f">프로토콜<select id="tk-proto"><option ${g0.protocol==='TCP'?'selected':''}>TCP</option><option ${g0.protocol==='UDP'?'selected':''}>UDP</option></select></label>
        <label class="f">방향<select id="tk-dir"><option value="ingress" ${q.direction==='ingress'?'selected':''}>인바운드</option><option value="egress" ${q.direction==='egress'?'selected':''}>아웃바운드</option></select></label></div></div></div>
    <div style="margin-top:8px"><b>대상 SG</b> <span class="mut" id="tk-sgmsg" style="font-size:12px">${(g0.suggested||[]).length?'티켓 내용으로 찾은 후보를 골라 두었습니다. 맞는지 확인하세요':'자동으로 고르지 못했습니다. 직접 선택하세요'}</span></div>
    <div class="dlbox" id="tk-sgs" style="max-height:170px;width:100%">${sgHtml(g0)}</div>
    ${dom?`<div style="margin-top:8px"><b>티켓에 나온 도메인</b> <span class="mut" style="font-size:12px">(메타 데이터 비교)</span><ul style="margin:4px 0">${dom}</ul></div>`:''}
    <div style="margin-top:8px"><b>진행 단계</b> <span class="mut" style="font-size:12px">${runNow?'실행 확인 창에서 한 번 더 확인합니다':'마법사에 채운 뒤 직접 실행합니다'} · apply/Jira 는 빠른 작업 카드의 체크박스를 따릅니다</span>
      <div class="row" style="gap:6px;margin-top:4px;flex-wrap:wrap">${AUTO_STEPS.map(stepBadge).join('')}</div></div>`;
  const res=await showModal('Jira 티켓에서 채우기',html,runNow?'채우고 실행 확인':'마법사에 채우기','취소',{wide:'ticket',onMount:m=>{
    m.querySelectorAll('.tk-dom').forEach(b=>b.onclick=()=>openDomainLookup(b.dataset.d));
    const sel=m.querySelector('#tk-grp');if(sel)sel.onchange=()=>{const g=G[+sel.value];
      m.querySelector('#tk-ips').value=g.ips.join('\n');m.querySelector('#tk-ports').value=portTxt(g);m.querySelector('#tk-proto').value=g.protocol;m.querySelector('#tk-act').value=g.action==='del'?'del':'add';
      m.querySelector('#tk-info').innerHTML=infoHtml(g);m.querySelector('#tk-sgs').innerHTML=sgHtml(g);
      m.querySelector('#tk-sgmsg').textContent=(g.suggested||[]).length?'티켓 내용으로 찾은 후보를 골라 두었습니다. 맞는지 확인하세요':'자동으로 고르지 못했습니다. 직접 선택하세요'};
  },collect:m=>({gi:m.querySelector('#tk-grp')?+m.querySelector('#tk-grp').value:0,act:m.querySelector('#tk-act').value,ips:m.querySelector('#tk-ips').value,ports:m.querySelector('#tk-ports').value.trim(),
    proto:m.querySelector('#tk-proto').value,dir:m.querySelector('#tk-dir').value,targets:[...m.querySelectorAll('.tk-sg:checked')].map(c=>c.value)})});
  if(!res)return null;
  const pl=parsePortList(res.ports,'');if(!pl||!pl.length)return toast('포트 형식이 올바르지 않습니다 (예: 443, 8080-8090)',true);
  const ips=parseIps(res.ips);if(ips.bad.length)return toast('IP 형식 오류: '+ips.bad.join(', '),true);if(!ips.ok.length)return toast('출발지 IP 를 입력하세요',true);
  if(!res.targets.length)return toast('대상 SG 를 하나 이상 선택하세요',true);
  const g=G[res.gi]||g0,c=$('#wzcard');c.open=true;S.wzOpen=true;
  $('#wz-act').value=res.act;$('#wz-ticket').value=p.key;$('#wz-dir').value=res.dir;$('#wz-proto').value=res.proto;$('#wz-from').value=res.ports;$('#wz-to').value='';$('#wz-ips').value=ips.ok.join('\n');$('#wz-src').value='';$('#wz-sum').value='';
  if(res.act==='del'){$('#wz-din').checked=res.dir==='ingress';$('#wz-dout').checked=res.dir==='egress'}
  S.wzJira={key:p.key,purpose:g.purpose||'',period:g.period||''};
  S.wzSel=new Set(res.targets);$('#wz-sgq').value='';$('#wz-act').dispatchEvent(new Event('change'));
  $('#wz-sgs').querySelectorAll('.wz-sg').forEach(i=>i.checked=S.wzSel.has(i.value));$('#wz-ips').dispatchEvent(new Event('input'));
  if(runNow)return runWizard();
  c.scrollIntoView({block:'start'});toast('티켓 내용을 마법사에 채웠습니다. 확인 후 "검토 후 실행"을 누르세요');return{ok:true,filled:true}}

// 여러 티켓 일괄: 티켓 번호 목록을 읽어 (티켓 × 요청 묶음) 목록을 보여 주고, 고른 것을 차례로 '채우기 확인 → 실행 확인'으로 처리한다.
async function openTicketQueue(){
  if(!S.envId)return toast('환경을 먼저 선택하세요',true);
  if(!$('#wz-ticket'))return toast('작업 탭의 빠른 작업 카드에서 실행하세요',true);
  const e=env();let items=[];
  const html=`<div class="mut">환경 <b>${esc(e.env)}${e.label?' · '+esc(e.label):''}</b> 에서 처리합니다. 티켓 번호를 줄바꿈·쉼표로 적고 <b>읽기</b>를 누르면 티켓마다 요청 묶음이 나옵니다 (최대 10개).</div>
    <textarea id="tq-in" rows="4" style="width:100%;margin-top:6px" placeholder="ISRIR-70001&#10;ISRIR-70002"></textarea>
    <div class="row" style="margin:6px 0;align-items:center"><button type="button" id="tq-read" class="blue">읽기</button><span class="mut" id="tq-msg"></span></div>
    <div id="tq-list" style="max-height:38vh;overflow:auto"></div>
    <div class="warnbox" style="margin-top:8px">묶음마다 '채우기 확인 → 실행 확인' 창을 거치며, 앞 건이 끝나야 다음으로 넘어갑니다. 같은 폴더의 plan 은 apply 하거나 unlock 하기 전까지 잠기므로, 이어서 처리하려면 빠른 작업의 <b>apply 까지 진행</b>을 켜 두세요 (이 경우 plan 이 이상 없을 때만 apply 합니다).</div>`;
  const res=await showModal('여러 티켓 일괄 처리',html,'차례로 실행','취소',{wide:'tickets',onMount:m=>{
    const list=m.querySelector('#tq-list');
    const draw=()=>{list.innerHTML=items.length?`<table><thead><tr><th></th><th>티켓</th><th>상태</th><th>요청 묶음</th><th>확인</th></tr></thead><tbody>${items.map((x,i)=>x.error?`<tr><td></td><td>${esc(x.key)}</td><td colspan="3" style="color:var(--err)">${esc(x.error)}</td></tr>`
      :`<tr><td><input type="checkbox" class="tq-ck" data-i="${i}" checked></td><td class="nw">${esc(x.key)}</td><td class="nw">${esc(x.status||'-')}</td><td>${esc(x.label)}<div class="mut" style="font-size:12px">${esc(x.summary||'')}</div></td><td>${x.warn?`<span class="badge b-warn">경고 ${x.warn}</span>`:''}</td></tr>`).join('')}</tbody></table>`:''};
    m.querySelector('#tq-read').onclick=guard(async()=>{const keys=[...new Set(m.querySelector('#tq-in').value.toUpperCase().split(/[\s,;]+/).filter(Boolean))].slice(0,10);
      if(!keys.length)return toast('티켓 번호를 입력하세요',true);items=[];const msg=m.querySelector('#tq-msg');
      for(const k of keys){msg.textContent=`읽는 중... ${k}`;
        if(!/^[A-Z][A-Z0-9_]+-\d+$/.test(k)){items.push({key:k,error:'티켓번호 형식이 올바르지 않습니다'});continue}
        try{const p=await api('GET',`/api/jira/plan?key=${encodeURIComponent(k)}&env_id=${encodeURIComponent(S.envId)}&light=1`),G=(p.parsed.groups&&p.parsed.groups.length)?p.parsed.groups:[p.parsed];
          G.forEach((g,gi)=>items.push({key:k,gi,status:p.status,summary:p.summary,warn:gi===0?p.parsed.warnings.length:0,
            label:`${G.length>1?`묶음 ${gi+1}: `:''}${g.action==='del'?'[삭제] ':''}${(g.dst_ips||[]).map(x=>x.replace(/\/32$/,'')).join(', ')||'목적지 미상'} · ${g.protocol||'TCP'} ${(g.ports||[]).map(r=>r.from===r.to?r.from:r.from+'-'+r.to).join(', ')||'-'} · 출발지 ${(g.ips||[]).length}개`}))}
        catch(err){items.push({key:k,error:err.message.split('\n')[0]})}}
      msg.textContent=`${items.filter(x=>!x.error).length}건 읽음`;draw()})},
    collect:m=>items.filter((x,i)=>!x.error&&m.querySelector(`.tq-ck[data-i="${i}"]`)&&m.querySelector(`.tq-ck[data-i="${i}"]`).checked)});
  if(!res||!res.length)return;
  const log=[];
  for(let i=0;i<res.length;i++){const it=res[i];
    if(i>0&&!await showModal('일괄 처리',`<div>다음: <b>${esc(it.key)}</b> (${i+1}/${res.length}) — ${esc(it.label)}</div><div class="mut" style="margin-top:6px">지금까지: ${log.map(x=>`${esc(x.key)} ${x.ok?(x.applied?'✅ apply 까지':'✅ plan 까지'):'⏸ 안 끝남'}`).join(' · ')||'-'}</div>`,'진행','중단'))break;
    $('#wz-ticket').value=it.key;
    const r=await ticketFillWizard(true,{key:it.key,group:it.gi});
    log.push({key:it.key,ok:!!(r&&r.ok),applied:!!(r&&r.applied)});
    if(!(r&&r.ok)&&i<res.length-1&&!await showModal('일괄 처리',`<div><b>${esc(it.key)}</b> 은(는) 끝나지 않았습니다 (취소했거나 중간에 멈춤). 나머지 ${res.length-1-i}건을 계속할까요?</div>`,'계속','중단'))break}
  toast(`일괄 처리를 마쳤습니다: ${log.filter(x=>x.ok).length}/${res.length}건 진행 (${log.filter(x=>x.applied).length}건 apply 까지)`,log.some(x=>!x.ok),8000)}

// 요청 양식: 요청자가 티켓 설명에 붙여 넣는 표준 표. 도구가 그대로 읽는다
async function openRequestTemplate(){
  const t=await api('GET','/api/jira/template');
  const html=`<div class="mut" style="margin-bottom:6px">요청자가 Jira 티켓 설명에 붙여 넣는 표준 양식입니다. <b>양식 복사</b>를 누른 뒤 티켓 설명 칸에 붙여 넣으면 표로 들어갑니다. 도구의 <b>Jira 티켓에서 채우기</b>는 이 표를 읽어, <b>Source IP</b>(허용할 출발지)를 소스로, <b>Destination IP</b>(서버)로 대상 SG 를 찾고, <b>Service Port</b>(예: <code>443 TCP</code>, <code>8080-8090 TCP</code>)로 규칙을 만듭니다.</div>
    <div class="row" style="margin:6px 0"><button type="button" class="blue" id="tpl-copy">양식 복사 (Jira 에 붙여 넣기)</button><button type="button" id="tpl-copy-t">텍스트로 복사 (Excel 등)</button></div>
    <div style="overflow:auto;max-height:44vh;border:1px solid var(--border);padding:8px">${t.html}</div>
    <div class="mut" style="font-size:12px;margin-top:6px">목적지·포트·구분(등록/삭제)이 다른 행은 별도 묶음으로 나뉩니다. 한 칸에 IP 를 여러 개 적으려면 줄바꿈으로 구분하세요. 구분에 '삭제'를 적으면 규칙 삭제 작업으로 채워집니다. 예시(예시/eg) 행은 읽지 않습니다.</div>`;
  await showModal('요청 양식',html,'닫기',null,{hideCancel:true,wide:'template',onMount:m=>{
    m.querySelector('#tpl-copy').onclick=async()=>{try{
      if(window.ClipboardItem&&navigator.clipboard.write)await navigator.clipboard.write([new ClipboardItem({'text/html':new Blob([t.html],{type:'text/html'}),'text/plain':new Blob([t.text],{type:'text/plain'})})]);
      else await navigator.clipboard.writeText(t.text);toast('요청 양식을 복사했습니다. Jira 설명 칸에 붙여 넣으세요')}catch(e){toast('복사하지 못했습니다: '+e.message,true)}};
    m.querySelector('#tpl-copy-t').onclick=async()=>{try{await navigator.clipboard.writeText(t.text);toast('탭으로 구분한 텍스트를 복사했습니다')}catch(e){toast('복사하지 못했습니다: '+e.message,true)}}}})}

// apply 모달에 plan 이 바꾸는 리소스와 자동 apply 조건 검사 결과를 보여 준다
function impactHtml(ps){if(!ps)return'';const im=ps.impact||{},n=k=>(im[k]||[]).length;
  const list=(t,k)=>n(k)?`<div><b>${t} ${n(k)}</b> <span class="mut">${im[k].slice(0,4).map(esc).join(', ')}${n(k)>4?' …':''}</span></div>`:'';
  const res=list('만들기','created')+list('변경','updated')+list('삭제','destroyed')+list('교체','replaced');
  const chk=(ps.checks||[]).map(c=>`<div>${c.ok?'✓':c.block?'✗':'△'} ${esc(c.label)}${c.detail?` <span class="mut">(${esc(c.detail)})</span>`:''}</div>`).join('');
  return res||chk?`<div style="margin-top:6px;font-size:12px">${res}${chk}</div>`:''}

// ---- 완료 처리(C): apply 가 끝난 뒤 Jira 에 코멘트를 남기고 상태를 전환한다
// 빠른 작업에서 '완료 시 Jira 코멘트·상태 전환'을 켰고 전환 이름을 기억해 둔 경우에는 묻지 않고 실행하고, 그 밖에는 내용을 보여 주고 확인을 받는다.
async function jiraFinishSend(key,comment,tid,tr){
  try{const r=await api('POST','/api/jira/finish',{key,comment,transition_id:tid});
    if(tid&&r.transitioned)ls.set('jiraDoneTr',r.transitioned);
    addHist('Jira 완료 처리 → '+key,(comment||'(코멘트 없음)')+(r.transitioned?`\n→ 상태 전환: ${r.transitioned}`:''),{kind:'apply',headline:`✓ Jira${r.commented?' 코멘트':''}${r.transitioned?' · 상태 → '+r.transitioned:''}`});
    toast(`Jira ${key} 에 기록했습니다${r.transitioned?` (상태 → ${r.transitioned})`:''}`,false,6000);return true}
  catch(err){addHist('Jira 완료 처리 안 됨 → '+key,err.message,{kind:'apply',state:'warn',headline:'⚠ Jira 완료 처리 안 됨'});toast('Jira 완료 처리를 하지 못했습니다: '+err.message,true,10000);return false}}
async function jiraFinishFlow(envId,fallbackTicket){
  if(!(S.jira&&S.jira.enabled))return;
  const ctx=(S.jiraCtx||{})[envId];if(S.jiraCtx)delete S.jiraCtx[envId];
  if(ctx&&ctx.on===false)return;
  const key=String((ctx&&ctx.ticket)||fallbackTicket||'').toUpperCase();
  if(!/^[A-Z][A-Z0-9_]+-\d+$/.test(key))return;
  let tr;try{tr=await api('GET','/api/jira/transitions?key='+encodeURIComponent(key))}
  catch(err){addHist('Jira 완료 처리 안 됨 → '+key,err.message,{kind:'apply',state:'warn',headline:'⚠ Jira 에 연결하지 못함'});toast('Jira 완료 처리를 하지 못했습니다: '+err.message,true,9000);return}
  const iid=(ctx&&ctx.iid)||(S.mr[envId]||{}).iid,mrUrl=(ctx&&ctx.url)||(S.mr[envId]||{}).url||'';let n={};
  if(iid){try{n=(await api('GET',`/api/env/${envId}/atlantis/plan-status?iid=${encodeURIComponent(iid)}`)).plan||{}}catch(err){/* plan 수치는 없어도 된다 */}}
  const ce=S.cfg.environments.find(x=>x.id===envId),when=new Date().toLocaleString('ko-KR',{hour12:false});
  const text=[`[ACL 적용 완료] ${(ctx&&ctx.summary)||tr.summary||''}`.trim(),ce?`- 환경: ${[ce.group,ce.env,ce.label].filter(Boolean).join(' · ')}`:'',mrUrl?`- MR: ${mrUrl}`:'',
    ctx&&ctx.purpose?`- 용도: ${ctx.purpose}`:'',n.add!=null?`- plan: 추가 ${n.add} / 변경 ${n.change} / 삭제 ${n.destroy}${n.replace?` / 교체 ${n.replace}`:''}`:'',`- apply: 완료 (${when})`,S.account?`- 처리: ${S.account}`:''].filter(Boolean).join('\n');
  const mem=ls.get('jiraDoneTr',''),rem=tr.transitions.find(t=>t.name===mem);
  if(ctx&&ctx.on&&rem){await jiraFinishSend(key,text,rem.id,tr);return}
  const guess=rem||tr.transitions.find(t=>/완료|done|resolve|close|complete/i.test(t.name+' '+t.to));
  const html=`<div><b>${esc(key)}</b> ${esc(tr.summary)} <span class="badge b-pending">${esc(tr.status||'-')}</span></div>
    <label class="chk" style="margin-top:8px"><input type="checkbox" id="jf-c" checked> 코멘트 남기기</label>
    <textarea id="jf-t" rows="7" style="width:100%">${esc(text)}</textarea>
    <div class="row" style="margin-top:8px;align-items:center;gap:8px"><b>상태 전환</b><select id="jf-s"><option value="">(전환 안 함)</option>${tr.transitions.map(t=>`<option value="${esc(t.id)}" ${guess&&guess.id===t.id?'selected':''}>${esc(t.name)}${t.to?' → '+esc(t.to):''}</option>`).join('')}</select></div>
    ${tr.transitions.length?'':'<div class="mut" style="margin-top:6px">지금 할 수 있는 상태 전환이 없습니다 (이미 완료 상태일 수 있습니다)</div>'}
    <div class="mut" style="font-size:12px;margin-top:6px">Jira 에 실제로 기록됩니다. 고른 전환 이름은 기억해 두었다가, 빠른 작업의 "완료 시 Jira 코멘트·상태 전환"을 켠 경우 다음부터 묻지 않고 같은 이름의 전환을 실행합니다.</div>`;
  await waitNoModal('Jira 완료 처리');
  const res=await showModal('Jira 완료 처리 — apply 가 끝났습니다',html,'Jira 에 기록','건너뛰기',{wide:'jirafinish',collect:m=>({c:m.querySelector('#jf-c').checked,text:m.querySelector('#jf-t').value,tid:m.querySelector('#jf-s').value})});
  if(!res)return;
  if(!(res.c&&res.text.trim())&&!res.tid)return toast('남길 코멘트나 전환할 상태가 없어 Jira 에 기록하지 않았습니다');
  await jiraFinishSend(key,res.c?res.text:'',res.tid,tr)}

// 도메인 조회: 메타 데이터(SG 태그·별명)와 비교하고, 메타 데이터가 있는 SG 의 태그에 도메인을 추가한다
const looksDomain=t=>/^[a-z0-9][a-z0-9.-]*\.[a-z][a-z0-9-]{1,23}$/i.test(String(t||'').trim())&&!/^[\d.]+$/.test(String(t||'').trim());
async function openDomainLookup(domain){
  toast('도메인을 조회하는 중... (DNS 확인 포함)',false,15000);
  let r;try{r=await api('GET','/api/domain/lookup?d='+encodeURIComponent(domain))}finally{$('#toast').style.display='none'}
  const tags=x=>(x.tags||[]).map(t=>(t.type?t.type+':':'')+t.value).join(', ')||'-';
  const row=x=>`<tr><td>${esc(x.env)}</td><td>${esc(x.sg)}${x.sg_id?`<div class="mut" style="font-size:11px">${esc(x.sg_id)}</div>`:''}</td><td>${esc(x.alias)}</td><td>${esc(tags(x))}</td>`;
  const cur=(S.meta&&S.meta.envs&&S.meta.envs[S.envId]&&S.meta.envs[S.envId].sgs)||{};
  const manual=Object.keys(cur).filter(n=>!r.candidates.some(c=>c.env_id===S.envId&&c.sg===n)&&!r.registered.some(c=>c.env_id===S.envId&&c.sg===n));
  const html=`<div><b>${esc(r.domain)}</b> — DNS: ${r.ips.length?r.ips.map(i=>`<code>${esc(i)}</code>`).join(', '):`<span class="mut">${esc(r.dns_error||'결과 없음')}</span>`}</div>
    ${r.registered.length?`<div class="warnbox ok" style="margin:8px 0"><b>메타 데이터에 이미 등록되어 있습니다</b> (SG 태그에 이 도메인이 있음)<table><thead><tr><th>환경</th><th>SG</th><th>별명</th><th>태그</th></tr></thead><tbody>${r.registered.map(x=>row(x)+'</tr>').join('')}</tbody></table></div>`:'<div class="mut" style="margin:8px 0">어느 SG 의 태그에도 이 도메인이 등록되어 있지 않습니다.</div>'}
    ${r.related.length?`<div style="margin:6px 0"><b>관련 도메인 태그</b> (상위/하위 도메인)<table><thead><tr><th>환경</th><th>SG</th><th>별명</th><th>태그</th><th>이유</th></tr></thead><tbody>${r.related.map(x=>row(x)+`<td>${esc(x.reason)}</td></tr>`).join('')}</tbody></table></div>`:''}
    ${r.candidates.length?`<div style="margin:6px 0"><b>태그를 추가할 후보 SG</b> (메타 데이터가 있는 SG)<table><thead><tr><th>환경</th><th>SG</th><th>별명</th><th>태그</th><th>이유</th><th></th></tr></thead><tbody>${r.candidates.map((x,i)=>row(x)+`<td>${esc(x.reason)}</td><td><button type="button" class="blue dm-add" data-i="${i}">태그에 추가</button></td></tr>`).join('')}</tbody></table></div>`:'<div class="mut" style="margin:6px 0">DNS 결과나 이름으로 맞는 SG 를 찾지 못했습니다.</div>'}
    ${manual.length?`<div class="row" style="margin-top:8px;gap:8px;align-items:center"><span>현재 환경에서 직접 선택:</span><select id="dm-man" style="max-width:300px">${manual.map(n=>`<option>${esc(n)}</option>`).join('')}</select><button type="button" id="dm-man-go">태그에 추가</button></div>`:''}
    <div class="mut" style="font-size:12px;margin-top:8px">메타 데이터에 이미 있는 SG 의 태그에만 추가합니다(SG 를 새로 만들지 않음). 태그는 <code>domain:${esc(r.domain)}</code> 형태로 저장되며, 메타 데이터 화면에서 고칠 수 있습니다.</div>`;
  await showModal('도메인 조회 — 메타 데이터 비교',html,'닫기',null,{hideCancel:true,wide:'domain',onMount:o=>{
    const add=guard(async(env_id,sg)=>{const a=await api('POST','/api/domain/apply',{domain:r.domain,env_id,sg});
      S.meta=await api('GET','/api/meta');if(!S.meta.envs)S.meta.envs={};toast(a.already?'이미 태그에 있습니다':`${sg} 의 태그에 ${r.domain} 을(를) 추가했습니다`);
      o.querySelector('.mo').click();setTimeout(()=>openDomainLookup(r.domain),50)});
    o.querySelectorAll('.dm-add').forEach(b=>b.onclick=()=>{const c=r.candidates[+b.dataset.i];add(c.env_id,c.sg)});
    const mg=o.querySelector('#dm-man-go');if(mg)mg.onclick=()=>add(S.envId,o.querySelector('#dm-man').value)}})}
