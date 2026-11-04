# app.py 에서 _include() 로 불러오는 부분 (app.py 와 같은 이름공간을 쓴다)
# ----------------------------------------------------------------- 서비스 사전 (이름 붙인 프로토콜·포트). 주소 묶음은 기존 '프리셋'을 쓴다.
SERVICE_NAME_RE = re.compile(r"^[^\s,;@/]{1,40}$")
SERVICE_DEFAULT = [{"name": "HTTPS", "protocol": "TCP", "ports": "443"}, {"name": "HTTP", "protocol": "TCP", "ports": "80"}, {"name": "SSH", "protocol": "TCP", "ports": "22"}]


def normalize_services(raw):
    """[{name, protocol(TCP/UDP), ports('443' 또는 '1000-2000')}] 검증. 잘못된 값은 ApiError"""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ApiError("서비스 목록 형식이 올바르지 않습니다")
    out, seen = [], set()
    for i, x in enumerate(raw, start=1):
        if not isinstance(x, dict):
            raise ApiError("서비스 %d번 형식이 올바르지 않습니다" % i)
        name = str(x.get("name") or "").strip()
        proto = str(x.get("protocol") or "TCP").strip().upper()
        ports = str(x.get("ports") or "").strip()
        if not name and not ports:
            continue
        if not SERVICE_NAME_RE.match(name):
            raise ApiError("서비스 %d번 이름은 공백·쉼표·@·/ 없이 40자 이하로 적으세요" % i)
        if name.lower() in seen:
            raise ApiError("서비스 이름이 중복됩니다: %s" % name)
        if proto not in ("TCP", "UDP"):
            raise ApiError("서비스 %d번 프로토콜은 TCP 또는 UDP 입니다" % i)
        if not re.match(r"^\d{1,5}(-\d{1,5})?$", ports):
            raise ApiError("서비스 %d번 포트는 443 또는 1000-2000 형식으로 적으세요 (여러 포트는 서비스를 나눠 등록)" % i)
        try:
            _port_ranges(ports)
        except ValueError as e:
            raise ApiError("서비스 %d번: %s" % (i, e))
        seen.add(name.lower())
        out.append({"name": name, "protocol": proto, "ports": ports})
    if len(out) > 200:
        raise ApiError("서비스는 200개까지 등록할 수 있습니다")
    return out


@app.get("/api/services")
def api_services_get():
    s = load_config().get("services")
    try:
        cur = normalize_services(s)
    except ApiError:
        cur = []
    return jsonify({"services": cur, "examples": SERVICE_DEFAULT})


@app.put("/api/services")
@cfg_locked
def api_services_put():
    sv = normalize_services((request.get_json(silent=True) or {}).get("services"))
    cfg = load_config()
    cfg["services"] = sv
    write_json(CONFIG_PATH, cfg)
    log_event("INFO", "서비스 사전 저장: %d개" % len(sv))
    return jsonify({"ok": True, "services": sv, "rev": file_rev(CONFIG_PATH)})
