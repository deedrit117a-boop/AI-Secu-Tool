# app.py 에서 _include() 로 불러오는 부분 (app.py 와 같은 이름공간을 쓴다)
# ----------------------------------------------------------------- 정책 규칙(위험 기준·예외) / 만료 규칙 / 정리 제안 / 접근 경로 / 변경 기록
POLICY_DEFAULT = {"mgmt_ports": {str(p): n for p, n in MGMT_PORTS.items()}, "mgmt_max_prefix": MGMT_MAX_PREFIX, "wide_prefix": 16, "exceptions": []}
PORT_NAMES = {22: "SSH", 23: "Telnet", 3389: "RDP", 5985: "WinRM", 5986: "WinRM(HTTPS)", 3306: "MySQL", 5432: "PostgreSQL", 1433: "MSSQL",
              6379: "Redis", 27017: "MongoDB", 9200: "Elasticsearch", 445: "SMB", 21: "FTP"}


def _port_ranges(text):
    """'22, 3389, 1000-2000' 또는 '*' -> [(낮은 포트, 높은 포트)]. 형식이 틀리면 ValueError"""
    out = []
    for part in re.split(r"[,\s;]+", str(text or "").strip()):
        if not part:
            continue
        if part == "*":
            out.append((0, 65535))
            continue
        m = re.match(r"^(\d{1,5})(?:-(\d{1,5}))?$", part)
        if not m:
            raise ValueError("포트 형식이 올바르지 않습니다: %s" % part)
        lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
        if not (0 <= lo <= hi <= 65535):
            raise ValueError("포트 범위가 올바르지 않습니다: %s" % part)
        out.append((lo, hi))
    return out


def normalize_policy(raw):
    """저장된/입력된 정책을 검증해 표준 형태로 만든다. 잘못된 값은 ApiError"""
    raw = raw if isinstance(raw, dict) else {}
    pol = json.loads(json.dumps(POLICY_DEFAULT))
    if "mgmt_ports" in raw:
        mp = raw["mgmt_ports"]
        items = mp.items() if isinstance(mp, dict) else [(p, "") for p in re.split(r"[,\s;]+", str(mp or "")) if p]
        out = {}
        for k, v in items:
            try:
                p = int(str(k).strip())
            except ValueError:
                raise ApiError("관리 포트는 숫자여야 합니다: %s" % k)
            if not 0 <= p <= 65535:
                raise ApiError("관리 포트 범위는 0~65535 입니다: %s" % p)
            out[str(p)] = (str(v).strip() if v else "") or PORT_NAMES.get(p, "포트 %d" % p)
        pol["mgmt_ports"] = out
    for key in ("mgmt_max_prefix", "wide_prefix"):
        if key in raw:
            try:
                v = int(raw[key])
            except (TypeError, ValueError):
                raise ApiError("대역 크기(/N)는 숫자여야 합니다")
            if not 1 <= v <= 32:
                raise ApiError("대역 크기(/N)는 1~32 사이여야 합니다")
            pol[key] = v
    exc = []
    for i, x in enumerate(raw.get("exceptions") or [], start=1):
        if not isinstance(x, dict):
            raise ApiError("예외 %d번 형식이 올바르지 않습니다" % i)
        cidrs = x.get("cidrs") or []
        if isinstance(cidrs, str):
            cidrs = [c for c in re.split(r"[,\s;]+", cidrs) if c]
        if not cidrs:
            raise ApiError("예외 %d번에 소스 대역이 없습니다" % i)
        for c in cidrs:
            if _net(c) is None:
                raise ApiError("예외 %d번 대역 형식이 올바르지 않습니다: %s" % (i, c))
        ports = str(x.get("ports") or "*").strip() or "*"
        try:
            _port_ranges(ports)
        except ValueError as e:
            raise ApiError("예외 %d번: %s" % (i, e))
        exc.append({"name": str(x.get("name") or "").strip() or "예외 %d" % i, "cidrs": [str(c).strip() for c in cidrs], "ports": ports,
                    "env": str(x.get("env") or "").strip()})
    pol["exceptions"] = exc
    return pol


def get_policy():
    try:
        return normalize_policy(load_config().get("policy"))
    except ApiError:
        return json.loads(json.dumps(POLICY_DEFAULT))   # 손으로 고친 설정이 깨져 있어도 검증은 기본 기준으로 계속 동작


def policy_exception(pol, env_id, net, f, t):
    """이 대역·포트 범위를 허용하기로 한 예외의 이름 (없으면 None)"""
    for x in pol["exceptions"]:
        if x["env"] and x["env"] != env_id:
            continue
        if not any(n and n.version == net.version and net.subnet_of(n) for n in (_net(c) for c in x["cidrs"])):
            continue
        if any(lo <= f and t <= hi for lo, hi in _port_ranges(x["ports"])):
            return x["name"]
    return None


@app.get("/api/policy")
def api_policy_get():
    return jsonify({"policy": get_policy(), "defaults": POLICY_DEFAULT})


@app.put("/api/policy")
@cfg_locked
def api_policy_put():
    pol = normalize_policy((request.get_json(silent=True) or {}).get("policy"))
    cfg = load_config()
    cfg["policy"] = pol
    write_json(CONFIG_PATH, cfg)
    log_event("INFO", "정책 규칙 저장: 관리 포트 %d개, 예외 %d개" % (len(pol["mgmt_ports"]), len(pol["exceptions"])))
    return jsonify({"ok": True, "policy": pol, "rev": file_rev(CONFIG_PATH)})


# ---- 규칙 만료일: 설명에 '만료:2026-12-31' (또는 expire=20261231, 만료 261231) 이라고 적으면 도구가 기한을 읽는다
EXPIRE_RE = re.compile(r"(?:만료|expire[sd]?|exp)\s*[:=]?\s*(\d{4}-\d{2}-\d{2}|\d{8}|\d{6})(?!\d)", re.I)


def rule_expiry(desc):
    m = EXPIRE_RE.search(desc or "")
    if not m:
        return None
    s = m.group(1)
    try:
        if "-" in s:
            return datetime.strptime(s, "%Y-%m-%d").date()
        return datetime.strptime(s, "%Y%m%d" if len(s) == 8 else "%y%m%d").date()
    except ValueError:
        return None


def _each_sg():
    """설정된 모든 환경의 (환경, 화면 이름, SG 이름, 규칙 데이터). 같은 폴더를 가리키는 환경은 한 번만"""
    cfg = load_config()
    seen = set()
    for ce in cfg["environments"]:
        try:
            env = _resolve_env(ce, cfg)
        except ApiError:
            continue
        key = (os.path.normcase(os.path.abspath(env["repo_dir"])), env["sg_dir"], env["kind"])
        if key in seen:
            continue
        seen.add(key)
        label = " · ".join(x for x in (env.get("group"), env.get("env"), env.get("label")) if x)
        try:
            sgs = list_sgs(env)
        except Exception:
            continue
        for sg in sgs:
            try:
                yield env, label, sg["name"], _cached_sg(env, sg["name"])
            except Exception as exc:
                log_event("WARN", "보고서 작성 중 SG 파일을 읽지 못했습니다 %s/%s: %r" % (env.get("id"), sg["name"], exc))


def _csv_response(header, rows, name):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow(r)
    return Response("﻿" + buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=%s" % name})


def expiry_rows(days=30, today=None):
    today = today or datetime.now().date()
    rows, with_exp = [], 0
    for env, label, name, data in _each_sg():
        for d in ("ingress", "egress"):
            for i, r in enumerate(data[d]):
                ex = rule_expiry(r["description"])
                if not ex:
                    continue
                with_exp += 1
                left = (ex - today).days
                if left > days:
                    continue
                pr, port, src, _ = _rule_cells(r)
                rows.append({"env_id": env["id"], "env": label, "sg": name, "direction": d, "protocol": pr, "port": port, "source": src,
                             "description": r["description"], "expires": ex.isoformat(), "days_left": left, "status": "expired" if left < 0 else "soon",
                             "idx": i, "sig": _cleanup_sig(r)})
    rows.sort(key=lambda x: (x["days_left"], x["env"], x["sg"]))
    add_owner(rows)
    return rows, with_exp


@app.get("/api/report/expiry")
def api_report_expiry():
    """만료일이 지났거나 N일 안에 오는 규칙 목록 (읽기 전용 - 지우지는 않는다)"""
    try:
        days = max(0, min(int(request.args.get("days", 30)), 3650))
    except ValueError:
        raise ApiError("days 는 숫자여야 합니다")
    rows, with_exp = expiry_rows(days)
    if request.args.get("format") == "csv":
        return _csv_response(["환경", "SG", "방향", "프로토콜", "포트", "소스", "설명", "만료일", "남은 일수", "상태", "담당자"],
                             [[r["env"], r["sg"], r["direction"], r["protocol"], r["port"], r["source"], r["description"], r["expires"], r["days_left"],
                               "지남" if r["status"] == "expired" else "임박", r["owner"]] for r in rows], "expiry-report.csv")
    return jsonify({"days": days, "count": len(rows), "expired": sum(1 for r in rows if r["status"] == "expired"), "with_expiry": with_exp, "rows": rows[:2000]})


# ---- 정리 제안: 다른 규칙에 이미 포함되거나 같은 규칙, 같은 소스인데 포트만 다른 규칙 묶음
def _src_model(r):
    nets, raw = [], set()
    for c in r["cidr_blocks"]:
        n = _net(c)
        (nets.append(n) if n else raw.add(str(c).strip()))
    sgs = {x.strip() for x in str(r["security_groups"] or "").split(",") if x.strip()}
    return nets, raw, sgs, {str(x) for x in (r["prefix_list_ids"] or [])}


def _covers(a, b):
    """규칙 a 가 규칙 b 를 포함하는가 (같은 방향 안에서)"""
    pa, pb = str(a["protocol"]).lower(), str(b["protocol"]).lower()
    if pa != "-1":
        if pa != pb:
            return False
        if pa in ("tcp", "udp"):
            if not (a["from_port"] <= b["from_port"] and b["to_port"] <= a["to_port"]):
                return False
        elif (a["from_port"], a["to_port"]) != (b["from_port"], b["to_port"]):
            return False
    an, ar, asg, apl = _src_model(a)
    bn, br, bsg, bpl = _src_model(b)
    if not (bn or br or bsg or bpl):
        return False
    if not (br <= ar and bsg <= asg and bpl <= apl):
        return False
    return all(any(x.version == y.version and x.subnet_of(y) for y in an) for x in bn)


def _rule_text(d, r):
    pr, port, src, _ = _rule_cells(r)
    return "%s %s %s %s" % ("인바운드" if d == "ingress" else "아웃바운드", pr, port, src)


def _cleanup_sig(r):
    """정리 제안 적용 때 '그 사이 규칙이 바뀌지 않았는지' 확인하는 규칙 지문"""
    return json.dumps([str(r["protocol"]).lower(), r["from_port"], r["to_port"], sorted(r["cidr_blocks"]), r["security_groups"] or "", sorted(r["prefix_list_ids"] or [])], ensure_ascii=False)


def _cleanup_sg(env_label, env_id, name, data):
    out = []
    for d in ("ingress", "egress"):
        rules = data[d]
        sig = lambda r: (str(r["protocol"]).lower(), r["from_port"], r["to_port"], tuple(sorted(r["cidr_blocks"])), r["security_groups"], tuple(sorted(r["prefix_list_ids"] or [])))
        first, flagged = {}, set()
        for i, r in enumerate(rules):
            s = sig(r)
            if s in first:
                flagged.add(i)
                pr, port, src, _ = _rule_cells(r)
                out.append({"env_id": env_id, "env": env_label, "sg": name, "kind": "duplicate", "direction": d, "protocol": pr, "port": port, "source": src,
                            "description": r["description"], "by": _rule_text(d, rules[first[s]]), "note": "같은 규칙이 이미 있음", "idx": i, "sig": _cleanup_sig(r)})
            else:
                first[s] = i
        for i, r in enumerate(rules):
            if i in flagged:
                continue
            for j, o in enumerate(rules):
                if j == i or j in flagged:
                    continue
                if not _covers(o, r) or (_covers(r, o) and j > i):
                    continue
                if d == "egress" and str(o["protocol"]) == "-1" and "0.0.0.0/0" in o["cidr_blocks"]:
                    continue   # 아웃바운드 전체 허용이 기본인 경우 나머지 아웃바운드가 전부 '포함'으로 잡히는 것을 막는다
                pr, port, src, _ = _rule_cells(r)
                out.append({"env_id": env_id, "env": env_label, "sg": name, "kind": "covered", "direction": d, "protocol": pr, "port": port, "source": src,
                            "description": r["description"], "by": _rule_text(d, o), "note": "더 넓은 규칙에 포함됨", "idx": i, "sig": _cleanup_sig(r)})
                break
    return out


@app.get("/api/report/cleanup")
def api_report_cleanup():
    """모든 환경의 SG 에서 정리할 만한 규칙을 찾는다 (읽기 전용 - 제안만 하고 바꾸지 않는다)"""
    rows, sg_count = [], 0
    for env, label, name, data in _each_sg():
        sg_count += 1
        rows += _cleanup_sg(label, env["id"], name, data)
    add_owner(rows)
    kinds = {}
    for r in rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    if request.args.get("format") == "csv":
        lbl = {"duplicate": "중복", "covered": "포함됨"}
        return _csv_response(["환경", "SG", "구분", "방향", "프로토콜", "포트", "소스", "설명", "겹치는 규칙", "설명(제안)", "담당자"],
                             [[r["env"], r["sg"], lbl[r["kind"]], r["direction"], r["protocol"], r["port"], r["source"], r["description"], r["by"], r["note"], r["owner"]] for r in rows],
                             "cleanup-report.csv")
    return jsonify({"sgs": sg_count, "count": len(rows), "kinds": kinds, "rows": rows[:2000]})


# ---- 접근 경로: 이 IP/대역이 지금 어떤 SG 를 통해 어떤 포트로 열려 있는지 (SG 별로 묶어서)
def reach_groups(q, via=False):
    net = _net(q)
    if net is None:
        raise ApiError("IP 또는 CIDR 형식으로 입력하세요 (예: 10.1.2.3, 211.34.57.0/24)")
    meta = load_meta().get("envs", {})
    groups = {}
    for env, label, name, data in _each_sg():
        for d in ("ingress", "egress"):
            for r in data[d]:
                best = None
                for c in r["cidr_blocks"]:
                    n = _net(c)
                    if not n or n.version != net.version or not n.overlaps(net):
                        continue
                    full = net.subnet_of(n)
                    best = "full" if full else (best or "part")
                    if full:
                        break
                if not best:
                    continue
                g = groups.setdefault((env["id"], name, d), {"env_id": env["id"], "env": label, "sg": name, "direction": d, "access": best, "ports": [], "rules": 0})
                if best == "full":
                    g["access"] = "full"
                pr, port, _src, _ = _rule_cells(r)
                txt = "ALL" if pr == "ALL" else "%s %s" % (pr, port)
                if txt not in g["ports"]:
                    g["ports"].append(txt)
                g["rules"] += 1
    if via and groups:
        # SG 경유(간접): 열려 있는 SG 를 소스로 허용하는 다른 SG (그 SG 의 서버를 거쳐 이어지는 경로). 직접 열린 SG 는 그대로 둔다
        items, by_id = _sg_index()
        direct = {(k[0], k[1]) for k in groups if k[2] == "ingress"}
        starts = {}
        for it in items:
            if (it["env_id"], it["name"]) in direct and it["sg_id"]:
                starts[it["sg_id"]] = it
        for lvl, src, holder, ports in _downstream(items, by_id, set(starts), 2):
            key = (holder["env_id"], holder["name"], "ingress")
            if key in groups and groups[key]["access"] != "via":
                continue
            g = groups.setdefault(key, {"env_id": holder["env_id"], "env": holder["env"], "sg": holder["name"], "direction": "ingress", "access": "via", "ports": [], "rules": 0, "via": ""})
            for t in ports:
                if t not in g["ports"]:
                    g["ports"].append(t)
            g["rules"] += len(ports)
            hop = "%s → %s" % (src["name"] if src else "?", holder["name"])
            if hop not in g["via"]:
                g["via"] = (g["via"] + " / " if g["via"] else "") + hop
    out = []
    for g in groups.values():
        m = (meta.get(g["env_id"], {}).get("sgs", {}) or {}).get(g["sg"], {})
        g["alias"] = m.get("alias", "")
        g["sg_id"] = m.get("sg_id", "")
        g["tags"] = ", ".join(("%s:%s" % (t.get("type", ""), t.get("value", ""))) if t.get("type") else str(t.get("value", "")) for t in (m.get("tags") or []) if t.get("value"))
        out.append(g)
    out.sort(key=lambda g: (g["direction"] != "ingress", {"full": 0, "part": 1}.get(g["access"], 2), g["env"], g["sg"]))
    return str(net), out


@app.get("/api/report/reach")
def api_report_reach():
    net, rows = reach_groups(request.args.get("q", "").strip(), via=request.args.get("via") == "1")
    if request.args.get("format") == "csv":
        return _csv_response(["환경", "SG", "SG ID", "별명", "태그", "방향", "범위", "열린 포트", "규칙 수"],
                             [[r["env"], r["sg"], r["sg_id"], r["alias"], r["tags"], r["direction"], {"full": "전체", "via": "SG 경유"}.get(r["access"], "일부 대역만"),
                               " | ".join(r["ports"]), r["rules"]] for r in rows], "reach-report.csv")
    return jsonify({"q": net, "count": len(rows), "ingress": sum(1 for r in rows if r["direction"] == "ingress"), "rows": rows[:2000]})


# ---- 변경 기록(감사용): 티켓·작성자·변경 내용·위험/경고·MR·plan 결과를 한 장으로
def audit_record(env, ticket=""):
    cs = change_summary(env)
    branch = cs["branch"]
    ticket = (ticket or "").strip() or ticket_from_branch(branch)
    mr, plan = None, None
    try:
        m = find_open_mr(env, branch)
        if m:
            mr = {"iid": m["iid"], "url": m.get("web_url", ""), "title": m.get("title", ""), "state": m.get("state", "")}
            plan = plan_get(env, m["iid"])
    except ApiError as e:
        mr = {"error": str(e)[:200]}
    warnings = []
    for s in cs["sgs"]:
        warnings += ["%s: %s" % (s["name"], w) for w in s["warnings"]]
    pl = None
    if plan:
        n = plan.get("plan") or {}
        pl = {"state": plan.get("state", ""), "add": n.get("add", 0), "change": n.get("change", 0), "destroy": n.get("destroy", 0), "replace": n.get("replace", 0),
              "applied": bool(plan.get("applied")), "ts": plan.get("ts")}
    amap = approval_map(env["id"], branch)
    notes = []
    for r in cs["risks"]:
        a = amap.get(r)
        notes.append({"risk": r, "approved": bool(a), "reason": (a or {}).get("reason", ""), "by": (a or {}).get("user", ""), "ts": (a or {}).get("ts", "")})
    return {"created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "user": load_local().get("account", ""), "tool_version": VERSION, "ticket": ticket, "risk_notes": notes,
            "env": "%s · %s" % (env.get("group", ""), env.get("env", "")), "env_id": env["id"], "branch": branch, "base": cs["base"], "totals": cs["totals"],
            "sgs": cs["sgs"], "risks": cs["risks"], "warnings": warnings, "mr": mr, "plan": pl}


def audit_markdown(a):
    L = ["# SG 변경 기록 - %s" % (a["ticket"] or "(티켓 없음)"), "",
         "| 항목 | 내용 |", "|---|---|",
         "| 작성자 | %s |" % (a["user"] or "-"), "| 작성 시각 | %s |" % a["created"], "| 환경 | %s |" % a["env"], "| 브랜치 | `%s` (기준 `%s`) |" % (a["branch"], str(a["base"])[:10]),
         "| 변경 | SG %d개 / 규칙 추가 %d건 / 삭제 %d건 / 위험 %d건 |" % (a["totals"]["sgs"], a["totals"]["added"], a["totals"]["removed"], a["totals"]["risks"])]
    mr = a["mr"]
    if mr and mr.get("iid"):
        L.append("| MR | !%s %s |" % (mr["iid"], mr.get("url", "")))
    elif mr and mr.get("error"):
        L.append("| MR | 조회하지 못함 (%s) |" % mr["error"].replace("|", "/").replace("\n", " "))
    else:
        L.append("| MR | 아직 없음 |")
    p = a["plan"]
    if p:
        L.append("| plan 결과 | %s (추가 %d / 변경 %d / 삭제 %d / 교체 %d)%s |" % (p["state"] or "-", p["add"], p["change"], p["destroy"], p["replace"], " · apply 완료" if p["applied"] else ""))
    else:
        L.append("| plan 결과 | 이 도구에 기록이 없음 |")
    L += ["", _change_markdown(a["branch"], a["base"], a["sgs"], a["totals"], a["risks"]).split("\n", 1)[1].lstrip("\n").rstrip("\n")]
    if a.get("risk_notes"):
        L += ["", "**위험 규칙 승인 기록**"]
        for n in a["risk_notes"]:
            L.append("- %s — %s" % (n["risk"], ("승인 사유: %s (%s, %s)" % (n["reason"], n["by"] or "-", n["ts"])) if n["approved"] else "승인 기록 없음"))
    if a["warnings"]:
        L += ["", "**경고**"] + ["- " + w for w in a["warnings"]]
    L += ["", "_이 문서는 Traform ACL Tool v%s 가 저장소의 현재 변경 내용과 이 PC 의 기록으로 만들었습니다._" % a["tool_version"]]
    return "\n".join(L) + "\n"


@app.get("/api/env/<env_id>/report/audit")
def api_report_audit(env_id):
    env = get_env(env_id)
    a = audit_record(env, request.args.get("ticket", ""))
    name = "sg-change-record-%s-%s" % (re.sub(r"[^A-Za-z0-9_-]", "", a["ticket"]) or "noticket", datetime.now().strftime("%y%m%d_%H%M%S"))
    if request.args.get("format") == "json":
        return Response(json.dumps(a, ensure_ascii=False, indent=2) + "\n", mimetype="application/json",
                        headers={"Content-Disposition": 'attachment; filename="%s.json"' % name})
    md = audit_markdown(a)
    if request.args.get("download") == "1":
        return Response(md, mimetype="text/markdown", headers={"Content-Disposition": 'attachment; filename="%s.md"' % name})
    return jsonify({"record": a, "markdown": md, "filename": name + ".md"})


def mr_check_section(env):
    """MR 본문 끝에 붙일 '자동 점검 결과'. 변경 내용을 읽지 못하면 빈 문자열(MR 생성은 막지 않는다)"""
    try:
        cs = change_summary(env)
    except ApiError as e:
        log_event("WARN", "MR 자동 점검 결과를 만들지 못했습니다: %s" % str(e)[:200])
        return ""
    warns = []
    for s in cs["sgs"]:
        warns += ["%s: %s" % (s["name"], w) for w in s["warnings"]]
    t = cs["totals"]
    L = ["", "### 자동 점검 결과 (Traform ACL Tool)", "",
         "- 변경: SG %d개 · 규칙 추가 %d건 / 삭제 %d건" % (t["sgs"], t["added"], t["removed"])]
    if cs["risks"]:
        amap = approval_map(env["id"], cs["branch"])
        L += ["- ⚠ **위험 규칙 %d건** (리뷰어는 아래 항목을 확인해 주세요)" % len(cs["risks"])]
        for r in cs["risks"]:
            a = amap.get(r)
            L.append("  - %s → %s" % (r, ("승인 사유: %s (%s)" % (a["reason"], a.get("user") or "-")) if a else "승인 기록 없음"))
    else:
        L.append("- 위험 규칙: 없음")
    if warns:
        L += ["- 경고 %d건" % len(warns)] + ["  - " + w for w in warns[:20]] + (["  - … 외 %d건" % (len(warns) - 20)] if len(warns) > 20 else [])
    return "\n".join(L) + "\n"
