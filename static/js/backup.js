// ---------- 환경설정의 '백업 / 복구' 카드: 설정·토큰·메타 데이터를 JSON 파일 하나로 내려받고, 새로 설치한 도구에서 올려 되살린다
// 복구는 파일 내용을 서버에 보내 확인(dry_run)한 뒤 적용하며, 적용 전에 현재 파일을 data/backup 에 복사해 둔다.
async function drawBackupCard(){
  const host=$('#backup-card');if(!host)return;
  let info;try{info=await api('GET','/api/backup/info')}catch(e){host.innerHTML=`<div class="card"><div class="warnbox danger">${esc(e.message)}</div></div>`;return}
  if(!$('#backup-card'))return;
  const canPick=typeof window.showSaveFilePicker==='function';
  host.innerHTML=`<div class="card"><h3>백업 / 복구 <span class="mut" style="font-weight:400">(설정을 파일 하나로 저장하고, 새 PC 나 새로 설치한 도구에서 올려 되살립니다)</span></h3>
    <div class="mut" style="margin-bottom:8px" id="bk-last">${info.status&&info.status.last?`마지막 백업: ${esc(info.status.last)} (${info.status.days}일 전)`:'아직 백업 파일을 받은 적이 없습니다'}${info.status&&info.status.due?' — <b style="color:var(--warn)">백업할 때가 되었습니다</b>':''}</div>
    <div class="row" style="align-items:flex-start;gap:28px">
      <div style="flex:1;min-width:300px"><b>백업 만들기</b>
        ${info.groups.map(g=>`<label style="display:block;margin:4px 0"><input type="checkbox" class="bk-g" value="${esc(g.key)}" ${g.key==='excel'?'':'checked'} ${g.files.some(f=>f.exists)?'':'disabled'}> ${esc(g.label)} <span class="mut">(${g.files.map(f=>esc(f.name)+(f.exists?'':' — 없음')).join(', ')})</span></label>`).join('')}
        <div class="row" style="margin-top:8px"><button class="blue" id="bk-go">${canPick?'저장 위치 선택해서 백업':'백업 파일 내려받기'}</button><span class="mut" id="bk-msg" role="status"></span></div>
        <div class="warnbox" style="margin-top:8px">⚠ <b>계정·토큰 항목</b>을 넣으면 GitLab 토큰과 Jira 키가 <b>그대로</b> 파일에 들어갑니다. 내 PC 나 개인 보관함에만 두고 메신저·메일·위키에 올리지 마세요.</div></div>
      <div style="flex:1;min-width:300px"><b>백업 파일로 복구</b>
        <div class="mut" style="margin:4px 0 8px">새로 설치한 뒤 이 화면에서 백업 파일을 고르면 담긴 내용을 보여준 다음, 확인하면 현재 설정을 바꿉니다. 바꾸기 전의 파일은 <code>data/backup/</code> 에 복사해 둡니다.</div>
        <div class="row"><button id="bk-pick">백업 파일 선택...</button><input type="file" id="bk-file" accept=".json,application/json" style="display:none"><span class="mut" id="bk-fname"></span></div>
        <div id="bk-prev" style="margin-top:8px"></div></div></div></div>`;
  $('#bk-go').onclick=guard(async()=>{
    const gs=[...document.querySelectorAll('.bk-g:checked')].map(i=>i.value),msg=$('#bk-msg');
    if(!gs.length)return toast('백업할 항목을 하나 이상 선택하세요',true);
    const name='traform-acl-backup-'+new Date().toISOString().slice(0,10).replace(/-/g,'').slice(2)+'.json';
    let handle=null;
    if(canPick){
      try{handle=await window.showSaveFilePicker({suggestedName:name,types:[{description:'JSON 백업 파일',accept:{'application/json':['.json']}}]})}
      catch(e){if(e&&e.name==='AbortError'){msg.textContent='취소했습니다';return}throw e}
    }
    msg.textContent='만드는 중...';
    const r=await fetch('/api/backup/download?groups='+gs.join(','));
    if(!r.ok){let m='백업을 만들지 못했습니다';try{m=(await r.json()).error||m}catch{}msg.textContent='';throw new Error(m)}
    const blob=await r.blob();
    if(handle){const w=await handle.createWritable();await w.write(blob);await w.close();msg.textContent=`저장했습니다: ${handle.name} (${Math.round(blob.size/1024)||1} KB)`}
    else{const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),4000);msg.textContent=`내려받았습니다 (${Math.round(blob.size/1024)||1} KB) — 브라우저의 다운로드 폴더를 확인하세요`}
    toast('백업 파일을 만들었습니다');backupNudge(true);
  });
  $('#bk-pick').onclick=()=>$('#bk-file').click();
  $('#bk-file').onchange=guard(async()=>{
    const f=$('#bk-file').files[0];if(!f)return;$('#bk-fname').textContent=f.name;
    const prev=$('#bk-prev');let bk;
    try{bk=JSON.parse((await f.text()).replace(/^﻿/,''))}catch{prev.innerHTML='<div class="warnbox danger">JSON 파일로 읽을 수 없습니다. 이 도구에서 만든 백업 파일(.json)을 선택하세요.</div>';return}
    let r;try{r=await api('POST','/api/backup/restore',{backup:bk,dry_run:true})}catch(e){prev.innerHTML=`<div class="warnbox danger">${esc(e.message)}</div>`;return}
    const groups=Object.fromEntries(info.groups.map(g=>[g.key,g.label]));
    prev.innerHTML=`<div class="mut" style="margin-bottom:6px">만든 시각 ${esc(r.created||'?')} · 도구 v${esc(r.app_version||'?')}</div>
      <table><thead><tr><th></th><th>항목</th><th>내용</th></tr></thead><tbody>${r.available.map(k=>`<tr><td><input type="checkbox" class="bk-r" value="${esc(k)}" checked></td><td>${esc(groups[k]||k)}</td>
        <td>${r.items.filter(x=>x.group===k).map(x=>`<div><code>${esc(x.name)}</code> — ${esc(x.summary)}${x.replaces?' <span class="badge b-chg">현재 파일 교체</span>':' <span class="badge b-ok">새로 만듦</span>'}</div>`).join('')}</td></tr>`).join('')}</tbody></table>
      <label style="display:block;margin:8px 0 4px"><input type="checkbox" id="bk-clr"> 다른 PC 로 옮기는 중이라 <b>repo 로컬 경로를 비웁니다</b> <span class="mut">(이 PC 에 맞게 다시 입력해야 합니다)</span></label>
      <div class="row"><button class="pri" id="bk-apply">복구 적용</button><button id="bk-cancel">취소</button></div>`;
    $('#bk-cancel').onclick=()=>{prev.innerHTML='';$('#bk-fname').textContent='';$('#bk-file').value=''};
    $('#bk-apply').onclick=guard(async()=>{
      const gs=[...document.querySelectorAll('.bk-r:checked')].map(i=>i.value);
      if(!gs.length)return toast('복구할 항목을 선택하세요',true);
      if(!confirm('선택한 항목을 백업 파일 내용으로 바꿀까요?\n(바꾸기 전 파일은 data/backup 에 복사해 둡니다)'))return;
      const a=await api('POST','/api/backup/restore',{backup:bk,groups:gs,dry_run:false,clear_repo_dirs:$('#bk-clr').checked});
      await reloadCfg();S.meta=await api('GET','/api/meta');
      if(!S.cfg.environments.find(e=>e.id===S.envId)){S.envId='';S.sg=null}
      persist();renderPickers();
      toast(`복구했습니다: ${a.restored.join(', ')} (이전 파일: ${a.backup})`,false,9000);viewCfg()});
  });
}

// 사이드바 위쪽의 백업 안내: 설정이 있는데 14일 넘게 백업하지 않았으면 한 줄로 알린다 (오늘은 그만 보기 가능)
async function backupNudge(force){
  const h=$('#bknudge');if(!h)return;
  let st;try{st=(await api('GET','/api/backup/info')).status}catch{return}
  const today=new Date().toISOString().slice(0,10);
  if(!st||!st.due||(!force&&ls.get('bknudge','')===today)){h.innerHTML='';return}
  h.innerHTML=`<span>${st.last?`백업한 지 ${st.days}일 지났습니다`:'아직 백업이 없습니다'}</span> <button type="button" class="linkbtn" id="bkn-go">백업하기</button> <button type="button" class="linkbtn" id="bkn-x" aria-label="오늘은 그만 보기">×</button>`;
  $('#bkn-go').onclick=()=>{viewCfg()};
  $('#bkn-x').onclick=()=>{ls.set('bknudge',today);h.innerHTML=''};
}
