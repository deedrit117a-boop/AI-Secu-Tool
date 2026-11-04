# app.py 에서 _include() 로 불러오는 부분 (app.py 와 같은 이름공간을 쓴다)
# ----------------------------------------------------------------- Jira 티켓 읽기(자동 채우기) / 도메인 조회·메타 태그 적용
# 티켓은 읽기만 한다(Jira 쓰기 없음). 규칙을 바꾸는 일은 화면의 '빠른 작업' 확인을 거친 뒤에만 일어난다.
# 메타 데이터에 쓰는 것은 '도메인 태그 추가' 하나뿐이고, 화면에서 사용자가 누른 경우에만 호출된다.
from html import unescape as _html_unescape
from html.parser import HTMLParser as _HTMLParser

DOMAIN_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,23}$")
FILE_EXT = {"json", "txt", "md", "py", "js", "png", "jpg", "jpeg", "gif", "csv", "xlsx", "xls", "docx", "doc", "zip", "log", "pdf", "yml", "yaml", "tf", "html", "bat", "sh", "exe", "pptx"}
HOST_IN_TEXT_RE = re.compile(r"(?<![\w@./-])((?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z][A-Za-z0-9-]{1,23})(?![\w-])")
IP_IN_TEXT_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?:\s*/\s*(\d{1,2}))?(?![\d])")
PORT_TOKEN_RE = re.compile(r"(?<![\d.])(\d{1,5})(?:\s*[-~]\s*(\d{1,5}))?(?![\d.])")
PROTO_PORT_RE = re.compile(r"\b(tcp|udp)\s*[/:\-]?\s*(\d{1,5})(?:\s*[-~]\s*(\d{1,5}))?", re.I)
LABEL_SRC = re.compile(r"^[\W_]*(?:h\d\.)?[\W_]*(출발지|소스|source|src|from|요청자|접속자|client|허용\s*(?:대상|ip)|신청\s*ip)", re.I)
LABEL_DST = re.compile(r"^[\W_]*(?:h\d\.)?[\W_]*(목적지|destination|dest|dst|to\b|대상\s*(?:서버|sg|시스템)|서버\s*(?:정보|ip)?\s*[:：|])", re.I)
LABEL_PORT = re.compile(r"^[\W_]*(?:h\d\.)?[\W_]*(서비스\s*포트|포트|port|ports)", re.I)


def norm_domain(text):
    """도메인 입력을 정리한다 (http://, 경로, :포트 제거). 도메인 형식이 아니면 ''"""
    d = str(text or "").strip().lower()
    d = re.sub(r"^[a-z][a-z0-9+.-]*://", "", d)
    d = d.split("/")[0].split("?")[0].split(":")[0].rstrip(".")
    if not d or re.fullmatch(r"[\d.]+", d) or not DOMAIN_RE.match(d) or len(d) > 253:
        return ""
    return d


def _flatten(v):
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, dict):
        return _flatten(v.get("value") or v.get("name") or v.get("displayName") or v.get("key") or "")
    if isinstance(v, list):
        return ", ".join(x for x in (_flatten(i) for i in v) if x)
    return ""


def _ticket_text(fields, names):
    """요약 + 설명 + 문자열 사용자 정의 필드를 '필드이름: 값' 줄로 이어 붙인다 (라벨로 출발지/포트를 읽기 위해)"""
    lines = []
    if fields.get("summary"):
        lines.append("요약: " + _flatten(fields["summary"]))
    desc = _plain(_flatten(fields.get("description")))
    if desc:
        lines.append(desc)
    for k, v in fields.items():
        if not k.startswith("customfield_"):
            continue
        t = _flatten(v).strip()
        if t and len(t) <= 4000:
            lines.append("%s: %s" % ((names or {}).get(k, k), t))
    text = "\n".join(lines)
    text = re.sub(r"\{code[^}]*\}|\{noformat\}|\{quote\}|\{panel[^}]*\}", "\n", text)
    text = re.sub(r"\[([^\]|]+)\|[^\]]*\]", r"\1", text)         # [표시|링크]
    return text.replace("||", "|").replace("\r", "")


def _plain(s):
    """HTML 로 된 설명을 줄 단위 글자로 바꾼다 (표의 칸은 ' | ' 로 구분). HTML 이 아니면 그대로"""
    s = str(s or "")
    if not re.search(r"<[a-zA-Z/][^>]*>", s):
        return s
    s = re.sub(r"(?i)<br\s*/?>|</p>|</tr>|</div>|</li>|</h\d>", "\n", s)
    s = re.sub(r"(?i)</t[dh]>", " | ", s)
    s = _html_unescape(re.sub(r"<[^>]+>", "", s))
    s = s.replace("\u3000", " ").replace("\xa0", " ")
    return "\n".join(re.sub(r"[ \t]+", " ", ln).strip() for ln in s.split("\n"))


# ---- 표준 요청 양식(표): no / 구분 / Project / Source IP / Source Env / Destination IP / Destination Env / Service Port / 용도 / 사용 기간 / 비고
TABLE_HEAD = {"action": ("구분",), "project": ("project", "프로젝트"), "src_ip": ("sourceip", "출발지ip", "소스ip"), "src_env": ("sourceenv",),
              "dst_ip": ("destinationip", "목적지ip"), "dst_env": ("destinationenv",), "port": ("serviceport", "포트"), "purpose": ("용도",),
              "period": ("사용기간",), "note": ("비고",)}


def _cell_text(s):
    s = str(s or "").replace("\u3000", " ").replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in s.split("\n")]
    return "\n".join(ln for ln in lines if ln)


class _TableParser(_HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            self.cell = []
            if self.row is None:
                self.row = []
        elif tag == "br" and self.cell is not None:
            self.cell.append("\n")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(_cell_text("".join(self.cell)))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        elif tag in ("p", "div", "li") and self.cell is not None:
            self.cell.append("\n")

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)


def _wiki_rows(text):
    rows = []
    for ln in str(text or "").replace("\r", "").split("\n"):
        s = ln.strip()
        if s.startswith("|"):
            rows.append([_cell_text(c.replace("\\\\", "\n")) for c in re.split(r"\|\|?", s.strip("|"))])
        elif re.search(r"\[.*\]", s) and re.search(r"정책|policy|policies", s, re.I):
            rows.append([s])
    return rows


def _norm_head(s):
    return re.sub(r"\s+", "", re.sub(r"\(.*?\)", "", str(s or "").lower().replace("\n", " ")))


def _section_action(t):
    low = str(t or "").lower()
    if re.search(r"삭제|제거|delete|remov", low):
        return "del"
    if re.search(r"변경|modif|chang", low):
        return "change"
    if re.search(r"등록|new|추가|add", low):
        return "add"
    return ""


def _parse_port_cell(text):
    """'443 TCP', 'TCP 80, UDP 53', '8080-8090/tcp' -> [(proto, lo, hi)]. 못 읽으면 []"""
    out, last = [], "tcp"
    for tok in re.split(r"[,;\n]+", str(text or "")):
        pm = re.search(r"(tcp|udp)", tok, re.I)
        proto = pm.group(1).lower() if pm else last
        last = proto
        for m in PORT_TOKEN_RE.finditer(re.sub(r"(?i)tcp|udp", " ", tok)):
            lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
            if 1 <= lo <= hi <= 65535 and (proto, lo, hi) not in out:
                out.append((proto, lo, hi))
    return out


def _period_info(text):
    t = str(text or "").strip()
    m = re.search(r"(\d{4})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})", t)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date().isoformat()
        except ValueError:
            return ""
    return ""


def parse_request_table(raw):
    """표준 요청 양식(표)을 읽는다. 반환: (묶음 목록, 경고, 표를 찾았는지)
    묶음 = 같은 (구분, 목적지, 프로토콜, 포트)인 행의 출발지 IP 를 모은 것. 대상 SG 는 목적지 쪽이다."""
    raw = str(raw or "")
    if re.search(r"<t[dr][\s>]", raw, re.I):
        p = _TableParser()
        p.feed(raw)
        rows = p.rows
    else:
        rows = _wiki_rows(raw)
    cols, section, items, warns, found = None, "add", [], [], False
    for row in rows:
        if len(row) == 1:
            if re.search(r"\[.*\]", row[0]):
                section = _section_action(row[0]) or section
            continue
        heads = [_norm_head(c) for c in row]
        if any("sourceip" in h or "출발지ip" in h for h in heads) and any("destinationip" in h or "목적지ip" in h for h in heads):
            cols = {}
            for i, h in enumerate(heads):
                for k, keys in TABLE_HEAD.items():
                    if k not in cols and any(x in h for x in keys):
                        cols[k] = i
            found = True
            continue
        if not cols or re.search(r"예시|\beg\b", row[0] or "", re.I):
            continue

        def cell(k):
            i = cols.get(k)
            return row[i] if i is not None and i < len(row) else ""
        src, dst = [], []
        for m in IP_IN_TEXT_RE.finditer(cell("src_ip")):
            _add_ip(src, m)
        for m in IP_IN_TEXT_RE.finditer(cell("dst_ip")):
            _add_ip(dst, m)
        no = (row[0] or "").strip()
        if not src and not dst:
            continue
        action = _section_action(cell("action")) or section
        if action == "change":
            warns.append("행 %s: 구분이 '변경' 입니다. 추가로 채웠으니 내용을 확인하세요 (기존 규칙을 바꾸려면 삭제와 등록으로 나누세요)" % no)
            action = "add"
        if not src:
            warns.append("행 %s: 출발지 IP 가 없어 건너뜁니다" % no)
            continue
        ports = _parse_port_cell(cell("port"))
        if not ports:
            warns.append("행 %s: 포트를 읽지 못했습니다 (%s)" % (no, cell("port").replace("\n", " ")[:40] or "비어 있음"))
            continue
        for proto in sorted({p for p, _l, _h in ports}):
            items.append({"no": no, "action": action, "src": src, "dst": dst, "proto": proto.upper(), "ports": [(lo, hi) for p, lo, hi in ports if p == proto],
                          "project": cell("project").replace("\n", " ").strip(), "src_env": cell("src_env").replace("\n", " ").strip(), "dst_env": cell("dst_env").replace("\n", " ").strip(),
                          "purpose": cell("purpose").replace("\n", " ").strip(), "period": cell("period").replace("\n", " ").strip()})
    groups = {}
    for it in items:
        key = (it["action"], tuple(it["dst"]), it["proto"], tuple(it["ports"]))
        g = groups.get(key)
        if not g:
            g = groups[key] = {"action": it["action"], "ips": [], "dst_ips": list(it["dst"]), "ports": [{"from": lo, "to": hi} for lo, hi in it["ports"]], "protocol": it["proto"],
                               "project": it["project"], "src_env": it["src_env"], "dst_env": it["dst_env"], "purpose": it["purpose"], "period": it["period"],
                               "expires": _period_info(it["period"]), "rows": []}
        for ip in it["src"]:
            if ip not in g["ips"]:
                g["ips"].append(ip)
        g["rows"].append(it["no"])
    out = list(groups.values())
    for g in out:
        g["ips"] = g["ips"][:100]
        if "0.0.0.0/0" in g["ips"]:
            warns.append("0.0.0.0/0 이 포함되어 있습니다. 저장할 때 위험 규칙 확인이 나옵니다")
    if found and not out:
        warns.append("요청 양식(표)은 찾았지만 읽을 수 있는 행이 없습니다. 출발지·목적지 IP 와 포트를 확인하세요")
    if len(out) > 1:
        warns.append("표의 요청이 %d묶음(목적지·포트·구분이 다름)으로 나뉘었습니다. 한 번에 한 묶음씩 채우고 실행합니다" % len(out))
    return out[:20], warns, found


def parse_ticket(text, raw_desc=""):
    """티켓 글을 읽는다: 표준 요청 양식(표)이 있으면 그 표를, 없으면 줄의 라벨(출발지/포트 ...)을 읽는다"""
    base = parse_ticket_text(text)
    groups, warns, found = parse_request_table(raw_desc)
    base["action"] = "add"
    base["groups"], base["table"] = groups, found
    if groups:
        g0 = groups[0]
        base.update(ips=g0["ips"], dst_ips=g0["dst_ips"][:50], ports=g0["ports"], protocol=g0["protocol"], action=g0["action"])
        base["warnings"] = warns + [w for w in base["warnings"] if not w.startswith(("출발지로 표시된", "출발지 IP", "포트를 찾지", "0.0.0.0/0"))]
    elif found:
        base["warnings"] = warns + base["warnings"]
    return base


def _add_ip(bucket, m):
    ip, pre = m.group(1), m.group(2)
    if any(int(o) > 255 for o in ip.split(".")):
        return
    if pre is not None and int(pre) > 32:
        return
    cidr = "%s/%s" % (ip, pre if pre is not None else "32")
    if _net(cidr) is not None and cidr not in bucket:
        bucket.append(cidr)


def _add_ports(out, s, proto="tcp"):
    for m in PORT_TOKEN_RE.finditer(s):
        lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
        if 1 <= lo <= hi <= 65535 and (proto, lo, hi) not in out:
            out.append((proto, lo, hi))


def parse_ticket_text(text):
    """티켓 글에서 출발지 IP / 목적지 IP / 포트 / 프로토콜 / 방향 / 도메인을 읽는다. 라벨(출발지, 목적지, 포트 ...)이 있으면 그것을 따른다."""
    src, dst, other = [], [], []
    ports, warnings = [], []
    cur = None
    for raw in text.split("\n"):
        line = raw.strip().strip("|").strip()
        if not line:
            cur = None
            continue
        if LABEL_PORT.match(line):
            cur = "port"
        elif LABEL_SRC.match(line):
            cur = "src"
        elif LABEL_DST.match(line):
            cur = "dst"
        for m in PROTO_PORT_RE.finditer(line):
            lo, hi = int(m.group(2)), int(m.group(3) or m.group(2))
            if 1 <= lo <= hi <= 65535 and (m.group(1).lower(), lo, hi) not in ports:
                ports.append((m.group(1).lower(), lo, hi))
        no_ip = IP_IN_TEXT_RE.sub(" ", line)
        if cur == "port":
            _add_ports(ports, re.sub(r"(?i)\b(tcp|udp)\b", " ", PROTO_PORT_RE.sub(" ", no_ip)))
        bucket = {"src": src, "dst": dst}.get(cur, other)
        for m in IP_IN_TEXT_RE.finditer(line):
            _add_ip(bucket, m)
    low = text.lower()
    ips = src or [x for x in other if x not in dst]
    if not src and ips:
        warnings.append("출발지로 표시된 줄이 없어 목적지가 아닌 모든 IP 를 출발지로 읽었습니다. 확인하세요")
    if not ips:
        warnings.append("출발지 IP 를 찾지 못했습니다. 직접 입력하세요")
    if not ports:
        warnings.append("포트를 찾지 못했습니다. 직접 입력하세요")
    protos = sorted({p for p, _l, _h in ports})
    proto = "UDP" if protos == ["udp"] else "TCP"
    if len(protos) > 1:
        warnings.append("TCP 와 UDP 가 함께 있어 TCP 로 채웠습니다. UDP 는 따로 한 번 더 실행하세요")
        ports = [p for p in ports if p[0] == "tcp"]
    ranges = []
    for _p, lo, hi in ports:
        if (lo, hi) not in ranges:
            ranges.append((lo, hi))
    egress = bool(re.search(r"아웃바운드|outbound|egress", low))
    ingress = bool(re.search(r"인바운드|inbound|ingress", low))
    if egress and ingress:
        warnings.append("인바운드와 아웃바운드가 모두 언급되어 인바운드로 채웠습니다. 확인하세요")
    direction = "egress" if egress and not ingress else "ingress"
    domains = []
    for m in HOST_IN_TEXT_RE.finditer(text):
        d = norm_domain(m.group(1))
        if d and d.rsplit(".", 1)[-1] not in FILE_EXT and d not in domains and "smilegate" not in d and "playstove" not in d and "sginfra" not in d:
            domains.append(d)
    if any("0.0.0.0/0" == i for i in ips):
        warnings.append("0.0.0.0/0 이 포함되어 있습니다. 저장할 때 위험 규칙 확인이 나옵니다")
    return {"ips": ips[:100], "dst_ips": dst[:50], "ports": [{"from": lo, "to": hi} for lo, hi in ranges[:20]], "protocol": proto, "direction": direction,
            "domains": domains[:10], "warnings": warnings}


# ---- 도메인 조회: 메타 데이터(SG 태그·별명)와 비교한다 (DNS 는 읽기 전용 조회)
def _resolve(domain, timeout=4):
    import concurrent.futures
    import socket
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(lambda: sorted({i[4][0] for i in socket.getaddrinfo(domain, None, socket.AF_INET)}))
    try:
        return fut.result(timeout=timeout), ""
    except concurrent.futures.TimeoutError:
        return [], "DNS 조회 시간이 초과되었습니다"
    except OSError as e:
        return [], "DNS 조회 실패: %s" % str(e)[:80]
    finally:
        ex.shutdown(wait=False)


def _tag_text(sm):
    return [str(t.get("value", "")).strip() for t in (sm.get("tags") or []) if str(t.get("value", "")).strip()]


def domain_lookup(domain, dns=True, scope_env=""):
    d = norm_domain(domain)
    if not d:
        raise ApiError("도메인 형식이 올바르지 않습니다 (예: game.example.com)")
    ips, dns_err = _resolve(d) if dns else ([], "")
    nets = [n for n in (_net(i) for i in ips) if n]
    first = d.split(".")[0]
    meta = load_meta().get("envs", {})
    label = {e["id"]: " · ".join(x for x in (e.get("group"), e.get("env"), e.get("label")) if x) for e in load_config()["environments"]}
    registered, related, cands = [], [], []
    for eid, em in meta.items():
        if scope_env and eid != scope_env:
            continue
        if not isinstance(em, dict):
            continue
        for sg, sm in (em.get("sgs") or {}).items():
            if not isinstance(sm, dict):
                continue
            tags = _tag_text(sm)
            base = {"env_id": eid, "env": label.get(eid) or em.get("_label", eid), "sg": sg, "alias": sm.get("alias", ""), "sg_id": sm.get("sg_id", ""),
                    "tags": [{"type": t.get("type", ""), "value": t.get("value", "")} for t in (sm.get("tags") or [])]}
            low = [t.lower() for t in tags]
            if d in low:
                registered.append({**base, "match": "exact"})
                continue
            rel = [t for t in low if norm_domain(t) and (d.endswith("." + t) or t.endswith("." + d))]
            if rel:
                related.append({**base, "match": "parent", "reason": "관련 도메인 태그: %s" % rel[0]})
            why = ""
            for t in tags:
                n = _net(t)
                if n and any(x.version == n.version and x.subnet_of(n) for x in nets):
                    why = "태그의 IP/대역이 DNS 결과와 일치: %s" % t
                    break
            if not why and ips and any(re.search(r"(?<![\d.])%s(?![\d])" % re.escape(i), str(sm.get("alias", ""))) for i in ips):
                why = "별명에 DNS 결과 IP 가 있음"
            if not why and len(first) >= 4 and (first in sg.lower() or first in str(sm.get("alias", "")).lower()):
                why = "SG 이름/별명에 '%s' 포함" % first
            if why:
                cands.append({**base, "reason": why, "ip_match": why.startswith(("태그의", "별명에"))})
    cands.sort(key=lambda c: (not c["ip_match"], c["env"], c["sg"]))
    return {"domain": d, "ips": ips, "dns_error": dns_err, "registered": registered[:20], "related": related[:20], "candidates": cands[:15]}


@app.get("/api/domain/lookup")
def api_domain_lookup():
    return jsonify(domain_lookup(request.args.get("d", ""), request.args.get("dns", "1") != "0", request.args.get("env_id", "")))


@app.post("/api/domain/apply")
@cfg_locked
def api_domain_apply():
    """메타 데이터에 이미 있는 SG 의 태그에 도메인을 추가한다 (메타 데이터가 없는 SG 는 만들지 않는다)"""
    b = request.get_json(silent=True) or {}
    d = norm_domain(b.get("domain"))
    env_id, sg = str(b.get("env_id") or ""), str(b.get("sg") or "")
    if not d:
        raise ApiError("도메인 형식이 올바르지 않습니다")
    meta = load_meta()
    envm = (meta.get("envs") or {}).get(env_id)
    sm = (envm.get("sgs") or {}).get(sg) if isinstance(envm, dict) else None
    if not isinstance(sm, dict):
        raise ApiError("이 SG 의 메타 데이터가 없어 태그를 추가하지 않았습니다 (메타 데이터 화면에서 SG 를 먼저 등록하세요)")
    tags = sm.setdefault("tags", [])
    if any(str(t.get("value", "")).strip().lower() == d for t in tags):
        return jsonify({"ok": True, "already": True, "tags": tags, "rev": file_rev(META_PATH)})
    tags.append({"type": "domain", "value": d})
    stamp_meta(meta, load_config())
    write_json(META_PATH, meta)
    log_event("INFO", "도메인 태그 추가: %s / %s <- %s" % (env_id, sg, d))
    return jsonify({"ok": True, "already": False, "tags": tags, "rev": file_rev(META_PATH)})


# ---- Jira 티켓 읽기: 출발지 IP / 포트 / 대상 SG 후보를 읽어 빠른 작업(마법사)을 채운다
def _target_suggestions(env_id, text, dst_ips, domains, hints=()):
    low = text.lower()
    meta = (load_meta().get("envs") or {}).get(env_id, {})
    try:
        env = get_env(env_id)
        names = [s["name"] for s in list_sgs(env)]
    except ApiError:
        return []
    out = []
    for n in names:
        sm = ((meta.get("sgs") or {}).get(n)) or {}
        why, score = [], 0
        short = short_name(env, n)
        if len(short) >= 4 and short.lower() in low:
            why.append("이름 '%s' 언급" % short)
            score += 3
        al = str(sm.get("alias", "")).strip()
        if len(al) >= 3 and al.lower() in low:
            why.append("별명 '%s' 언급" % al)
            score += 3
        tags = _tag_text(sm)
        for t in tags:
            if t.lower() in domains:
                why.append("도메인 태그 일치: %s" % t)
                score += 5
            elif len(t) >= 4 and t.lower() in low:
                why.append("태그 '%s' 언급" % t)
                score += 2
        for h in hints:
            h = str(h or "").strip().lower()
            if len(h) >= 3 and (h in short.lower() or h in al.lower()):
                why.append("프로젝트 '%s' 포함" % h)
                score += 2
                break
        sid = str(sm.get("sg_id", ""))
        if sid and sid.lower() in low:
            why.append("SG ID 언급")
            score += 5
        for ip in dst_ips:
            bare = ip.split("/")[0]
            if bare in al or any(bare == t.split("/")[0] for t in tags):
                why.append("목적지 IP %s 일치" % bare)
                score += 4
                break
        if score:
            out.append({"name": n, "alias": al, "score": score, "reason": " · ".join(why)})
    out.sort(key=lambda x: (-x["score"], x["name"]))
    return out[:8]


def _pick_targets(env_id, text, dst_ips, domains, hints):
    targets = _target_suggestions(env_id, text, dst_ips, {x["domain"] for x in domains}, hints) if env_id else []
    for x in domains:                       # 도메인 태그가 이 환경 SG 에 이미 있으면 대상 후보에 반영
        for r in x["registered"]:
            if r["env_id"] == env_id and not any(t["name"] == r["sg"] for t in targets):
                targets.insert(0, {"name": r["sg"], "alias": r["alias"], "score": 5, "reason": "도메인 태그 일치: %s" % x["domain"]})
    best = targets[0]["score"] if targets else 0
    top = [t["name"] for t in targets if t["score"] == best]
    return targets, (top if best >= 4 and len(top) <= 3 else [])


@app.get("/api/jira/plan")
def api_jira_plan():
    """티켓(읽기 전용)에서 규칙 추가에 필요한 값을 읽어 온다. 채워진 값은 화면에서 확인·수정한 뒤에만 쓰인다.
    표준 요청 양식(표)이 있으면 묶음(groups)별로 값과 대상 SG 후보를 따로 돌려준다. light=1 이면 도메인 DNS 조회를 건너뛴다(일괄 미리보기용)."""
    key = (request.args.get("key") or "").strip().upper()
    env_id = request.args.get("env_id", "")
    if not JIRA_KEY_RE.match(key):
        raise ApiError("티켓번호 형식이 올바르지 않습니다 (예: ISRIR-12345)")
    d = jira_call("GET", "/issue/%s" % key, params={"fields": "*all", "expand": "names"})
    fields = d.get("fields") or {}
    names = d.get("names") or {}
    text = _ticket_text(fields, names)
    parsed = parse_ticket(text, _flatten(fields.get("description")))
    project = next((_flatten(fields.get(k)).strip() for k, n in names.items() if str(n).strip().lower() in ("프로젝트", "project") and k in fields), "")
    domains = []
    if request.args.get("light") != "1":
        for dom in parsed["domains"][:3]:
            try:
                domains.append(domain_lookup(dom, dns=True, scope_env=env_id))
            except ApiError:
                continue
    if parsed["groups"]:
        for g in parsed["groups"][:6]:
            g["targets"], g["suggested"] = _pick_targets(env_id, text, g["dst_ips"], domains, [g.get("project") or project])
        for g in parsed["groups"][6:]:
            g["targets"], g["suggested"] = [], []
        targets, suggested = parsed["groups"][0]["targets"], parsed["groups"][0]["suggested"]
    else:
        targets, suggested = _pick_targets(env_id, text, parsed["dst_ips"], domains, [project])
    base = jira_settings()["base_url"]
    return jsonify({"key": d.get("key", key), "summary": _flatten(fields.get("summary")), "status": _flatten(fields.get("status")), "type": _flatten(fields.get("issuetype")),
                    "url": "%s/browse/%s" % (base, key), "parsed": parsed, "domains": domains, "targets": targets, "suggested": suggested, "project": project, "text_len": len(text)})


# ---- 완료 처리(C): 끝난 뒤 Jira 에 코멘트를 남기고 상태를 전환한다. 화면에서 사용자가 확인(또는 위저드에서 옵션을 켠)한 경우에만 호출된다.
def _jira_key_arg(v):
    key = str(v or "").strip().upper()
    if not JIRA_KEY_RE.match(key):
        raise ApiError("티켓번호 형식이 올바르지 않습니다 (예: ISRIR-12345)")
    return key


@app.get("/api/jira/transitions")
def api_jira_transitions():
    """지금 이 티켓에서 할 수 있는 상태 전환 목록 (읽기 전용)"""
    key = _jira_key_arg(request.args.get("key"))
    st = jira_call("GET", "/issue/%s" % key, params={"fields": "summary,status"})
    d = jira_call("GET", "/issue/%s/transitions" % key)
    f = st.get("fields") or {}
    return jsonify({"key": key, "summary": f.get("summary", ""), "status": (f.get("status") or {}).get("name", ""),
                    "transitions": [{"id": str(t.get("id")), "name": t.get("name", ""), "to": (t.get("to") or {}).get("name", "")} for t in (d.get("transitions") or [])]})


@app.post("/api/jira/finish")
def api_jira_finish():
    b = request.get_json(silent=True) or {}
    key = _jira_key_arg(b.get("key"))
    comment, tid = str(b.get("comment") or "").strip(), str(b.get("transition_id") or "").strip()
    if not comment and not tid:
        raise ApiError("남길 코멘트나 전환할 상태를 선택하세요")
    if len(comment) > 8000:
        raise ApiError("코멘트가 너무 깁니다 (최대 8000자)")
    pick = None
    if tid:
        trs = jira_call("GET", "/issue/%s/transitions" % key).get("transitions") or []
        pick = next((t for t in trs if str(t.get("id")) == tid), None)
        if not pick:
            raise ApiError("선택한 상태 전환을 지금은 할 수 없습니다 (티켓 상태가 바뀌었을 수 있습니다). 다시 열어 선택하세요")
    done = {"commented": False, "transitioned": ""}
    if comment:
        jira_call("POST", "/issue/%s/comment" % key, json={"body": comment})
        done["commented"] = True
    if pick:
        try:
            jira_call("POST", "/issue/%s/transitions" % key, json={"transition": {"id": tid}})
        except ApiError as e:
            raise ApiError("%s상태 전환에 실패했습니다: %s" % ("코멘트는 남겼지만 " if done["commented"] else "", e), e.code, **done)
        done["transitioned"] = pick.get("name") or tid
    log_event("INFO", "Jira 완료 처리: %s 코멘트=%s 전환=%s" % (key, done["commented"], done["transitioned"] or "-"))
    return jsonify({"ok": True, **done, "url": "%s/browse/%s" % (jira_settings()["base_url"], key)})


# ---- 요청 양식: 요청자가 티켓 설명에 붙여 넣는 표준 표 (도구가 그대로 읽는다)
TEMPLATE_HEAD = ["no", "구분\n(application type)", "Project", "Source IP", "Source Env", "Destination IP", "Destination Env", "Service Port", "용도\n(purpose of use)", "사용 기간\n(period of use)", "비고\n(note)"]
TEMPLATE_EXAMPLE = ["(예시/eg)", "등록\n(new)", "Drive", "10.5.X.X\n10.2.X.X", "Dev / QA / Perf / Sandbox / Live / 사내(office) PC", "10.130.X.X", "Dev / QA / Perf / Sandbox / Live / 사내(office) PC",
                    "443 TCP", "테스트용 웹서버 접속", "~2023.12.31 또는 서비스 운영 기간(영구)", "10.5.X.X/사용자명/SGS"]


def request_template(rows=3):
    def td(t, head=False, gray=False):
        tag = "th" if head else "td"
        st = "border:1px solid #888;padding:4px 6px;text-align:center;vertical-align:middle;" + ("background:#e7e6e6;font-weight:700;" if head else "") + ("color:#999;font-style:italic;" if gray else "")
        return "<%s style=\"%s\">%s</%s>" % (tag, st, "<br>".join(x for x in str(t).split("\n")), tag)
    body = "<tr>%s</tr>" % "".join(td(c, True) for c in TEMPLATE_HEAD)
    body += "<tr>%s</tr>" % "".join(td(c, gray=True) for c in TEMPLATE_EXAMPLE)
    for i in range(rows):
        body += "<tr>%s</tr>" % "".join(td(str(i + 1) if j == 0 else "") for j in range(len(TEMPLATE_HEAD)))
    html = "<p><b>[ 정책 등록 (new policies) ]</b></p><table style=\"border-collapse:collapse\"><tbody>%s</tbody></table><p>설명</p><p>(요청 배경과 용도를 적어 주세요)</p>" % body
    text = "[ 정책 등록 (new policies) ]\n" + "\t".join(c.replace("\n", " ") for c in TEMPLATE_HEAD) + "\n" + "\t".join(c.replace("\n", " ") for c in TEMPLATE_EXAMPLE) + "\n" + "\n".join(str(i + 1) + "\t" * (len(TEMPLATE_HEAD) - 1) for i in range(rows))
    return {"html": html, "text": text}


@app.get("/api/jira/template")
def api_jira_template():
    return jsonify(request_template())
