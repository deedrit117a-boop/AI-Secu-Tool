// ---------- 환경설정의 '자가 점검 / 문제 신고' 카드
// 이 PC 에서 도구가 동작하는지(Python/패키지/git/토큰/접속/AWS CLI/엑셀) 한 번에 점검하고, 문제가 있으면 해결 방법을 보여준다.
// 문제 신고 파일은 토큰이 빠진 진단 정보 + 로그 일부를 JSON 하나로 묶어 내려받는 것이다.
const CK_ICON={ok:['✓','ck-ok','정상'],warn:['⚠','ck-warn','확인 필요'],fail:['✗','ck-fail','문제'],info:['·','ck-info','참고']};
function checkRows(list){return `<table><tbody>${list.map(c=>{const i=CK_ICON[c.status]||CK_ICON.info;
  return `<tr><td style="width:26px" class="${i[1]}" aria-label="${i[2]}"><b>${i[0]}</b></td><td style="white-space:nowrap">${esc(c.label)}</td><td>${esc(c.detail)}${c.fix&&c.status!=='ok'?`<div class="mut" style="font-size:12px">→ ${esc(c.fix)}</div>`:''}</td></tr>`}).join('')}</tbody></table>`}
async function drawSelfcheckCard(){
  const host=$('#selfcheck-card');if(!host)return;
  host.innerHTML=`<div class="card"><h3>자가 점검 / 문제 신고 <span class="mut" style="font-weight:400">(이 PC 에서 도구가 잘 동작하는지 확인합니다)</span></h3>
    <div class="row"><button class="blue" id="ck-run">점검 실행</button><button id="ck-online" title="GitLab / Jira 에 실제로 접속해 봅니다 (읽기 전용, 몇 초 걸림)">접속 확인 포함</button>
      <button id="ck-bundle" title="토큰은 빼고, 버전·점검 결과·환경 목록·서버 로그 일부를 JSON 파일 하나로 저장합니다">문제 신고 파일 만들기</button><span class="mut" id="ck-msg" role="status"></span></div>
    <div id="ck-res" style="margin-top:8px"></div>
    <div class="mut" style="font-size:12px;margin-top:6px">문제가 생기면 '문제 신고 파일'을 받아 담당자에게 전달하세요. 토큰·API 키는 들어가지 않고, 로그 속 비밀 값과 사용자 폴더 이름은 가려집니다. 그래도 보내기 전에 파일을 한 번 열어 보세요.</div></div>`;
  const run=online=>guard(async()=>{const m=$('#ck-msg');m.textContent=online?'접속 확인 중...':'점검 중...';
    try{const r=await api('GET','/api/selfcheck'+(online?'?online=1':''));const n={};r.checks.forEach(c=>n[c.status]=(n[c.status]||0)+1);
      $('#ck-res').innerHTML=checkRows(r.checks);m.textContent=`정상 ${n.ok||0} · 확인 필요 ${n.warn||0} · 문제 ${n.fail||0}`}
    finally{if($('#ck-msg')&&/중\.\.\.$/.test($('#ck-msg').textContent))$('#ck-msg').textContent=''}});
  $('#ck-run').onclick=run(false);$('#ck-online').onclick=run(true);
  $('#ck-bundle').onclick=guard(async()=>{const r=await fetch('/api/support/bundle');if(!r.ok)throw new Error('문제 신고 파일을 만들지 못했습니다');
    const blob=await r.blob(),name='traform-acl-support-'+new Date().toISOString().slice(0,10).replace(/-/g,'').slice(2)+'.json';
    const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),4000);
    $('#ck-msg').textContent=`내려받았습니다: ${name} — 브라우저의 다운로드 폴더를 확인하세요`;toast('문제 신고 파일을 만들었습니다')});
}
