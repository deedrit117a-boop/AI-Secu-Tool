# app.py 에서 _include() 로 불러오는 부분 (app.py 와 같은 이름공간을 쓴다)
# ----------------------------------------------------------------- 담당자(owner) / 감사 보고서(Excel)
# 담당자는 메타 데이터(meta.json)의 SG 항목에 적는 문자열이다 (팀 또는 사람). 보고서는 읽기 전용이다.

from datetime import timedelta


def owner_map():
    """{(환경 ID, SG 이름): 담당자}"""
    out = {}
    for eid, em in (load_meta().get("envs") or {}).items():
        if not isinstance(em, dict):
            continue
        for sg, sm in (em.get("sgs") or {}).items():
            if isinstance(sm, dict) and str(sm.get("owner", "")).strip():
                out[(eid, sg)] = str(sm["owner"]).strip()
    return out


def add_owner(rows):
    om = owner_map()
    for r in rows:
        r["owner"] = om.get((r.get("env_id"), r.get("sg")), "")
    return rows


NO_OWNER = "(미지정)"


def owner_summary(days=30):
    """담당자별 건수: SG 수 / 만료 지남 / 만료 임박 / 정리 제안 / 기준 점검에 걸린 규칙"""
    om = owner_map()
    rows = {}

    def bucket(owner):
        return rows.setdefault(owner or NO_OWNER, {"owner": owner or NO_OWNER, "sgs": 0, "expired": 0, "soon": 0, "cleanup": 0, "issues": 0})
    for env, _label, name, _data in _each_sg():
        bucket(om.get((env["id"], name), "")) ["sgs"] += 1
    ex, _w = expiry_rows(days)
    for r in ex:
        bucket(r["owner"])["expired" if r["status"] == "expired" else "soon"] += 1
    for env, label, name, data in _each_sg():
        n = len(_cleanup_sg(label, env["id"], name, data))
        if n:
            bucket(om.get((env["id"], name), ""))["cleanup"] += n
    _envs, sc = score_report()
    for r in sc:
        if r["kind"] != "dup":
            bucket(r["owner"])["issues"] += 1
    out = sorted(rows.values(), key=lambda x: (x["owner"] == NO_OWNER, -(x["expired"] * 3 + x["soon"] + x["issues"]), x["owner"]))
    return out


@app.get("/api/report/owners")
def api_report_owners():
    try:
        days = max(0, min(int(request.args.get("days", 30)), 3650))
    except ValueError:
        raise ApiError("days 는 숫자여야 합니다")
    out = owner_summary(days)
    if request.args.get("format") == "csv":
        return _csv_response(["담당자", "SG 수", "만료 지남", "만료 임박", "정리 제안", "기준 점검 항목"], [[r["owner"], r["sgs"], r["expired"], r["soon"], r["cleanup"], r["issues"]] for r in out], "owner-report.csv")
    return jsonify({"days": days, "owners": out, "unassigned": next((r["sgs"] for r in out if r["owner"] == NO_OWNER), 0)})


# ---- 감사 보고서: 기간별 변경 이력 + 위험 규칙 승인 + 만료 + 정리 제안 + 기준 점검 + 담당자별을 한 파일(.xlsx)로
def _date_arg(name, default):
    v = (request.args.get(name) or "").strip()
    if not v:
        return default
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except ValueError:
        raise ApiError("%s 는 YYYY-MM-DD 형식이어야 합니다" % name)


def _first_line(s, n=300):
    return str(s or "").strip().split("\n")[0][:n]


def audit_workbook(d_from, d_to, days=30):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    wb = Workbook()
    head_fill = PatternFill("solid", fgColor="E7E6E6")

    def sheet(title, header, rows, widths=None, first=False):
        ws = wb.active if first else wb.create_sheet()
        ws.title = title
        ws.append(header)
        for c in ws[1]:
            c.font = Font(bold=True)
            c.fill = head_fill
            c.alignment = Alignment(vertical="center", wrap_text=True)
        for r in rows[:20000]:
            ws.append([("" if v is None else v) for v in r])
        ws.freeze_panes = "A2"
        for i, w in enumerate(widths or [], 1):
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w
        return ws
    lo = datetime.combine(d_from, datetime.min.time()).timestamp() * 1000
    hi = datetime.combine(d_to, datetime.max.time()).timestamp() * 1000
    hist = []
    for key, items in (read_json(HISTORY_PATH, {}) or {}).items():
        for x in items or []:
            if x.get("kind") in ("rule", "push", "mr", "plan", "apply", "unlock") and lo <= (x.get("ts") or 0) <= hi:
                hist.append([datetime.fromtimestamp(x["ts"] / 1000).strftime("%Y-%m-%d %H:%M:%S"), key, x.get("user", ""), x.get("step", ""), x.get("kind", ""),
                             {"ok": "완료", "error": "실패", "warn": "확인 필요", "pending": "진행 중"}.get(x.get("state"), x.get("state", "")), x.get("headline", ""), _first_line(x.get("text"))])
    hist.sort(key=lambda r: r[0])
    appr = [[a.get("ts", ""), a.get("user", ""), a.get("env_id", ""), a.get("ticket", ""), a.get("branch", ""), a.get("sg", ""), " / ".join(a.get("risks") or []), a.get("reason", "")]
            for a in _approvals() if str(a.get("ts", ""))[:10] >= d_from.isoformat() and str(a.get("ts", ""))[:10] <= d_to.isoformat()]
    ex, with_exp = expiry_rows(days)
    cl = []
    for env, label, name, data in _each_sg():
        cl += _cleanup_sg(label, env["id"], name, data)
    add_owner(cl)
    envs, sc = score_report()
    owners = owner_summary(days)
    tz = {"duplicate": "중복", "covered": "포함됨"}
    kinds = {k: v[0] for k, v in SCORE_KINDS.items()}
    ws = sheet("요약", ["항목", "값"], [
        ["작성 시각", datetime.now().strftime("%Y-%m-%d %H:%M:%S")], ["작성자", load_local().get("account", "")], ["대상 기간", "%s ~ %s" % (d_from, d_to)],
        ["변경 이력(규칙·push·MR·plan·apply) 건수", len(hist)], ["위험 규칙 승인 건수", len(appr)], ["만료일이 적힌 규칙", with_exp],
        ["만료 지남", sum(1 for r in ex if r["status"] == "expired")], ["만료 임박 (%d일 안)" % days, sum(1 for r in ex if r["status"] != "expired")],
        ["정리 제안", len(cl)], ["담당자 미지정 SG", next((r["sgs"] for r in owners if r["owner"] == NO_OWNER), 0)], [],
        ["환경별 기준 점검 점수", ""]] + [["%s (SG %d개 / 규칙 %d개)" % (e["env"], e["sgs"], e["rules"]), "%d점 %s" % (e["score"], e["grade"])] for e in envs], [60, 28], first=True)
    ws.append([])
    ws.append(["* 이 보고서는 받아 둔 파일과 도구의 기록(작업 이력, 승인 기록)을 모은 것으로, 읽기 전용입니다."])
    sheet("변경 이력", ["시각", "저장소", "사용자", "단계", "종류", "결과", "요약", "내용(첫 줄)"], hist, [19, 34, 12, 30, 8, 10, 40, 60])
    sheet("위험 규칙 승인", ["시각", "승인자", "환경", "티켓", "브랜치", "SG", "위험 규칙", "승인 사유"], appr, [19, 12, 26, 14, 30, 30, 50, 40])
    sheet("만료 규칙", ["환경", "SG", "담당자", "방향", "프로토콜", "포트", "소스", "만료일", "남은 일수", "상태", "설명"],
          [[r["env"], r["sg"], r["owner"], r["direction"], r["protocol"], r["port"], r["source"], r["expires"], r["days_left"], "지남" if r["status"] == "expired" else "임박", r["description"]] for r in ex],
          [28, 30, 14, 9, 9, 12, 22, 12, 9, 7, 50])
    sheet("정리 제안", ["환경", "SG", "담당자", "구분", "방향", "프로토콜", "포트", "소스", "설명", "겹치는 규칙"],
          [[r["env"], r["sg"], r["owner"], tz.get(r["kind"], r["kind"]), r["direction"], r["protocol"], r["port"], r["source"], r["description"], r["by"]] for r in cl], [28, 30, 14, 8, 9, 9, 12, 22, 50, 40])
    sheet("기준 점검", ["환경", "SG", "담당자", "항목", "방향", "프로토콜", "포트", "소스", "설명"],
          [[r["env"], r["sg"], r["owner"], kinds.get(r["kind"], r["kind"]), r["direction"], r["protocol"], r["port"], r["source"], r["description"]] for r in sc], [28, 30, 14, 18, 9, 9, 12, 22, 50])
    sheet("담당자별", ["담당자", "SG 수", "만료 지남", "만료 임박", "정리 제안", "기준 점검 항목"], [[r["owner"], r["sgs"], r["expired"], r["soon"], r["cleanup"], r["issues"]] for r in owners], [24, 8, 10, 10, 10, 14])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@app.get("/api/report/audit-xlsx")
def api_report_audit_xlsx():
    """감사 보고서(.xlsx): from/to(YYYY-MM-DD, 기본 최근 90일), days(만료 임박 기준, 기본 30)"""
    today = datetime.now().date()
    d_to = _date_arg("to", today)
    d_from = _date_arg("from", d_to - timedelta(days=90))
    if d_from > d_to:
        raise ApiError("시작일이 종료일보다 늦습니다")
    try:
        days = max(0, min(int(request.args.get("days", 30)), 3650))
    except ValueError:
        raise ApiError("days 는 숫자여야 합니다")
    data = audit_workbook(d_from, d_to, days)
    log_event("INFO", "감사 보고서 내보내기: %s ~ %s" % (d_from, d_to))
    return Response(data, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename=acl-audit-%s.xlsx" % today.strftime("%Y%m%d")})
