// ---------- AWS 에서 메타 데이터 가져오기 (AWS CLI, 조회 전용)
// 흐름: 프로필/리전 선택 → 조회(미리보기) → 확인 후 메타 데이터에 반영.
// AWS 로그인이 필요하면 안내하고(로그인 창 열기 → 승인 대기 → 자동 재시도), 권한이 없으면(Access Denied) 권한 요청이 필요하다고 따로 알려준다.
const AWS_STATUS={new:['신규','b-ok'],same:['동일','b-pending'],diff:['AWS와 다름','b-warn'],missing:['AWS에서 못 찾음','b-warn'],ambiguous:['후보 여러 개','b-warn']};

async function awsWaitLogin(profile){
  let timer,done=false;
  const p=showModal('AWS 로그인 승인 대기',`<div>브라우저에 열린 AWS 로그인 창에서 <b>승인(Allow)</b>을 눌러 주세요.</div>
    <div class="mut" style="margin-top:6px">프로필: <code>${esc(profile)}</code> — 승인되면 이 창이 자동으로 닫히고 조회를 이어갑니다 (최대 5분).</div><div id="aw-st" class="mut" style="margin-top:8px" role="status">승인 확인 중...</div>`,'닫기',null,
    {hideCancel:true,onMount:o=>{const t0=Date.now();timer=setInterval(async()=>{
      try{await api('GET','/api/aws/whoami?profile='+encodeURIComponent(profile));done=true;clearInterval(timer);o.querySelector('.mo').click()}
      catch(e){if(Date.now()-t0>5*60*1000){clearInterval(timer);const st=o.querySelector('#aw-st');if(st)st.textContent='시간이 지났습니다. 다시 시도하세요.'}}},3000)}});
  await p;clearInterval(timer);return done;
}

// 로그인 안내 → 로그인 창 열기 → 승인 대기. 로그인되면 true
async function awsLoginFlow(profile,msg){
  const go=await showModal('AWS 로그인이 필요합니다',`<div class="warnbox danger">${esc(msg)}</div>
    <div style="margin-top:8px">사용자가 직접 승인해야 합니다. 아래 버튼을 누르면 브라우저에 AWS 로그인 창이 열립니다.</div>
    <div class="mut" style="margin-top:6px">직접 하려면 터미널에서: <code>aws sso login --profile ${esc(profile)}</code></div>`,'로그인 창 열기','취소');
  if(!go)return false;
  await api('POST','/api/aws/login',{profile});
  return await awsWaitLogin(profile);
}

async function awsFetch(profile,region){
  for(let attempt=0;attempt<3;attempt++){
    try{return await api('POST',`/api/env/${S.envId}/aws/fetch`,{profile,region})}
    catch(e){
      const k=e.data&&e.data.aws_error;
      if(k==='login_needed'){
        if(!await awsLoginFlow(profile,e.message))return null;
        continue;   // 로그인되면 같은 조회를 다시 시도
      }
      const why={denied:'권한이 없습니다 (Access Denied)',profile_missing:'AWS 프로필을 찾을 수 없습니다',wrong_account:'다른 계정의 프로필입니다',cli_missing:'AWS CLI 가 없습니다',ssl_error:'회사 보안 인증서 문제 (SSL)'}[k]||'AWS 조회 실패';
      await showModal(why,`<div class="warnbox danger">${esc(e.message)}</div>${k==='denied'?`<div class="mut" style="margin-top:8px">프로필 <code>${esc(profile)}</code> 에 EC2 조회 권한(<code>ec2:Describe*</code>)이 필요합니다. 로그인을 다시 해도 해결되지 않으니 AWS 관리자에게 권한을 요청하세요.</div>`:''}
        ${e.data&&e.data.detail?`<details style="margin-top:8px"><summary>AWS 원문</summary><pre style="white-space:pre-wrap">${esc(e.data.detail)}</pre></details>`:''}`,'확인',null,{hideCancel:true});
      return null;
    }
  }
  return null;
}

// 별명을 리소스 IP 로 채운다: IP 하나면 "10.0.0.1", 여럿이면 "10.0.0.1, 10.0.0.2".
// 별명 끝에 이미 IP 목록이 있으면 그 부분만 새 값으로 바꾸고, 앞에 직접 쓴 글은 그대로 둔다 ("web, 10.0.0.1" → "web, 새 IP들"). 너무 많으면 앞의 10개만 + "외 N개".
const ALIAS_IP_TAIL=/(?:^|\s*,\s*|\s+)\d{1,3}(?:\.\d{1,3}){3}(?:\s*,\s*\d{1,3}(?:\.\d{1,3}){3})*(?:\s*외\s*\d+개)?\s*$/;
function aliasWithIps(alias,ips){
  let base=String(alias||'').replace(/\s*\[IP:[^\]]*\]\s*$/,'');   // 이전 버전의 [IP: …] 표기도 걷어낸다
  base=base.replace(ALIAS_IP_TAIL,'').replace(/[\s,]+$/,'').trim();
  if(!ips||!ips.length)return String(alias||'');                    // IP 를 못 찾았으면 별명을 건드리지 않는다
  const shown=ips.slice(0,10).join(', ')+(ips.length>10?` 외 ${ips.length-10}개`:'');
  return(base?base+', ':'')+shown;
}
// 조회 결과를 메타 데이터(S.meta)에 합친다. overwrite=false 면 이미 입력된 값은 그대로 두고 빈 곳/없는 항목만 채운다
function mergeAwsIntoMeta(r,overwrite,withIps){
  const em=S.meta.envs[S.envId]||(S.meta.envs[S.envId]={});em.sgs=em.sgs||{};const cnt={sg:0,sub:0,alias:0};
  r.sgs.forEach(x=>{if(!x.sg_id)return;const m=em.sgs[x.name]||(em.sgs[x.name]={alias:'',sg_id:'',tags:[]});
    if(!m.sg_id||(overwrite&&m.sg_id!==x.sg_id)){m.sg_id=x.sg_id;cnt.sg++}
    if(withIps&&x.ips&&x.ips.length){const a=aliasWithIps(m.alias,x.ips);if(a!==(m.alias||'')){m.alias=a;cnt.alias++}}});
  const cur=(em.subnets&&em.subnets.length)?em.subnets:[...(em.vpc_cidrs||[]).map(c=>({ipv4_cidr:c})),...(em.nat_ips||[]).map(n=>({nat_ip:n}))].filter(x=>Object.keys(x).length);
  if(overwrite||!cur.length){em.subnets=r.subnets.map(x=>({...x}));cnt.sub=r.subnets.length}
  else{const have=new Set(cur.map(x=>(x.vpc_id||'')+'|'+(x.ipv4_cidr||'')));const add=r.subnets.filter(x=>!have.has(x.vpc_id+'|'+x.ipv4_cidr));
    em.subnets=[...cur,...add.map(x=>({...x}))];cnt.sub=add.length}
  return cnt;
}

const awsFetchModal=guard(async()=>{
  if(!S.envId)return toast('환경을 먼저 선택하세요',true);
  const c=await api('GET',`/api/env/${S.envId}/aws/context`);
  if(!c.cli)return showModal('AWS CLI 가 필요합니다','<div>이 PC 에 AWS CLI(v2)가 설치되어 있지 않습니다. 설치한 뒤 <code>aws configure sso</code> 로 프로필을 만들고 다시 시도하세요.</div>','확인',null,{hideCancel:true});
  if(!c.profiles.length)return showModal('AWS 프로필이 없습니다','<div><code>~/.aws/config</code> 에 프로필이 없습니다. <code>aws configure sso</code> 로 프로필을 만든 뒤 다시 시도하세요.</div>','확인',null,{hideCancel:true});
  let pre=c.saved||(c.suggestions[0]||''),autoMsg=c.saved?`저장된 프로필 <b>${esc(c.saved)}</b> 을 사용합니다.`:'';
  if(!c.saved&&c.region){   // 저장된 프로필이 없으면 자동으로 맞는 계정을 찾는다 (이 환경의 SG 이름이 보이는 계정)
    for(let round=0;round<2;round++){
      toast('프로필 자동 매칭 중... (보통 10초 안팎, 맞는 계정을 못 찾으면 최대 1분)',false,90000);
      let d=null;try{d=await api('POST',`/api/env/${S.envId}/aws/detect`,{region:c.region})}catch(e){autoMsg='자동 매칭 실패: '+esc(e.message);break}
      $('#toast').style.display='none';
      if(d.best){pre=d.best.profile;autoMsg=`✅ 자동 매칭: <b>${esc(d.best.profile)}</b> ${d.best.account_id?`(계정 ${esc(d.best.account_id)}) `:''}— 이 환경의 SG ${d.best.found}/${d.best.total}개를 찾았습니다${d.best.ambiguous?' (같은 결과의 계정이 더 있어 가장 알맞은 것을 골랐습니다)':''}.`;break}
      const lg=d.results.filter(x=>x.status==='login_needed');
      if(round===0&&d.results.length&&lg.length===d.results.length){   // 전부 로그인 필요 → 한 번 로그인하고 다시 찾기
        if(!await awsLoginFlow(lg[0].profile,'AWS 로그인이 필요해서 프로필을 자동으로 찾지 못했습니다.'))break;continue}
      autoMsg=d.note?esc(d.note):`자동으로 맞는 계정을 찾지 못했습니다${lg.length?` (로그인이 필요해 확인하지 못한 프로필 ${lg.length}개)`:''}. 프로필을 직접 선택하세요.`;break}
    $('#toast').style.display='none';
  }
  const sel=await showModal('AWS 에서 가져오기',`${autoMsg?`<div class="warnbox" style="margin-bottom:8px" role="status">${autoMsg}</div>`:''}<div class="mut" style="margin-bottom:8px">계정 폴더 <b>${esc(c.account||'-')}</b> · 환경 <b>${esc(env().env)}</b>. AWS 에서 SG ID, 서브넷(이름/CIDR/VPC ID), NAT IP 를 <b>읽기만</b> 하고, 확인 후에 메타 데이터에 반영합니다.</div>
    <label class="f">프로필 / 계정 검색<input type="text" id="aw-q" placeholder="프로필 이름, 계정 ID, 역할로 검색 (예: lord, 3705)" autocomplete="off" aria-describedby="aw-cnt"></label>
    <select id="aw-p" size="8" style="width:100%" aria-label="AWS 프로필 목록"></select><div class="mut" id="aw-cnt" style="font-size:12px;margin:2px 0 8px" role="status"></div>
    <label class="f">리전<input type="text" id="aw-r" list="aw-rl" value="${esc(c.region)}" placeholder="ap-northeast-2 또는 apne2" autocomplete="off"></label>
    <datalist id="aw-rl">${(c.regions||[]).map(x=>`<option value="${esc(x.code)}">${esc(x.name)}</option>`).join('')}</datalist>
    ${c.region?'':'<div class="mut" style="font-size:12px">이 환경 경로에서 리전을 알 수 없습니다. 리전을 직접 입력하세요 (예: 홍콩 <code>ap-east-1</code>, 도쿄 <code>ap-northeast-1</code>, 버지니아 <code>us-east-1</code> — 짧은 코드 <code>ape1</code>, <code>apne1</code> 도 됩니다).</div>'}
    <div class="mut" style="font-size:12px">성공하면 이 환경 그룹에서 쓸 프로필을 이 PC 에 기억합니다 (local.json, 공유되지 않음).</div>`,'조회','취소',
    {onMount:o=>{
      const info=c.profile_info||{},sel=o.querySelector('#aw-p'),q=o.querySelector('#aw-q'),cnt=o.querySelector('#aw-cnt');
      const label=p=>`${p}${info[p]&&info[p].account_id?'  ·  '+info[p].account_id:''}${info[p]&&info[p].role?'  ·  '+info[p].role:''}${p===c.saved?'  (저장됨)':(c.suggestions.includes(p)?'  (추천)':'')}`;
      const draw=()=>{const words=q.value.toLowerCase().split(/\s+/).filter(Boolean);
        const shown=c.profiles.filter(p=>words.every(w=>label(p).toLowerCase().includes(w)));
        if(shown.length&&!shown.includes(S._awCur))S._awCur=shown[0];
        sel.innerHTML=shown.map(p=>`<option value="${esc(p)}" ${p===S._awCur?'selected':''}>${esc(label(p))}</option>`).join('');
        cnt.textContent=`${shown.length} / ${c.profiles.length}개 표시`+(shown.length?'':' — 일치하는 프로필이 없습니다');};
      // 리전을 입력한 뒤 '프로필 자동 찾기' 로 이 환경의 SG 가 보이는 계정을 찾아 선택한다
      o.querySelector('#aw-r').closest('label').insertAdjacentHTML('afterend','<div class="row" style="margin:6px 0"><button id="aw-auto" type="button">이 리전에서 프로필 자동 찾기</button><span class="mut" id="aw-am" role="status"></span></div>');
      o.querySelector('#aw-auto').onclick=async()=>{const am=o.querySelector('#aw-am');const rg=o.querySelector('#aw-r').value.trim();
        if(!rg){am.textContent='리전을 먼저 입력하세요';return}
        am.textContent='찾는 중... (보통 10초 안팎)';
        try{const d=await api('POST',`/api/env/${S.envId}/aws/detect`,{region:rg});
          if(d.best){S._awCur=d.best.profile;q.value='';draw();am.textContent=`✅ ${d.best.profile} — SG ${d.best.found}/${d.best.total}개 일치`}
          else{const lg=(d.login_needed||[]).length;am.textContent=d.note||`맞는 계정을 못 찾았습니다${lg?` (로그인이 필요해 확인 못 한 프로필 ${lg}개 — 로그인 후 다시 시도)`:' (리전이 맞는지, 프로필이 있는지 확인하세요)'}`}}
        catch(e){am.textContent=e.message}};
      S._awCur=pre;draw();
      sel.onchange=()=>{S._awCur=sel.value};
      q.oninput=draw;
      q.onkeydown=e=>{if(e.key==='ArrowDown'){e.preventDefault();sel.focus()}else if(e.key==='Enter'){e.preventDefault();const f=sel.options[0];if(f){S._awCur=f.value;draw()}}};
      setTimeout(()=>q.focus(),0)},
     collect:o=>({profile:o.querySelector('#aw-p').value||S._awCur||'',region:o.querySelector('#aw-r').value.trim()})});
  if(!sel)return;
  toast('AWS 에서 조회 중... (AWS CLI 특성상 5~10초 걸립니다)',false,60000);
  const r=await awsFetch(sel.profile,sel.region);
  $('#toast').style.display='none';
  if(!r)return;
  api('POST','/api/aws/profile-map',{key:c.key,profile:sel.profile,region:r.region}).catch(()=>{});
  const stc={};r.sgs.forEach(x=>stc[x.status]=(stc[x.status]||0)+1);
  const res=await showModal('AWS 조회 결과 — 반영 전 확인',`<div class="mut">프로필 <code>${esc(r.profile)}</code> · 리전 <code>${esc(r.region)}</code> · VPC ${r.vpc_ids.map(v=>`<code>${esc(v)}</code>`).join(', ')||'-'}</div>
    ${r.note?`<div class="warnbox" style="margin-top:6px">${esc(r.note)}</div>`:''}
    <h4 style="margin:10px 0 4px">SG ID (${r.sgs.length}개: ${Object.keys(stc).map(k=>(AWS_STATUS[k]||[k])[0]+' '+stc[k]).join(' / ')})</h4>
    <div style="max-height:180px;overflow:auto"><table><thead><tr><th>SG</th><th>AWS SG ID</th><th>현재 메타</th><th>리소스 IP</th><th>상태</th></tr></thead><tbody>${r.sgs.map(x=>`<tr><td>${esc(x.name)}${x.aws_name?`<div class="mut" style="font-size:11px">AWS: ${esc(x.aws_name)}</div>`:''}</td><td>${esc(x.sg_id||(x.candidates||[]).join(', ')||'-')}</td><td>${esc(x.current||'-')}</td><td>${esc((x.ips||[]).length?aliasWithIps('',x.ips):'-')}</td><td><span class="badge ${(AWS_STATUS[x.status]||[0,''])[1]}">${esc((AWS_STATUS[x.status]||[x.status])[0])}</span></td></tr>`).join('')}</tbody></table></div>
    <h4 style="margin:10px 0 4px">서브넷 ${r.subnets.length}개 · VPC 대역 ${esc(r.vpc_cidrs.join(', ')||'-')} · NAT IP ${esc(r.nat_ips.join(', ')||'-')}</h4>
    <div style="max-height:160px;overflow:auto"><table><thead><tr><th>Subnet name</th><th>VPC ID</th><th>IPv4 CIDR</th><th>NAT IP</th></tr></thead><tbody>${r.subnets.map(x=>`<tr><td>${esc(x.subnet_name||'-')}</td><td>${esc(x.vpc_id)}</td><td>${esc(x.ipv4_cidr)}</td><td>${esc(x.nat_ip)}</td></tr>`).join('')}</tbody></table></div>
    <label style="display:block;margin-top:10px"><input type="checkbox" id="aw-ip" checked> 별명에 SG 를 쓰는 리소스의 IP 넣기 <span class="mut">(예: <code>10.0.0.1, 10.0.0.2</code> — 다시 가져오면 별명 끝의 IP 목록만 갱신하고, 앞에 직접 쓴 글은 그대로 둡니다)</span></label>
    <label style="display:block;margin-top:6px"><input type="checkbox" id="aw-ow"> 기존 값 덮어쓰기 <span class="mut">(체크하지 않으면 비어 있는 SG ID 와 없는 서브넷만 채웁니다)</span></label>
    <div class="mut" style="font-size:12px;margin-top:4px">태그는 AWS 에서 가져오지 않고 그대로 둡니다. 리소스 IP 는 SG 가 붙은 네트워크 인터페이스(EC2/ALB/RDS 등)의 사설·공인 IP 입니다.</div>`,'메타 데이터에 반영','취소',
    {collect:o=>({ow:o.querySelector('#aw-ow').checked,ip:o.querySelector('#aw-ip').checked})});
  if(!res)return;
  const n=mergeAwsIntoMeta(r,res.ow,res.ip);
  await api('PUT','/api/meta',S.meta);
  toast(`반영했습니다: SG ID ${n.sg}개, 서브넷 ${n.sub}개${res.ip?`, 별명(리소스 IP) ${n.alias}개`:''}`,false,6000);viewMeta();
});

// ---------- AWS 규칙 ↔ 저장소 파일 규칙 비교 보고서 (읽기 전용)
// AWS 인증이 되어 있으면 SG 마다 두 쪽 규칙을 비교해 보여주고, 되어 있지 않으면 '넘어간다'는 안내만 보여준다 (로그인은 사용자가 직접 한다).
const CMP_STATUS={same:['일치','b-pending'],diff:['다름','b-chg'],missing:['AWS에서 못 찾음','b-warn'],ambiguous:['후보 여러 개','b-warn'],file_error:['파일 읽기 실패','b-warn']};
function cmpCsv(r){
  const q=v=>'"'+String(v??'').replace(/"/g,'""')+'"',rows=[['SG','SG ID','구분','방향','프로토콜','포트','소스종류','소스','설명']];
  r.sgs.forEach(s=>{[['AWS에만 있음',s.aws_only],['파일에만 있음',s.file_only]].forEach(([k,list])=>(list||[]).forEach(x=>rows.push([s.name,s.sg_id,k,x.direction,x.protocol,x.port,x.source_type,x.source,x.description])))});
  return '\ufeff'+rows.map(x=>x.map(q).join(',')).join('\r\n')+'\r\n'}
// 지난 비교와 비교한 변화 (서버가 data/compare_history.json 에 남긴 기록 기준)
function cmpHistory(h){if(!h)return '';
  if(!h.previous)return '<div class="mut" style="margin:4px 0;font-size:12px">이번 결과를 기록했습니다. 다음 비교부터 지난 비교와의 변화를 알려 줍니다.</div>';
  const li=(l,t)=>l.length?`<details style="margin-top:4px"><summary>${t} ${l.length}건</summary><table><thead><tr><th>SG</th><th>구분</th><th>방향</th><th>프로토콜</th><th>포트</th><th>소스</th></tr></thead><tbody>${l.map(x=>`<tr><td>${esc(x.sg)}</td><td>${esc(x.side)}</td><td>${x.direction==='ingress'?'인':'아웃'}</td><td>${esc(x.protocol)}</td><td>${esc(x.port)}</td><td>${esc(x.source)}</td></tr>`).join('')}</tbody></table></details>`:'';
  return `<div class="warnbox ${h.new?'':'ok'}" style="margin:6px 0"><b>지난 비교(${esc(h.previous)}) 대비</b>: 새로 생긴 차이 <b>${h.new}</b>건 · 해소된 차이 <b>${h.resolved}</b>건 · 그대로 ${h.unchanged}건${li(h.new_items,'새로 생긴 차이')}${li(h.resolved_items,'해소된 차이')}</div>`}
async function awsCompareReport(){
  if(!S.envId)return toast('환경을 먼저 선택하세요',true);
  toast('AWS 와 비교하는 중... (AWS CLI 특성상 10~30초 걸릴 수 있습니다)',false,90000);
  let r;try{r=await api('POST',`/api/env/${S.envId}/aws/compare`,{})}finally{$('#toast').style.display='none'}
  awsPill.refresh(true);
  if(r.skipped){
    const login=r.reason==='login_needed'&&r.profile;
    const go=await showModal('AWS 인증이 없어 AWS 비교는 넘어갑니다',`<div class="warnbox">${esc(r.message)}</div>
      <div class="mut" style="margin-top:8px">AWS 에 로그인(자격인증)한 뒤 다시 실행하면 비교 보고서를 볼 수 있습니다. 위쪽 <b>AWS 자격인증</b> 표시가 주황색이면 인증된 상태입니다.</div>`,login?'로그인 안내 열기':'확인',login?'닫기':null,{hideCancel:!login});
    if(go&&login&&await awsLoginFlow(r.profile,r.message))return awsCompareReport();
    return}
  const e=env(),c=r.counts||{};
  const html=`<div class="mut">환경 <b>${esc(e.group)} · ${esc(e.env)}</b> · 프로필 <code>${esc(r.profile)}</code> · 리전 <code>${esc(r.region)}</code> · VPC ${r.vpc_ids.map(v=>`<code>${esc(v)}</code>`).join(', ')||'-'}</div>
    <div class="row" style="margin:6px 0;gap:12px">${Object.keys(CMP_STATUS).filter(k=>c[k]).map(k=>`<span><span class="badge ${CMP_STATUS[k][1]}">${CMP_STATUS[k][0]}</span> ${c[k]}</span>`).join('')}<span class="mut">AWS에만 있는 규칙 <b>${r.aws_only_total}</b> · 파일에만 있는 규칙 <b>${r.file_only_total}</b></span></div>
    ${cmpHistory(r.history)}
    <label style="display:block;margin:4px 0"><input type="checkbox" id="cm-only" checked> 일치하지 않는 SG 만 보기</label>
    <div id="cm-list"></div>
    <div class="mut" style="font-size:12px;margin-top:8px"><b>AWS에만 있음</b> = AWS 콘솔 등에서 직접 추가되었거나, 파일에서는 지웠지만 아직 apply 전인 규칙. <b>파일에만 있음</b> = 아직 apply 전이거나 다른 계정/VPC 의 SG. 파일은 지금 받아 둔 작업 폴더(브랜치) 기준이며, 설명·SG 이름 접두어 차이는 비교하지 않습니다.</div>
    <div class="row" style="margin-top:8px"><button id="cm-csv">CSV 다운로드</button><button id="cm-xlsx">엑셀(.xlsx) 다운로드</button><button id="cm-copy" title="AWS 에만 있는 규칙을 탭으로 구분된 표로 복사합니다. 파일에 반영할지 검토할 때 쓰세요 (자동으로 바꾸지는 않습니다)">AWS에만 있는 규칙 복사</button><span class="mut" id="cm-msg" role="status"></span></div>`;
  await showModal('AWS 규칙 비교 보고서',html,'닫기',null,{hideCancel:true,wide:'compare',onMount:o=>{
    const tbl=(title,list,total)=>list&&list.length?`<div style="margin:4px 0 2px"><b>${title}</b> ${total}건${total>list.length?` (상위 ${list.length}건 표시 — 전체는 CSV)`:''}</div><table><thead><tr><th>방향</th><th>프로토콜</th><th>포트</th><th>소스</th><th>설명</th></tr></thead><tbody>${list.map(x=>`<tr><td>${x.direction==='ingress'?'인':'아웃'}</td><td>${esc(x.protocol)}</td><td>${esc(x.port)}</td><td>${esc(x.source)}</td><td>${esc(x.description)}</td></tr>`).join('')}</tbody></table>`:'';
    const draw=()=>{const only=o.querySelector('#cm-only').checked,list=r.sgs.filter(s=>!only||s.status!=='same');
      o.querySelector('#cm-list').innerHTML=list.map(s=>`<div style="margin:10px 0;padding-bottom:8px;border-bottom:1px solid var(--border)"><b>${esc(s.name)}</b>${s.sg_id?` <span class="mut">(${esc(s.sg_id)})</span>`:''} <span class="badge ${(CMP_STATUS[s.status]||[0,''])[1]}">${esc((CMP_STATUS[s.status]||[s.status])[0])}</span>${s.same?` <span class="mut" style="font-size:12px">일치 ${s.same}건</span>`:''}
        ${s.aws_name?`<div class="mut" style="font-size:11px">AWS: ${esc(s.aws_name)}</div>`:''}${s.message?`<div class="mut" style="font-size:12px">${esc(s.message)}</div>`:''}${s.candidates?`<div class="mut" style="font-size:12px">후보: ${esc(s.candidates.join(', '))}</div>`:''}
        ${tbl('AWS에만 있음',s.aws_only,s.aws_only_count)}${tbl('파일에만 있음',s.file_only,s.file_only_count)}</div>`).join('')||'<div class="mut" style="padding:8px">모든 SG 가 AWS 와 일치합니다.</div>'};
    o.querySelector('#cm-only').onchange=draw;draw();
    o.querySelector('#cm-xlsx').onclick=async()=>{const m=o.querySelector('#cm-msg');m.textContent='만드는 중...';
      try{const res=await fetch('/api/aws/compare/xlsx',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({report:r})});
        if(!res.ok){let t='엑셀 파일을 만들지 못했습니다';try{t=(await res.json()).error||t}catch{}throw new Error(t)}
        const a=document.createElement('a');a.href=URL.createObjectURL(await res.blob());a.download=`aws-compare-${e.group}-${e.env}.xlsx`;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),4000);m.textContent='내려받았습니다'}
      catch(x){m.textContent='';toast(x.message,true)}};
    o.querySelector('#cm-copy').onclick=async()=>{const m=o.querySelector('#cm-msg'),T=String.fromCharCode(9),N=String.fromCharCode(10);
      const rows=[];r.sgs.forEach(s=>(s.aws_only||[]).forEach(x=>rows.push([s.name,x.direction,x.protocol,x.port,x.source,x.description].join(T))));
      if(!rows.length){m.textContent='AWS에만 있는 규칙이 없습니다';return}
      try{await navigator.clipboard.writeText([['SG','방향','프로토콜','포트','소스','설명'].join(T),...rows].join(N));m.textContent=`${rows.length}건을 복사했습니다`}catch{m.textContent='복사하지 못했습니다 (브라우저 권한). CSV 를 이용하세요'}};
    o.querySelector('#cm-csv').onclick=()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([cmpCsv(r)],{type:'text/csv'}));a.download=`aws-compare-${e.group}-${e.env}.csv`;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),4000)}}})}
