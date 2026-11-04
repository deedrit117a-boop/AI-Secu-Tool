// ---------- 되돌리기 / 변경 취소 / 작업 브랜치 전환
// Commit/Push 전의 변경은 저장할 때마다 이전 내용이 서버(data/undo.json)에 보관되어 한 단계씩 되돌릴 수 있다.
// 한 저장소에는 한 번에 하나의 작업 브랜치만 열 수 있으므로, 여러 티켓을 번갈아 작업할 때는 '브랜치 전환'을 쓴다 (저장 안 된 변경이 없을 때만).

// 변경이 일어난 뒤 화면을 다시 맞춘다
async function afterWorkChange(){
  await loadSgs();
  if(S.sg&&(S.sgs||[]).some(x=>x.name===S.sg)){S.edit=null;try{S.sgData=await api('GET',`/api/env/${S.envId}/sg/${S.sg}`);await loadChg()}catch{}}
  else{S.sg='';S.sgData=null}
  if($('#sgl'))drawSgList();if($('#detail'))drawDetail();drawBranchBanner();gitStatus(true);
}

const drawWorkTools=guard(async host=>{
  if(!host||!S.envId)return;
  const u=await api('GET',`/api/env/${S.envId}/undo`);if(!host.isConnected)return;
  const last=u.items[0];
  host.innerHTML=`<button class="wt-undo" ${u.usable?'':'disabled'} title="${esc(u.usable?'가장 최근 변경을 저장 직전 상태로 되돌립니다: '+last.label:(last?'변경 기록이 다른 브랜치의 것이라 되돌릴 수 없습니다':'되돌릴 변경 기록이 없습니다 (Commit/Push 하면 비워집니다)'))}">↶ 되돌리기${u.items.length?` (${u.items.length})`:''}</button>
    <button class="wt-revall" title="SG 폴더 안의 Commit 하지 않은 변경을 모두 취소합니다 (되돌리기로 다시 살릴 수 있음)">변경 전체 취소</button>
    <button class="wt-br" title="다른 티켓의 작업 브랜치로 전환합니다">작업 브랜치 전환</button>`;
  host.querySelector('.wt-undo').onclick=()=>undoLast(u);
  host.querySelector('.wt-revall').onclick=revertAll;
  host.querySelector('.wt-br').onclick=switchBranchModal;
});

const undoLast=guard(async u=>{
  const last=u.items[0];if(!last)return toast('되돌릴 변경 기록이 없습니다',true);
  if(!await showModal('되돌리기',`<div>가장 최근 변경을 저장 직전 상태로 되돌립니다.</div><div style="margin-top:6px"><b>${esc(last.label)}</b> · 파일 ${last.files}개 · ${esc(new Date(last.ts*1000).toLocaleTimeString('ko-KR',{hour12:false}))}</div>`,'되돌리기'))return;
  const r=await api('POST',`/api/env/${S.envId}/undo`);
  addHist('되돌리기 → '+r.label,'',{kind:'undo',headline:'↶ 되돌림'});
  toast(`되돌렸습니다: ${r.label}`);await afterWorkChange();drawHist&&drawHist()});

const revertAll=guard(async()=>{
  const s=await api('GET',`/api/env/${S.envId}/git/status?fresh=1`);
  if(!s.cloned||!(s.in_scope||[]).length)return toast('취소할 변경이 없습니다');
  if(!await showModal('변경 전체 취소',`<div>브랜치 <b>${esc(s.branch)}</b> 의 SG 폴더 안 변경 ${s.in_scope.length}개를 마지막 커밋 상태로 되돌립니다 (새로 만든 SG 파일은 삭제).</div>
    <ul style="max-height:200px;overflow:auto">${s.in_scope.map(f=>`<li>${esc(f.state)} — ${esc(f.path)}</li>`).join('')}</ul><div class="mut">취소한 뒤에도 [↶ 되돌리기] 로 다시 살릴 수 있습니다.</div>`,'변경 전체 취소'))return;
  const r=await api('POST',`/api/env/${S.envId}/git/revert-all`,{confirm:true});
  addHist('변경 전체 취소',r.files.join('\n'),{kind:'undo',headline:'✕ 변경 취소 '+r.files.length+'개'});
  toast(`${r.files.length}개 파일의 변경을 취소했습니다`);await afterWorkChange()});

const revertSg=guard(async name=>{
  if(!await showModal('이 SG 변경 취소',`<div><b>${esc(name)}</b> 의 Commit 하지 않은 변경을 취소하고 마지막 커밋 상태로 되돌립니다 (새로 만든 SG 면 파일 삭제).</div><div class="mut" style="margin-top:6px">취소한 뒤에도 [↶ 되돌리기] 로 다시 살릴 수 있습니다.</div>`,'변경 취소'))return;
  const r=await api('POST',`/api/env/${S.envId}/sg/${encodeURIComponent(name)}/revert`,{confirm:true});
  addHist('SG 변경 취소 → '+name,r.files.join('\n'),{kind:'undo',headline:'✕ 변경 취소'});
  toast('변경을 취소했습니다: '+name);await afterWorkChange()});

const switchBranchModal=guard(async()=>{
  const r=await api('GET',`/api/env/${S.envId}/git/branches`);
  if(!r.branches.length)return toast('전환할 로컬 작업 브랜치가 없습니다 (작업 탭에서 먼저 브랜치를 만드세요)');
  const v=await showModal('작업 브랜치 전환',`<div class="mut" style="margin-bottom:8px">현재: <b>${esc(r.current)}</b> — 저장하지 않은 변경이 있으면 전환할 수 없습니다 (먼저 Commit/Push 하거나 변경 취소).</div>
    <fieldset style="border:0;padding:0;margin:0"><legend class="sr-only">전환할 브랜치</legend>${r.branches.map((b,i)=>`<label style="display:flex;gap:8px;align-items:flex-start;padding:4px 0"><input type="radio" name="wtb" value="${esc(b.name)}" ${b.current?'checked disabled':''} ${!b.current&&i===0?'checked':''}>
    <span><b>${esc(b.name)}</b>${b.current?' <span class="badge b-ok">현재</span>':''}${b.ticket?` <span class="tag">${esc(b.ticket)}</span>`:''}<br><span class="mut">${esc(b.date)} · ${esc(b.subject)}</span></span></label>`).join('')}</fieldset>`,'전환',null,
    {collect:o=>({branch:(o.querySelector('input[name=wtb]:checked:not(:disabled)')||{}).value||''})});
  if(!v||!v.branch)return;
  const x=await api('POST',`/api/env/${S.envId}/git/switch`,{branch:v.branch});
  addHist('작업 브랜치 전환 → '+x.branch,x.log||'',{kind:'prep',headline:'⇄ 브랜치 전환'});
  toast('전환했습니다: '+x.branch);S.sg='';S.sgData=null;await loadSgs();render()});
