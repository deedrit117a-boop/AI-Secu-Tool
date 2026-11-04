# app.py 에서 _include() 로 불러오는 부분 (app.py 와 같은 이름공간을 쓴다)
# ----------------------------------------------------------------- AWS 자격인증 상태 (화면 위쪽의 'AWS 자격인증' 표시)
_AWS_ST = {}                 # 프로필 -> (확인 시각, 결과)
AWS_ST_TTL_OK, AWS_ST_TTL_FAIL = 120, 15


def aws_saved_profile(env):
    """이 환경 그룹에서 쓰기로 기억해 둔 AWS 프로필 (없으면 '')"""
    saved = (load_local().get("aws_profiles") or {}).get(aws_profile_key(env), "")
    return saved if saved in aws_profiles() else ""


def aws_auth_state(env, force=False):
    """저장된 프로필로 로그인(자격증명) 여부를 확인한다 (sts get-caller-identity, 조회 전용). 결과는 잠깐 기억해 AWS CLI 호출을 줄인다."""
    if not aws_cli_present():
        return {"state": "no_cli", "message": "AWS CLI 가 설치되어 있지 않습니다"}
    profile = aws_saved_profile(env)
    if not profile:
        return {"state": "no_profile", "message": "이 환경에서 쓸 AWS 프로필이 아직 정해지지 않았습니다 (메타 데이터의 'AWS 에서 가져오기'에서 한 번 선택)"}
    hit = _AWS_ST.get(profile)
    if hit and not force and time.time() - hit[0] < (AWS_ST_TTL_OK if hit[1]["state"] == "ok" else AWS_ST_TTL_FAIL):
        return hit[1]
    try:
        r = aws_run(profile, "sts", "get-caller-identity", timeout=40)
        res = {"state": "ok", "profile": profile, "account": r.get("Account", "")}
    except ApiError as e:
        k = e.extra.get("aws_error")
        res = {"state": "login_needed" if k == "login_needed" else "error", "profile": profile, "message": str(e)}
    _AWS_ST[profile] = (time.time(), res)
    return res


@app.get("/api/aws/status")
def api_aws_status():
    env_id = request.args.get("env_id", "")
    if not env_id:
        return jsonify({"state": "no_env", "message": "환경을 선택하면 확인합니다"})
    return jsonify(aws_auth_state(get_env(env_id), request.args.get("force") == "1"))


# ----------------------------------------------------------------- AWS 규칙 ↔ 저장소 파일 규칙 비교 보고서 (조회 전용)
def _norm_proto(p):
    p = str(p if p is not None else "").strip().lower()
    return {"6": "tcp", "17": "udp", "1": "icmp", "all": "-1", "": "-1"}.get(p, p)


def _norm_cidr(c):
    c = str(c).strip()
    try:
        return str(ipaddress.ip_network(c, strict=False))
    except ValueError:
        return c.lower()


def _cmp_key(direction, proto, fp, tp, stype, src):
    proto = _norm_proto(proto)
    if proto == "-1":
        fp = tp = None
    return (direction, proto, fp, tp, stype, src)


def file_rule_keys(rules, direction):
    """저장소 파일의 규칙을 (방향, 프로토콜, 포트, 소스종류, 소스) 단위로 펼친다 -> {키: 설명}"""
    out = {}
    for r in rules:
        srcs = [("cidr", _norm_cidr(c)) for c in r.get("cidr_blocks") or []]
        srcs += [("sg", s.strip()) for s in str(r.get("security_groups") or "").split(",") if s.strip()]
        srcs += [("pl", str(p).strip()) for p in r.get("prefix_list_ids") or []]
        for st, s in srcs:
            out.setdefault(_cmp_key(direction, r.get("protocol"), r.get("from_port"), r.get("to_port"), st, s), r.get("description", "") or "")
    return out


def aws_rule_keys(perms, direction):
    """AWS 규칙(IpPermissions)을 같은 형태로 펼친다 (IPv4/IPv6/SG/prefix list 소스마다 한 줄)"""
    out = {}
    for p in perms or []:
        fp, tp = p.get("FromPort"), p.get("ToPort")
        for x in p.get("IpRanges") or []:
            out.setdefault(_cmp_key(direction, p.get("IpProtocol"), fp, tp, "cidr", _norm_cidr(x.get("CidrIp", ""))), x.get("Description", "") or "")
        for x in p.get("Ipv6Ranges") or []:
            out.setdefault(_cmp_key(direction, p.get("IpProtocol"), fp, tp, "cidr", _norm_cidr(x.get("CidrIpv6", ""))), x.get("Description", "") or "")
        for x in p.get("UserIdGroupPairs") or []:
            out.setdefault(_cmp_key(direction, p.get("IpProtocol"), fp, tp, "sg", x.get("GroupId", "")), x.get("Description", "") or "")
        for x in p.get("PrefixListIds") or []:
            out.setdefault(_cmp_key(direction, p.get("IpProtocol"), fp, tp, "pl", x.get("PrefixListId", "")), x.get("Description", "") or "")
    return out


def _rule_view(key, desc):
    d, proto, fp, tp, st, src = key
    if proto == "-1":
        port = "전체"
    elif fp is None or fp == tp:
        port = str(fp) if fp is not None else "-"
    else:
        port = "%s-%s" % (fp, tp)
    return {"direction": d, "protocol": "전체" if proto == "-1" else proto, "port": port, "source_type": st, "source": src, "description": desc}


def _sorted_views(keys, desc_of, limit=200):
    order = sorted(keys, key=lambda k: (k[0], k[1], -1 if k[2] is None else k[2], k[4], k[5]))
    return [_rule_view(k, desc_of[k]) for k in order[:limit]]


def aws_compare(env, profile, region):
    """이 환경의 SG 마다 AWS 에 실제로 열려 있는 규칙과 저장소 파일의 규칙을 비교한다.
    AWS 에만 있음 = 콘솔 등에서 직접 추가되었거나 파일에서 지워졌지만 아직 적용 전, 파일에만 있음 = 아직 적용(apply) 전이거나 다른 계정/VPC"""
    sgs = aws_run(profile, "ec2", "describe-security-groups",
                  ["--query", "SecurityGroups[].{id:GroupId,name:GroupName,vpc:VpcId,tags:Tags}"], region) or []
    names = [x["name"] for x in list_sgs(env)]
    em = (load_meta().get("envs") or {}).get(env["id"], {})
    cur_vpcs = {x.get("vpc_id") for x in (em.get("subnets") or []) if x.get("vpc_id")}
    hits, vpcs = aws_resolve(env, sgs, names, cur_vpcs)
    ids = sorted({h[0]["id"] for h in hits.values() if len({x["id"] for x in h}) == 1})
    q = "SecurityGroups[].{id:GroupId,ingress:IpPermissions,egress:IpPermissionsEgress}"
    chunks = [ids[i:i + 40] for i in range(0, len(ids), 40)]
    rules = {}
    for part in aws_par(*[(lambda c=c: aws_run(profile, "ec2", "describe-security-groups", ["--group-ids"] + c + ["--query", q], region) or []) for c in chunks]):
        for g in part:
            rules[g["id"]] = g
    rows, keys = [], {}
    for n in names:
        hit = hits[n]
        if not hit:
            rows.append({"name": n, "status": "missing"})
            continue
        if len({h["id"] for h in hit}) > 1:
            rows.append({"name": n, "status": "ambiguous", "candidates": [h["id"] for h in hit][:5]})
            continue
        sid = hit[0]["id"]
        row = {"name": n, "sg_id": sid, "aws_only": [], "file_only": [], "same": 0}
        if (hit[0].get("name") or "").lower() != n.lower() and _tag(hit[0].get("tags")).lower() != n.lower():
            row["aws_name"] = hit[0].get("name") or ""
        try:
            fsg = load_sg(env, n)
        except ApiError as e:
            row.update(status="file_error", message=str(e))
            rows.append(row)
            continue
        a_only, f_only, same = [], [], 0
        a_desc, f_desc = {}, {}
        for d in ("ingress", "egress"):
            ak, fk = aws_rule_keys((rules.get(sid) or {}).get(d), d), file_rule_keys(fsg[d], d)
            a_desc.update(ak)
            f_desc.update(fk)
            a_only += [k for k in ak if k not in fk]
            f_only += [k for k in fk if k not in ak]
            same += len([k for k in ak if k in fk])
        keys[n] = {"a": a_only, "f": f_only}
        row.update(status="same" if not a_only and not f_only else "diff", same=same,
                   aws_only=_sorted_views(a_only, a_desc), file_only=_sorted_views(f_only, f_desc),
                   aws_only_count=len(a_only), file_only_count=len(f_only))
        rows.append(row)
    cnt = {}
    for r in rows:
        cnt[r["status"]] = cnt.get(r["status"], 0) + 1
    return {"_keys": keys, "profile": profile, "region": region, "vpc_ids": sorted(vpcs), "sgs": rows, "counts": cnt,
            "aws_only_total": sum(r.get("aws_only_count", 0) for r in rows), "file_only_total": sum(r.get("file_only_count", 0) for r in rows)}


@app.post("/api/env/<env_id>/aws/compare")
def api_aws_compare(env_id):
    """AWS 인증이 되어 있으면 비교 결과를, 되어 있지 않으면 '넘어간다'는 안내(skipped)를 돌려준다. 로그인은 사용자가 직접 한다."""
    env = get_env(env_id)
    b = request.get_json(silent=True) or {}

    def skip(reason, msg, profile=""):
        return jsonify({"skipped": True, "reason": reason, "message": msg, "profile": profile})
    if not aws_cli_present():
        return skip("no_cli", "AWS CLI 가 설치되어 있지 않아 AWS 비교는 넘어갑니다.")
    profile = (b.get("profile") or "").strip() or aws_saved_profile(env)
    if not profile:
        return skip("no_profile", "이 환경에서 쓸 AWS 프로필이 아직 정해지지 않아 AWS 비교는 넘어갑니다. 메타 데이터의 'AWS 에서 가져오기'에서 프로필을 한 번 선택하면 기억합니다.")
    region = normalize_region(b.get("region") or "") or aws_scope(env)[1] or (load_local().get("aws_regions") or {}).get(aws_profile_key(env), "")
    if not region:
        return skip("no_region", "이 환경 경로에서 리전을 알 수 없어 AWS 비교는 넘어갑니다. 리전을 지정해 다시 실행하세요.")
    try:
        res = aws_compare(env, profile, region)
    except ApiError as e:
        k = e.extra.get("aws_error")
        if k == "login_needed":
            _AWS_ST[profile] = (time.time(), {"state": "login_needed", "profile": profile, "message": str(e)})
            return skip(k, "AWS 인증이 되어 있지 않아 AWS 비교는 넘어갑니다. (프로필 %s — AWS 로그인 후 다시 실행하세요)" % profile, profile)
        if k in ("denied", "profile_missing", "wrong_account", "cli_missing", "ssl_error", "timeout"):
            return skip(k, "AWS 비교는 넘어갑니다: %s" % e, profile)
        raise
    _AWS_ST[profile] = (time.time(), {"state": "ok", "profile": profile, "account": ""})
    keys = res.pop("_keys", {})
    try:
        hist = compare_history_add(env, res, keys)
    except Exception as exc:
        log_event("WARN", "비교 이력을 저장하지 못했습니다: %r" % exc)
        hist = None
    return jsonify({"skipped": False, "history": hist, **res})


# ---- 비교 이력: 지난 비교와 비교해 새로 생긴 차이 / 사라진 차이를 알려 준다 (data/compare_history.json, 환경마다 최근 30회)
def _hist_path():
    return os.path.join(DATA, "compare_history.json")


def _hist_ids(keys):
    out = set()
    for sg, k in keys.items():
        for side in ("a", "f"):
            for key in k.get(side, []):
                out.add(json.dumps([sg, side] + list(key), ensure_ascii=False))
    return out


def compare_history_add(env, res, keys):
    data = read_json(_hist_path(), {})
    if not isinstance(data, dict):
        data = {}
    lst = data.get(env["id"]) or []
    ids = sorted(_hist_ids(keys))
    prev = lst[-1] if lst else None
    hist = {"previous": None, "new": 0, "resolved": 0, "unchanged": 0, "new_items": [], "resolved_items": []}
    if prev:
        before = set(prev.get("ids") or [])
        now = set(ids)

        def view(i):
            v = json.loads(i)
            r = _rule_view(tuple(v[2:]), "")
            return {"sg": v[0], "side": "AWS에만 있음" if v[1] == "a" else "파일에만 있음", "direction": r["direction"], "protocol": r["protocol"], "port": r["port"], "source": r["source"]}
        new, gone = sorted(now - before), sorted(before - now)
        hist = {"previous": prev.get("ts"), "new": len(new), "resolved": len(gone), "unchanged": len(now & before),
                "new_items": [view(i) for i in new[:100]], "resolved_items": [view(i) for i in gone[:100]]}
    lst.append({"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "profile": res.get("profile"), "region": res.get("region"), "counts": res.get("counts"),
                "aws_only_total": res.get("aws_only_total", 0), "file_only_total": res.get("file_only_total", 0), "ids": ids[:5000]})
    data[env["id"]] = lst[-30:]
    write_json(_hist_path(), data)
    return hist


@app.get("/api/env/<env_id>/aws/compare/history")
def api_compare_history(env_id):
    env = get_env(env_id)
    data = read_json(_hist_path(), {})
    lst = (data.get(env["id"]) if isinstance(data, dict) else None) or []
    return jsonify({"history": [{k: v for k, v in h.items() if k != "ids"} for h in lst][::-1]})


@app.post("/api/aws/compare/xlsx")
def api_aws_compare_xlsx():
    """화면에 나온 비교 보고서(JSON)를 엑셀 파일로 만들어 준다 (요약 시트 + 차이 목록 시트). AWS 는 다시 조회하지 않는다."""
    r = (request.get_json(silent=True) or {}).get("report")
    if not isinstance(r, dict) or not isinstance(r.get("sgs"), list):
        raise ApiError("비교 보고서 내용이 올바르지 않습니다")
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
    except ImportError:
        raise ApiError("엑셀 파일을 만들려면 openpyxl 패키지가 필요합니다 (run.bat 을 다시 실행하면 설치됩니다). CSV 로 받아 주세요")
    import io
    label = {"same": "일치", "diff": "다름", "missing": "AWS에서 못 찾음", "ambiguous": "후보 여러 개", "file_error": "파일 읽기 실패"}
    wb = Workbook()
    ws = wb.active
    ws.title = "요약"
    ws.append(["프로필", r.get("profile", ""), "리전", r.get("region", ""), "만든 시각", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
    ws.append([])
    head = ["SG", "SG ID", "결과", "일치한 규칙", "AWS에만 있음", "파일에만 있음"]
    ws.append(head)
    for r0 in r["sgs"]:
        ws.append([r0.get("name", ""), r0.get("sg_id", ""), label.get(r0.get("status"), r0.get("status", "")), r0.get("same", 0),
                   r0.get("aws_only_count", 0), r0.get("file_only_count", 0)])
    d = wb.create_sheet("차이 목록")
    d.append(["SG", "SG ID", "구분", "방향", "프로토콜", "포트", "소스 종류", "소스", "설명"])
    for r0 in r["sgs"]:
        for k, lst in (("AWS에만 있음", r0.get("aws_only")), ("파일에만 있음", r0.get("file_only"))):
            for x in lst or []:
                d.append([r0.get("name", ""), r0.get("sg_id", ""), k, x.get("direction", ""), x.get("protocol", ""), str(x.get("port", "")),
                          x.get("source_type", ""), x.get("source", ""), x.get("description", "")])
    for sheet, row in ((ws, 3), (d, 1)):
        for c in sheet[row]:
            c.font = Font(bold=True)
            c.fill = PatternFill("solid", fgColor="E8EEF7")
        for col, w in zip("ABCDEFGHI", (34, 24, 16, 12, 14, 14, 12, 40, 50)):
            sheet.column_dimensions[col].width = w
    buf = io.BytesIO()
    wb.save(buf)
    name = "aws-compare-%s.xlsx" % datetime.now().strftime("%y%m%d_%H%M%S")
    return Response(buf.getvalue(), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="%s"' % name})
