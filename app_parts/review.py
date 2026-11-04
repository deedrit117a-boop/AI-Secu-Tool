# app.py 에서 _include() 로 불러오는 부분 (app.py 와 같은 이름공간을 쓴다)
# ----------------------------------------------------------------- 검토 도구
# 위험 규칙 승인 사유 / 이미 열려 있음 사전 점검 / SG 참조 관계 / 규칙 기준 점검 점수 / 티켓별 찾기 / 정리 제안 적용
# 보고서·조회는 모두 읽기 전용이다. 규칙을 바꾸는 것은 '정리 제안 적용'(규칙 삭제, 작업 브랜치에서만) 하나뿐이다.


# ---- 위험 규칙 승인 사유: 위험 확인 창에서 받은 사유를 data/risk_approvals.json 에 남기고, 변경 기록과 MR 본문에 붙인다
def _approvals_path():
    return os.path.join(DATA, "risk_approvals.json")


def _approvals():
    v = read_json(_approvals_path(), [])
    return v if isinstance(v, list) else []


@app.post("/api/env/<env_id>/risk-approval")
def api_risk_approval(env_id):
    env = get_env(env_id)
    b = request.get_json(silent=True) or {}
    reason = str(b.get("reason") or "").strip()[:300]
    risks = [str(x).strip() for x in (b.get("risks") or []) if str(x).strip()][:50]
    sg = str(b.get("sg") or "").strip()[:120]
    if len(reason) < 2:
        raise ApiError("승인 사유를 적어 주세요 (2자 이상)")
    if not risks:
        raise ApiError("승인할 위험 규칙이 없습니다")
    try:
        branch = git_status(env).get("branch", "")
    except Exception:
        branch = ""
    rec = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "user": load_local().get("account", ""), "env_id": env["id"], "branch": branch,
           "ticket": ticket_from_branch(branch) if branch else "", "sg": sg, "risks": risks, "reason": reason}
    items = _approvals()
    items.append(rec)
    write_json(_approvals_path(), items[-2000:])
    log_event("INFO", "위험 규칙 승인 기록: %s %s (%d건)" % (env["id"], sg, len(risks)))
    return jsonify({"ok": True, "approval": rec})


@app.get("/api/env/<env_id>/risk-approvals")
def api_risk_approvals(env_id):
    env = get_env(env_id)
    branch = request.args.get("branch", "")
    return jsonify({"approvals": [a for a in _approvals() if a.get("env_id") == env["id"] and (not branch or a.get("branch") == branch)][-200:]})


def approval_map(env_id, branch):
    """이 브랜치에서 받은 승인 사유 {'SG이름: 위험 내용': 기록} (같은 위험이면 가장 최근 것)"""
    out = {}
    for a in _approvals():
        if a.get("env_id") != env_id or a.get("branch") != branch:
            continue
        for r in a.get("risks") or []:
            out["%s: %s" % (a.get("sg"), r) if a.get("sg") else r] = a
    return out


# ---- 규칙 추가 전 '이미 열려 있음' 점검: 새 규칙을 같은 SG 의 다른 규칙이 이미 허용하는지, 이 환경의 다른 SG 에도 열려 있는지
def already_open_info(env, name, new_sg, old_sg):
    kind = env["kind"]
    same, others, seen_other = [], [], set()
    others_pool = None
    for d in ("ingress", "egress"):
        pool = {}
        for r in (old_sg or {}).get(d, []):
            s = rule_sig(norm_rule(r, kind))
            pool[s] = pool.get(s, 0) + 1
        allr = [norm_rule(r, kind) for r in new_sg.get(d, [])]
        for i, r in enumerate(allr):
            s = rule_sig(r)
            if pool.get(s, 0) > 0:
                pool[s] -= 1
                continue          # 이미 있던 규칙
            for j, o in enumerate(allr):
                if j == i or not _covers(o, r) or _covers(r, o):
                    continue          # 똑같은 규칙은 '중복' 경고가 따로 알려 준다 (규칙 복사 직후에도 걸리지 않게)
                if d == "egress" and str(o["protocol"]) == "-1" and "0.0.0.0/0" in o["cidr_blocks"]:
                    continue
                same.append("%s 은(는) 이미 열려 있습니다 → %s" % (_rule_text(d, r), _rule_text(d, o)))
                break
            if d != "ingress" or not (r["cidr_blocks"] or r["security_groups"]):
                continue
            if others_pool is None:
                others_pool = []
                for sg in list_sgs(env):
                    if sg["name"] == name:
                        continue
                    try:
                        others_pool.append((sg["name"], _cached_sg(env, sg["name"])["ingress"]))
                    except Exception:
                        continue
            hit = [n for n, rules in others_pool if any(_covers(o, r) for o in rules)]
            if hit and _rule_text(d, r) not in seen_other:
                seen_other.add(_rule_text(d, r))
                others.append("%s 은(는) 이 환경의 다른 SG 에도 열려 있습니다: %s%s" % (_rule_text(d, r), ", ".join(hit[:4]), " 외 %d곳" % (len(hit) - 4) if len(hit) > 4 else ""))
    return {"already": same[:20], "others": others[:20]}


# ---- SG 참조 관계: 어떤 SG 가 다른 SG 를 소스로 허용하는지 (SG 안의 서버가 다른 SG 로 이어지는 간접 경로)
def _sg_index():
    meta = load_meta().get("envs", {})
    items, by_id = [], {}
    for env, label, name, data in _each_sg():
        sid = (((meta.get(env["id"], {}).get("sgs", {}) or {}).get(name, {}) or {}).get("sg_id", "") or "").strip()
        it = {"env_id": env["id"], "env": label, "name": name, "data": data, "sg_id": sid}
        items.append(it)
        if sid:
            by_id[sid] = it
    return items, by_id


def _sg_refs(items):
    """[(규칙을 가진 SG, 소스로 지정된 SG ID, 규칙)] - 인바운드 규칙의 소스가 SG 인 것만"""
    out = []
    for it in items:
        for r in it["data"]["ingress"]:
            for sid in str(r["security_groups"] or "").split(","):
                sid = sid.strip()
                if sid:
                    out.append((it, sid, r))
    return out


def _port_txt(r):
    pr, port, _src, _d = _rule_cells(r)
    return "ALL" if pr == "ALL" else "%s %s" % (pr, port)


def _downstream(items, by_id, start_ids, depth):
    """시작 SG 들을 소스로 허용하는 SG 를 depth 단계까지 [(단계, 소스 SG 항목, 규칙 SG 항목, 포트 목록)]"""
    refs = _sg_refs(items)
    seen, frontier, out = set(start_ids), set(start_ids), []
    for lvl in range(1, depth + 1):
        found, nxt = {}, set()
        for holder, sid, r in refs:
            if sid not in frontier:
                continue
            src = by_id.get(sid)
            k = (sid, holder["env_id"], holder["name"])
            f = found.setdefault(k, [src, holder, []])
            t = _port_txt(r)
            if t not in f[2]:
                f[2].append(t)
            hid = holder["sg_id"] or "%s/%s" % (holder["env_id"], holder["name"])
            if hid not in seen:
                nxt.add(hid)
        for src, holder, ports in found.values():
            out.append((lvl, src, holder, ports))
        seen |= nxt
        frontier = nxt
        if not frontier:
            break
    return out


def _upstream(items, by_id, start, depth):
    """시작 SG 의 인바운드 규칙이 소스로 지정한 SG(와 그 SG 가 다시 받는 소스)를 depth 단계까지"""
    out, seen, frontier = [], {start["env_id"] + "/" + start["name"]}, [start]
    for lvl in range(1, depth + 1):
        nxt = []
        for holder in frontier:
            found = {}
            for r in holder["data"]["ingress"]:
                for sid in str(r["security_groups"] or "").split(","):
                    sid = sid.strip()
                    if not sid:
                        continue
                    f = found.setdefault(sid, [])
                    t = _port_txt(r)
                    if t not in f:
                        f.append(t)
            for sid, ports in found.items():
                src = by_id.get(sid)
                out.append((lvl, src, sid, holder, ports))
                if src and src["env_id"] + "/" + src["name"] not in seen:
                    seen.add(src["env_id"] + "/" + src["name"])
                    nxt.append(src)
        frontier = nxt
        if not frontier:
            break
    return out


def sg_graph(q, depth=2):
    q = (q or "").strip()
    if not q:
        raise ApiError("SG 이름, SG ID, 별명 중 하나를 입력하세요")
    depth = max(1, min(int(depth or 2), 3))
    items, by_id = _sg_index()
    meta = load_meta().get("envs", {})
    low = q.lower()

    def alias_of(it):
        return (((meta.get(it["env_id"], {}).get("sgs", {}) or {}).get(it["name"], {}) or {}).get("alias", "") or "")
    starts = [it for it in items if it["name"].lower() == low or (it["sg_id"] and it["sg_id"].lower() == low) or (alias_of(it) and alias_of(it).lower() == low)]
    if not starts:
        starts = [it for it in items if low in it["name"].lower()][:5]
    if not starts:
        raise ApiError("일치하는 SG 를 찾지 못했습니다: %s (이름·SG ID·별명으로 찾습니다)" % q, 404)

    def node(it, sid=""):
        if it:
            return {"name": it["name"], "env": it["env"], "sg_id": it["sg_id"], "alias": alias_of(it)}
        return {"name": sid, "env": "(받아 둔 파일에 없음)", "sg_id": sid, "alias": ""}
    res = []
    for st in starts:
        ids = {st["sg_id"]} if st["sg_id"] else set()
        down = [{"depth": l, "from": node(s), "to": node(h), "ports": p} for l, s, h, p in _downstream(items, by_id, ids, depth)] if ids else []
        up = [{"depth": l, "from": node(s, sid), "to": node(h), "ports": p} for l, s, sid, h, p in _upstream(items, by_id, st, depth)]
        res.append({"sg": node(st), "down": down, "up": up, "no_sg_id": not st["sg_id"]})
    return {"q": q, "depth": depth, "starts": res}


@app.get("/api/report/sgrefs")
def api_report_sgrefs():
    r = sg_graph(request.args.get("q", ""), request.args.get("depth", 2))
    if request.args.get("format") == "csv":
        rows = []
        for s in r["starts"]:
            for kind, lst in (("이 SG 를 소스로 허용하는 SG(아래로)", s["down"]), ("이 SG 가 소스로 허용하는 SG(위로)", s["up"])):
                for e in lst:
                    rows.append([s["sg"]["name"], kind, e["depth"], e["from"]["name"], e["from"]["sg_id"], e["to"]["name"], e["to"]["env"], " | ".join(e["ports"])])
        return _csv_response(["기준 SG", "방향", "단계", "소스 SG", "소스 SG ID", "규칙을 가진 SG", "환경", "포트"], rows, "sg-refs.csv")
    return jsonify(r)


# ---- 규칙 기준 점검 점수: 환경별로 위험한 규칙을 세어 점수와 등급을 매긴다 (읽기 전용)
SCORE_KINDS = {"open_all": ("전체 개방(0.0.0.0/0)", 10, 5), "mgmt": ("관리 포트를 넓은 대역에", 5, 6), "all_ports": ("전체 포트·프로토콜 허용", 3, 5),
               "wide": ("광범위 대역", 3, 6), "expired": ("만료일 지난 규칙", 4, 5), "no_desc": ("설명 없음", 1, 10), "dup": ("중복·포함되는 규칙", 1, 10)}


def _grade(score):
    return "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60 else "D"


def score_report(today=None):
    today = today or datetime.now().date()
    pol = get_policy()
    mgmt = {int(p): n for p, n in pol["mgmt_ports"].items()}
    envs, rows = {}, []
    for env, label, name, data in _each_sg():
        e = envs.setdefault(env["id"], {"env_id": env["id"], "env": label, "sgs": 0, "rules": 0, "counts": {k: 0 for k in SCORE_KINDS}})
        e["sgs"] += 1

        def add(kind, d, r):
            e["counts"][kind] += 1
            pr, port, src, desc = _rule_cells(r)
            rows.append({"env_id": env["id"], "env": label, "sg": name, "kind": kind, "direction": d, "protocol": pr, "port": port, "source": src, "description": r["description"]})
        for d in ("ingress", "egress"):
            for r in data[d]:
                e["rules"] += 1
                proto = str(r["protocol"]).lower()
                lo, hi = (0, 65535) if proto == "-1" else (r["from_port"], r["to_port"])
                if d == "ingress":
                    flags = set()
                    nets = [n for n in (_net(c) for c in r["cidr_blocks"]) if n is not None]
                    open_nets = [n for n in nets if not policy_exception(pol, env["id"], n, lo, hi)]
                    for n in open_nets:
                        if n.prefixlen == 0:
                            flags.add("open_all")
                        elif n.version == 4 and n.prefixlen < pol["wide_prefix"]:
                            flags.add("wide")
                        if 0 < n.prefixlen < pol["mgmt_max_prefix"] and proto in ("tcp", "udp") and not (lo == 0 and hi >= 65535) and any(lo <= p <= hi for p in mgmt):
                            flags.add("mgmt")
                    if open_nets and (proto == "-1" or (proto in ("tcp", "udp") and lo == 0 and hi >= 65535)):
                        flags.add("all_ports")
                    for k in ("open_all", "mgmt", "all_ports", "wide"):
                        if k in flags:
                            add(k, d, r)
                ex = rule_expiry(r["description"])
                if ex and ex < today:
                    add("expired", d, r)
                if not (r["description"] or "").strip():
                    add("no_desc", d, r)
        for c in _cleanup_sg(label, env["id"], name, data):
            e["counts"]["dup"] += 1
            rows.append({"env_id": env["id"], "env": label, "sg": name, "kind": "dup", "direction": c["direction"], "protocol": c["protocol"], "port": c["port"],
                         "source": c["source"], "description": c["description"]})
    out = []
    for e in envs.values():
        s = 100 - sum(w * min(e["counts"][k], cap) for k, (_l, w, cap) in SCORE_KINDS.items())
        e["score"] = max(0, s)
        e["grade"] = _grade(e["score"])
        out.append(e)
    out.sort(key=lambda x: (x["score"], x["env"]))
    add_owner(rows)
    return out, rows


@app.get("/api/report/score")
def api_report_score():
    envs, rows = score_report()
    if request.args.get("format") == "csv":
        return _csv_response(["환경", "SG", "항목", "방향", "프로토콜", "포트", "소스", "설명", "담당자"],
                             [[r["env"], r["sg"], SCORE_KINDS[r["kind"]][0], r["direction"], r["protocol"], r["port"], r["source"], r["description"], r["owner"]] for r in rows], "score-report.csv")
    return jsonify({"envs": envs, "rows": rows[:3000], "count": len(rows), "kinds": {k: {"label": v[0], "weight": v[1], "cap": v[2]} for k, v in SCORE_KINDS.items()}})


# ---- 티켓별 찾기: 티켓 번호가 설명에 들어간 규칙, 이름에 들어간 브랜치, 제목·설명에 들어간 MR
@app.get("/api/ticket/<ticket>")
def api_ticket_find(ticket):
    t = (ticket or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_\-]{2,40}", t):
        raise ApiError("티켓 번호 형식이 올바르지 않습니다 (예: ISRIR-12345)")
    low = t.lower()
    rules = []
    for env, label, name, data in _each_sg():
        for d in ("ingress", "egress"):
            for r in data[d]:
                if low in (r["description"] or "").lower():
                    pr, port, src, _ = _rule_cells(r)
                    rules.append({"env_id": env["id"], "env": label, "sg": name, "direction": d, "protocol": pr, "port": port, "source": src, "description": r["description"]})
    branches, mrs, errors = [], [], []
    cfg = load_config()
    seen_repo, seen_proj = set(), set()
    want_mr = request.args.get("mr", "1") != "0"
    for ce in cfg["environments"]:
        try:
            env = _resolve_env(ce, cfg)
        except ApiError:
            continue
        repo = os.path.normcase(os.path.abspath(env["repo_dir"]))
        if repo not in seen_repo and os.path.isdir(os.path.join(env["repo_dir"], ".git")):
            seen_repo.add(repo)
            try:
                out = run_git(env, "for-each-ref", "--format=%(refname:short)\t%(committerdate:short)\t%(subject)", "refs/heads", "refs/remotes", check=False)
            except Exception:
                out = ""
            names = {}
            for line in out.splitlines():
                p = line.split("\t")
                if len(p) >= 2 and low in p[0].lower():
                    nm = re.sub(r"^origin/", "", p[0])
                    b = names.setdefault(nm, {"branch": nm, "date": p[1], "subject": p[2] if len(p) > 2 else "", "local": False, "remote": False, "env": " · ".join(x for x in (env.get("group"), env.get("env")) if x)})
                    b["remote" if p[0].startswith("origin/") else "local"] = True
            branches += sorted(names.values(), key=lambda x: x["date"], reverse=True)
        if not want_mr or len(seen_proj) >= 8 or len(errors) >= 2:
            continue
        try:
            proj = pid(env)
            if proj in seen_proj:
                continue
            seen_proj.add(proj)
            for m in gl(env, "GET", "/projects/%s/merge_requests" % proj, params={"search": t, "state": "all", "per_page": 10}) or []:
                mrs.append({"env": " · ".join(x for x in (env.get("group"), env.get("env")) if x), "iid": m.get("iid"), "title": m.get("title", ""), "state": m.get("state", ""),
                            "url": m.get("web_url", ""), "branch": m.get("source_branch", "")})
        except ApiError as e:
            errors.append("%s: %s" % (env.get("env", ""), str(e)[:120]))
    return jsonify({"ticket": t, "rules": rules[:500], "rule_count": len(rules), "branches": branches[:100], "mrs": mrs[:50], "mr_errors": errors})


# ---- 정리 제안 적용: 정리 제안에서 고른 규칙을 삭제한다 (작업 브랜치에서만, 파일만 바꾸고 Commit/Push 는 작업 탭에서)
@app.post("/api/cleanup/apply")
def api_cleanup_apply():
    b = request.get_json(silent=True) or {}
    items, dry = b.get("items") or [], bool(b.get("dry_run"))
    if not isinstance(items, list) or not items or len(items) > 500:
        raise ApiError("삭제할 항목(1~500개)을 선택하세요")
    groups = {}
    for it in items:
        d = it.get("direction")
        if d not in ("ingress", "egress"):
            raise ApiError("direction 은 ingress/egress 이어야 합니다")
        try:
            idx = int(it.get("idx"))
        except (TypeError, ValueError):
            raise ApiError("항목 형식이 올바르지 않습니다")
        groups.setdefault((str(it.get("env_id", "")), str(it.get("sg", ""))), []).append((d, idx, str(it.get("sig", ""))))
    plans = []
    for (eid, sg), lst in groups.items():
        env = get_env(eid)
        check_name(sg)
        if not dry:
            require_work_branch(env)
        data = load_sg(env, sg)
        dels, removed, skipped = {"ingress": set(), "egress": set()}, [], 0
        for d, idx, sig in lst:
            rules = data[d]
            if not (0 <= idx < len(rules)) or _cleanup_sig(norm_rule(rules[idx], env["kind"])) != sig:
                skipped += 1          # 그 사이 규칙이 바뀌었다 - 건드리지 않는다
                continue
            if idx not in dels[d]:
                dels[d].add(idx)
                removed.append(_rule_text(d, norm_rule(rules[idx], env["kind"])))
        new = json.loads(json.dumps(data))
        for d in dels:
            new[d] = [r for i, r in enumerate(data[d]) if i not in dels[d]]
        plans.append({"env_id": env["id"], "sg": sg, "removed": removed, "skipped": skipped, "_env": env, "_new": new})
    if not dry:
        for p in plans:
            if p["removed"]:
                save_sg(p["_env"], p["sg"], p["_new"])
        log_event("INFO", "정리 제안 적용: SG %d개에서 규칙 %d건 삭제" % (len([p for p in plans if p["removed"]]), sum(len(p["removed"]) for p in plans)))
    out = [{k: v for k, v in p.items() if not k.startswith("_")} for p in plans]
    return jsonify({"ok": True, "dry_run": dry, "results": out, "removed": sum(len(p["removed"]) for p in plans), "skipped": sum(p["skipped"] for p in plans)})


# ---- 화면 안에서 바로 보고 고치기: SG 규칙 미리보기(삭제·만료 연장에 쓰는 위치/지문 포함)와 만료 연장
@app.get("/api/env/<env_id>/sg/<name>/rules")
def api_sg_rules_panel(env_id, name):
    """SG 한 개의 규칙을 위치(idx)와 지문(sig)과 함께 돌려준다 (읽기 전용). 작업 브랜치인지도 알려 준다."""
    env = get_env(env_id)
    data = load_sg(env, name)
    rows = []
    for d in ("ingress", "egress"):
        for i, r in enumerate(data[d]):
            pr, port, src, _ = _rule_cells(r)
            ex = rule_expiry(r["description"])
            rows.append({"direction": d, "idx": i, "sig": _cleanup_sig(r), "protocol": pr, "port": port, "source": src,
                         "description": r["description"], "expires": ex.isoformat() if ex else ""})
    try:
        require_work_branch(env)
        ok, branch = True, ""
    except ApiError as e:
        ok, branch = False, e.extra.get("branch", "")
    sm = ((load_meta().get("envs") or {}).get(env["id"]) or {}).get("sgs", {}).get(name) or {}
    label = " · ".join(x for x in (env.get("group"), env.get("env"), env.get("label")) if x)
    return jsonify({"env_id": env["id"], "env": label, "sg": name, "rules": rows, "work_branch": ok, "branch": branch,
                    "meta": {"alias": sm.get("alias", ""), "sg_id": sm.get("sg_id", ""), "owner": sm.get("owner", ""), "tags": sm.get("tags") or []}})


@app.post("/api/rule/extend")
def api_rule_extend():
    """규칙 설명의 만료일을 바꾼다 (없으면 '만료:YYYY-MM-DD' 를 덧붙인다). 작업 브랜치에서만, 규칙이 그 사이 바뀌지 않았을 때만"""
    b = request.get_json(silent=True) or {}
    eid, sg, d = str(b.get("env_id", "")), str(b.get("sg", "")), b.get("direction")
    if d not in ("ingress", "egress"):
        raise ApiError("direction 은 ingress/egress 이어야 합니다")
    try:
        idx = int(b.get("idx"))
        date = datetime.strptime(str(b.get("date", "")), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise ApiError("규칙 위치와 만료일(YYYY-MM-DD)을 확인하세요")
    if date < datetime.now().date():
        raise ApiError("만료일은 오늘 이후여야 합니다")
    env = get_env(eid)
    check_name(sg)
    dry = bool(b.get("dry_run"))
    if not dry:
        require_work_branch(env)
    data = load_sg(env, sg)
    rules = data[d]
    if not (0 <= idx < len(rules)) or _cleanup_sig(rules[idx]) != str(b.get("sig", "")):
        raise ApiError("그 사이 규칙이 바뀌었습니다. 화면을 새로 고친 뒤 다시 하세요", 409)
    old = rules[idx]["description"] or ""
    iso = date.isoformat()
    new = EXPIRE_RE.sub(lambda m: m.group(0).replace(m.group(1), iso), old, count=1) if EXPIRE_RE.search(old) else (old.rstrip() + " 만료:" + iso).strip()
    if not dry:
        rules[idx]["description"] = new
        save_sg(env, sg, data)
        log_event("INFO", "만료일 연장: %s/%s %s #%d -> %s" % (eid, sg, d, idx, iso))
    return jsonify({"ok": True, "dry_run": dry, "old": old, "new": new})
