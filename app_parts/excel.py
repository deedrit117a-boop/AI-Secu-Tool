# app.py 에서 _include() 로 불러오는 부분 (app.py 와 같은 이름공간을 쓴다)
# ----------------------------------------------------------------- 엑셀 연동 (ACL 적용내역 시트에 한 건당 한 줄 기록)
# 설정(폴더/파일/시트/작성자)은 이 PC 의 local.json 에 저장한다 (경로가 PC 마다 다르므로 공유하지 않음).
# 기록 전에 사용자가 미리보기에서 확인/수정하고, 파일은 쓰기 전에 data/excel_backup 에 복사해 둔다.
EXCEL_DEFAULT_SHEET = "ACL 적용내역"
EXCEL_HEADERS = ["적용", "Account(Cloud 일경우)", "리전(Cloud일 경우)", "출발지 (Zone)", "출발지 (보안그룹)", "목적지 (Zone)",
                 "목적지 (보안그룹)", "프로토콜", "서비스", "Action", "티켓번호", "처리자"]       # C ~ N 열
EXCEL_FIRST_COL, EXCEL_LAST_COL = 3, 14
EXCEL_EXT = (".xlsx", ".xlsm")
EXCEL_LOCK = threading.RLock()


def excel_settings():
    ex = load_local().get("excel") or {}
    return {"folder": ex.get("folder", ""), "file": ex.get("file", ""), "sheet": ex.get("sheet") or EXCEL_DEFAULT_SHEET, "writer": ex.get("writer", "")}


def excel_list_files(folder):
    if not folder or not os.path.isdir(folder):
        return []
    return sorted(f for f in os.listdir(folder) if f.lower().endswith(EXCEL_EXT) and not f.startswith("~$")
                  and os.path.isfile(os.path.join(folder, f)))


def excel_path(st=None):
    st = st or excel_settings()
    if not st["folder"] or not st["file"]:
        raise ApiError("환경설정의 '엑셀 연동'에서 폴더와 엑셀 파일을 먼저 선택하세요", 400, excel_error="not_configured")
    if st["file"] not in excel_list_files(st["folder"]):
        raise ApiError("선택한 엑셀 파일을 찾을 수 없습니다: %s (폴더 %s)" % (st["file"], st["folder"]), 404, excel_error="file_missing")
    return os.path.join(st["folder"], st["file"])


def excel_pick_folder(initial=""):
    """이 PC 에서 폴더 선택 창을 연다 (서버가 사용자의 PC 에서 실행되므로 가능). 별도 프로세스로 띄워 서버를 막지 않는다.
    한글 경로가 윈도우 콘솔 인코딩(cp949)으로 깨지지 않도록 자식 프로세스는 UTF-8 로 출력하게 하고, 받는 쪽도 바이트로 받아 직접 해석한다."""
    code = ("import sys, tkinter as tk\nfrom tkinter import filedialog\nr = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
            "p = filedialog.askdirectory(initialdir=sys.argv[1] or None, title='엑셀 파일이 있는 폴더 선택', parent=r)\n"
            "sys.stdout.buffer.write((p or '').encode('utf-8')); sys.stdout.flush()\n")
    try:
        out = subprocess.run([sys.executable, "-X", "utf8", "-c", code, initial or ""], capture_output=True, timeout=600,
                             env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"))
    except subprocess.TimeoutExpired:
        raise ApiError("폴더 선택 창이 응답하지 않아 닫았습니다. 경로를 직접 입력하세요.")
    if out.returncode != 0:
        log_event("WARN", "폴더 선택 창 실패: %s" % (out.stderr or b"").decode("utf-8", "replace")[:300])
        raise ApiError("폴더 선택 창을 열 수 없습니다 (tkinter 없음). 경로를 직접 입력하세요.")
    raw = out.stdout or b""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp949", "replace")
    text = text.strip()
    return os.path.normpath(text) if text else ""


def _openpyxl():
    try:
        import openpyxl
        return openpyxl
    except ImportError:
        raise ApiError("엑셀 연동에는 openpyxl 패키지가 필요합니다. run.bat 을 다시 실행하거나 'pip install openpyxl' 을 실행하세요.", 424, excel_error="no_openpyxl")


def _norm_header(x):
    return re.sub(r"\s+", "", str(x or "")).lower()


def excel_locked_by_excel(path):
    """다른 프로그램(엑셀)이 이 파일을 쓰기 잠금으로 열고 있는지. '~$' 잠금 파일이 있거나, 쓰기로 열어 보려 할 때 공유 위반이면 True"""
    if os.path.exists(os.path.join(os.path.dirname(path), "~$" + os.path.basename(path))):
        return True
    if os.name != "nt" or not os.path.exists(path):
        return False
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateFileW.restype = wintypes.HANDLE
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    h = k.CreateFileW(path, 0xC0000000, 1, None, 3, 0x80, None)       # 읽기+쓰기 / 읽기만 공유 / 기존 파일만 (열기만 하고 바로 닫음)
    if h == wintypes.HANDLE(-1).value:
        return ctypes.get_last_error() == 32                          # 32 = 다른 프로세스가 사용 중
    k.CloseHandle(h)
    return False


def excel_find_sheet(wb, name):
    if name in wb.sheetnames:
        return wb[name]
    low = {_norm_header(n): n for n in wb.sheetnames}
    if _norm_header(name) in low:
        return wb[low[_norm_header(name)]]
    raise ApiError("엑셀에 '%s' 시트가 없습니다. 시트 목록: %s" % (name, ", ".join(wb.sheetnames)), 404, excel_error="sheet_missing", sheets=wb.sheetnames)


def excel_last_row(ws):
    """C 열에서 내용이 있는 마지막 행 번호 (없으면 0)"""
    for r in range(ws.max_row, 0, -1):
        v = ws.cell(row=r, column=EXCEL_FIRST_COL).value
        if v is not None and str(v).strip() != "":
            return r
    return 0


def excel_header_check(ws, last):
    """C~N 열 머리글이 기대한 양식과 같은지 확인 (다르면 경고만)"""
    for r in range(1, min(last, 15) + 1):
        if _norm_header(ws.cell(row=r, column=EXCEL_FIRST_COL).value) == _norm_header(EXCEL_HEADERS[0]):
            found = [str(ws.cell(row=r, column=c).value or "").strip() for c in range(EXCEL_FIRST_COL, EXCEL_LAST_COL + 1)]
            diff = [(EXCEL_HEADERS[i], found[i]) for i in range(len(EXCEL_HEADERS)) if _norm_header(found[i]) != _norm_header(EXCEL_HEADERS[i])]
            return {"row": r, "headers": found, "mismatch": diff}
    return {"row": 0, "headers": [], "mismatch": [("적용", "머리글 행을 찾지 못함")]}


def read_shared(path):
    """파일 전체를 읽는다. 엑셀이 열고 있는 파일은 파이썬의 기본 열기(open)가 '공유 위반(권한 없음)'으로 거부되므로,
    윈도우에서는 삭제 공유까지 허용하는 방식(CreateFile)으로 읽는다 (엑셀은 읽기는 허용함)."""
    if os.name != "nt":
        with open(path, "rb") as f:
            return f.read()
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateFileW.restype = wintypes.HANDLE
    k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    k.ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    h = k.CreateFileW(path, 0x80000000, 7, None, 3, 0x80, None)      # 읽기 / 읽기·쓰기·삭제 공유 / 기존 파일만
    if h == wintypes.HANDLE(-1).value:
        err = ctypes.get_last_error()
        raise PermissionError(13, "파일을 읽을 수 없습니다 (윈도우 오류 %d)" % err, path)
    try:
        chunks, buf = [], ctypes.create_string_buffer(1 << 20)
        got = wintypes.DWORD(0)
        while k.ReadFile(h, buf, len(buf), ctypes.byref(got), None) and got.value:
            chunks.append(buf.raw[:got.value])
        return b"".join(chunks)
    finally:
        k.CloseHandle(h)


def excel_open(path):
    import io
    ox = _openpyxl()
    try:
        return ox.load_workbook(io.BytesIO(read_shared(path)), keep_vba=path.lower().endswith(".xlsm"))
    except PermissionError:
        raise ApiError("엑셀 파일을 읽을 수 없습니다 (권한 없음 또는 문서 보안 프로그램이 막고 있습니다): %s" % os.path.basename(path), 423, excel_error="locked")
    except Exception as e:
        raise ApiError("엑셀 파일을 열지 못했습니다 (.xlsx 형식이 아니거나 암호/문서 보안이 걸린 파일일 수 있습니다): %s" % str(e)[:160], 400, excel_error="open_failed")


def excel_backup(path):
    d = os.path.join(DATA, "excel_backup")
    os.makedirs(d, exist_ok=True)
    dest = os.path.join(d, "%s_%s" % (datetime.now().strftime("%y%m%d_%H%M%S"), os.path.basename(path)))
    with open(dest, "wb") as f:                 # 엑셀이 열고 있어도 복사할 수 있게 공유 읽기로 읽는다
        f.write(read_shared(path))
    old = sorted(os.listdir(d))
    for f in old[:-10]:                    # 최근 10개만 보관
        try:
            os.remove(os.path.join(d, f))
        except OSError:
            pass
    return dest


def _cell_value(v):
    t = str(v if v is not None else "").strip()
    return int(t) if re.fullmatch(r"\d{1,5}", t) else t        # 포트 번호는 숫자로, 나머지는 글자로


EXCEL_COM_PS1 = r"""
param([string]$PayloadPath)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
function Done($o) { [Console]::Out.Write(($o | ConvertTo-Json -Compress -Depth 6)); exit 0 }
try {
  $p = Get-Content -Raw -Encoding UTF8 -LiteralPath $PayloadPath | ConvertFrom-Json
  try { $xl = [System.Runtime.InteropServices.Marshal]::GetActiveObject('Excel.Application') } catch { Done @{ ok = $false; code = 'not_open'; detail = 'Excel is not running' } }
  $wb = $null
  foreach ($w in $xl.Workbooks) { if ($w.FullName -ieq $p.path) { $wb = $w } }
  if ($wb -eq $null) { foreach ($w in $xl.Workbooks) { if ($w.Name -ieq $p.name) { $wb = $w } } }
  if ($wb -eq $null) { Done @{ ok = $false; code = 'not_open'; detail = 'workbook is not open in the running Excel' } }
  $names = @(); foreach ($w in $wb.Worksheets) { $names += $w.Name }
  $ws = $null; foreach ($w in $wb.Worksheets) { if ($w.Name -eq $p.sheet) { $ws = $w } }
  if ($ws -eq $null) { Done @{ ok = $false; code = 'sheet_missing'; sheets = $names } }
  $last = $ws.Cells.Item($ws.Rows.Count, 3).End(-4162).Row
  if ($last -eq 1 -and [string]::IsNullOrWhiteSpace([string]$ws.Cells.Item(1, 3).Text)) { $last = 0 }
  $hrow = 0; $headers = @()
  $top = [Math]::Min([Math]::Max($last, 1), 15)
  for ($r = 1; $r -le $top; $r++) {
    if (([string]$ws.Cells.Item($r, 3).Text).Replace(' ', '') -eq $p.header_first) {
      $hrow = $r; for ($c = 3; $c -le 14; $c++) { $headers += [string]$ws.Cells.Item($r, $c).Text }; break
    }
  }
  if ($p.mode -eq 'query') { Done @{ ok = $true; last = $last; header_row = $hrow; headers = $headers; sheets = $names; readonly = [bool]$wb.ReadOnly; protected = [bool]$ws.ProtectContents } }
  if ($wb.ReadOnly) { Done @{ ok = $false; code = 'readonly' } }
  if ($ws.ProtectContents) { Done @{ ok = $false; code = 'protected' } }
  $n = $p.rows.Count
  $first = $last + 1
  $data = New-Object 'object[,]' $n, 12
  for ($i = 0; $i -lt $n; $i++) { for ($j = 0; $j -lt 12; $j++) { $data[$i, $j] = $p.rows[$i][$j] } }
  $dest = $ws.Range($ws.Cells.Item($first, 3), $ws.Cells.Item($first + $n - 1, 14))
  if ($last -gt 0) {
    $ws.Range($ws.Cells.Item($last, 3), $ws.Cells.Item($last, 14)).Copy() | Out-Null
    $dest.PasteSpecial(-4122) | Out-Null
    $wb.Application.CutCopyMode = $false
  }
  $dest.Value2 = $data
  Done @{ ok = $true; first = $first; last = ($first + $n - 1); written = $n }
} catch {
  Done @{ ok = $false; code = 'error'; detail = $_.Exception.Message }
}
"""


def excel_com(mode, path, sheet, rows=None):
    """엑셀 프로그램이 이 파일을 열어 둔 경우, 실행 중인 엑셀에 직접 읽기/쓰기 (PowerShell COM, 윈도우 + 엑셀 설치 필요).
    반환: dict(ok, ...). 엑셀에 열려 있지 않으면 {'ok': False, 'code': 'not_open'}"""
    if os.name != "nt":
        return {"ok": False, "code": "not_open"}
    import tempfile
    d = tempfile.mkdtemp(prefix="tfacl_xl_")
    try:
        ps1, pj = os.path.join(d, "x.ps1"), os.path.join(d, "p.json")
        with open(ps1, "w", encoding="utf-8-sig") as f:
            f.write(EXCEL_COM_PS1)
        with open(pj, "w", encoding="utf-8") as f:
            json.dump({"mode": mode, "path": path, "name": os.path.basename(path), "sheet": sheet, "rows": rows or [],
                       "header_first": _norm_header(EXCEL_HEADERS[0])}, f, ensure_ascii=False)
        try:
            out = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", ps1, pj],
                                 capture_output=True, timeout=90, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired) as e:
            raise ApiError("실행 중인 엑셀에 연결하지 못했습니다 (PowerShell): %s" % str(e)[:120], 502, excel_error="com_failed")
        text = (out.stdout or b"").decode("utf-8", "replace").strip()
        try:
            return json.loads(text)
        except ValueError:
            log_event("WARN", "엑셀 COM 응답 해석 실패: %s | %s" % (text[:200], (out.stderr or b"").decode("utf-8", "replace")[:200]))
            raise ApiError("실행 중인 엑셀의 응답을 해석하지 못했습니다. 정책으로 PowerShell 이 막혀 있을 수 있습니다.", 502, excel_error="com_failed")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def excel_com_error(res):
    code = res.get("code")
    msgs = {"sheet_missing": "열려 있는 엑셀에 이 시트가 없습니다: %s" % ", ".join(res.get("sheets") or []),
            "readonly": "엑셀에서 이 파일이 '읽기 전용'으로 열려 있어 기록할 수 없습니다.",
            "protected": "시트가 보호되어 있어 기록할 수 없습니다 (시트 보호를 해제하세요)."}
    return ApiError(msgs.get(code) or "열려 있는 엑셀에 기록하지 못했습니다: %s" % (res.get("detail") or code), 502, excel_error=code or "com_failed")


def excel_append(path, sheet, rows):
    """시트의 C 열 마지막 내용 바로 아래부터 rows(각 12칸: C~N)를 한 줄씩 쓴다. 이전 줄의 서식을 그대로 복사."""
    from copy import copy
    # 엑셀이 이 파일을 열어 두었으면(~$ 잠금 파일) 파일을 바꿔치기하지 않고, 실행 중인 엑셀에 직접 기록한다
    # (엑셀의 자동 저장/클라우드 동기화로 반영됨, 서식·그림 등도 그대로). 엑셀에서 열려 있지 않다고 나오면 파일에 직접 기록한다.
    open_in_excel = excel_locked_by_excel(path)
    if open_in_excel:
        with EXCEL_LOCK:
            res = excel_com("append", path, sheet, [[_cell_value(v) for v in r] for r in rows])      # 포트 번호는 숫자로
            if res.get("ok"):
                try:
                    backup = excel_backup(path)
                except Exception:
                    backup = ""
                return {"first_row": res["first"], "last_row": res["last"], "backup": backup, "written": res["written"],
                        "open_in_excel": True, "via": "excel"}
            if res.get("code") != "not_open":
                raise excel_com_error(res)
    with EXCEL_LOCK:
        wb = excel_open(path)
        ws = excel_find_sheet(wb, sheet)
        last = excel_last_row(ws)
        first = last + 1
        for i, cells in enumerate(rows):
            r = first + i
            for j, v in enumerate(cells[:EXCEL_LAST_COL - EXCEL_FIRST_COL + 1]):
                c = ws.cell(row=r, column=EXCEL_FIRST_COL + j)
                c.value = _cell_value(v)
                if last:
                    src = ws.cell(row=last, column=EXCEL_FIRST_COL + j)
                    if src.has_style:
                        c._style = copy(src._style)
            if last and ws.row_dimensions[last].height:
                ws.row_dimensions[r].height = ws.row_dimensions[last].height
        end = first + len(rows) - 1
        af = ws.auto_filter.ref
        if af:                                  # 필터 범위가 마지막 줄까지였다면 새 줄도 포함하도록 늘린다
            m = re.match(r"^([A-Z]+)(\d+):([A-Z]+)(\d+)$", af)
            if m and int(m.group(4)) >= last:
                ws.auto_filter.ref = "%s%s:%s%d" % (m.group(1), m.group(2), m.group(3), max(end, int(m.group(4))))
        backup = excel_backup(path)
        tmp = os.path.join(os.path.dirname(path), "~tf_tmp_%d%s" % (os.getpid(), os.path.splitext(path)[1]))
        try:
            wb.save(tmp)
            for attempt in range(5):
                try:
                    os.replace(tmp, path)
                    break
                except PermissionError:
                    if attempt == 4:
                        raise ApiError("엑셀 파일에 저장하지 못했습니다 (다른 프로그램이 파일을 잠그고 있습니다). 잠시 후 다시 시도하거나 엑셀을 닫아 보세요. 백업: %s" % backup, 423, excel_error="locked")
                    time.sleep(0.4)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
    return {"first_row": first, "last_row": end, "backup": backup, "written": len(rows), "open_in_excel": open_in_excel, "via": "file"}


def _excel_log_path():
    return os.path.join(DATA, "excel_log.json")


def excel_row_key(cells, direction):
    # 티켓|목적지|출발지|프로토콜|서비스|Action|방향 (같은 건을 두 번 기록하지 않도록)
    return "|".join(str(x) for x in (cells[10], cells[6], cells[4], cells[7], cells[8], cells[9], direction))


def _strip32(c):
    return c[:-3] if c.endswith("/32") else c


def excel_account_name(env):
    """엑셀 D열(Account): 작업한 종류-환경 (예: Lordnine-Asia-review). 환경 이름이 종류 이름과 같거나 이미 들어 있으면 겹쳐 쓰지 않는다."""
    group, e = (env.get("group") or "").strip(), (env.get("env") or "").strip()
    if not e or e.lower() == group.lower() or group.lower().endswith("-" + e.lower()):
        return group or e
    return "%s-%s" % (group, e) if group else e


def excel_cells_for_rule(env, sg_name, rule, direction, action, ticket, writer):
    em = ((load_meta().get("envs") or {}).get(env["id"], {}).get("sgs") or {}).get(sg_name, {})
    sg_id = (em.get("sg_id") or "").strip()
    region_code = aws_scope(env)[1]
    zone = re.sub(r"-sg$", "", sg_name)
    dest = "%s(%s)" % (sg_name, sg_id) if sg_id else sg_name
    other = rule["security_groups"] or ", ".join(_strip32(c) for c in rule["cidr_blocks"]) or "-"
    proto = "ALL" if str(rule["protocol"]) == "-1" else str(rule["protocol"]).upper()
    port = "ALL" if str(rule["protocol"]) == "-1" else (str(rule["from_port"]) if rule["from_port"] == rule["to_port"] else "%s-%s" % (rule["from_port"], rule["to_port"]))
    account = excel_account_name(env)
    region = REGION_NAMES.get(region_code, region_code)
    if direction == "ingress":      # 소스 -> 이 SG
        src_zone, src, dst_zone, dst = "-", other, zone, dest
    else:                           # 이 SG -> 대상 (아웃바운드는 출발지/목적지를 바꿔 기록)
        src_zone, src, dst_zone, dst = zone, dest, "-", other
    return ["AWS", account, region, src_zone, src, dst_zone, dst, proto, port, action, ticket, writer]


def excel_build_rows(env, ticket):
    """이번 작업(브랜치)의 변경 규칙을 엑셀 한 줄씩으로 만든다. 추가/변경 -> 허용, 삭제 -> 삭제."""
    st = excel_settings()
    summ = change_summary(env)
    ticket = (ticket or "").strip() or (re.search(r"[A-Za-z][A-Za-z0-9]*-\d+", summ["branch"]) or [""])[0]
    rows = []
    done = (read_json(_excel_log_path(), {}).get("keys") or {})
    for sg in summ["sgs"]:
        try:
            e = get_env(sg["env_id"])
        except ApiError:
            e = env
        for items, action in ((sg["added"], "허용"), (sg["removed"], "삭제")):
            for r in items:
                cells = excel_cells_for_rule(e, sg["name"], r, r["direction"], action, ticket, st["writer"])
                key = excel_row_key(cells, r["direction"])
                rows.append({"cells": cells, "direction": r["direction"], "sg": sg["name"], "env_id": e["id"], "dup": key in done,
                             "checked": r["direction"] == "ingress" and key not in done, "key": key,
                             "note": "" if (((load_meta().get("envs") or {}).get(e["id"], {}).get("sgs") or {}).get(sg["name"], {}).get("sg_id")) else "SG ID 없음(메타 데이터)"})
    return {"branch": summ["branch"], "ticket": ticket, "rows": rows}


def _excel_pending_path():
    return os.path.join(DATA, "excel_pending.json")


@app.get("/api/excel/settings")
def api_excel_settings():
    st = excel_settings()
    try:
        import openpyxl  # noqa: F401
        has = True
    except ImportError:
        has = False
    return jsonify({**st, "files": excel_list_files(st["folder"]), "openpyxl": has, "default_sheet": EXCEL_DEFAULT_SHEET,
                    "configured": bool(st["folder"] and st["file"] and st["file"] in excel_list_files(st["folder"]))})


@app.put("/api/excel/settings")
def api_excel_settings_put():
    b = request.get_json() or {}
    folder = (b.get("folder") or "").strip().strip('"')
    if folder and not os.path.isdir(folder):
        raise ApiError("폴더를 찾을 수 없습니다: %s" % folder)
    fname = (b.get("file") or "").strip()
    if fname and (os.path.basename(fname) != fname or fname not in excel_list_files(folder)):
        raise ApiError("선택한 폴더에 없는 엑셀 파일입니다: %s" % fname)
    with CFG_LOCK:
        loc = load_local()
        loc["excel"] = {"folder": os.path.normpath(folder) if folder else "", "file": fname,
                        "sheet": (b.get("sheet") or "").strip() or EXCEL_DEFAULT_SHEET, "writer": (b.get("writer") or "").strip()}
        write_json(LOCAL_PATH, loc)
    return jsonify({"ok": True, "files": excel_list_files(loc["excel"]["folder"])})


@app.post("/api/excel/pick-folder")
def api_excel_pick_folder():
    folder = excel_pick_folder((request.get_json(silent=True) or {}).get("initial", ""))
    return jsonify({"folder": folder, "files": excel_list_files(folder)})


@app.get("/api/excel/files")
def api_excel_files():
    return jsonify({"files": excel_list_files((request.args.get("folder") or "").strip().strip('"'))})


@app.get("/api/excel/check")
def api_excel_check():
    """연결 테스트: 파일/시트를 열어 C 열 마지막 행과 머리글(C~N)이 양식과 맞는지 확인 (읽기 전용)"""
    st = excel_settings()
    path = excel_path(st)
    locked = excel_locked_by_excel(path)
    if locked:                       # 엑셀에서 열려 있으면 열려 있는 엑셀의 현재 내용을 본다 (아직 저장 안 한 편집 포함)
        res = excel_com("query", path, st["sheet"])
        if res.get("ok"):
            found = [str(x).strip() for x in (res.get("headers") or [])]
            diff = [(EXCEL_HEADERS[i], found[i] if i < len(found) else "") for i in range(len(EXCEL_HEADERS))
                    if _norm_header(found[i] if i < len(found) else "") != _norm_header(EXCEL_HEADERS[i])] if res.get("header_row") else [("적용", "머리글 행을 찾지 못함")]
            return jsonify({"file": path, "sheet": st["sheet"], "sheets": res.get("sheets") or [], "last_row": res["last"], "next_row": res["last"] + 1,
                            "header_row": res.get("header_row", 0), "mismatch": diff, "locked": True, "via": "excel",
                            "readonly": bool(res.get("readonly")), "protected": bool(res.get("protected"))})
        if res.get("code") != "not_open":
            raise excel_com_error(res)
    wb = excel_open(path)
    ws = excel_find_sheet(wb, st["sheet"])
    last = excel_last_row(ws)
    chk = excel_header_check(ws, last)
    return jsonify({"file": path, "sheet": ws.title, "sheets": wb.sheetnames, "last_row": last, "next_row": last + 1,
                    "header_row": chk["row"], "mismatch": chk["mismatch"], "locked": locked, "via": "file"})


@app.get("/api/env/<env_id>/excel/preview")
def api_excel_preview(env_id):
    """엑셀에 기록할 줄 미리보기: 이번 브랜치의 추가/삭제 규칙. apply 후 main 으로 돌아간 뒤에는 직전에 계산해 둔 내용을 쓴다."""
    env = get_env(env_id)
    st = excel_settings()
    key = _status_key(env)
    res = excel_build_rows(env, request.args.get("ticket", ""))
    pend = read_json(_excel_pending_path(), {})
    from_pending = False
    if res["rows"]:
        pend[key] = {"branch": res["branch"], "ticket": res["ticket"], "rows": res["rows"], "ts": time.time()}
        write_json(_excel_pending_path(), pend)
    elif pend.get(key):
        done = (read_json(_excel_log_path(), {}).get("keys") or {})
        saved = pend[key]
        rows = [dict(r) for r in saved["rows"]]
        for r in rows:
            r["cells"] = list(r["cells"])
            if request.args.get("ticket"):
                r["cells"][10] = request.args["ticket"].strip()
            r["key"] = excel_row_key(r["cells"], r["direction"])
            r["dup"] = r["key"] in done
            r["checked"] = r["direction"] == "ingress" and not r["dup"]
        rows = [r for r in rows if not r["dup"]]
        res = {"branch": saved["branch"], "ticket": saved["ticket"], "rows": rows}
        from_pending = bool(rows)
    return jsonify({**res, "configured": bool(st["folder"] and st["file"]), "writer": st["writer"], "headers": EXCEL_HEADERS, "from_pending": from_pending})


@app.post("/api/excel/append")
def api_excel_append():
    """사용자가 미리보기에서 확인한 줄을 엑셀에 기록 (C 열 마지막 내용 바로 아래부터)"""
    b = request.get_json() or {}
    rows = b.get("rows") or []
    if not rows:
        raise ApiError("기록할 줄이 없습니다")
    cells = []
    for r in rows:
        c = r.get("cells") if isinstance(r, dict) else r
        if not isinstance(c, list) or len(c) != EXCEL_LAST_COL - EXCEL_FIRST_COL + 1:
            raise ApiError("각 줄은 C~N 열 12칸이어야 합니다")
        cells.append([str(x) if x is not None else "" for x in c])
    st = excel_settings()
    path = excel_path(st)
    res = excel_append(path, st["sheet"], cells)
    with CFG_LOCK:
        log = read_json(_excel_log_path(), {"keys": {}})
        for r in rows:
            if isinstance(r, dict) and r.get("key"):
                log["keys"][r["key"]] = {"ts": time.time(), "file": os.path.basename(path)}
        if len(log["keys"]) > 3000:
            for k in sorted(log["keys"], key=lambda x: log["keys"][x]["ts"])[:len(log["keys"]) - 3000]:
                del log["keys"][k]
        write_json(_excel_log_path(), log)
        pend = read_json(_excel_pending_path(), {})
        sent = {r.get("key") for r in rows if isinstance(r, dict)}
        for k, v in list(pend.items()):
            v["rows"] = [x for x in v["rows"] if x["key"] not in sent]
            if not v["rows"]:
                del pend[k]
        write_json(_excel_pending_path(), pend)
    log_event("INFO", "엑셀 기록: %s 시트 %s, %d줄 (%d~%d행)" % (os.path.basename(path), st["sheet"], res["written"], res["first_row"], res["last_row"]))
    return jsonify({**res, "file": path, "sheet": st["sheet"]})
