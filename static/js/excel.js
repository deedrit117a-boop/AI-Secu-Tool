// ---------- 엑셀 연동: ACL 적용내역 시트에 한 건당 한 줄 기록
// 설정(작성자/폴더/파일/시트)은 환경설정의 '엑셀 연동' 카드에서 한다. 기록은 미리보기에서 확인·수정한 뒤에만 쓰고,
// 시트의 C 열 마지막 내용 바로 아래부터 이어서 씁니다 (쓰기 전에 data/excel_backup 에 백업).
const EXCEL_COLS=['적용','Account','리전','출발지(Zone)','출발지(보안그룹)','목적지(Zone)','목적지(보안그룹)','프로토콜','서비스','Action','티켓번호','처리자'];

async function drawExcelCard(){
  const host=$('#excel-card');if(!host)return;
  let st;try{st=await api('GET','/api/excel/settings')}catch(e){host.innerHTML=`<div class="card"><div class="warnbox danger">${esc(e.message)}</div></div>`;return}
  if(!$('#excel-card'))return;
  host.innerHTML=`<div class="card"><h3>엑셀 연동 <span class="mut" style="font-weight:400">(ACL 적용내역 기록 — 이 PC 의 local.json 에 저장, 공유 안 됨)</span></h3>
    ${st.openpyxl?'':'<div class="warnbox danger">openpyxl 패키지가 없습니다. run.bat 을 다시 실행하거나 <code>pip install openpyxl</code> 을 실행하세요.</div>'}
    <div class="row" style="align-items:flex-end">
      <label class="f">작성자 이름 (엑셀 N열 처리자)<input type="text" id="ex-writer" size="16" value="${esc(st.writer)}" placeholder="예: 임희재"></label>
      <label class="f">시트 이름<input type="text" id="ex-sheet" size="16" value="${esc(st.sheet)}"></label></div>
    <div class="row" style="align-items:flex-end;margin-top:6px">
      <label class="f" style="flex:1;min-width:280px">엑셀 폴더<input type="text" id="ex-folder" style="width:100%" value="${esc(st.folder)}" placeholder="폴더를 선택하거나 경로를 입력하세요"></label>
      <button id="ex-pick">폴더 선택...</button></div>
    <div class="row" style="align-items:flex-end;margin-top:6px">
      <label class="f" style="flex:1;min-width:280px">엑셀 파일 (폴더 안의 .xlsx / .xlsm)<select id="ex-file" style="width:100%"></select></label>
      <button class="pri" id="ex-save">저장</button><button id="ex-test">연결 테스트</button></div>
    <div class="mut" id="ex-msg" style="margin-top:6px" role="status"></div>
    <div class="mut" style="font-size:12px;margin-top:6px">기록 위치: 시트의 <b>C열에서 내용이 있는 마지막 줄 바로 아래</b>부터 한 건당 한 줄 (C 적용 · D Account · E 리전 · F 출발지 Zone · G 출발지 보안그룹 · H 목적지 Zone · I 목적지 보안그룹 · J 프로토콜 · K 서비스 · L Action · M 티켓번호 · N 처리자). 엑셀이 열려 있으면 열려 있는 엑셀에 직접 기록하고(자동 저장/클라우드로 반영), 닫혀 있으면 파일에 기록합니다. 기록 전 파일은 <code>data/excel_backup</code> 에 백업합니다.</div></div>`;
  const fillFiles=(files,cur)=>{const sel=$('#ex-file');sel.innerHTML=(files.length?'':'<option value="">(폴더에 엑셀 파일이 없습니다)</option>')+files.map(f=>`<option value="${esc(f)}" ${f===cur?'selected':''}>${esc(f)}</option>`).join('')};
  fillFiles(st.files,st.file);
  const reload=guard(async()=>{const r=await api('GET','/api/excel/files?folder='+encodeURIComponent($('#ex-folder').value.trim()));fillFiles(r.files,'');$('#ex-msg').textContent=r.files.length?`엑셀 파일 ${r.files.length}개`:'이 폴더에 .xlsx/.xlsm 파일이 없습니다'});
  $('#ex-folder').onchange=reload;
  $('#ex-pick').onclick=guard(async()=>{const r=await api('POST','/api/excel/pick-folder',{initial:$('#ex-folder').value.trim()});
    if(!r.folder)return;$('#ex-folder').value=r.folder;fillFiles(r.files,'');$('#ex-msg').textContent=r.files.length?`엑셀 파일 ${r.files.length}개 — 사용할 파일을 선택하세요`:'이 폴더에 .xlsx/.xlsm 파일이 없습니다'});
  const body=()=>({folder:$('#ex-folder').value.trim(),file:$('#ex-file').value,sheet:$('#ex-sheet').value.trim(),writer:$('#ex-writer').value.trim()});
  $('#ex-save').onclick=guard(async()=>{const b=body();if(!b.folder||!b.file)return toast('폴더와 엑셀 파일을 선택하세요',true);await api('PUT','/api/excel/settings',b);toast('엑셀 연동 설정을 저장했습니다')});
  $('#ex-test').onclick=guard(async()=>{const b=body();if(!b.folder||!b.file)return toast('폴더와 엑셀 파일을 선택하세요',true);
    await api('PUT','/api/excel/settings',b);const m=$('#ex-msg');m.textContent='확인 중...';
    const r=await api('GET','/api/excel/check');
    m.innerHTML=`✅ <b>${esc(r.sheet)}</b> 시트 · C열 마지막 내용 <b>${r.last_row}행</b> → 다음 기록은 <b>${r.next_row}행</b>부터`+(r.locked?` <span class="mut">(엑셀에서 열려 있습니다 — ${r.via==='excel'?'열려 있는 엑셀의 현재 내용을 읽었고, 기록도 그 엑셀에 직접 합니다':'열려 있어도 기록할 수 있습니다'})</span>`:'')+(r.readonly?' <span style="color:var(--err)">⚠ 엑셀에서 읽기 전용으로 열려 있어 기록할 수 없습니다</span>':'')+(r.protected?' <span style="color:var(--err)">⚠ 시트가 보호되어 있어 기록할 수 없습니다</span>':'')+
      (r.mismatch.length?`<div class="warnbox" style="margin-top:6px">머리글이 예상과 다릅니다 (C~N 열 순서 확인): ${r.mismatch.map(x=>esc(x[0])+' ↔ '+esc(x[1]||'(빈칸)')).join(', ')}</div>`:'<div class="mut">머리글(C~N열)이 양식과 일치합니다.</div>')});
}

// 기록할 줄 미리보기 → 확인/수정 → 엑셀에 기록. auto=true 면 apply 완료 직후 자동으로 묻는 경우 (설정/변경이 없으면 조용히 건너뜀)
async function excelRecordModal(envId,auto){
  let pv;
  try{pv=await api('GET',`/api/env/${envId}/excel/preview?ticket=${encodeURIComponent(($('#ticket')||{value:''}).value.trim())}`)}
  catch(e){if(!auto)toast(e.message,true);return false}
  if(!pv.configured){if(!auto)toast('환경설정의 "엑셀 연동"에서 폴더와 엑셀 파일을 먼저 선택하세요',true);return false}
  if(!pv.rows.length){if(!auto)toast('엑셀에 기록할 변경 규칙이 없습니다');return false}
  const rowHtml=(r,i)=>`<tr data-i="${i}"><td><input type="checkbox" class="ex-ck" ${r.checked?'checked':''} aria-label="${i+1}번 줄 기록"></td>
    <td class="mut" style="white-space:nowrap">${r.direction==='ingress'?'인바운드':'아웃바운드'}${r.dup?' <span class="badge b-warn">이미 기록됨</span>':''}${r.note?` <span class="badge b-warn">${esc(r.note)}</span>`:''}</td>
    ${r.cells.map((c,j)=>`<td><input type="text" class="ex-c" data-j="${j}" value="${esc(c)}" aria-label="${esc(EXCEL_COLS[j])}" style="width:${[46,110,70,90,150,150,250,70,64,60,100,80][j]}px"></td>`).join('')}</tr>`;
  const res=await showModal('엑셀에 기록 — 기록할 줄 확인',
    `<div class="mut" style="margin-bottom:6px">브랜치 <b>${esc(pv.branch)}</b> · 티켓 <b>${esc(pv.ticket||'-')}</b>${pv.from_pending?' · <span class="badge b-warn">apply 전에 계산해 둔 내용</span>':''} — 한 건당 한 줄입니다. 값은 고칠 수 있고, 기록하지 않을 줄은 체크를 끄세요 (아웃바운드는 기본 꺼짐).</div>
     <div style="overflow:auto;max-height:55vh"><table style="min-width:1250px"><thead><tr><th></th><th>방향</th>${EXCEL_COLS.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${pv.rows.map(rowHtml).join('')}</tbody></table></div>
     <div class="mut" style="font-size:12px;margin-top:6px">추가/변경은 <b>허용</b>, 삭제는 <b>삭제</b>로 기록합니다. 규칙을 수정했다면 이전 규칙(삭제)과 새 규칙(허용)이 각각 한 줄입니다. 시트의 C열 마지막 내용 바로 아래에 이어서 씁니다.</div>`,
    '엑셀에 기록',auto?'건너뛰기':'취소',{collect:o=>({rows:[...o.querySelectorAll('tbody tr')].map((tr,i)=>({ck:tr.querySelector('.ex-ck').checked,
      cells:[...tr.querySelectorAll('.ex-c')].map(x=>x.value.trim()),key:pv.rows[i].key,direction:pv.rows[i].direction}))
      .filter(r=>r.ck).map(({cells,key,direction})=>({cells,key,direction}))})});
  if(!res)return false;
  if(!res.rows.length){toast('기록할 줄이 선택되지 않았습니다',true);return false}
  try{const r=await api('POST','/api/excel/append',{rows:res.rows});
    addHist('엑셀 기록 → '+r.sheet,`${r.file}\n${r.first_row}~${r.last_row}행 (${r.written}줄)\n백업: ${r.backup}`,{kind:'prep',headline:`✓ 엑셀 ${r.written}줄 기록 (${r.first_row}~${r.last_row}행)`});
    toast(`엑셀에 ${r.written}줄을 기록했습니다 (${r.first_row}~${r.last_row}행)`+(r.open_in_excel?'\n엑셀이 열려 있다면 동기화 후 새로고침해서 확인하세요':''),false,7000);return true}
  catch(e){toast(e.message,true,12000);return false}
}
