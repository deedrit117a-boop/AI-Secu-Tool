# app.py 에서 _include() 로 불러오는 부분 (app.py 와 같은 이름공간을 쓴다)
# ----------------------------------------------------------------- 자가 점검 / 문제 신고 파일
def _chk(cid, label, status, detail="", fix=""):
    return {"id": cid, "label": label, "status": status, "detail": detail, "fix": fix}


def _cmd_version(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return ((p.stdout or "") + (p.stderr or "")).strip().splitlines()[0][:120] if p.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError, IndexError):
        return ""


def run_selfcheck(online=False):
    """이 PC 에서 도구가 동작하는 데 필요한 것들을 점검한다. online=True 면 GitLab/Jira 에 실제로 접속해 본다(읽기 전용)."""
    import importlib.util
    out = []
    pv = sys.version_info
    out.append(_chk("python", "Python", "ok" if pv >= (3, 10) else "fail", "%d.%d.%d" % pv[:3],
                    "" if pv >= (3, 10) else "Python 3.10 이상을 설치하세요 (python.org, 설치 화면의 'Add python.exe to PATH' 체크)"))
    for mod, label, need in (("flask", "Flask 패키지", True), ("requests", "requests 패키지", True), ("openpyxl", "openpyxl 패키지 (엑셀 연동)", False)):
        ok = importlib.util.find_spec(mod) is not None
        out.append(_chk(mod, label, "ok" if ok else ("fail" if need else "warn"), "설치됨" if ok else "없음",
                        "" if ok else "도구 폴더에서 run.bat 을 다시 실행하거나, 터미널에서 python -m pip install -r requirements.txt"))
    gv = _cmd_version(["git", "--version"]) if shutil.which("git") else ""
    out.append(_chk("git", "git", "ok" if gv else "fail", gv or "찾을 수 없음", "" if gv else "git 을 설치한 뒤 도구를 다시 시작하세요 (git-scm.com, 설치 옵션은 기본값)"))
    try:
        os.makedirs(DATA, exist_ok=True)
        probe = os.path.join(DATA, ".write_test_%d" % os.getpid())
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
        free = shutil.disk_usage(DATA).free // (1024 * 1024)
        out.append(_chk("data", "데이터 폴더 쓰기", "ok" if free >= 500 else "warn", "%s (여유 %d MB)" % (DATA, free),
                        "" if free >= 500 else "저장소를 받을 여유 공간이 부족합니다. 디스크를 정리하세요"))
    except OSError as e:
        out.append(_chk("data", "데이터 폴더 쓰기", "fail", "%s: %s" % (DATA, e), "도구 폴더를 쓰기 가능한 위치(예: 사용자 폴더)로 옮기세요"))
    cfg = load_config()
    envs = cfg.get("environments", [])
    out.append(_chk("envs", "등록된 환경", "ok" if envs else "warn", "%d개" % len(envs),
                    "" if envs else "환경설정에서 환경을 추가하거나, 백업 파일을 올려 복구하세요"))
    if envs:
        got = empty = 0
        for e in envs:
            r = _resolve_env(e, cfg)
            if not r.get("repo_dir"):
                empty += 1
            elif os.path.isdir(sg_path(r)):
                got += 1
        out.append(_chk("repos", "저장소 받음", "ok" if got == len(envs) else "warn", "%d / %d개 환경 (repo 경로 비어 있음 %d개)" % (got, len(envs), empty),
                        "" if got == len(envs) else "작업 탭에서 저장소를 다운로드하세요. repo 로컬 경로가 비어 있으면 환경설정의 유형별 기본값에 입력하세요"))
    loc = load_local()
    for kind, site in cfg.get("sites", {}).items():
        has = bool((loc.get("tokens") or {}).get(kind))
        out.append(_chk("token_" + kind, "%s GitLab 토큰" % site.get("label", kind), "ok" if has else "warn", "설정됨" if has else "없음",
                        "" if has else "환경설정에서 api scope 토큰을 입력하세요"))
        if online and has:
            e0 = next((x for x in envs if x.get("kind") == kind), None)
            if e0:
                try:
                    who = gl(get_env(e0["id"]), "GET", "/user")
                    out.append(_chk("gitlab_" + kind, "%s GitLab 접속" % site.get("label", kind), "ok", "%s (%s)" % (who.get("username", ""), site.get("base_url", ""))))
                except ApiError as ex:
                    out.append(_chk("gitlab_" + kind, "%s GitLab 접속" % site.get("label", kind), "fail", str(ex)[:200], "VPN/사내망 연결과 토큰(api scope, 만료일)을 확인하세요"))
    js = jira_settings()
    if js["token"]:
        if online:
            try:
                d = jira_call("GET", "/myself")
                out.append(_chk("jira", "Jira 접속", "ok", "%s (%s)" % (d.get("displayName", ""), js["base_url"])))
            except ApiError as ex:
                out.append(_chk("jira", "Jira 접속", "fail", str(ex)[:200], "주소·인증 방식·API 키를 확인하세요"))
        else:
            out.append(_chk("jira", "Jira API 키", "ok", "설정됨 (접속 확인은 '접속 확인 포함')"))
    else:
        out.append(_chk("jira", "Jira API 키", "info", "없음 (선택 기능)"))
    av = _cmd_version(["aws", "--version"]) if aws_cli_present() else ""
    out.append(_chk("aws", "AWS CLI (AWS 조회·비교용)", "ok" if av else "info", ("%s, 프로필 %d개" % (av, len(aws_profiles()))) if av else "없음 (선택 기능)",
                    "" if av else "AWS 가져오기/비교를 쓰려면 AWS CLI v2 를 설치하고 aws configure sso 로 프로필을 만드세요"))
    ex = excel_settings()
    ex_ok = bool(ex["folder"] and ex["file"])
    out.append(_chk("excel", "엑셀 연동", "ok" if ex_ok else "info", ("%s / %s" % (ex["folder"], ex["file"])) if ex_ok else "설정 안 됨 (선택 기능)"))
    try:
        errs = 0
        cutoff = datetime.now().timestamp() - 86400
        with open(os.path.join(DATA, "app.log"), encoding="utf-8", errors="replace") as f:
            for line in f.readlines()[-2000:]:
                m = re.match(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) \[ERROR\]", line)
                if m and datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp() >= cutoff:
                    errs += 1
        out.append(_chk("log", "최근 24시간 서버 오류", "ok" if not errs else "warn", "%d건" % errs, "" if not errs else "'문제 신고 파일 만들기'로 로그를 담아 전달하세요"))
    except OSError:
        out.append(_chk("log", "최근 24시간 서버 오류", "ok", "기록 없음"))
    root = os.path.join(DATA, "backup")
    last = sorted(d for d in os.listdir(root) if re.match(r"^\d{6}_\d{6}$", d))[-1:] if os.path.isdir(root) else []
    out.append(_chk("backup", "자동 보관된 설정 사본", "info", ("가장 최근 %s (data/backup)" % last[0]) if last else "없음",
                    "토큰·메타 데이터는 위의 '백업 / 복구'에서 파일로 받아 두세요"))
    bs = backup_status()
    if bs["has_data"]:
        out.append(_chk("backup_file", "설정 백업 파일", "ok" if not bs["due"] else "warn",
                        ("마지막 %s (%d일 전)" % (bs["last"], bs["days"])) if bs["last"] else "한 번도 받지 않음",
                        "" if not bs["due"] else "환경설정의 '백업 / 복구'에서 백업 파일을 받아 두세요 (%d일마다 권장)" % bs["due_days"]))
    try:
        total = 0
        for cur, _d, names in os.walk(DATA):
            for n in names:
                try:
                    total += os.path.getsize(os.path.join(cur, n))
                except OSError:
                    pass
        mb = total // (1024 * 1024)
        out.append(_chk("datasize", "data 폴더 크기", "ok" if mb < 300 else "warn", "%d MB" % mb,
                        "" if mb < 300 else "data/backup, excel_backup 의 오래된 사본이나 repo 가 쌓였습니다. 필요 없는 사본을 지우세요"))
        lg = os.path.getsize(os.path.join(DATA, "app.log")) // 1024 if os.path.exists(os.path.join(DATA, "app.log")) else 0
        out.append(_chk("logsize", "서버 로그 크기", "ok" if lg < 5120 else "warn", "%d KB" % lg, "" if lg < 5120 else "로그가 커졌습니다. 서버를 재시작하면 새 파일로 교체됩니다"))
    except OSError:
        pass
    if _code_mtime() > _START_MTIME + 1:
        out.append(_chk("stale", "서버 코드 변경", "warn", "도구가 업데이트되었지만 서버가 이전 코드로 실행 중", "서버를 재시작하세요 (왼쪽 아래 '서버 재시작')"))
    return out


@app.get("/api/selfcheck")
def api_selfcheck():
    return jsonify({"version": VERSION, "online": request.args.get("online") == "1", "checks": run_selfcheck(request.args.get("online") == "1")})


def scrub_text(text):
    """로그/설정에 섞였을 수 있는 비밀을 가린다: 저장된 토큰 + 흔한 토큰 모양 + 사용자 폴더 이름"""
    text = scrub(text)
    text = re.sub(r"glpat-[A-Za-z0-9_\-]{8,}", "glpat-***", text)
    text = re.sub(r"(?i)(PRIVATE-TOKEN|Authorization)(['\"]?\s*[:=]\s*['\"]?)(Bearer\s+)?[^\s'\",]{6,}", r"\1\2***", text)
    text = re.sub(r"(?i)(token|secret|password)(['\"]?\s*[:=]\s*['\"]?)[^\s'\",}]{6,}", r"\1\2***", text)
    text = re.sub(r"(?i)([A-Z]:[\\/]+Users[\\/]+)[^\\/\s'\"]+", r"\1***", text)
    return text


@app.get("/api/support/bundle")
def api_support_bundle():
    """문제가 생겼을 때 개발자에게 전달할 진단 파일(JSON). 토큰·API 키는 들어가지 않고, 로그의 비밀 값과 사용자 폴더 이름은 가린다."""
    import platform
    loc = load_local()
    cfg = load_config()
    tail = []
    try:
        with open(os.path.join(DATA, "app.log"), encoding="utf-8", errors="replace") as f:
            tail = [scrub_text(x.rstrip("\n")) for x in f.readlines()[-400:]]
    except OSError:
        pass
    info = {"app_version": VERSION, "os": platform.platform(), "python": sys.version.split()[0], "git": _cmd_version(["git", "--version"]) if shutil.which("git") else "",
            "aws_cli": _cmd_version(["aws", "--version"]) if aws_cli_present() else "", "demo": os.environ.get("TF_ACL_DEMO") == "1"}
    envs = [{"id": e.get("id"), "kind": e.get("kind"), "group": e.get("group"), "env": e.get("env"), "sg_dir": e.get("sg_dir")} for e in cfg.get("environments", [])]
    settings = {"tokens_set": sorted(k for k, v in (loc.get("tokens") or {}).items() if v), "jira_token_set": bool((loc.get("jira") or {}).get("token")),
                "account_set": bool(loc.get("account")), "aws_profile_map_count": len(loc.get("aws_profiles") or {}), "excel_configured": bool(excel_settings()["file"])}
    bundle = {"format": "traform-acl-support", "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "info": info, "settings": settings,
              "selfcheck": [{k: scrub_text(v) if isinstance(v, str) else v for k, v in c.items()} for c in run_selfcheck(False)],
              "environments": envs, "log_tail": tail}
    name = "traform-acl-support-%s.json" % datetime.now().strftime("%y%m%d_%H%M%S")
    log_event("INFO", "문제 신고 파일 생성: %s (로그 %d줄)" % (name, len(tail)))
    return Response(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", mimetype="application/json",
                    headers={"Content-Disposition": 'attachment; filename="%s"' % name})
