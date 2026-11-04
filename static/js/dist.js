// ---------- 배포 메뉴: 다른 사용자에게 줄 프로그램 zip 을 만들어 원하는 위치에 저장
// 토큰(local.json)·작업 이력·백업·로그는 들어가지 않는다 (서버가 만들 때 한 번 더 검사).
async function viewDist(){
  const v=$('#view');v.innerHTML='<div class="card mut">불러오는 중...</div>';
  let info;try{info=await api('GET','/api/dist/info')}catch(e){v.innerHTML=`<div class="card"><div class="warnbox danger">${esc(e.message)}</div></div>`;return}
  const canPick=typeof window.showSaveFilePicker==='function';
  v.innerHTML=`<div class="card"><h3>배포용 파일 만들기</h3>
    <div class="mut" style="margin-bottom:10px">다른 사용자에게 줄 프로그램을 zip 하나로 묶습니다. 받는 사람은 압축을 풀고 <code>run.bat</code> 을 실행하면 됩니다 (Python 3.10 이상과 git 필요).</div>
    <div class="row" style="gap:18px;margin-bottom:8px"><span>버전 <b>v${esc(info.version)}</b></span><span>프로그램 파일 <b>${info.files}</b>개</span><span>파일 이름 <code>${esc(info.filename)}</code></span></div>
    <div style="margin:10px 0"><label style="display:block;margin:4px 0"><input type="checkbox" id="dz-cfg" checked> 환경 목록 포함 <span class="mut">(현재 환경 ${info.environments}개 — 내 PC 의 저장소 경로는 비워서 넣습니다)</span></label>
      <label style="display:block;margin:4px 0"><input type="checkbox" id="dz-meta" ${info.has_meta?'':'disabled'}> 메타 데이터 포함 <span class="mut">(SG ID/태그/서브넷 정보, meta.json)${info.has_meta?'':' — 아직 없음'}</span></label></div>
    <div class="row"><button class="blue" id="dz-go">${canPick?'저장 위치 선택해서 만들기':'만들어서 내려받기'}</button><span class="mut" id="dz-msg" role="status"></span></div>
    ${canPick?'':'<div class="mut" style="font-size:12px;margin-top:6px">이 브라우저는 저장 위치 선택 창을 지원하지 않아 브라우저의 기본 다운로드 위치(또는 다운로드 시 묻기 설정)를 따릅니다. Edge/Chrome 을 쓰면 저장 위치를 고를 수 있습니다.</div>'}</div>
    <div class="card"><h3>들어가지 않는 것</h3><ul style="margin:0;padding-left:20px">${info.excluded.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>
      <div class="mut" style="font-size:12px;margin-top:8px">토큰 값이 파일에 섞여 있으면 만들기를 중단합니다. 받는 사람은 처음 실행할 때 계정과 토큰을 직접 입력합니다.</div></div>`;
  $('#dz-go').onclick=guard(async()=>{
    const q=`with_config=${$('#dz-cfg').checked?1:0}&with_meta=${$('#dz-meta').checked?1:0}`,msg=$('#dz-msg');
    let handle=null;
    if(canPick){   // 저장 위치는 사용자의 클릭 직후에 물어야 하므로 만들기 전에 먼저 선택 창을 연다
      try{handle=await window.showSaveFilePicker({suggestedName:info.filename,types:[{description:'ZIP 압축 파일',accept:{'application/zip':['.zip']}}]})}
      catch(e){if(e&&e.name==='AbortError'){msg.textContent='취소했습니다';return}throw e}
    }
    msg.textContent='만드는 중...';
    const r=await fetch('/api/dist/zip?'+q);
    if(!r.ok){let m='만들지 못했습니다';try{m=(await r.json()).error||m}catch{}msg.textContent='';throw new Error(m)}
    const blob=await r.blob();
    if(handle){const w=await handle.createWritable();await w.write(blob);await w.close();msg.textContent=`저장했습니다: ${handle.name} (${Math.round(blob.size/1024)} KB)`}
    else{const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=info.filename;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),4000);msg.textContent=`내려받았습니다: ${info.filename} (${Math.round(blob.size/1024)} KB)`}
    toast('배포용 파일을 만들었습니다');
  });
}
