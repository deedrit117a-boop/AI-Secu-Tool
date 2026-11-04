// 화면(브라우저) 자동 테스트 — 외부 패키지 없이 Node + 설치된 Edge/Chrome(헤드리스, CDP)만 사용
//
// 실행:  node tests/ui/run_ui_tests.js        (또는 run_ui_tests.bat)
// 동작:  tests/ui_server.py 를 임시 포트(8093)로 띄워서(임시 폴더의 가짜 git 저장소 + 가짜 GitLab/Jira) 브라우저로 화면을 실제로 눌러 본다.
//        실제 저장소/GitLab/Jira 에는 접속하지 않고, 실제 data/ 폴더도 쓰지 않는다.
const { spawn, execSync } = require('child_process');
const fs = require('fs'), path = require('path'), os = require('os'), http = require('http');

const ROOT = path.resolve(__dirname, '..', '..');
const PORT = +process.env.UI_TEST_PORT || 8093, CDP_PORT = +process.env.UI_TEST_CDP || 9333;
const URL = `http://127.0.0.1:${PORT}/`;
const BROWSER = [process.env.BROWSER, 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe', 'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe', 'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe'].filter(Boolean).find(p => fs.existsSync(p));
const sleep = ms => new Promise(r => setTimeout(r, ms));
const getJson = u => new Promise((res, rej) => http.get(u, r => { let b = ''; r.on('data', d => b += d); r.on('end', () => { try { res(JSON.parse(b)) } catch (e) { rej(e) } }) }).on('error', rej));
async function waitUntil(fn, ms, what) { const t0 = Date.now(); for (;;) { try { const v = await fn(); if (v) return v } catch (e) { } if (Date.now() - t0 > ms) throw new Error('시간 초과: ' + what); await sleep(250) } }

let server, browser, tmpDir, profile, cdp;
const procs = [];
function killAll() {
  for (const p of procs) { try { execSync(`taskkill /PID ${p.pid} /T /F`, { stdio: 'ignore' }) } catch (e) { } }
  // Edge/Chrome 은 시작 프로세스가 곧 종료되고 실제 브라우저는 다른 프로세스라서, 이 테스트 전용 프로필을 쓰는 프로세스를 찾아 종료한다
  if (profile) { try { execSync(`powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*${path.basename(profile)}*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"`, { stdio: 'ignore' }) } catch (e) { } }
}
process.on('exit', killAll);

class CDP {
  constructor(ws) { this.ws = ws; this.id = 0; this.cb = new Map(); this.exceptions = []; this.dialogs = [];
    ws.onmessage = ev => { const m = JSON.parse(ev.data);
      if (m.id && this.cb.has(m.id)) { this.cb.get(m.id)(m); this.cb.delete(m.id) }
      else if (m.method === 'Runtime.exceptionThrown') this.exceptions.push((m.params.exceptionDetails.exception && m.params.exceptionDetails.exception.description) || m.params.exceptionDetails.text);
      else if (m.method === 'Page.javascriptDialogOpening') { this.dialogs.push(m.params.message); this.send('Page.handleJavaScriptDialog', { accept: this.acceptDialogs !== false }) } }; }
  send(method, params = {}) { return new Promise((res, rej) => { const id = ++this.id; this.cb.set(id, m => m.error ? rej(new Error(method + ': ' + m.error.message)) : res(m.result)); this.ws.send(JSON.stringify({ id, method, params })) }) }
  // 노드 함수(문자열화)를 브라우저 안에서 실행하고 결과값을 돌려준다. 브라우저 안에서는 앱의 전역(S, api, ...)을 그대로 쓸 수 있다.
  async ev(fn, arg) { const expr = `(${fn.toString()})(${JSON.stringify(arg === undefined ? null : arg)})`;
    const r = await this.send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error('브라우저 예외: ' + ((r.exceptionDetails.exception && r.exceptionDetails.exception.description) || r.exceptionDetails.text));
    return r.result.value; }
  async go() { await this.send('Page.navigate', { url: URL }); await waitUntil(() => this.ev(() => typeof S !== 'undefined' && S.cfg && !!document.querySelector('#view')), 15000, '페이지 로드'); await sleep(300) }
  async waitFor(fn, arg, ms = 8000, what = '조건') { return waitUntil(() => this.ev(fn, arg), ms, what) }
}

const tests = [];
const test = (name, fn) => tests.push([name, fn]);
const eq = (a, b, msg) => { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`${msg || '값 불일치'}: 기대 ${JSON.stringify(b)} / 실제 ${JSON.stringify(a)}`) };
const ok = (c, msg) => { if (!c) throw new Error(msg || '조건 실패') };
const flag = n => fs.writeFileSync(path.join(tmpDir, n), '');
const unflag = n => { try { fs.unlinkSync(path.join(tmpDir, n)) } catch (e) { } };

// ───────────────────────────── 테스트 ─────────────────────────────
test('앱이 오류 없이 로드되고 버전이 표시된다', async () => {
  await cdp.go();
  const r = await cdp.ev(() => ({ foot: document.querySelector('#vfoot').innerText, banner: document.querySelector('#vbanner').innerText.trim(), tabs: [...document.querySelectorAll('.tab-btn')].map(b => b.textContent.trim()) }));
  ok(/v\d+\.\d+\.\d+/.test(r.foot), '버전 표시 없음: ' + r.foot);
  eq(r.banner, '', '버전 불일치/재시작 배너가 떠 있음');
  eq(r.tabs.length, 5);
});

test('유형 → 종류 → 환경 드롭다운을 하나씩 선택할 수 있다', async () => {
  await cdp.go();
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms));
    const pick = async (id, text) => { document.querySelector(id + ' button').click(); await w(120); [...document.querySelectorAll(id + ' .list>div')].find(d => d.textContent === text).click(); await w(500) };
    await pick('#c1', '게임환경'); await pick('#c2', 'bbz'); await pick('#c3', 'live');
    const hover = getComputedStyle(document.querySelector('.panel') || document.body).backgroundColor;
    return { kind: S.kind, group: S.group, env: S.envId, c3: document.querySelector('#c3 button').textContent };
  });
  eq([r.kind, r.group, r.env], ['game', 'bbz', 'g']);
});

test('Jira: 티켓번호를 입력하면 제목/상태가 표시된다', async () => {
  const t = await cdp.ev(async () => { const w = ms => new Promise(r => setTimeout(r, ms)); const i = document.querySelector('#ticket'); i.value = 'ISRIR-69281'; i.dispatchEvent(new Event('input')); await w(1500); return document.querySelector('#tkinfo').innerText });
  ok(t.includes('ISRIR-69281') && t.includes('테스트 티켓 제목'), 'tkinfo: ' + t);
});

test('main 브랜치에서는 규칙 수정이 막히고 배너가 안내한다', async () => {
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); S.tab = 'acl'; persist(); render(); await selectEnv(); await openSg('l-sg-bbz-x-sg'); await w(800);
    const banner = document.querySelector('#bbanner').innerText;
    S.sgData.ingress.push({ from_port: 443, to_port: 443, protocol: 'TCP', cidr_blocks: ['10.9.9.9/32'], security_groups: '', prefix_list_ids: [], description: 'tf_261020_ISRIR-1_b to x Connection' });
    await saveSg(); await w(300);
    return { banner, toast: document.querySelector('#toast').innerText, rules: S.sgData.ingress.length };
  });
  ok(r.banner.includes('작업 브랜치'), '배너 없음: ' + r.banner); ok(r.toast.includes('작업 브랜치가 아닙니다'), 'toast: ' + r.toast); eq(r.rules, 1, '차단 후 규칙이 되돌려져야 함');
});

test('규칙 검증: 호스트 비트 오류는 차단, 0.0.0.0/0 은 확인 모달', async () => {
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); const out = {};
    await api('POST', '/api/env/g/git/prepare', { ticket: 'ISRIR-1' }); await openSg('l-sg-bbz-x-sg'); await w(600);
    const mk = (c, d) => ({ from_port: 443, to_port: 443, protocol: 'TCP', cidr_blocks: [c], security_groups: '', prefix_list_ids: [], description: d || 'tf_261020_ISRIR-1_b to x Connection' });
    S.sgData.ingress.push(mk('10.0.0.1/24')); await saveSg(); await w(300); out.err = document.querySelector('#toast').innerText; out.afterErr = S.sgData.ingress.length;
    S.sgData.ingress.push(mk('0.0.0.0/0')); const p = saveSg(); await w(500); out.modal = !!document.querySelector('.modal') && document.querySelector('.modal').innerText.includes('전체 개방');
    document.querySelector('.modal .mc').click(); await p; await w(500); out.afterCancel = S.sgData.ingress.length;
    S.sgData.ingress.push(mk('10.5.5.5/32')); await saveSg(); await w(700); out.afterOk = S.sgData.ingress.length; return out;
  });
  ok(r.err.includes('호스트 비트'), r.err); eq(r.afterErr, 1); ok(r.modal, '위험 모달 없음'); eq(r.afterCancel, 1); eq(r.afterOk, 2);
});

test('선택 삭제 / IP로 규칙 삭제(미리보기 후) / 여러 SG에 적용', async () => {
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); const out = {};
    // 규칙 몇 개 만들기 (API)
    const sg = await api('GET', '/api/env/g/sg/l-sg-bbz-x-sg');
    for (const [c, p] of [['10.7.7.1/32', 1101], ['10.7.7.2/32', 1102], ['10.7.7.3/32', 1103]]) sg.ingress.push({ from_port: p, to_port: p, protocol: 'TCP', cidr_blocks: [c], security_groups: '', prefix_list_ids: [], description: 'tf_261020_ISRIR-1_c to x Connection' });
    await api('PUT', '/api/env/g/sg/l-sg-bbz-x-sg', sg); await openSg('l-sg-bbz-x-sg'); await w(600);
    // 선택 삭제: 1101
    const rows = [...document.querySelectorAll('.rsel')]; const idx = S.sgData.ingress.findIndex(r => r.from_port === 1101); rows[idx].checked = true;
    document.querySelector('#bdel').click(); await w(500); out.delModal = document.querySelector('.modal').innerText.includes('삭제'); document.querySelector('.modal .mo').click(); await w(1200);
    out.afterDel = S.sgData.ingress.some(r => r.from_port === 1101);
    // IP 로 삭제: 10.7.7.2 (미리보기 전에는 삭제 버튼 비활성)
    document.querySelector('#bipd').click(); await w(500); const m = document.querySelector('.modal');
    out.runDisabled = m.querySelector('#bd-run').disabled; m.querySelector('#bd-ips').value = '10.7.7.2'; m.querySelector('#bd-prev').click(); await w(900);
    out.preview = m.querySelector('#bd-msg').innerText; out.runEnabled = !m.querySelector('#bd-run').disabled; m.querySelector('#bd-run').click(); await w(1500);
    out.afterIp = S.sgData.ingress.some(r => r.from_port === 1102); if (document.querySelector('.modal')) document.querySelector('.modal .mo').click(); await w(300);
    // 다른 SG 에 적용: 1103 규칙을 y 에
    const i3 = S.sgData.ingress.findIndex(r => r.from_port === 1103); document.querySelectorAll('.rsel')[i3].checked = true; document.querySelector('#bsg').click(); await w(700);
    const mm = document.querySelector('.modal'); const cb = [...mm.querySelectorAll('.bt')].find(c => c.value === 'l-sg-bbz-y-sg'); cb.checked = true; cb.dispatchEvent(new Event('change'));
    mm.querySelector('#bs-prev').click(); await w(800); out.prevTxt = mm.querySelector('#bs-res').innerText; mm.querySelector('.mo').click(); await w(1500);
    const y = await api('GET', '/api/env/g/sg/l-sg-bbz-y-sg'); out.y = y.ingress.map(r => r.description); return out;
  });
  ok(r.delModal); eq(r.afterDel, false, '선택 삭제 실패'); eq(r.runDisabled, true, '미리보기 전 삭제 버튼 활성'); ok(r.preview.includes('삭제 1건'), r.preview); eq(r.runEnabled, true); eq(r.afterIp, false, 'IP 삭제 실패');
  ok(r.prevTxt.includes('l-sg-bbz-y-sg'), r.prevTxt); eq(r.y, ['tf_261020_ISRIR-1_c to y Connection'], '다른 SG 적용/설명 목적지 변경 실패');
});

test('CSV 업로드 미리보기 / 변경 내용 보기', async () => {
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); const out = {};
    await openSg('l-sg-bbz-x-sg'); await w(600);
    document.querySelector('#dv').click(); await w(800); out.diff = [...document.querySelectorAll('.modal pre .ln')].some(e => e.className.includes('add')); document.querySelector('.modal .mo').click(); await w(300);
    const csv = 'direction,protocol,from_port,to_port,source_type,source,description\ningress,tcp,22,22,cidr,10.3.3.3/32,tf_261020_ISRIR-1_d to x Connection\ningress,tcp,23,23,cidr,0.0.0.0/0,tf_261020_ISRIR-1_d to x Connection\n';
    const dt = new DataTransfer(); dt.items.add(new File([csv], 'a.csv', { type: 'text/csv' })); const inp = document.querySelector('#upf'); inp.files = dt.files; inp.dispatchEvent(new Event('change')); await w(1200);
    const m = document.querySelector('.modal'); out.modal = m ? m.innerText : ''; const before = S.sgData.ingress.length;
    m.querySelector('input[value=replace]').click(); m.querySelector('input[value=replace]').dispatchEvent(new Event('change')); await w(200); out.replaceShown = [...m.querySelectorAll('.pv')].map(p => p.style.display === 'none' ? 'hidden' : 'shown').join(',');
    m.querySelector('.mc').click(); await w(300); out.unchanged = S.sgData.ingress.length === before; return out;
  });
  ok(r.diff, '변경 내용 보기에 추가 줄 없음'); ok(r.modal.includes('위험 규칙') && r.modal.includes('추가 2건'), r.modal.slice(0, 200)); eq(r.replaceShown, 'hidden,shown'); ok(r.unchanged, '취소했는데 규칙이 바뀜');
});

test('Commit/Push 확인 창(diff, 최신 여부)과 변경 요약 보고서', async () => {
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); const out = {};
    S.tab = 'work'; persist(); render(); await w(1500);
    document.querySelector('#push').click(); await w(1800); const m = document.querySelector('.modal'); out.push = m ? m.innerText.slice(0, 200) : ''; out.diffColors = m ? [...m.querySelectorAll('pre .ln')].some(e => e.className.includes('add')) : false;
    if (m) m.querySelector('.mc').click(); await w(300);
    document.querySelector('#rpt').click(); await w(1500); const rm = document.querySelector('.modal'); out.report = rm ? rm.innerText.slice(0, 260) : ''; out.copyBtn = !!(rm && rm.querySelector('#rp-copy')); out.auditBtn = !!(rm && rm.querySelector('#rp-audit')); if (rm) rm.querySelector('.mo').click();
    return out;
  });
  ok(r.push.includes('Commit & Push 확인'), r.push); ok(r.diffColors, 'diff 색상 없음'); ok(r.report.includes('변경 요약 보고서') && r.report.includes('변경 SG'), r.report); ok(r.copyBtn); ok(r.auditBtn, '변경 기록 파일 버튼 없음');
});

test('빠른 작업 마법사: 규칙 추가 → push → MR → plan 이 끝까지 진행된다', async () => {
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); const out = {};
    const c = document.querySelector('#wzcard'); c.open = true;
    document.querySelector('#wz-ticket').value = 'ISRIR-1'; S.wzSel = new Set(['l-sg-bbz-x-sg']); document.querySelector('#wz-sgq').dispatchEvent(new Event('input'));
    document.querySelector('#wz-from').value = '6001'; document.querySelector('#wz-ips').value = '10.20.0.1\n10.20.0.2'; document.querySelector('#wz-src').value = 'match3';
    const p = runWizard(); await w(1200); out.modal = document.querySelector('.modal') ? document.querySelector('.modal').innerText.slice(0, 120) : '';
    document.querySelector('.modal .mo').click(); await p; await w(1200);
    out.steps = [...document.querySelectorAll('#wzs > div')].map(d => d.innerText.replace(/\n/g, ' ').slice(0, 40));
    out.iid = document.querySelector('#iid').value; return out;
  });
  ok(r.modal.includes('빠른 작업 실행 확인'), r.modal); ok(r.steps.length === 5 && r.steps.every(s => s.startsWith('✅')), JSON.stringify(r.steps)); eq(r.iid, '9');
});

test('작업 이력: 서버에 저장되어 새로고침해도 유지, 복제 버튼이 마법사를 채운다', async () => {
  await cdp.go();
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); const out = {};
    S.tab = 'work'; persist(); render(); await w(1800);
    out.steps = [...document.querySelectorAll('#hl details summary b')].map(b => b.textContent.slice(0, 16)); out.clone = !!document.querySelector('.wzc');
    document.querySelector('.wzc').click(); await w(400); out.fill = { ips: document.querySelector('#wz-ips').value, from: document.querySelector('#wz-from').value, ticket: document.querySelector('#wz-ticket').value };
    return out;
  });
  ok(r.steps.some(s => s.startsWith('규칙 추가')) && r.steps.some(s => s.startsWith('MR')), JSON.stringify(r.steps)); ok(r.clone); eq(r.fill.ips, '10.20.0.1/32\n10.20.0.2/32'); eq(r.fill.from, '6001'); eq(r.fill.ticket, '');
});

test('마법사: 새 SG 만들고 규칙 추가 / 규칙 삭제(IP 기준)', async () => {
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); const out = {};
    S.tab = 'work'; persist(); render(); await w(1800); document.querySelector('#wzcard').open = true;
    const setAct = v => { const a = document.querySelector('#wz-act'); a.value = v; a.dispatchEvent(new Event('change')) };
    // 새 SG
    setAct('newsg'); document.querySelector('#wz-ticket').value = 'ISRIR-1'; document.querySelector('#wz-new').value = 'zz'; document.querySelector('#wz-new').dispatchEvent(new Event('input'));
    document.querySelector('#wz-from').value = '6002'; document.querySelector('#wz-ips').value = '10.30.0.1';
    let p = runWizard(); await w(1500); out.newModal = document.querySelector('.modal') ? document.querySelector('.modal').innerText.includes('새 SG') : false; document.querySelector('.modal .mo').click(); await p; await w(1500);
    out.newSteps = [...document.querySelectorAll('#wzs > div')].map(d => d.innerText.slice(0, 1)).join('');
    const zz = await api('GET', '/api/env/g/sg/l-sg-bbz-zz-sg'); out.zz = zz.ingress.map(r => r.cidr_blocks[0] + ' ' + r.from_port);
    // 삭제
    S.sgs = (await api('GET', '/api/env/g/sgs')).sgs; S.wzSel = new Set(['l-sg-bbz-zz-sg']); render(); await w(1800); document.querySelector('#wzcard').open = true;
    setAct('del'); document.querySelector('#wz-ticket').value = 'ISRIR-1'; document.querySelector('#wz-ips').value = '10.30.0.1'; document.querySelectorAll('.wz-sg').forEach(c => { c.checked = c.value === 'l-sg-bbz-zz-sg'; c.dispatchEvent(new Event('change')) });
    p = runWizard(); await w(1500); out.delModal = document.querySelector('.modal') ? document.querySelector('.modal').innerText.includes('삭제') : false; document.querySelector('.modal .mo').click(); await p; await w(1500);
    out.delSteps = [...document.querySelectorAll('#wzs > div')].map(d => d.innerText.slice(0, 1)).join('');
    out.zzAfter = (await api('GET', '/api/env/g/sg/l-sg-bbz-zz-sg')).ingress.length; return out;
  });
  ok(r.newModal, '새 SG 확인 모달 없음'); eq(r.newSteps, '✅✅✅✅✅', '새 SG 단계'); eq(r.zz, ['10.30.0.1/32 6002']);
  ok(r.delModal, '삭제 확인 모달 없음'); eq(r.delSteps, '✅✅✅✅✅', '삭제 단계'); eq(r.zzAfter, 0, 'IP 기준 삭제 실패');
});

test('MR 중복 방지: 열린 MR 이 있으면 안내하고 새로 만들지 않는다', async () => {
  flag('mr.flag'); await cdp.go();
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); S.tab = 'work'; persist(); render(); await w(1800);
    const before = { ex: document.querySelector('#mrex').innerText, btn: document.querySelector('#mkmr').innerText };
    document.querySelector('#mkmr').click(); await w(1500);
    return { before, hist: [...document.querySelectorAll('#hl details summary')].slice(0, 1).map(s => s.innerText) };
  });
  ok(r.before.ex.includes('이미 열린 MR'), r.before.ex); eq(r.before.btn, '기존 MR 연결'); ok(r.hist[0].includes('기존 MR'), r.hist[0]);
});

test('Atlantis: plan 성공 시 apply 가능 표시', async () => {
  flag('note.flag');
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); document.querySelector('#iid').value = '9'; document.querySelector('#iid').dispatchEvent(new Event('change'));
    document.querySelector('#plan').click(); await w(9500); return { plst: document.querySelector('#plst').innerText };
  });
  ok(r.plst.includes('apply 가능'), r.plst);
});

test('Atlantis: plan 실패 시 원인 안내와 다시 실행/Push 이동 버튼', async () => {
  unflag('note.flag'); flag('noteerr.flag');
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms));
    document.querySelector('#plan').click(); await w(9500);
    const box = document.querySelector('#hl .warnbox'); return { hint: box ? box.innerText : '', retry: !!document.querySelector('.hb-retry'), push: !!document.querySelector('.hb-push') };
  });
  ok(r.hint.includes('브랜치가 원격에 없습니다'), r.hint); ok(r.retry && r.push, '버튼 없음');
  unflag('noteerr.flag');
  const n = await cdp.ev(async () => { const w = ms => new Promise(r => setTimeout(r, ms)); const before = histLoad(histKey()).length; document.querySelector('.hb-retry').click(); await w(1200); return histLoad(histKey()).length - before });
  eq(n, 1, '다시 실행 이력이 추가되어야 함');
});

test('환경 점검/정리: 중복 환경 ID 를 찾아 정리한다', async () => {
  const cfgPath = path.join(tmpDir, 'config.json'); const cfg = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
  cfg.environments.push({ ...cfg.environments[1], label: '복제본', sg_dir: 'aws/plat/sg/sg_rule' });   // 같은 ID 가 두 번
  fs.writeFileSync(cfgPath, JSON.stringify(cfg, null, 2)); await cdp.go();
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); S.tab = 'cfg'; persist(); render(); await w(500);
    const banner = !!document.querySelector('#erepair2'); document.querySelector('#erepair').click(); await w(1000);
    const m = document.querySelector('.modal'); const txt = m ? m.innerText : ''; if (m) m.querySelector('.mo').click(); await w(1500);
    const ids = S.cfg.environments.map(e => e.id); return { banner, txt, unique: ids.length === new Set(ids).size, n: ids.length };
  });
  ok(r.banner, '중복 경고 배너 없음'); ok(r.txt.includes('중복 환경 ID'), r.txt.slice(0, 120)); ok(r.unique, '정리 후에도 중복'); eq(r.n, 3);
});

test('프리셋: 설정에서 저장하면 마법사에서 불러올 수 있다', async () => {
  await cdp.go();
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); S.tab = 'cfg'; persist(); render(); await w(500);
    document.querySelector('#pr-add').click(); const tr = document.querySelector('#pr-body tr:last-child');
    tr.querySelector('.pr-n').value = 'SGP Office'; tr.querySelector('.pr-i').value = '211.34.57.0/24\n10.0.0.5'; document.querySelector('#pr-save').click(); await w(1200);
    S.kind = 'game'; S.group = 'bbz'; S.envId = 'g'; S.tab = 'work'; persist(); renderPickers(); await selectEnv(); await w(1500);
    document.querySelector('#wzcard').open = true; const sel = document.querySelector('#wzcard .presetpick'); sel.value = '0'; sel.dispatchEvent(new Event('change')); await w(300);
    return { ips: document.querySelector('#wz-ips').value, src: document.querySelector('#wz-src').value, saved: S.cfg.presets.length };
  });
  eq(r.saved, 1); eq(r.ips, '211.34.57.0/24\n10.0.0.5/32'); eq(r.src, 'SGP Office');
});

test('통합 검색: IP 로 찾으면 환경이 자동 선택되고 사용처 보고서가 열린다', async () => {
  await cdp.go();
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); S.tab = 'work'; S.kind = ''; S.group = ''; S.envId = ''; persist(); render(); await w(300);
    const q = document.querySelector('#gq'); q.focus(); q.value = '10.1.1.1'; q.dispatchEvent(new Event('input')); await w(2500);
    const count = document.querySelectorAll('#gres .gi').length; document.querySelector('#gq-rp').dispatchEvent(new MouseEvent('mousedown', { bubbles: true })); await w(1200);
    const report = document.querySelector('.modal') ? document.querySelector('.modal').innerText.slice(0, 80) : ''; if (document.querySelector('.modal')) document.querySelector('.modal .mo').click(); await w(300);
    q.value = '10.1.1.1'; q.dispatchEvent(new Event('input')); await w(2200); q.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); await w(2500);
    return { count, report, env: S.envId, tab: S.tab, sg: S.sg };
  });
  ok(r.count >= 1, '검색 결과 없음'); ok(r.report.includes('사용처 보고서'), r.report); eq(r.tab, 'acl'); eq(r.env, 'g'); ok(!!r.sg);
});

test('통합 검색: SG 를 고르면 규칙 필터가 비어 보이지 않는다 (검색어가 규칙이 아니라 SG 별칭/태그에서 찾아진 경우)', async () => {
  await cdp.go();
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); S.kind = 'game'; S.group = 'bbz'; S.envId = 'g'; S.tab = 'acl'; persist(); renderPickers(); await selectEnv(); await w(800);
    await openSg('l-sg-bbz-x-sg'); await w(400);
    const rows = () => [...document.querySelectorAll('#detail tbody tr:not(.edit)')].filter(tr => tr.style.display !== 'none').length;
    S.rf = 'no-such-domain.example.net'; fitRuleFilter(); await w(200);
    const cleared = { rf: S.rf, shown: rows(), input: document.querySelector('#rf').value };
    S.rf = 'ISRIR-1_a'; fitRuleFilter(); await w(200);                      // 규칙에 실제로 있는 문구는 그대로 필터로 쓴다
    return { cleared, kept: { rf: S.rf, shown: rows() } };
  });
  eq(r.cleared.rf, ''); eq(r.cleared.input, ''); ok(r.cleared.shown >= 1, '필터를 비웠는데 규칙이 안 보임'); eq(r.kept.rf, 'ISRIR-1_a'); ok(r.kept.shown >= 1, '일치하는 규칙이 안 보임');
});

test('환경설정: Jira 카드와 서버 재시작 링크가 있다', async () => {
  const r = await cdp.ev(async () => { S.tab = 'cfg'; persist(); render(); await new Promise(r => setTimeout(r, 400)); return { jira: !!document.querySelector('#jr-save') && !!document.querySelector('#jr-test'), restart: !!document.querySelector('#vrs'), url: document.querySelector('#jr-url').value } });
  ok(r.jira, 'Jira 카드 없음'); ok(r.restart, '재시작 링크 없음'); eq(r.url, 'https://jira.smilegate.net');
});

test('환경설정: 백업 파일을 올리면 내용을 보여주고 확인 후 설정이 복구된다', async () => {
  await cdp.go();
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); S.tab = 'cfg'; persist(); render(); await w(1200);
    const card = !!document.querySelector('#bk-go') && document.querySelectorAll('.bk-g').length === 4;
    const text = await (await fetch('/api/backup/download?groups=settings,personal')).text(); const orig = S.account;
    await api('PUT', '/api/local', { account: 'changed-acct' }); await reloadCfg();
    const dt = new DataTransfer(); dt.items.add(new File([text], 'b.json', { type: 'application/json' }));
    const inp = document.querySelector('#bk-file'); inp.files = dt.files; inp.dispatchEvent(new Event('change')); await w(1200);
    const preview = document.querySelector('#bk-prev').innerText; const boxes = document.querySelectorAll('.bk-r').length;
    document.querySelector('#bk-apply').click(); await w(2500);
    const bad = new DataTransfer(); bad.items.add(new File(['not json'], 'x.json')); const inp2 = document.querySelector('#bk-file'); inp2.files = bad.files; inp2.dispatchEvent(new Event('change')); await w(600);
    return { card, preview, boxes, orig, after: S.account, badMsg: document.querySelector('#bk-prev').innerText };
  });
  ok(r.card, '백업 카드 없음'); ok(r.preview.includes('local.json') && r.preview.includes('config.json'), r.preview); eq(r.boxes, 2); eq(r.after, r.orig); ok(r.badMsg.includes('JSON'), r.badMsg);
});

test('AWS 자격인증 표시: 인증 중이면 주황색 타원, 로그인이 필요하면 바탕색으로 돌아간다', async () => {
  unflag('login.flag'); await cdp.go();
  const step = async () => cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); while (awsPill.busy) await w(200);
    await awsPill.refresh(true); await w(200); const b = document.querySelector('#awspill');
    return { on: b.classList.contains('on'), label: b.getAttribute('aria-label'), bg: getComputedStyle(b).backgroundColor, text: b.innerText };
  });
  await cdp.ev(async () => { S.kind = 'game'; S.group = 'bbz'; S.envId = 'g'; S.tab = 'acl'; persist(); renderPickers(); await selectEnv();
    await api('POST', '/api/aws/profile-map', { key: 'bbz|live', profile: 'qa-bbz-global', region: 'ap-northeast-2' }) });
  const on = await step(); flag('login.flag'); let off; try { off = await step() } finally { unflag('login.flag') }
  ok(on.on && on.label.includes('인증 중'), JSON.stringify(on)); ok(on.text.includes('AWS 자격인증'), on.text); ok(!off.on && off.label.includes('인증 안 됨'), JSON.stringify(off));
  ok(on.bg !== off.bg, '켜졌을 때와 꺼졌을 때 색이 같음: ' + on.bg); ok(off.bg === 'rgba(0, 0, 0, 0)', '꺼진 상태는 투명(바탕색)이어야 함: ' + off.bg);
});

test('AWS 규칙 비교 보고서: 인증이 있으면 차이를 보여주고, 없으면 넘어간다는 안내만 보여준다', async () => {
  unflag('login.flag'); await cdp.go();
  const run = () => cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms));
    S.kind = 'game'; S.group = 'bbz'; S.envId = 'g'; S.tab = 'acl'; persist(); renderPickers(); await selectEnv(); await w(500);
    document.querySelector('#awscmp').click(); for (let i = 0; i < 30 && !document.querySelector('.modal'); i++) await w(250);
    const m = document.querySelector('.modal'); const txt = m ? m.innerText : ''; const title = m ? m.querySelector('h3').innerText : '';
    if (m) { const c = m.querySelector('.mc'); (c || m.querySelector('.mo')).click() } await w(300);
    return { title, txt };
  });
  const good = await run(); flag('login.flag'); let skipped; try { skipped = await run() } finally { unflag('login.flag') }
  eq(good.title, 'AWS 규칙 비교 보고서'); ok(good.txt.includes('l-sg-bbz-x-sg') && good.txt.includes('10.9.9.9/32') && good.txt.includes('AWS에만 있음'), good.txt.slice(0, 300));
  ok(good.txt.includes('엑셀(.xlsx) 다운로드') && good.txt.includes('AWS에만 있는 규칙 복사'), good.txt.slice(-300));
  ok(skipped.title.includes('넘어갑니다') && skipped.txt.includes('AWS 인증이 되어 있지 않아'), skipped.title + ' / ' + skipped.txt.slice(0, 200));
});

test('백업 안내: 백업할 때가 되면 위쪽에 한 줄로 알리고, 오늘은 그만 보기를 누르면 사라진다', async () => {
  await cdp.go();
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); const old = api; localStorage.removeItem('bknudge');
    api = async (m, u, b) => (u || '').startsWith('/api/backup/info') ? { groups: [], status: { due: true, last: '2026-01-01 09:00:00', days: 30 } } : old(m, u, b);
    let shown, gone, quiet;
    try {
      await backupNudge(true); shown = document.querySelector('#bknudge').innerText;
      document.querySelector('#bkn-x').click(); gone = document.querySelector('#bknudge').innerText;
      await backupNudge(false); quiet = document.querySelector('#bknudge').innerText;
      api = async (m, u, b) => (u || '').startsWith('/api/backup/info') ? { groups: [], status: { due: false } } : old(m, u, b);
      await backupNudge(true); var none = document.querySelector('#bknudge').innerText;
    } finally { api = old; localStorage.removeItem('bknudge') }
    return { shown, gone, quiet, none };
  });
  ok(r.shown.includes('30일') && r.shown.includes('백업하기'), r.shown); eq(r.gone, ''); eq(r.quiet, ''); eq(r.none, '');
});

test('환경설정: 정책 규칙 카드에서 허용 예외를 저장하면 서버 정책에 반영된다', async () => {
  await cdp.go();
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); S.tab = 'cfg'; persist(); render(); await w(1500);
    const has = !!document.querySelector('#pl-save') && !!document.querySelector('#pl-mp');
    document.querySelector('#pl-add').click(); const tr = document.querySelector('#pl-body tr.plx:last-child');
    tr.querySelector('.pl-n').value = '사무실 SSH'; tr.querySelector('.pl-c').value = '211.34.57.0/24'; tr.querySelector('.pl-p').value = '22';
    document.querySelector('#pl-save').click(); await w(1200);
    const saved = (await api('GET', '/api/policy')).policy; const msg = document.querySelector('#pl-msg').innerText;
    tr.querySelector('.pl-c').value = 'bad'; document.querySelector('#pl-save').click(); await w(800); const err = document.querySelector('#toast') ? document.querySelector('#toast').innerText : '';
    await api('PUT', '/api/policy', { policy: { exceptions: [] } }); await reloadCfg();
    return { has, saved, msg, err };
  });
  ok(r.has, '정책 카드 없음'); eq(r.saved.exceptions.length, 1); eq(r.saved.exceptions[0].cidrs[0], '211.34.57.0/24'); ok(r.msg.includes('저장했습니다'), r.msg); ok(r.err.includes('대역 형식'), r.err);
});

test('규칙 점검 보고서: 만료 / 정리 제안 / 접근 경로 탭이 열린다', async () => {
  await cdp.go();
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); S.kind = 'game'; S.group = 'bbz'; S.envId = 'g'; S.tab = 'acl'; persist(); renderPickers(); await selectEnv(); await w(500);
    document.querySelector('#hyg').click(); for (let i = 0; i < 30 && !document.querySelector('.modal #rp-body'); i++) await w(200); await w(1200);
    const m = () => document.querySelector('.modal'); const out = { title: m().querySelector('h3').innerText, expiry: m().innerText };
    m().querySelector('[data-t=cleanup]').click(); await w(1500); out.cleanup = m().innerText;
    m().querySelector('[data-t=reach]').click(); await w(500); m().querySelector('#rc-q').value = '10.1.1.1'; m().querySelector('#rc-go').click(); await w(1500); out.reach = m().innerText; out.topo = !!m().querySelector('svg .tp-node'); out.grip = !!m().querySelector('.rz-grip');
    m().querySelector('#rc-q').value = 'nope'; m().querySelector('#rc-go').click(); await w(800); out.bad = (document.querySelector('#toast') || {}).innerText || '';
    (m().querySelector('.mc') || m().querySelector('.mo')).click();
    return out;
  });
  eq(r.title, '규칙 점검 보고서'); ok(r.expiry.includes('만료일이 지난 규칙') && r.expiry.includes('만료:2026-12-31'), r.expiry.slice(0, 200));
  ok(r.cleanup.includes('SG') && r.cleanup.includes('제안만 하고'), r.cleanup.slice(0, 200)); ok(r.reach.includes('열려 있는 SG') && r.reach.includes('10.1.1.1'), r.reach.slice(0, 300)); ok(r.bad.includes('IP 또는 CIDR'), r.bad); ok(r.topo, '토폴로지 그림 없음'); ok(r.grip, '크기 조절 손잡이 없음');
});

test('위험 규칙 확인: 승인 사유를 적어야 저장되고 기록이 남는다', async () => {
  await cdp.go();
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); const out = {};
    S.allowMain = true; S.kind = 'game'; S.group = 'bbz'; S.envId = 'g'; S.tab = 'acl'; persist(); renderPickers(); await selectEnv(); await w(500);
    await openSg('l-sg-bbz-x-sg'); await w(300);
    const n0 = S.sgData.ingress.length; S.sgData.ingress.push({ protocol: 'TCP', from_port: 22, to_port: 22, cidr_blocks: ['0.0.0.0/0'], security_groups: '', prefix_list_ids: [], description: 'tf_261101_ISRIR-1_a to x Connection' });
    const p = saveSg(); for (let i = 0; i < 20 && !document.querySelector('#rk-why'); i++) await w(150);
    out.asked = !!document.querySelector('#rk-why');
    document.querySelector('.modal .mo').click(); await w(500);                    // 사유 없이 확인 -> 다시 묻는다
    out.again = !!document.querySelector('#rk-why');
    document.querySelector('#rk-why').value = '사무실 이전 팀장 승인'; document.querySelector('.modal .mo').click(); await p; await w(500);
    out.saved = (await api('GET', '/api/env/g/sg/l-sg-bbz-x-sg')).ingress.length === n0 + 1;
    out.rec = (await api('GET', '/api/env/g/risk-approvals')).approvals.filter(a => a.reason === '사무실 이전 팀장 승인').length;
    await api('POST', '/api/env/g/undo'); S.allowMain = false; await afterWorkChange(); return out;
  });
  ok(r.asked, '사유 입력칸이 없음'); ok(r.again, '사유 없이 통과함'); ok(r.saved, '저장되지 않음'); eq(r.rec, 1, '승인 기록이 없음');
});

test('규칙 점검 보고서: SG 관계 / 기준 점검 / 티켓 찾기 탭과 정리 제안 삭제 버튼, 경유 옵션이 있다', async () => {
  await cdp.go();
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); S.kind = 'game'; S.group = 'bbz'; S.envId = 'g'; S.tab = 'acl'; persist(); renderPickers(); await selectEnv(); await w(500);
    document.querySelector('#hyg').click(); for (let i = 0; i < 30 && !document.querySelector('.modal #rp-body'); i++) await w(200); await w(800);
    const m = () => document.querySelector('.modal'); const out = { tabs: [...m().querySelectorAll('#rp-tabs button')].map(b => b.innerText) };
    m().querySelector('[data-t=score]').click(); await w(1500); out.score = m().querySelector('#rp-body').innerText;
    m().querySelector('[data-t=refs]').click(); await w(500); m().querySelector('#sr-q').value = 'l-sg-bbz-x-sg'; m().querySelector('#sr-go').click(); await w(1500); out.refs = m().querySelector('#rp-body').innerText;
    m().querySelector('#sr-q').value = 'zzz-none'; m().querySelector('#sr-go').click(); await w(800); out.refsBad = (document.querySelector('#toast') || {}).innerText || '';
    m().querySelector('[data-t=ticket]').click(); await w(500); m().querySelector('#tk-q').value = 'ISRIR-99999'; m().querySelector('#tk-go').click(); await w(2500); out.ticket = m().querySelector('#rp-body').innerText;
    m().querySelector('[data-t=cleanup]').click(); await w(1500); out.del = !!m().querySelector('#cl-del');
    m().querySelector('[data-t=reach]').click(); await w(500); out.via = !!m().querySelector('#rc-via');
    out.wide = m().classList.contains('rz'); (m().querySelector('.mc') || m().querySelector('.mo')).click(); return out;
  });
  eq(r.tabs.length, 8); ok(r.score.includes('환경별 점수') && r.score.includes('점'), r.score.slice(0, 120)); ok(r.refs.includes('l-sg-bbz-x-sg'), r.refs.slice(0, 160));
  ok(r.refsBad.includes('찾지 못했습니다'), r.refsBad); ok(r.ticket.includes('ISRIR-99999') && r.ticket.includes('규칙'), r.ticket.slice(0, 160)); ok(r.del && r.via && r.wide);
});

test('v1.15: 빠른 작업 apply 선택 박스(삭제 작업이면 꺼짐), 요청 양식 창, 보고서 담당자별/감사 탭, 메타 담당자 칸', async () => {
  await cdp.go();
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); const out = {}; S.kind = 'game'; S.group = 'bbz'; S.envId = 'g'; S.tab = 'work'; persist(); renderPickers(); await selectEnv(); render(); await w(1500);
    const c = document.querySelector('#wzcard'); c.open = true; c.dispatchEvent(new Event('toggle'));
    const ap = document.querySelector('#wz-apply'); out.apply0 = ap && ap.checked === false && ap.disabled === false;
    ap.checked = true; document.querySelector('#wz-plan').checked = false; document.querySelector('#wz-plan').dispatchEvent(new Event('change')); out.apply1 = ap.disabled && !ap.checked;
    document.querySelector('#wz-plan').checked = true; document.querySelector('#wz-plan').dispatchEvent(new Event('change')); out.apply2 = !ap.disabled;
    ap.checked = true; document.querySelector('#wz-act').value = 'del'; document.querySelector('#wz-act').dispatchEvent(new Event('change')); out.apply3 = ap.disabled && !ap.checked;
    document.querySelector('#wz-act').value = 'add'; document.querySelector('#wz-act').dispatchEvent(new Event('change'));
    document.querySelector('#wz-tpl').click(); for (let i = 0; i < 40 && !document.querySelector('.modal'); i++) await w(150);
    out.tpl = document.querySelector('.modal') ? document.querySelector('.modal').innerText : ''; const mo = document.querySelector('.modal .mo'); if (mo) mo.click(); await w(300);
    out.steps = AUTO_STEPS.map(s => s.id).join(',');
    S.tab = 'acl'; persist(); render(); await w(500); document.querySelector('#hyg').click(); for (let i = 0; i < 30 && !document.querySelector('.modal #rp-body'); i++) await w(200); await w(600);
    const m = () => document.querySelector('.modal');
    m().querySelector('[data-t=owners]').click(); await w(1500); out.owners = m().querySelector('#rp-body').innerText;
    m().querySelector('[data-t=audit]').click(); await w(600); out.audit = m().querySelector('#rp-body').innerText; out.auditHref = m().querySelector('#au-dl') ? m().querySelector('#au-dl').getAttribute('href') : '';
    m().querySelector('[data-t=expiry]').click(); await w(1200); out.ow = !!m().querySelector('#rp-ow'); (m().querySelector('.mc') || m().querySelector('.mo')).click(); await w(300);
    S.tab = 'meta'; persist(); render(); await w(900); out.metaOwner = !!document.querySelector('.m-ow') && document.querySelector('#view').innerText.includes('담당자');
    return out;
  });
  ok(r.apply0 && r.apply1 && r.apply2 && r.apply3, JSON.stringify([r.apply0, r.apply1, r.apply2, r.apply3]));
  ok(r.tpl.includes('Source IP') && r.tpl.includes('Destination IP') && r.tpl.includes('Service Port'), r.tpl.slice(0, 160)); eq(r.steps, 'prep,rules,push,mr,plan,apply,jira');
  ok(r.owners.includes('담당자') && r.owners.includes('(미지정)'), r.owners.slice(0, 160)); ok(r.audit.includes('감사') === false || r.audit.includes('Excel'), r.audit.slice(0, 120));
  ok(/^\/api\/report\/audit-xlsx\?from=\d{4}-\d{2}-\d{2}&to=/.test(r.auditHref), r.auditHref); ok(r.ow && r.metaOwner);
});

test('v1.16 UX: 오류 알림(복사·닫기·Esc), 테마·글자 크기, 표 정렬·찾기, 창 Enter 확인·위험 창 포커스, 창 대기, 처음 안내', async () => {
  await cdp.go();
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); const out = {};
    toast('오류 시험 메시지', true); const t = document.querySelector('#toast'); out.errBtns = !!t.querySelector('.tcp') && !!t.querySelector('.tx');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); out.escHide = t.style.display === 'none';
    toast('성공 알림'); out.okBtns = !!t.querySelector('.tx'); t.style.display = 'none';
    toast('오류 2', true); t.querySelector('.tx').click(); out.xHide = t.style.display === 'none';
    const th = document.querySelector('#ux-th'); th.click(); out.t1 = document.documentElement.dataset.theme; th.click(); out.t2 = document.documentElement.dataset.theme; th.click(); out.t3 = document.documentElement.dataset.theme || 'auto';
    document.querySelector('#ux-zp').click(); out.z1 = document.documentElement.style.getPropertyValue('--zoom'); document.querySelector('#ux-zm').click(); out.z2 = document.documentElement.style.getPropertyValue('--zoom');
    const host = document.createElement('div'); document.body.appendChild(host);
    host.innerHTML = '<table class="rp-t"><thead><tr><th>이름</th><th>수</th></tr></thead><tbody>' + [10, 9, 100, 2, 33, 4, 5, 6, 7, 8].map(n => `<tr><td>n${n}</td><td>${n}</td></tr>`).join('') + '</tbody></table>';
    const tb = host.querySelector('table'); uxTable(tb); out.find = !!host.querySelector('.rp-q');
    tb.tHead.rows[0].cells[1].click(); out.asc = [...tb.tBodies[0].rows].map(x => x.cells[1].innerText).join(',');
    tb.tHead.rows[0].cells[1].click(); out.desc = tb.tBodies[0].rows[0].cells[1].innerText;
    const q = host.querySelector('.rp-q'); q.value = 'n3'; q.dispatchEvent(new Event('input')); out.filtered = [...tb.tBodies[0].rows].filter(x => x.style.display !== 'none').length; host.remove();
    const p1 = showModal('입력 시험', '<input type="text" id="zz">', '확인', null, { collect: o => ({ v: o.querySelector('#zz').value }) });
    const zz = document.querySelector('#zz'); zz.value = 'abc'; zz.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); const r1 = await p1; out.enter = r1 && r1.v;
    const p2 = showModal('위험 시험', '<div>x</div>', '실행', null, { danger: true }); out.dangerFocus = document.activeElement.classList.contains('mc') && document.querySelector('.mo').classList.contains('danger-fill'); document.querySelector('.mc').click(); await p2;
    const p3 = showModal('먼저 열린 창', '<div>a</div>', '확인'); let waited = false; const pw = waitNoModal('시험 창').then(() => { waited = true });
    await w(700); out.waitBar = (document.querySelector('#jobbar') || {}).innerText || ''; out.notYet = !waited; document.querySelector('.mo').click(); await p3; await pw; out.after = waited; await w(100);
    ls.set('hintWork', false); S.kind = 'game'; S.group = 'bbz'; S.envId = 'g'; S.tab = 'work'; persist(); renderPickers(); await selectEnv(); render(); await w(1200);
    out.hint = !!document.querySelector('#wk-hint'); const c = document.querySelector('#wzcard'); c.open = true;
    const ap = document.querySelector('#wz-apply'); ap.checked = true; ap.dispatchEvent(new Event('change')); out.chip = document.querySelector('#wz-optsum').innerText + '|' + document.querySelector('#wz-optsum').className; ap.checked = false; ap.dispatchEvent(new Event('change'));
    document.querySelector('#wk-hint-x').click(); out.hintGone = !document.querySelector('#wk-hint') && ls.get('hintWork', false) === true; ls.set('hintWork', true);
    S.tab = 'acl'; persist(); render(); await w(500); document.querySelector('#hyg').click(); for (let i = 0; i < 30 && !document.querySelector('.modal #rp-body'); i++) await w(200); await w(500);
    document.querySelector('.modal [data-t=score]').click(); await w(1500); out.srt = !!document.querySelector('.modal table.rp-t th.srt'); (document.querySelector('.modal .mc') || document.querySelector('.modal .mo')).click();
    ls.set('uxTheme', 'auto'); ls.set('uxZoom', 1); uxApplyPrefs();
    return out;
  });
  ok(r.errBtns && r.escHide && !r.okBtns && r.xHide, JSON.stringify([r.errBtns, r.escHide, r.okBtns, r.xHide])); eq(r.t1, 'light'); eq(r.t2, 'dark'); eq(r.t3, 'auto'); eq(r.z1, '1.1'); eq(r.z2, '1');
  ok(r.find && r.asc === '2,4,5,6,7,8,9,10,33,100' && r.desc === '100' && r.filtered === 1, JSON.stringify([r.find, r.asc, r.desc, r.filtered]));
  eq(r.enter, 'abc'); ok(r.dangerFocus); ok(r.notYet && r.waitBar.includes('확인 대기') && r.after, JSON.stringify([r.notYet, r.waitBar, r.after]));
  ok(r.hint && r.hintGone && r.chip.startsWith('plan 까지 + apply') && r.chip.includes('danger'), JSON.stringify([r.hint, r.hintGone, r.chip])); ok(r.srt);
});

test('v1.17 한 화면: 작업 바, Ctrl+K 팔레트, 주소(#) 복원·뒤로가기, 최근 칩, 보고서 탭 기억', async () => {
  await cdp.go();
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); const out = {};
    S.kind = 'game'; S.group = 'bbz'; S.envId = 'g'; S.tab = 'acl'; persist(); renderPickers(); await selectEnv(); render(); await w(1200);
    const bar = document.querySelector('#actbar'); out.bar = bar ? bar.innerText : ''; out.btns = ['ab-push', 'ab-plan', 'ab-wz', 'ab-rp', 'ab-k'].filter(id => document.querySelector('#' + id)).join(',');
    out.hash1 = location.hash;
    S.tab = 'meta'; persist(); render(); await w(300); out.hash2 = location.hash;
    history.back(); await w(1500); out.back = S.tab;
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true, bubbles: true })); await w(200);
    out.pal = !!document.querySelector('#palette'); const q = document.querySelector('#pal-q'); q.value = '메타'; q.dispatchEvent(new Event('input')); await w(100);
    out.palItems = [...document.querySelectorAll('#pal-l .pi')].map(x => x.innerText).join('|');
    q.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); await w(900); out.palTab = S.tab; out.palGone = !document.querySelector('#palette');
    S.tab = 'acl'; persist(); render(); await w(300);
    ls.set('recentEnv', [{ e: 'g', t: 'ISRIR-11' }, { e: 'g', t: 'ISRIR-12' }]); dockRecentDraw(); out.chips = document.querySelectorAll('#recent .rc').length;
    ls.set('rpTab', 'score'); document.querySelector('#ab-rp').click(); for (let i = 0; i < 30 && !document.querySelector('.modal #rp-body'); i++) await w(200); await w(500);
    out.rpOn = (document.querySelector('.modal [data-t=score]') || {}).className || ''; (document.querySelector('.modal .mc') || document.querySelector('.modal .mo')).click(); ls.set('rpTab', 'expiry');
    return out;
  });
  ok(r.bar.includes('⎇') && r.btns === 'ab-push,ab-plan,ab-wz,ab-rp,ab-k', JSON.stringify([r.bar, r.btns]));
  ok(r.hash1.includes('tab=acl') && r.hash1.includes('env=g') && r.hash2.includes('tab=meta'), r.hash1 + ' ' + r.hash2); eq(r.back, 'acl');
  ok(r.pal && r.palItems.includes('메타') && r.palTab === 'meta' && r.palGone, JSON.stringify([r.pal, r.palItems, r.palTab])); eq(r.chips >= 2, true); ok(r.rpOn.includes('on'), r.rpOn);
});

test('v1.17 옆 패널: 접근제어 탭에서 빠른 작업 패널, SG 패널(규칙·메타 저장), 검색 결과 미리보기, 보고서의 SG 링크', async () => {
  await cdp.go();
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); const out = {};
    S.kind = 'game'; S.group = 'bbz'; S.envId = 'g'; S.tab = 'acl'; persist(); renderPickers(); await selectEnv(); render(); await w(1000);
    await openWizardDrawer({ sg: 'l-sg-bbz-x-sg' }); await w(500); const d = document.querySelector('#drawer');
    out.wz = d && d.classList.contains('open') && !!d.querySelector('#wz-act') && !!d.querySelector('#wz-run'); out.wzSel = [...d.querySelectorAll('.wz-sg:checked')].map(x => x.value).join(',');
    d.querySelector('.dw-x').click(); await w(400); out.closed = !d.classList.contains('open');
    await openSgPanel('g', 'l-sg-bbz-x-sg'); await w(300); const b = document.querySelector('#drawer .dw-b');
    out.rules = b.querySelectorAll('tbody tr').length; out.acts = b.querySelectorAll('.sp-act').length; out.title = document.querySelector('#drawer .dw-t').innerText;
    b.querySelector('#sp-ow').value = '패널팀'; b.querySelector('#sp-ms').click(); await w(800); out.owner = (S.meta.envs.g.sgs['l-sg-bbz-x-sg'] || {}).owner;
    document.querySelector('#drawer .dw-x').click(); await w(300);
    const q = document.querySelector('#gq'); q.focus(); q.value = 'l-sg-bbz'; q.dispatchEvent(new Event('input')); for (let i = 0; i < 25 && !document.querySelector('.gi-pv'); i++) await w(200); out.pv = !!document.querySelector('.gi-pv'); q.blur(); document.querySelector('#gres').style.display = 'none';
    document.querySelector('#hyg').click(); for (let i = 0; i < 30 && !document.querySelector('.modal #rp-body'); i++) await w(200); await w(500);
    document.querySelector('.modal [data-t=cleanup]').click(); await w(1500); out.link = !!document.querySelector('.modal a.sgl') || document.querySelector('.modal #rp-body').innerText.includes('정리할 규칙이 없습니다');
    (document.querySelector('.modal .mc') || document.querySelector('.modal .mo')).click();
    return out;
  });
  ok(r.wz && r.wzSel === 'l-sg-bbz-x-sg' && r.closed, JSON.stringify([r.wz, r.wzSel, r.closed])); ok(r.rules >= 1 && r.acts >= 2 && r.title === 'l-sg-bbz-x-sg', JSON.stringify([r.rules, r.acts, r.title]));
  eq(r.owner, '패널팀'); ok(r.pv, '검색 결과 미리보기 버튼 없음'); ok(r.link);
});

test('v1.17 진행 패널의 plan/apply, 오류 알림의 설정 바로가기', async () => {
  unflag('apply.flag'); unflag('noteerr.flag'); flag('note.flag'); await cdp.go();
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); const out = {};
    S.kind = 'game'; S.group = 'bbz'; S.envId = 'g'; S.tab = 'acl'; persist(); renderPickers(); await selectEnv(); render(); await w(800);
    S.mr.g = { iid: '9', url: 'http://x/9' }; ls.set('mr', S.mr); await startPlan('9', 'g');
    for (let i = 0; i < 40 && !(document.querySelector('#jobbar .jb-atl') && /plan 이상 없음/.test(document.querySelector('#jobbar').innerText)); i++) await w(500);
    const bar = document.querySelector('#jobbar'); out.atl = bar ? bar.innerText : ''; const ap = bar && bar.querySelector('.jb-apply'); out.apOn = !!ap && !ap.disabled;
    if (ap && !ap.disabled) { ap.click(); for (let i = 0; i < 30 && !document.querySelector('.modal'); i++) await w(150); out.modal = document.querySelector('.modal') ? document.querySelector('.modal').innerText : ''; const mc = document.querySelector('.modal .mc'); if (mc) mc.click() }
    toast('Jira 주소와 토큰을 먼저 입력하세요', true); const fb = document.querySelector('#toast .tfix'); out.fix = fb ? fb.innerText : '';
    if (fb) { fb.click(); for (let i = 0; i < 20 && !document.querySelector('.modal'); i++) await w(150); out.fixModal = document.querySelector('.modal') ? document.querySelector('.modal').innerText : ''; const mc = document.querySelector('.modal .mc'); if (mc) mc.click() }
    return out;
  });
  unflag('note.flag');
  ok(r.atl.includes('MR !9') && r.atl.includes('plan 이상 없음') && r.apOn, JSON.stringify([r.atl, r.apOn])); ok(r.modal && r.modal.includes('apply 확인'), String(r.modal));
  eq(r.fix, 'Jira 설정'); ok(r.fixModal && r.fixModal.includes('API 키'), String(r.fixModal));
});

test('환경설정: 서비스 사전을 저장하면 빠른 작업에서 이름으로 고를 수 있다', async () => {
  await cdp.go();
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); S.tab = 'cfg'; persist(); render(); await w(1500);
    const has = !!document.querySelector('#sv-save'); document.querySelector('#sv-add').click();
    const tr = document.querySelector('#sv-body tr.svx:last-child'); tr.querySelector('.sv-n').value = '웹HTTPS'; tr.querySelector('.sv-t').value = '8443';
    document.querySelector('#sv-save').click(); await w(1200);
    const saved = (await api('GET', '/api/services')).services; const msg = document.querySelector('#sv-msg').innerText;
    tr.querySelector('.sv-t').value = '80,443'; document.querySelector('#sv-save').click(); await w(800); const err = (document.querySelector('#toast') || {}).innerText || '';
    S.tab = 'work'; persist(); render(); await w(1500); const wz = document.querySelector('#wzcard'); if (wz) { wz.open = true; wz.dispatchEvent(new Event('toggle')); }
    await w(600); const pick = document.querySelector('#wz-svc'); let from = ''; if (pick) { pick.value = String(saved.findIndex(x => x.name === '웹HTTPS')); pick.dispatchEvent(new Event('change')); from = document.querySelector('#wz-from').value; }
    await api('PUT', '/api/services', { services: [] }); await reloadCfg();
    return { has, saved, msg, err, pick: !!pick, from };
  });
  ok(r.has, '서비스 카드 없음'); eq(r.saved.length, 1); eq(r.saved[0].ports, '8443'); ok(r.msg.includes('저장했습니다'), r.msg); ok(r.err.includes('포트는'), r.err); ok(r.pick, '마법사에 서비스 선택이 없음'); eq(r.from, '8443');
});

test('도메인 조회: 통합 검색에 비교 버튼이 나오고, 조회 창이 열린다. 포트 목록 해석이 맞다', async () => {
  await cdp.go();
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); const out = {};
    out.ports = [parsePortList('443', ''), parsePortList('443, 8080-8090', ''), parsePortList('80', '90'), parsePortList('70000', ''), parsePortList('a', ''), parsePortList('', '')].map(x => JSON.stringify(x));
    out.dom = [looksDomain('game.example.com'), looksDomain('10.1.1.1'), looksDomain('abc')];
    const q = document.querySelector('#gq'); q.focus(); q.value = 'game.example.com'; q.dispatchEvent(new Event('input')); for (let i = 0; i < 25 && !document.querySelector('#gq-dom'); i++) await w(200);
    out.btn = !!document.querySelector('#gq-dom'); q.blur();
    openDomainLookup('zz-test.example.com').catch(() => {}); for (let i = 0; i < 60 && !document.querySelector('.modal'); i++) await w(200);
    out.modal = document.querySelector('.modal') ? document.querySelector('.modal').innerText : ''; const mo = document.querySelector('.modal .mo'); if (mo) mo.click();
    return out;
  });
  eq(r.ports[0], '[[443,443]]'); eq(r.ports[1], '[[443,443],[8080,8090]]'); eq(r.ports[2], '[[80,90]]'); eq(r.ports[3], 'null'); eq(r.ports[4], 'null'); eq(r.ports[5], '[]');
  eq(JSON.stringify(r.dom), '[true,false,false]'); ok(r.btn, '도메인 비교 버튼 없음'); ok(r.modal.includes('도메인 조회') && r.modal.includes('zz-test.example.com'), r.modal.slice(0, 160));
});

test('빠른 작업: 포트를 쉼표로 여러 개 적으면 IP × 포트 규칙이 만들어진다', async () => {
  await cdp.go();
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); S.kind = 'game'; S.group = 'bbz'; S.envId = 'g'; S.tab = 'work'; persist(); renderPickers(); await selectEnv(); render(); await w(1500);
    const c = document.querySelector('#wzcard'); c.open = true; c.dispatchEvent(new Event('toggle'));
    document.querySelector('#wz-ticket').value = 'ISRIR-70001'; document.querySelector('#wz-from').value = '443, 8080-8090'; document.querySelector('#wz-to').value = '';
    document.querySelector('#wz-ips').value = '10.9.9.1\n10.9.9.2'; S.wzSel = new Set(['l-sg-bbz-x-sg']); document.querySelector('#wz-ips').dispatchEvent(new Event('input'));
    const seen = []; const orig = window.api; window.api = async (m, u, b, f) => { if (u === '/api/bulk-apply') seen.push(b); return orig(m, u, b, f) };
    const p = runWizard(); for (let i = 0; i < 40 && !document.querySelector('.modal'); i++) await w(150);
    const modal = document.querySelector('.modal') ? document.querySelector('.modal').innerText : ''; const mc = document.querySelector('.modal .mc'); if (mc) mc.click(); await p; window.api = orig;
    const dry = seen.find(x => x.dry_run);
    return { modal, rules: dry ? dry.rules.map(x => x.cidr_blocks[0] + ':' + x.from_port + '-' + x.to_port) : null };
  });
  eq(JSON.stringify(r.rules), JSON.stringify(['10.9.9.1/32:443-443', '10.9.9.1/32:8080-8090', '10.9.9.2/32:443-443', '10.9.9.2/32:8080-8090']));
  ok(r.modal.includes('443, 8080-8090'), r.modal.slice(0, 200));
});

test('환경설정: 자가 점검을 실행하면 항목별 결과가 나온다', async () => {
  await cdp.go();
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); S.tab = 'cfg'; persist(); render(); await w(1200);
    const has = !!document.querySelector('#ck-run') && !!document.querySelector('#ck-bundle');
    document.querySelector('#ck-run').click(); for (let i = 0; i < 40 && !document.querySelector('#ck-res table'); i++) await w(250);
    return { has, txt: (document.querySelector('#ck-res') || {}).innerText || '', msg: document.querySelector('#ck-msg').innerText };
  });
  ok(r.has, '자가 점검 카드 없음'); ok(r.txt.includes('Python') && r.txt.includes('git') && r.txt.includes('Flask'), r.txt.slice(0, 200)); ok(/정상 \d+/.test(r.msg), r.msg);
});

test('입력 중인 값은 작업 화면이 다시 그려져도 유지된다', async () => {
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); S.tab = 'work'; persist(); render(); await w(1500);
    const el = document.querySelector('#sum'); el.value = '작성 중 요약'; viewWork(); await w(500);
    return { iid: document.querySelector('#sum').value };
  });
  eq(r.iid, '작성 중 요약');
});

test('설정이 다른 곳에서 먼저 바뀌면 저장이 거부되고 최신 내용을 다시 불러온다', async () => {
  const r = await cdp.ev(async () => {
    S.cfgRev = 'deadbeef0000'; let msg = '', code = 0;
    try { await api('PUT', '/api/config', S.cfg) } catch (e) { msg = e.message; code = e.data && e.data.conflict }
    return { msg, code, rev: S.cfgRev };
  });
  ok(r.code, '충돌 응답이 아님: ' + r.msg); ok(r.rev !== 'deadbeef0000', '최신 rev 로 갱신되지 않음');
});

test('오늘 날짜는 서버 기준이고 서버 로그 창이 열린다', async () => {
  const r = await cdp.ev(async () => {
    const v = await api('GET', '/api/version'); const t = today();
    document.querySelector('#vlog').click(); await new Promise(r => setTimeout(r, 600));
    const m = document.querySelector('.modal'); const title = m ? m.querySelector('h3').innerText : '';
    if (m) m.querySelector('.mo').click();
    return { same: v.today === t, title };
  });
  ok(r.same, '서버 날짜와 다름'); ok(r.title.includes('서버 로그'), r.title);
});

test('되돌리기: 저장한 규칙을 버튼으로 되돌리고, SG 변경 취소도 된다', async () => {
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); const out = {};
    S.tab = 'acl'; persist(); render(); await w(1200); await openSg('l-sg-bbz-x-sg'); await w(500);
    const n0 = (await api('GET', '/api/env/g/sg/l-sg-bbz-x-sg')).ingress.length;
    const sg = await api('GET', '/api/env/g/sg/l-sg-bbz-x-sg');
    sg.ingress.push({ from_port: 4411, to_port: 4411, protocol: 'TCP', cidr_blocks: ['10.9.9.9/32'], security_groups: '', prefix_list_ids: [], description: 'undo test' });
    await api('PUT', '/api/env/g/sg/l-sg-bbz-x-sg', sg); await afterWorkChange(); await w(800);
    const b = document.querySelector('#wtools-acl .wt-undo'); out.btn = b ? b.innerText : 'none'; out.disabled = b ? b.disabled : true;
    b.click(); await w(600); const m = document.querySelector('.modal'); out.modal = m ? m.innerText.slice(0, 80) : ''; out.dialog = m ? m.getAttribute('role') === 'dialog' : false;
    if (m) m.querySelector('.mo').click(); await w(1500);
    out.after = (await api('GET', '/api/env/g/sg/l-sg-bbz-x-sg')).ingress.length - n0;
    // SG 변경 취소
    const sg2 = await api('GET', '/api/env/g/sg/l-sg-bbz-x-sg'); sg2.ingress.push({ from_port: 4412, to_port: 4412, protocol: 'TCP', cidr_blocks: ['10.9.9.8/32'], security_groups: '', prefix_list_ids: [], description: 'revert test' });
    await api('PUT', '/api/env/g/sg/l-sg-bbz-x-sg', sg2); await afterWorkChange(); await w(800);
    const rv = document.querySelector('#rvsg'); out.rv = !!rv; if (rv) { rv.click(); await w(500); document.querySelector('.modal .mo').click(); await w(1500) }
    out.after2 = (await api('GET', '/api/env/g/sg/l-sg-bbz-x-sg')).ingress.some(x => x.from_port === 4412);
    return out;
  });
  ok(r.btn.includes('되돌리기') && !r.disabled, JSON.stringify(r)); ok(r.modal.includes('되돌리기'), r.modal); ok(r.dialog, '대화상자 role 없음'); eq(r.after, 0, '되돌리기 실패'); ok(r.rv, 'SG 변경 취소 버튼 없음'); eq(r.after2, false, 'SG 변경 취소 실패');
});

test('작업 브랜치 전환 창이 열리고 현재 브랜치가 표시된다', async () => {
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms));
    S.tab = 'acl'; persist(); render(); await w(1200);
    document.querySelector('#wtools-acl .wt-br').click(); await w(800); const m = document.querySelector('.modal');
    const out = { txt: m ? m.innerText.slice(0, 160) : '', radios: m ? m.querySelectorAll('input[name=wtb]').length : 0 };
    if (m) m.querySelector('.mc').click(); return out;
  });
  ok(r.txt.includes('작업 브랜치 전환') || r.txt.includes('전환할 로컬'), r.txt);
});

test('접근성: 건너뛰기 링크, 메뉴 현재 표시, 알림 영역, 대화상자 포커스, 콤보 키보드 조작', async () => {
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); const out = {};
    out.skip = !!document.querySelector('a.skip-link[href="#view"]'); out.main = !!document.querySelector('main#main');
    out.cur = !!document.querySelector('#tabs .tab-btn[aria-current=page]'); out.live = document.querySelector('#toast').getAttribute('aria-live');
    toast('x', true); out.errRole = document.querySelector('#toast').getAttribute('role');
    // 모달: 역할/포커스 이동/Esc/포커스 복원
    const opener = document.querySelector('#tabs .tab-btn'); opener.focus();
    const p = showModal('테스트', '<input id="a11y-i" type="text"><button id="a11y-b">버튼</button>', '확인'); await w(100);
    const m = document.querySelector('.modal-ov .modal'); out.dlg = m.getAttribute('role') + '/' + m.getAttribute('aria-modal') + '/' + (document.getElementById(m.getAttribute('aria-labelledby')) || {}).innerText;
    out.focusIn = !!document.activeElement.closest('.modal');
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })); await p; await w(50); out.restored = document.activeElement === opener;
    // 콤보: 열면 listbox, 방향키+Enter 선택
    const btn = document.querySelector('#c1 button'); out.haspopup = btn.getAttribute('aria-haspopup'); btn.click(); await w(150);
    out.expanded = btn.getAttribute('aria-expanded'); const inp = document.querySelector('#c1 .panel input'); out.listbox = !!document.querySelector('#c1 [role=listbox]') && document.querySelectorAll('#c1 [role=option]').length > 0;
    inp.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true })); out.act = document.querySelectorAll('#c1 [role=option].act').length;
    inp.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); await w(100); out.closed = !document.querySelector('#c1 .panel');
    // 키보드로 쓸 수 있는 SG 목록 항목
    S.tab = 'acl'; persist(); render(); await w(1200); await window.a11yEnhance(); const it = document.querySelector('#sgl [data-n]'); out.sgKbd = !!it && it.tabIndex === 0 && it.getAttribute('role') === 'button';
    return out;
  });
  ok(r.skip && r.main && r.cur, JSON.stringify(r)); eq(r.live, 'polite'); eq(r.errRole, 'alert'); eq(r.dlg, 'dialog/true/테스트'); ok(r.focusIn, '대화상자로 포커스 이동 안 됨'); ok(r.restored, '포커스 복원 안 됨');
  eq(r.haspopup, 'listbox'); eq(r.expanded, 'true'); ok(r.listbox, 'listbox/option 없음'); eq(r.act, 1, '방향키 선택 표시 없음'); ok(r.closed, 'Esc 로 닫히지 않음'); ok(r.sgKbd, 'SG 항목 키보드 접근 불가');
});

test('처음 시작하기 안내: 계정/토큰이 없으면 단계 카드가 표시된다', async () => {
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms));
    const keep = { a: S.account, t: S.tokenSet, e: S.envId, tab: S.tab, envs: S.cfg.environments };
    S.account = ''; S.tokenSet = {}; S.envId = ''; S.cfg.environments = []; S.tab = 'acl'; render(); await w(300);
    const card = document.querySelector('#onboard'); const out = { has: !!card, steps: card ? card.querySelectorAll('li').length : 0, btn: card ? card.querySelectorAll('.ob-go').length : 0 };
    const add = document.querySelector('.ob-go[data-add="1"]'); if (add) { add.click(); await w(500); out.form = !!document.querySelector('#eform #esave'); out.tab = S.tab }
    S.account = keep.a; S.tokenSet = keep.t; S.envId = keep.e; S.cfg.environments = keep.envs; S.tab = keep.tab; return out;
  });
  ok(r.has && r.steps === 4 && r.btn >= 3, JSON.stringify(r)); ok(r.form, '환경 추가 양식이 열리지 않음'); eq(r.tab, 'cfg');
});

test('배포 메뉴: 저장 위치 선택 창이 열리고 선택한 파일에 zip 이 저장된다', async () => {
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); const out = {};
    // 저장 위치 선택 창(브라우저 기능)을 가짜로 바꿔 어떤 이름을 제안하고 무엇이 써지는지 확인
    const saved = { name: '', bytes: 0, head: '' };
    window.showSaveFilePicker = async opts => { saved.name = opts.suggestedName; return { name: 'chosen.zip', createWritable: async () => ({ write: async b => { saved.bytes = b.size; saved.head = new TextDecoder().decode(await b.slice(0, 2).arrayBuffer()) }, close: async () => {} }) } };
    out.menu = [...document.querySelectorAll('#tabs .tab-btn')].map(b => b.innerText.trim()).includes('배포');
    S.tab = 'dist'; persist(); render(); await w(800);
    out.card = !!document.querySelector('#dz-go'); out.btn = document.querySelector('#dz-go') ? document.querySelector('#dz-go').innerText : '';
    document.querySelector('#dz-go').click(); for (let i = 0; i < 40 && !saved.bytes; i++) await w(250); await w(300);
    out.msg = document.querySelector('#dz-msg').innerText; out.saved = saved;
    S.tab = 'acl'; persist(); render(); return out;
  });
  ok(r.menu, '배포 메뉴 없음'); ok(r.card, '배포 화면 없음'); ok(r.btn.includes('저장 위치'), r.btn);
  ok(r.saved.name.startsWith('Traform-ACL-Tool-') && r.saved.name.endsWith('.zip'), r.saved.name); eq(r.saved.head, 'PK', 'zip 이 아님'); ok(r.saved.bytes > 10000, '파일이 너무 작음');
  ok(r.msg.includes('저장했습니다') && r.msg.includes('chosen.zip'), r.msg);
});

test('복사한 규칙은 맨 아래에 추가되고, 브랜치 이름 미리보기에 입력 문자가 붙는다', async () => {
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); const out = {};
    S.tab = 'acl'; persist(); render(); await w(1200); await openSg('l-sg-bbz-x-sg'); await w(500);
    const before = (await api('GET', '/api/env/g/sg/l-sg-bbz-x-sg')).ingress; out.n0 = before.length;
    document.querySelectorAll('.rsel')[0].checked = true; document.querySelector('#cp').click(); await w(1500);
    const after = (await api('GET', '/api/env/g/sg/l-sg-bbz-x-sg')).ingress;
    out.n1 = after.length; out.firstSame = JSON.stringify(after[0]) === JSON.stringify(before[0]); out.secondSame = after.length > 1 && JSON.stringify(after[1]) === JSON.stringify(before[1]);
    out.lastIsCopy = JSON.stringify(after[after.length - 1]) === JSON.stringify(before[0]); out.editRow = S.edit ? S.edit.i : null; S.edit = null;
    await api('POST', '/api/env/g/undo'); await afterWorkChange();
    S.tab = 'work'; persist(); render(); await w(1200);
    $('#ticket').value = 'ISRIR-69431'; $('#bsuf').value = '입력 문자'; $('#bsuf').dispatchEvent(new Event('input'));
    out.preview = document.querySelector('#bpv').textContent; return out;
  });
  eq(r.n1, r.n0 + 1); ok(r.firstSame && (r.n0 < 2 || r.secondSame), '기존 규칙 순서가 바뀜'); ok(r.lastIsCopy, '복사본이 맨 아래에 없음'); eq(r.editRow, r.n0, '수정 대상이 복사본이 아님');
  ok(/\/\d{6}_ISRIR-69431_입력_문자$/.test(r.preview), r.preview);
});

test('Atlantis apply 완료 후: main 브랜치로 전환되고 접근제어의 변경 표시가 해제된다', async () => {
  unflag('note.flag'); unflag('noteerr.flag'); flag('apply.flag');
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); const out = {};
    const st0 = await api('GET', '/api/env/g/git/status?fresh=1');
    if (st0.files.length) await api('POST', '/api/env/g/git/revert-all', { confirm: true });
    if (st0.on_default) await api('POST', '/api/env/g/git/prepare', { ticket: 'ISRIR-777', suffix: 'apply' });
    const cur = await api('GET', '/api/env/g/git/status?fresh=1'); out.before = cur.branch;
    S.tab = 'work'; persist(); render(); await w(1200);
    const hid = addHist('atlantis apply → MR !9', 'cmd', { kind: 'apply', state: 'pending', headline: '⏳' });
    pollOut('9', 0, 'apply', hid, histKey(), S.envId); await w(7000);
    const jm = document.querySelector('.modal'); out.jira = jm ? jm.innerText : ''; out.jsel = jm && jm.querySelector('#jf-s') ? jm.querySelector('#jf-s').value : ''; out.jtext = jm && jm.querySelector('#jf-t') ? jm.querySelector('#jf-t').value : '';
    if (jm && out.jira.includes('Jira 완료 처리')) { jm.querySelector('.mo').click(); await w(2500) }
    const st = await api('GET', '/api/env/g/git/status?fresh=1'); out.after = st.branch;
    out.sgs = (await api('GET', '/api/env/g/sgs')).sgs.map(x => x.change); out.hist = document.querySelector('#hl') ? document.querySelector('#hl').innerText.slice(0, 400) : '';
    return out;
  });
  unflag('apply.flag');
  ok(r.before !== 'main', '작업 브랜치 준비 실패: ' + r.before); eq(r.after, 'main'); ok(r.sgs.every(x => !x), '변경 표시가 남아 있음'); ok(r.hist.includes('main'), r.hist);
  ok(/ISRIR-\d+/.test(r.jira) && r.jtext.includes('[ACL 적용 완료]') && r.jtext.includes('- apply: 완료'), r.jtext.slice(0, 200)); eq(r.jsel, '71');   // 티켓은 브랜치 이름(접미어 포함)에서 읽고, 완료 전환을 미리 골라 둔다
});

test('빠른 작업: apply 까지 진행을 켜면 plan 이 이상 없을 때 apply 하고, 끝나면 Jira 완료 처리 창이 뜬다', async () => {
  unflag('note.flag'); unflag('noteerr.flag'); unflag('apply.flag'); flag('autoflip.flag');
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); const out = {};
    const st0 = await api('GET', '/api/env/g/git/status?fresh=1'); if (st0.files.length) await api('POST', '/api/env/g/git/revert-all', { confirm: true });
    S.kind = 'game'; S.group = 'bbz'; S.envId = 'g'; S.tab = 'work'; persist(); renderPickers(); await selectEnv(); render(); await w(1500);
    const c = document.querySelector('#wzcard'); c.open = true; c.dispatchEvent(new Event('toggle'));
    document.querySelector('#wz-ticket').value = 'ISRIR-70002'; document.querySelector('#wz-from').value = '443'; document.querySelector('#wz-to').value = '';
    document.querySelector('#wz-ips').value = '10.9.9.9'; S.wzSel = new Set(['l-sg-bbz-x-sg']); document.querySelector('#wz-ips').dispatchEvent(new Event('input'));
    document.querySelector('#wz-apply').checked = true; document.querySelector('#wz-jira').checked = true;
    try { localStorage.removeItem('jiraDoneTr') } catch (e) { }
    const p = runWizard(); for (let i = 0; i < 40 && !document.querySelector('.modal'); i++) await w(150);
    out.confirm = document.querySelector('.modal') ? document.querySelector('.modal').innerText : ''; const mo = document.querySelector('.modal .mo'); if (mo) mo.click();
    let done = false; p.then(() => { done = true });
    for (let i = 0; i < 200 && !done; i++) { await w(300); if (!out.job && document.querySelector('#jobbar')) out.job = document.querySelector('#jobbar').innerText; const m = document.querySelector('.modal'); if (m && m.innerText.includes('Jira 완료 처리') && !out.jira) { out.jira = m.innerText; out.jtext = m.querySelector('#jf-t').value; out.jsel = m.querySelector('#jf-s').value; m.querySelector('.mo').click() } }
    const res = await p; out.res = res ? { ok: res.ok, applied: res.applied, held: res.held } : null;
    out.hist = (histLoad(histKey()) || []).slice(-8).map(x => x.step + ' | ' + (x.headline || '')).join('\n');
    return out;
  });
  unflag('autoflip.flag'); unflag('note.flag'); unflag('apply.flag');
  ok(r.confirm.includes('apply 까지'), r.confirm.slice(0, 200)); ok(r.job && r.job.includes('ISRIR-70002'), String(r.job)); eq(JSON.stringify(r.res), JSON.stringify({ ok: true, applied: true, held: '' }), r.hist);
  ok(r.jira && r.jira.includes('ISRIR-70002') && r.jtext.includes('[ACL 적용 완료]') && r.jtext.includes('- MR: http://x/9') && r.jtext.includes('- plan: 추가 1'), String(r.jtext).slice(0, 300)); eq(r.jsel, '71'); ok(r.hist.includes('atlantis apply') && r.hist.includes('Jira 완료 처리'), r.hist);
});

test('접근제어 SG 목록: 메타 데이터에 SG ID 가 있으면 이름(SG ID) 로 표시되고 SG ID 로도 찾을 수 있다', async () => {
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); const out = {};
    S.meta.envs[S.envId] = S.meta.envs[S.envId] || { sgs: {} }; S.meta.envs[S.envId].sgs = S.meta.envs[S.envId].sgs || {};
    S.meta.envs[S.envId].sgs['l-sg-bbz-x-sg'] = { ...(S.meta.envs[S.envId].sgs['l-sg-bbz-x-sg'] || {}), sg_id: 'sg-0abc1234def567890' };
    S.tab = 'acl'; S.sgf = ''; persist(); render(); await w(1200);
    const items = [...document.querySelectorAll('#sgl [data-n]')]; const x = items.find(d => d.querySelector('b').textContent === 'l-sg-bbz-x-sg');
    out.text = x ? x.querySelector('b').parentElement.firstChild.textContent + '|' + (x.querySelector('.sgid') || {}).textContent : 'none';
    out.other = items.filter(d => d.querySelector('b').textContent !== 'l-sg-bbz-x-sg').every(d => !d.querySelector('.sgid'));
    S.sgf = '0abc1234'; drawSgList(); out.found = [...document.querySelectorAll('#sgl [data-n] b')].map(b => b.textContent); S.sgf = ''; drawSgList();
    delete S.meta.envs[S.envId].sgs['l-sg-bbz-x-sg'].sg_id; return out;
  });
  ok(r.text.includes('(sg-0abc1234def567890)'), JSON.stringify(r)); ok(r.other, '다른 SG 에 SG ID 가 잘못 표시됨'); eq(r.found, ['l-sg-bbz-x-sg']);
});

test('AWS 에서 가져오기: 미리보기 → 반영, 로그인 필요/권한 없음 안내', async () => {
  unflag('login.flag'); unflag('denied.flag');
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); const out = {};
    S.tab = 'meta'; persist(); render(); await w(900);
    const em0 = S.meta.envs[S.envId] || {}; delete (em0.sgs || {})['l-sg-bbz-x-sg'];
    document.querySelector('#awsf').click(); await w(700);
    let m = document.querySelector('.modal'); out.step1 = m ? m.innerText.slice(0, 60) : ''; out.profiles = m ? [...m.querySelectorAll('#aw-p option')].map(o => o.value) : [];
    m.querySelector('#aw-r').value = 'ap-northeast-2'; m.querySelector('.mo').click(); await w(2500);
    m = document.querySelector('.modal'); out.preview = m ? m.innerText : ''; out.hasSg = out.preview.includes('sg-0aaa111');
    if (m) m.querySelector('.mo').click(); await w(2000);
    out.sgid = ((S.meta.envs[S.envId] || {}).sgs || {})['l-sg-bbz-x-sg'];
    out.subs = ((S.meta.envs[S.envId] || {}).subnets || []).map(x => x.subnet_name + ':' + x.nat_ip);
    return out;
  });
  ok(r.step1.includes('AWS 에서 가져오기') && r.profiles.length === 2, JSON.stringify(r)); ok(r.hasSg && r.preview.includes('반영 전 확인'), r.preview.slice(0, 200));
  eq(r.sgid && r.sgid.sg_id, 'sg-0aaa111'); eq(r.sgid && r.sgid.alias, '10.1.0.9, 10.1.0.10, 10.1.1.20, 52.0.0.1', '리소스 IP 가 별명에 들어가지 않음'); eq(r.subs, ['pub-a:-', 'pri-a:3.3.3.3']);
  // 로그인 필요 -> 안내 -> 로그인 창 열기(가짜) -> 승인 후 자동 재시도
  flag('login.flag');
  const r2 = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); const out = {};
    document.querySelector('#awsf').click(); await w(600); document.querySelector('#aw-r').value = 'ap-northeast-2'; document.querySelector('.modal .mo').click(); await w(1800);
    let m = document.querySelector('.modal'); out.login = m ? m.innerText : ''; out.role = m ? m.getAttribute('role') : '';
    m.querySelector('.mo').click(); await w(5500);   // 로그인 창 열기 -> (가짜) 승인 -> whoami 확인 -> 재시도
    m = document.querySelector('.modal'); out.after = m ? m.innerText.slice(0, 80) : 'none';
    if (m) m.querySelector('.mc') ? m.querySelector('.mc').click() : m.querySelector('.mo').click(); await w(300);
    return out;
  });
  ok(r2.login.includes('AWS 로그인이 필요합니다') && r2.login.includes('aws sso login --profile'), r2.login); ok(r2.after.includes('반영 전 확인'), r2.after);
  // 권한 없음 -> 로그인 안내가 아니라 권한 요청 안내
  flag('denied.flag');
  const r3 = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms));
    document.querySelector('#awsf').click(); await w(600); document.querySelector('#aw-r').value = 'ap-northeast-2'; document.querySelector('.modal .mo').click(); await w(1800);
    const m = document.querySelector('.modal'); const t = m ? m.innerText : ''; if (m) m.querySelector('.mo').click(); return t;
  });
  unflag('denied.flag');
  ok(r3.includes('권한이 없습니다') && r3.includes('권한을 요청'), r3); ok(!r3.includes('로그인 창 열기'), '권한 없음인데 로그인 버튼이 보임');
});

test('별명에 리소스 IP: 한 개/여러 개 표기, 직접 쓴 별명 보존, 다시 가져오면 IP 만 갱신', async () => {
  const r = await cdp.ev(() => ({
    one: aliasWithIps('', ['10.162.142.198']),
    many: aliasWithIps('', ['10.162.142.198', '10.162.142.199']),
    keep: aliasWithIps('웹서버', ['10.0.0.1', '10.0.0.2']),
    refresh: aliasWithIps('웹서버, 10.0.0.1, 10.0.0.2', ['10.0.0.9']),
    onlyIps: aliasWithIps('10.0.0.1, 10.0.0.2', ['10.0.0.3']),
    legacy: aliasWithIps('웹서버 [IP: 10.0.0.1]', ['10.0.0.5']),
    none: aliasWithIps('웹서버', []),
    noneIps: aliasWithIps('10.0.0.1', []),
    big: aliasWithIps('', Array.from({ length: 12 }, (_, i) => '10.0.0.' + (i + 1))),
    bigAgain: aliasWithIps(aliasWithIps('', Array.from({ length: 12 }, (_, i) => '10.0.0.' + (i + 1))), ['10.0.1.1']),
  }));
  eq(r.one, '10.162.142.198'); eq(r.many, '10.162.142.198, 10.162.142.199'); eq(r.keep, '웹서버, 10.0.0.1, 10.0.0.2'); eq(r.refresh, '웹서버, 10.0.0.9');
  eq(r.onlyIps, '10.0.0.3'); eq(r.legacy, '웹서버, 10.0.0.5'); eq(r.none, '웹서버'); eq(r.noneIps, '10.0.0.1');
  eq(r.big, '10.0.0.1, 10.0.0.2, 10.0.0.3, 10.0.0.4, 10.0.0.5, 10.0.0.6, 10.0.0.7, 10.0.0.8, 10.0.0.9, 10.0.0.10 외 2개'); eq(r.bigAgain, '10.0.1.1');
});

test('AWS 프로필 자동 매칭: 맞는 계정을 찾아 미리 선택하고, 로그인이 필요하면 로그인 후 다시 찾는다', async () => {
  unflag('login.flag'); unflag('denied.flag');
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); const out = {};
    S.tab = 'meta'; persist(); render(); await w(900);
    await api('POST', '/api/aws/profile-map', { key: 'bbz|live', profile: 'dev-other' });   // 이 환경에 저장된 값이 틀려도(다른 계정) 자동 매칭이 우선하진 않지만, 저장 없으면 찾는다
    const orig = api; window.api = api = (m, u, b, f) => orig(m, u, b, f).then(x => (u.endsWith('/aws/context') ? { ...x, region: 'ap-northeast-2', saved: '' } : x));
    document.querySelector('#awsf').click(); await w(4000);
    const m = document.querySelector('.modal'); out.txt = m ? m.innerText.slice(0, 200) : ''; out.sel = m ? m.querySelector('#aw-p').value : '';
    if (m) m.querySelector('.mc').click(); await w(300);
    api = orig; return out;
  });
  ok(r.txt.includes('자동 매칭') && r.txt.includes('qa-bbz-global') && r.txt.includes('2/2'), r.txt); eq(r.sel, 'qa-bbz-global');
  flag('login.flag');
  const r2 = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); const out = {};
    const orig = api; window.api = api = (m, u, b, f) => orig(m, u, b, f).then(x => (u.endsWith('/aws/context') ? { ...x, region: 'ap-northeast-2', saved: '' } : x));
    document.querySelector('#awsf').click(); await w(2500);
    let m = document.querySelector('.modal'); out.login = m ? m.innerText.slice(0, 120) : '';
    m.querySelector('.mo').click(); await w(9000);        // 로그인 창 열기 -> (가짜) 승인 -> 다시 자동 매칭
    m = document.querySelector('.modal'); out.after = m ? m.innerText.slice(0, 200) : 'none'; if (m) m.querySelector('.mc').click(); await w(300);
    api = orig; return out;
  });
  ok(r2.login.includes('AWS 로그인이 필요합니다'), r2.login); ok(r2.after.includes('자동 매칭') && r2.after.includes('qa-bbz-global'), r2.after);
});

test('AWS 프로필 검색: 이름/계정 ID 로 목록이 걸러지고, 리전을 입력하면 자동 찾기로 프로필이 선택된다', async () => {
  unflag('login.flag'); unflag('denied.flag');
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); const out = {};
    S.tab = 'meta'; persist(); render(); await w(900);
    document.querySelector('#awsf').click(); await w(800);
    const m = document.querySelector('.modal'); const q = m.querySelector('#aw-q'), sel = m.querySelector('#aw-p');
    out.all = sel.options.length; out.cnt0 = m.querySelector('#aw-cnt').textContent;
    q.value = 'dev'; q.dispatchEvent(new Event('input')); out.afterDev = [...sel.options].map(o => o.value);
    q.value = 'zzzz'; q.dispatchEvent(new Event('input')); out.none = m.querySelector('#aw-cnt').textContent; out.noneOpts = sel.options.length;
    q.value = ''; q.dispatchEvent(new Event('input'));
    m.querySelector('#aw-r').value = 'apne2'; m.querySelector('#aw-auto').click(); await w(3000);
    out.picked = sel.value; out.msg = m.querySelector('#aw-am').textContent; out.datalist = m.querySelectorAll('#aw-rl option').length;
    out.region = m.querySelector('#aw-r').value;
    m.querySelector('.mc').click(); return out;
  });
  eq(r.all, 2); ok(r.cnt0.includes('2 / 2'), r.cnt0); eq(r.afterDev, ['dev-other']); eq(r.noneOpts, 0); ok(r.none.includes('일치하는 프로필이 없습니다'), r.none);
  eq(r.picked, 'qa-bbz-global'); ok(r.msg.includes('qa-bbz-global') && r.msg.includes('2/2'), r.msg); ok(r.datalist >= 10, '리전 목록이 없음');
});

test('엑셀 연동: 폴더 선택 → 파일 선택 → 연결 테스트 → 기록할 줄 확인 후 C열 마지막 아래에 기록', async () => {
  const r = await cdp.ev(async () => {
    const w = ms => new Promise(r => setTimeout(r, ms)); const out = {};
    S.tab = 'cfg'; persist(); render(); await w(1200);
    out.card = !!document.querySelector('#excel-card #ex-save');
    document.querySelector('#ex-writer').value = '임희재'; document.querySelector('#ex-pick').click(); await w(900);
    out.folder = document.querySelector('#ex-folder').value.endsWith('xls'); out.files = [...document.querySelectorAll('#ex-file option')].map(o => o.value);
    document.querySelector('#ex-save').click(); await w(800);
    document.querySelector('#ex-test').click(); await w(1500); out.test = document.querySelector('#ex-msg').innerText;
    // 작업 탭의 '엑셀 기록'
    S.tab = 'work'; persist(); render(); await w(1500);
    $('#ticket').value = 'ISRIR-68062';
    document.querySelector('#xls').click(); await w(1500);
    let m = document.querySelector('.modal'); out.title = m ? m.querySelector('h3').innerText : '';
    const rows = [...m.querySelectorAll('tbody tr')]; out.rows = rows.length; out.checked = rows.map(t => t.querySelector('.ex-ck').checked);
    out.firstCells = [...rows[0].querySelectorAll('.ex-c')].map(x => x.value);
    rows[0].querySelector('.ex-c[data-j="4"]').value = '10.7.7.77';             // 값 수정
    m.querySelector('.mo').click(); await w(2500);
    const chk = await api('GET', '/api/excel/check'); out.next = chk.next_row;
    return out;
  });
  ok(r.card, '엑셀 연동 카드 없음'); ok(r.folder, '폴더 선택 안 됨'); eq(r.files, ['acl.xlsx']); ok(r.test.includes('3행') && r.test.includes('4행부터'), r.test);
  ok(r.title.includes('엑셀에 기록'), r.title); eq(r.rows, 3); eq(r.checked, [true, true, false]);
  eq(r.firstCells.slice(0, 4), ['AWS', 'qa-bbz', '홍콩', '-']); eq(r.firstCells[10], 'ISRIR-68062'); eq(r.firstCells[11], '임희재');
  eq(r.next, 6);        // 기존 3행 아래에 2줄(체크된 것만) 기록 -> 다음은 6행
});

test('엑셀 연동: 설정이 없으면 apply 직후 자동 확인은 조용히 건너뛴다', async () => {
  const r = await cdp.ev(async () => {
    await api('PUT', '/api/excel/settings', { folder: '', file: '', sheet: '', writer: '' });
    const res = await excelRecordModal(S.envId, true); return { res, modal: !!document.querySelector('.modal') };
  });
  eq(r.res, false); eq(r.modal, false);
});

test('화면에서 처리되지 않은 JavaScript 예외가 없다', async () => { eq(cdp.exceptions, [], '처리되지 않은 예외'); });

// ───────────────────────────── 실행 ─────────────────────────────
(async () => {
  if (!BROWSER) { console.error('Edge/Chrome 을 찾지 못했습니다. 환경변수 BROWSER 에 실행 파일 경로를 지정하세요.'); process.exit(2) }
  tmpDir = null; profile = fs.mkdtempSync(path.join(os.tmpdir(), 'tfacl_prof_'));
  server = spawn('python', ['-X', 'utf8', 'tests/ui_server.py', String(PORT)], { cwd: ROOT, stdio: ['ignore', 'pipe', 'pipe'] }); procs.push(server);
  let log = ''; server.stderr.on('data', d => log += d); await new Promise((res, rej) => { server.stdout.on('data', d => { const m = /READY (.+)/.exec(d.toString()); if (m) { tmpDir = m[1].trim(); res() } }); server.on('exit', c => rej(new Error('서버가 종료됨(' + c + ')\n' + log.slice(-800)))); setTimeout(() => rej(new Error('서버 시작 시간 초과')), 30000) });
  await waitUntil(() => getJson(URL + 'api/version'), 15000, '서버 응답');
  browser = spawn(BROWSER, ['--headless=new', '--disable-gpu', `--remote-debugging-port=${CDP_PORT}`, `--user-data-dir=${profile}`, '--no-first-run', '--window-size=1400,1000', 'about:blank'], { stdio: 'ignore' }); procs.push(browser);
  const target = await waitUntil(async () => (await getJson(`http://127.0.0.1:${CDP_PORT}/json/list`)).find(t => t.type === 'page'), 20000, '브라우저 시작');
  const ws = new WebSocket(target.webSocketDebuggerUrl); await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error('CDP 연결 실패')) });
  cdp = new CDP(ws); await cdp.send('Page.enable'); await cdp.send('Runtime.enable'); await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1400, height: 1000, deviceScaleFactor: 1, mobile: false });
  let pass = 0, fail = 0;
  for (const [name, fn] of tests) {
    const t0 = Date.now();
    try { await fn(); pass++; console.log(`PASS  ${name}  (${((Date.now() - t0) / 1000).toFixed(1)}s)`) }
    catch (e) { fail++; console.log(`FAIL  ${name}\n      ${String(e.message).split('\n').join('\n      ')}`) }
  }
  console.log(`\n결과: ${pass} 통과, ${fail} 실패`);
  try { ws.close() } catch (e) { }
  killAll(); await sleep(500);
  for (const d of [profile, tmpDir]) { try { if (d) fs.rmSync(d, { recursive: true, force: true }) } catch (e) { } }   // 임시 폴더 정리
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error('테스트 실행 오류:', e.message); killAll(); process.exit(2) });
