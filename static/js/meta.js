// ---------- 메타
function viewMeta(){
  const em=S.meta.envs[S.envId]||(S.meta.envs[S.envId]={});em.sgs=em.sgs||{};
  const subs=(em.subnets&&em.subnets.length)?em.subnets:[...(em.vpc_cidrs||[]).map(c=>({ipv4_cidr:c})),...(em.nat_ips||[]).map(n=>({nat_ip:n}))];
  const srow=r=>`<tr class="sr"><td><input type="text" class="s-n" style="width:100%" value="${esc(r.subnet_name||'')}" placeholder="예: sub-a"></td>
    <td><input type="text" class="s-v" style="width:100%" value="${esc(r.vpc_id||'')}" placeholder="vpc-xxxxxxxx"></td>
    <td><input type="text" class="s-c" style="width:100%" value="${esc(r.ipv4_cidr||'')}" placeholder="10.0.0.0/24"></td>
    <td><input type="text" class="s-i" style="width:100%" value="${esc(r.nat_ip||'')}" placeholder="NAT 공인 IP"></td>
    <td style="width:70px"><button class="danger sdel">삭제</button></td></tr>`;
  $('#view').innerHTML=`<div class="card"><div class="row"><h3 style="margin:0">환경 정보 — ${esc(env().label?env().env+' · '+env().label:env().env)}</h3><span style="margin-left:auto" class="row">
      <button class="blue" id="awsf" title="AWS 에서 SG ID / 서브넷 / NAT IP 를 읽기만 해서 가져옵니다 (AWS CLI 필요)">AWS 에서 가져오기</button>
      <a class="btn" style="text-decoration:none" href="/api/meta/env-csv?env_id=${encodeURIComponent(S.envId)}">CSV 다운로드(현재 환경)</a>
      <a class="btn" style="text-decoration:none" href="/api/meta/env-csv">CSV 다운로드(전체)</a>
      <button id="eu">CSV 업로드</button><input type="file" id="euf" accept=".csv" hidden></span></div>
    <div class="mut" style="font-size:12px;margin:6px 0 10px">열: <code>env_id</code>, <code>Subnet name</code>, <code>VPC ID</code>, <code>IPv4 CIDR</code>, <code>NAT IP</code> · 업로드하면 CSV에 포함된 환경의 목록은 CSV 내용으로 교체됩니다.</div>
    <table><thead><tr><th>Subnet name</th><th>VPC ID</th><th>IPv4 CIDR</th><th>NAT IP</th><th></th></tr></thead><tbody id="subb">${subs.map(srow).join('')}</tbody></table>
    <div class="row" style="margin-top:8px"><button id="subadd">행 추가</button><button class="pri" id="subsave">환경 정보 저장 (meta.json)</button>
      ${(!em.subnets&&subs.length)?'<span class="mut">기존 VPC 대역/NAT IP 값을 불러왔습니다. 저장하면 새 형식으로 반영됩니다.</span>':''}</div></div>
  <div class="card"><div class="row"><h3 style="margin:0">SG별 별명 / SG ID / 태그</h3><button class="blue" id="msync">SG명 불러오기 (태그 없는 항목으로 반영)</button><span class="mut" id="mcnt"></span><span style="margin-left:auto" class="row">
    <a href="/api/meta/csv" style="text-decoration:none;padding:4px 12px;border:1px solid var(--mut);color:inherit">CSV 다운로드(전체)</a><button id="mu">CSV 업로드</button><input type="file" id="muf" accept=".csv" hidden></span></div>
    <div class="mut" style="font-size:12px">태그 형식: <code>유형:값</code> 쉼표 구분 — 예) <code>사설IP:10.0.0.1, 도메인:a.example.com</code> · <b>담당자</b>는 팀 또는 사람 이름이며, 규칙 점검 보고서(만료·정리 제안·기준 점검)와 담당자별 현황, 감사 보고서에 표시됩니다.</div>
    <div class="row" style="margin:10px 0"><input type="text" id="mfq" style="flex:1;min-width:200px" placeholder="필터 (SG명/SG ID/별명/태그)" value="${esc(S.mfq||'')}">
      <label><input type="checkbox" id="mfn" ${S.mfn?'checked':''}> 태그 없는 항목만</label><span class="mut" id="mfc"></span></div>
    <datalist id="m-owl">${[...new Set(Object.values(S.meta.envs).flatMap(x=>Object.values((x&&x.sgs)||{}).map(s=>s&&s.owner).filter(Boolean)))].map(o=>`<option value="${esc(o)}">`).join('')}</datalist>
    <table><thead><tr><th>SG</th><th>SG ID</th><th>별명</th><th>담당자</th><th>태그</th></tr></thead><tbody>${S.sgs.map(s=>{const m=em.sgs[s.name]||{};
      return`<tr data-sg="${esc(s.name)}"><td>${esc(s.name)}</td><td><input type="text" class="m-id" size="24" value="${esc(m.sg_id||'')}" placeholder="sg-xxxx"></td>
      <td><input type="text" class="m-al" size="20" value="${esc(m.alias||'')}"></td>
      <td><input type="text" class="m-ow" size="14" list="m-owl" value="${esc(m.owner||'')}" placeholder="팀/담당자"></td>
      <td><input type="text" class="m-tg" style="width:100%" value="${esc((m.tags||[]).map(t=>(t.type?t.type+':':'')+t.value).join(', '))}"></td></tr>`}).join('')}</tbody></table>
    <div style="margin-top:8px"><button class="pri" id="msave">저장 (meta.json)</button></div></div>`;
  $('#awsf').onclick=awsFetchModal;
  $('#msave').onclick=guard(async()=>{const csv=s=>s.split(',').map(x=>x.trim()).filter(Boolean);
    document.querySelectorAll('tr[data-sg]').forEach(tr=>{const n=tr.dataset.sg;
      const tags=csv(tr.querySelector('.m-tg').value).map(t=>{const i=t.indexOf(':');return i>0&&/[^\d.]/.test(t.slice(0,i))?{type:t.slice(0,i),value:t.slice(i+1)}:{type:'',value:t}});
      em.sgs[n]={...(em.sgs[n]||{}),sg_id:tr.querySelector('.m-id').value.trim(),alias:tr.querySelector('.m-al').value.trim(),owner:tr.querySelector('.m-ow').value.trim(),tags}});
    await api('PUT','/api/meta',S.meta);toast('meta.json 저장됨')});
  const sb=$('#subb'),bind=tr=>tr.querySelector('.sdel').onclick=()=>tr.remove();sb.querySelectorAll('tr').forEach(bind);
  $('#subadd').onclick=()=>{sb.insertAdjacentHTML('beforeend',srow({}));bind(sb.lastElementChild)};
  $('#subsave').onclick=guard(async()=>{const rows=[...sb.querySelectorAll('tr')].map(tr=>({subnet_name:tr.querySelector('.s-n').value.trim(),vpc_id:tr.querySelector('.s-v').value.trim(),
      ipv4_cidr:tr.querySelector('.s-c').value.trim(),nat_ip:tr.querySelector('.s-i').value.trim()})).filter(r=>Object.values(r).some(Boolean));
    const ip4=/^\d{1,3}(\.\d{1,3}){3}$/,cidr=/^\d{1,3}(\.\d{1,3}){3}\/\d{1,2}$/;
    const bad=rows.filter(r=>(r.ipv4_cidr&&!cidr.test(r.ipv4_cidr)&&!ip4.test(r.ipv4_cidr))||(r.nat_ip&&!ip4.test(r.nat_ip)));
    if(bad.length&&!confirm(`IPv4 CIDR / NAT IP 형식이 올바르지 않은 행이 ${bad.length}개 있습니다. 그대로 저장할까요?`))return;
    em.subnets=rows;await api('PUT','/api/meta',S.meta);toast(`환경 정보 ${rows.length}행 저장됨`);viewMeta()});
  $('#eu').onclick=()=>$('#euf').click();
  $('#euf').onchange=guard(async e=>{const fd=new FormData();fd.append('file',e.target.files[0]);const r=await api('POST','/api/meta/env-csv',fd,true);
    S.meta=await api('GET','/api/meta');const extra=[...(r.unknown_env_ids.length?['알 수 없는 env_id 제외: '+r.unknown_env_ids.join(', ')]:[]),...r.warnings];
    toast(`환경 ${r.envs}개, ${r.rows}행 적용`+(extra.length?'\n'+extra.join('\n'):''),extra.length>0);viewMeta()});
  const untagged=()=>S.sgs.filter(x=>!(em.sgs[x.name]?.tags||[]).length).length;
  $('#mcnt').textContent=`SG ${S.sgs.length}개 / 태그 없음 ${untagged()}개`;
  $('#msync').onclick=guard(async()=>{await loadSgs();let added=0;
    S.sgs.forEach(x=>{if(!em.sgs[x.name]){em.sgs[x.name]={sg_id:'',alias:'',tags:[]};added++}});
    if(added)await api('PUT','/api/meta',S.meta);toast(`SG ${S.sgs.length}개 확인, 신규 ${added}개를 태그 없는 항목으로 반영했습니다 (기존 항목은 유지)`);viewMeta()});
  const mfilt=()=>{S.mfq=$('#mfq').value;S.mfn=$('#mfn').checked;const ws=S.mfq.trim().toLowerCase().split(/\s+/).filter(Boolean);let n=0;
    document.querySelectorAll('tr[data-sg]').forEach(tr=>{const t=(tr.dataset.sg+' '+[...tr.querySelectorAll('input')].map(i=>i.value).join(' ')).toLowerCase();
      const ok=ws.every(w=>t.includes(w))&&(!S.mfn||!tr.querySelector('.m-tg').value.trim());tr.style.display=ok?'':'none';if(ok)n++});
    $('#mfc').textContent=`${n} / ${S.sgs.length}개`};
  $('#mfq').oninput=mfilt;$('#mfn').onchange=mfilt;mfilt();
  $('#mu').onclick=()=>$('#muf').click();
  $('#muf').onchange=guard(async e=>{const fd=new FormData();fd.append('file',e.target.files[0]);const r=await api('POST','/api/meta/csv',fd,true);
    S.meta=await api('GET','/api/meta');toast(`적용: ${r.updated}건`);viewMeta()});
}

