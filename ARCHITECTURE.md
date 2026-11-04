# 구조 / 유지보수 안내 (개발자용)

## 폴더 구성
| 경로 | 역할 |
|---|---|
| `app.py` | Flask 서버 중심 (라우트 + 로직). 파일 안에 `# ----- 섹션` 구분선으로 나뉨 |
| `app_parts/` | `app.py` 가 `_include()` 로 같은 이름공간에서 실행하는 부분: `excel`, `aws_info`, `aws_compare`, `selfcheck`, `policy`(정책·만료·정리·접근 경로·변경 기록), `review`(위험 승인·이미 열려 있음·SG 관계·기준 점검·티켓 찾기·정리 적용), `objects`(서비스 사전), `jira_auto`(티켓·요청 양식 해석·도메인 조회·태그 적용·Jira 완료 처리), `audit`(담당자·감사 보고서 xlsx), `backup` (분리해도 `app` 모듈의 변수를 테스트가 그대로 바꿔 쓸 수 있다) |
| `static/index.html` | 화면 뼈대(HTML)만 있음. `__V__` 는 서버가 버전으로 바꿔서 내려줌 |
| `static/app.css` | 화면 스타일 (라이트/다크) |
| `static/js/*.js` | 화면 동작. 아래 순서대로 로드되며 전역 변수/함수를 공유 (번들러 없음) |
| `data/` | 실행 중 생기는 파일 (config/meta/local/history/plans/app.log/backup) |
| `tests/` | 서버 테스트(`test_app.py`), 화면 테스트(`ui/run_ui_tests.js`, `ui_server.py`) |

## 화면 스크립트 로드 순서 (`static/index.html`)
1. `core.js` — `api()`(rev/충돌 처리), 모달, 상태 `S`, 검색형 드롭다운, 탭, `parseIps`(IP 목록 해석)
2. `acl.js` — 접근제어 탭, 작업 브랜치 배너, 규칙 편집
3. `work.js` — 작업 탭(Git/MR/Atlantis), 저장소 다운로드, Assignees/Reviewers
4. `meta.js` — 메타 데이터 탭
5. `config.js` — 환경설정 탭
6. `search_version.js` — 통합 검색, 버전/서버 코드 변경 감지, 입력값 유지(`keepDraft`)
7. `wizard.js` — 빠른 작업 마법사, 다른 SG 에 적용
8. `undo.js` — 되돌리기 / 변경 취소 / 작업 브랜치 전환 화면
9. `a11y.js` — 접근성 보강(변경 감지 후 키보드·이름 속성 일괄 부여)
10. `integrations.js` — Jira, 서버 재시작, IP 일괄 삭제, 영향 분석 보고서, Atlantis 이어서 하기, **시작 코드(마지막)**

규칙: 함수/상수는 사용하는 시점(클릭·로드 완료 후)에만 서로 참조하면 되므로 파일 순서는 크게 중요하지 않지만,
**화면 시작 코드(마지막 `(async()=>{...})()`)는 항상 마지막 파일**에 둡니다. 새 파일을 추가하면 `index.html` 에 `<script>` 를 추가하세요.

## 서버 주요 개념 (`app.py`)
- **저장**: `read_json/write_json`(원자적 교체, Windows 재시도). config/meta 수정 요청은 `@cfg_locked` + `X-Rev` 확인(`check_rev`)
- **git**: `run_git`(토큰 처리/오류 안내) · `git_status`(1.5초 캐시, 결정에는 `fresh=True`) · `changed_files`(캐시) · `par()`(독립 git 호출 병렬 실행)
  - 쓰기 작업 뒤에는 `invalidate_status(env)` 를 호출해야 화면에 즉시 반영됩니다.
- **오류 처리**: `ApiError`(예상된 오류) / 그 외 예외는 `_unhandled` 가 `data/app.log` 에 기록 후 JSON 500
- **보안**: `_guard_local_only`(Host/Origin 검사), 토큰은 `scrub()` 로 로그에서 가림
- **버전**: `VERSION`(app.py) 과 `CLIENT_VERSION`(search_version.js) 을 같이 올립니다. 다르면 화면에 재시작 안내가 뜹니다.

## 테스트
- `run_tests.bat` — 서버 테스트 (임시 가짜 저장소만 사용, 실제 저장소/GitLab/Jira 는 건드리지 않음)
- `run_ui_tests.bat` — 화면 테스트 (Edge headless + 가짜 서버)
- 테스트는 `A.DATA`, `A.CONFIG_PATH` 등을 임시 폴더로 바꿔 실행하므로, 새 경로 변수를 만들 때는 호출 시점에 읽어야 합니다.

## 되돌리기 (서버)
- `save_sg` 가 파일을 쓰기 직전에 `undo_snapshot()` 으로 원본 바이트(없던 파일은 '없음')를 `data/undo.json` 에 보관 (요청 1건 = 기록 1건).
- `POST /api/env/<id>/undo` 는 가장 최근 기록만 복원. push/브랜치 준비/전환 시 `undo_clear()`.
- 파일을 쓰는 새 기능을 만들 때는 쓰기 전에 `undo_snapshot()` 을 호출하세요.

## 설계 결정
- 저장은 JSON 파일만 사용합니다 (SQLite 등 PC 종속 저장소는 쓰지 않음): 프로그램을 다른 사용자에게 그대로 배포할 수 있어야 하기 때문입니다.
- SG 파일 삭제/이름 변경 기능은 만들지 않습니다: 이 도구는 SG 생성이 아니라 Rule 관리가 목적입니다.

## 앞으로 분리 후보 (아직 하지 않음)
- `app.py` 의 나머지(저장/깃/GitLab/Atlantis/Jira/라우트)도 `app_parts/` 로 옮기기: `_include()` 방식이라 테스트 수정 없이 한 구역씩 옮길 수 있습니다. 진짜 모듈로 나누려면 테스트가 `app` 의 변수를 직접 바꿔 쓰는 부분을 함께 바꿔야 합니다.

## 티켓 자동화 (B, C, D 단계)

- 흐름: 티켓 읽기(읽기 전용) → 마법사 채우기 → 실행 확인 → 브랜치/규칙/Push/MR/plan → (선택) 조건 검사 후 apply → (선택) Jira 완료 처리. 단계 표시는 `static/js/ticketauto.js` 의 `AUTO_STEPS` 이고, apply 와 Jira 는 빠른 작업 카드의 체크박스(`#wz-apply`, `#wz-jira`)가 켜 줍니다.
- **표 읽기**: `parse_request_table()` 이 HTML/위키 표를 머리글 이름으로 매핑해 묶음을 만듭니다. 양식이 바뀌면 `TABLE_HEAD` 의 머리글 키워드를 고치세요. 표가 없으면 기존 라벨 해석(`parse_ticket_text`)으로 되돌아갑니다.
- **D(apply 자동)**: `runWizard()` 가 `waitPlanResult()` 로 plan 결과를 기다리고 `GET /atlantis/plan-status?targets=&expect=` 의 `auto_ok` 가 참일 때만 `applyAndWait()` 를 부릅니다. 조건은 `plan_checks()`(app.py) 에 있으며 `block:true` 항목이 하나라도 실패하면 보류합니다. 위험 규칙 승인(`riskUsed`)이 있었으면 항상 보류합니다. 서버의 `apply_gate()` 는 그대로 마지막 방어선입니다(같은 커밋의 성공한 plan 필요, 이미 apply 한 MR 은 불가).
- **C(완료 처리)**: apply 결과가 `ok` 이면 `pollOut()` 이 `finishAfterApply()` 를 부르고 그 끝에서 `jiraFinishFlow()` 가 코멘트·상태 전환을 합니다. `S.jiraCtx[envId]` 에 위저드가 티켓·MR·옵션을 넣어 둡니다(`on:false` 면 건너뜀). 전환 이름은 localStorage(`jiraDoneTr`)에 기억합니다. 서버는 `/api/jira/finish` 에서 전환 ID 가 지금 가능한 목록에 있는지 먼저 확인하고, 코멘트 → 전환 순서로 실행합니다.
- Jira 에 쓰는 곳은 이 두 번(코멘트, 전환)뿐입니다. 새 쓰기 동작을 넣을 때는 화면 확인 단계를 거치게 하세요.

## 화면 보강 도구 (uxkit.js)

- `jobSet()/jobEnd()/uxJobDraw()`: 오른쪽 아래 진행 패널. 빠른 작업의 `draw()` 가 단계 상태를 넘기고 `pollOut()` 이 대기 건수를 갱신합니다. 새 장시간 작업을 만들면 같은 함수를 부르세요.
- `waitNoModal(label)`: 자동으로 뜨는 창을 열기 전에 부르면 열린 창이 닫힐 때까지 기다립니다. 사용자가 직접 연 창 안에서 다른 창을 여는 경우(도메인 조회 등)에는 쓰지 마세요(서로 기다려 멈춥니다).
- `uxObserveTables(root, rerender)`: 보고서 본문에 그려지는 `table.rp-t` 에 정렬·찾기를 붙이고, '건만 표시' 안내에 '더 보기'를 붙입니다. 행 수 한도는 `RPL()`(기본 400)입니다.
- `showModal(..., {danger:true})`: 되돌릴 수 없거나 운영에 영향을 주는 확인에 쓰세요. `noEnter:true` 면 Enter 확인을 끕니다.

## 한 화면 도구 (dock.js)

- 작업 바(`#actbar`)는 `render()`·`gitStatus()`·`drawDetail()`·`refreshPlanStatus()` 를 감싸서(wrap) 상태가 바뀔 때 `actbarSoon()`/`atlSoon()` 으로 새로 그립니다. 새 화면 함수를 만들면 같은 방식으로 감싸지 말고 이 함수들을 부르세요.
- 같은 동작을 여러 곳에서 부르도록 `doPush()`(work.js), `ruleAction()`, `atlantisRunApply()`, `dockPrep()`, `dockMakeMr()` 처럼 전역 함수로 뽑아 두었습니다. 작업 카드는 이 함수를 그대로 씁니다.
- 옆 패널은 `openDrawer(title, html, onMount, key)` 하나이고 key 가 `wizard` 면 빠른 작업, `sg:<환경>|<SG>` 면 SG 패널입니다. 작업 탭으로 가면 `wizard` 패널은 자동으로 닫힙니다(같은 id 의 카드가 겹치지 않게).
- 규칙 한 건 삭제/연장은 위치(`idx`)와 지문(`sig`)을 서버가 다시 확인하므로, 그 사이 파일이 바뀌면 건드리지 않고 거절합니다(보고서·SG 패널 공통).
- 오류 알림 버튼은 `uxFixButtons(t, msg)` 의 메시지 패턴으로 정해집니다. 새 오류 문구에 바로가기를 붙이려면 패턴과 핸들러를 한 줄 추가하세요.
- 주소 해시는 `dockHashWrite()`(pushState) 와 `dockHashApply()`(popstate)로 오갑니다. 복원 중에는 `DK.busy` 로 되쓰기를 막습니다.
