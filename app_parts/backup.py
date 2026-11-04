# app.py 에서 _include() 로 불러오는 부분 (app.py 와 같은 이름공간을 쓴다)
# ----------------------------------------------------------------- 설정 백업 / 복구 (JSON 파일 하나: 새 PC 에서 올리면 설정이 돌아온다)
BACKUP_FORMAT = "traform-acl-backup"
BACKUP_VERSION = 1


def _backup_groups():
    """백업 묶음 -> (화면 이름, [(파일명, 경로)]). 경로는 호출 시점에 읽는다 (테스트가 DATA 를 바꿔 쓰므로)"""
    return {
        "settings": ("환경 목록·메타 데이터", [("config.json", CONFIG_PATH), ("meta.json", META_PATH)]),
        "personal": ("계정·GitLab 토큰·Jira 키·엑셀 설정", [("local.json", LOCAL_PATH)]),
        "history": ("작업 이력·진행 중인 계획", [("history.json", HISTORY_PATH), ("plans.json", PLANS_PATH)]),
        "excel": ("엑셀 기록 상태", [("excel_log.json", _excel_log_path()), ("excel_pending.json", _excel_pending_path())]),
    }


def _backup_check(name, obj):
    bad = ApiError("백업 파일의 %s 내용이 올바르지 않아 복구하지 않았습니다" % name)
    if not isinstance(obj, dict):
        raise bad
    if name == "config.json":
        envs = obj.get("environments")
        if not isinstance(envs, list) or not isinstance(obj.get("sites"), dict) or not isinstance(obj.get("defaults"), dict):
            raise bad
        if any(not isinstance(e, dict) or not e.get("id") or not e.get("kind") or not e.get("sg_dir") for e in envs):
            raise bad
    elif name == "meta.json":
        if not isinstance(obj.get("envs"), dict):
            raise bad
    elif name == "local.json":
        if not isinstance(obj.get("tokens", {}), dict):
            raise bad


def _backup_summary(name, obj):
    """백업 안의 내용을 한 줄로 (토큰 값은 절대 보여주지 않는다)"""
    if name == "config.json":
        return "환경 %d개, 프리셋 %d개" % (len(obj.get("environments") or []), len(obj.get("presets") or []))
    if name == "meta.json":
        return "환경 %d개 분량의 SG 별명/태그/서브넷" % len(obj.get("envs") or {})
    if name == "local.json":
        toks = [k for k, v in (obj.get("tokens") or {}).items() if v]
        return "계정 %s, GitLab 토큰 %s, Jira 키 %s" % (obj.get("account") or "(없음)", ", ".join(toks) if toks else "없음",
                                                      "있음" if (obj.get("jira") or {}).get("token") else "없음")
    return "항목 %d개" % len(obj)


BACKUP_DUE_DAYS = 14


def backup_status():
    """마지막으로 백업을 내려받은 때와 '백업할 때가 되었는지'. 아직 저장한 설정이 없으면(막 설치) 알릴 필요가 없다"""
    loc = load_local()
    last = (loc.get("last_backup") or {}).get("at") or ""
    days = None
    try:
        days = (datetime.now() - datetime.strptime(last, "%Y-%m-%d %H:%M:%S")).days if last else None
    except ValueError:
        last = ""
    has_data = bool(any((loc.get("tokens") or {}).values()) or (loc.get("jira") or {}).get("token") or os.path.exists(META_PATH))
    demo = os.environ.get("TF_ACL_DEMO") == "1"   # 시연 모드는 가짜 데이터라 백업을 권하지 않는다
    return {"last": last or None, "days": days, "has_data": has_data and not demo, "due_days": BACKUP_DUE_DAYS,
            "due": bool(has_data and not demo and (days is None or days >= BACKUP_DUE_DAYS))}


@app.get("/api/backup/info")
def api_backup_info():
    out = []
    for key, (label, files) in _backup_groups().items():
        out.append({"key": key, "label": label, "files": [{"name": n, "exists": os.path.exists(p)} for n, p in files]})
    return jsonify({"groups": out, "version": VERSION, "status": backup_status()})


@app.get("/api/backup/download")
@cfg_locked
def api_backup_download():
    """선택한 묶음의 데이터 파일을 JSON 하나로 묶어 내려보낸다 (personal 을 넣으면 토큰이 들어 있으니 보관에 주의)"""
    groups = _backup_groups()
    want = [x for x in (request.args.get("groups") or ",".join(groups)).split(",") if x]
    if not want or any(k not in groups for k in want):
        raise ApiError("백업할 항목이 올바르지 않습니다")
    files = {}
    for k in want:
        for name, path in groups[k][1]:
            if os.path.exists(path):
                files[name] = read_json(path, {})
    secrets = any(v for v in ((files.get("local.json") or {}).get("tokens") or {}).values()) or bool(((files.get("local.json") or {}).get("jira") or {}).get("token"))
    bk = {"format": BACKUP_FORMAT, "format_version": BACKUP_VERSION, "app_version": VERSION,
          "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "contains_secrets": secrets, "files": files}
    name = "traform-acl-backup-%s.json" % datetime.now().strftime("%y%m%d_%H%M%S")
    loc = load_local()
    loc["last_backup"] = {"at": bk["created"], "groups": want, "secrets": secrets}
    write_json(LOCAL_PATH, loc)
    log_event("INFO", "설정 백업 내려받기: %s (항목 %s, 파일 %d개, 토큰 포함=%s)" % (name, ",".join(want), len(files), secrets))
    data = json.dumps(bk, ensure_ascii=False, indent=2) + "\n"
    return Response(data, mimetype="application/json", headers={"Content-Disposition": 'attachment; filename="%s"' % name})


@app.post("/api/backup/restore")
@cfg_locked
def api_backup_restore():
    """백업 파일 내용으로 데이터 파일을 교체한다. dry_run=true 면 무엇이 들어 있는지만 알려준다.
    교체 전에 현재 파일을 data/backup/<날짜_시간>/ 에 복사해 둔다."""
    b = request.get_json(silent=True) or {}
    bk = b.get("backup")
    if not isinstance(bk, dict) or bk.get("format") != BACKUP_FORMAT or not isinstance(bk.get("files"), dict):
        raise ApiError("Traform ACL 도구가 만든 백업 파일이 아닙니다")
    if (bk.get("format_version") or 0) > BACKUP_VERSION:
        raise ApiError("더 새로운 버전의 도구가 만든 백업 파일입니다. 도구를 최신 버전으로 올린 뒤 다시 시도하세요")
    groups = _backup_groups()
    want = b.get("groups") or list(groups)
    if any(k not in groups for k in want):
        raise ApiError("복구할 항목이 올바르지 않습니다")
    plan = []
    for k in want:
        for name, path in groups[k][1]:
            if name in bk["files"]:
                obj = bk["files"][name]
                _backup_check(name, obj)
                plan.append({"group": k, "label": groups[k][0], "name": name, "path": path, "obj": obj,
                             "summary": _backup_summary(name, obj), "replaces": os.path.exists(path)})
    if not plan:
        raise ApiError("선택한 항목이 백업 파일에 들어 있지 않습니다")
    shown = [{k: v for k, v in p.items() if k not in ("path", "obj")} for p in plan]
    head = {"created": bk.get("created"), "app_version": bk.get("app_version"), "contains_secrets": bool(bk.get("contains_secrets")),
            "available": [k for k in groups if any(n in bk["files"] for n, _ in groups[k][1])]}
    if b.get("dry_run"):
        return jsonify({"dry_run": True, "items": shown, **head})
    dest = os.path.join(DATA, "backup", datetime.now().strftime("%y%m%d_%H%M%S"))
    os.makedirs(dest, exist_ok=True)
    for p in plan:
        if os.path.exists(p["path"]):
            shutil.copy2(p["path"], os.path.join(dest, p["name"]))
    for p in plan:
        obj = p["obj"]
        if p["name"] == "config.json" and b.get("clear_repo_dirs"):   # 다른 PC 로 옮길 때: 이 PC 에는 없는 저장소 경로를 비움
            obj = json.loads(json.dumps(obj))
            for e in obj["environments"]:
                e["repo_dir"] = ""
            for d in (obj.get("defaults") or {}).values():
                if isinstance(d, dict):
                    d["repo_dir"] = ""
        write_json(p["path"], obj)
    _SG_CACHE.clear()
    prune_backups()
    log_event("INFO", "설정 복구: %s (이전 파일 백업 %s)" % (", ".join(p["name"] for p in plan), dest))
    return jsonify({"dry_run": False, "restored": [p["name"] for p in plan], "backup": dest, **head})
