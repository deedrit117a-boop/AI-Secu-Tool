# app.py 에서 _include() 로 불러오는 부분 (app.py 와 같은 이름공간을 쓴다)
# ----------------------------------------------------------------- AWS 정보 조회 (AWS CLI 사용, 조회 전용)
# 메타 데이터(SG ID, 서브넷 이름/CIDR/VPC ID, NAT IP)를 AWS 에서 읽어 미리보기로 보여준다. AWS 에는 아무것도 만들거나 바꾸지 않는다:
# 아래 허용 목록의 describe/get 명령만 실행할 수 있다. 로그인(SSO)은 사용자가 브라우저에서 직접 승인한다.
AWS_READ_ALLOW = {("ec2", "describe-security-groups"), ("ec2", "describe-subnets"), ("ec2", "describe-vpcs"),
                  ("ec2", "describe-nat-gateways"), ("ec2", "describe-route-tables"), ("ec2", "describe-network-interfaces"),
                  ("sts", "get-caller-identity")}
REGION_MAP = {"apne1": "ap-northeast-1", "apne2": "ap-northeast-2", "apne3": "ap-northeast-3", "apse1": "ap-southeast-1",
              "apse2": "ap-southeast-2", "aps1": "ap-south-1", "use1": "us-east-1", "use2": "us-east-2", "usw1": "us-west-1",
              "usw2": "us-west-2", "euw1": "eu-west-1", "euw2": "eu-west-2", "euw3": "eu-west-3", "euc1": "eu-central-1",
              "eun1": "eu-north-1", "sae1": "sa-east-1", "cac1": "ca-central-1", "ape1": "ap-east-1", "ape2": "ap-east-2",
              "apse3": "ap-southeast-3", "apse4": "ap-southeast-4", "apse5": "ap-southeast-5", "aps2": "ap-south-2",
              "mes1": "me-south-1", "mec1": "me-central-1", "afs1": "af-south-1", "eus1": "eu-south-1", "eus2": "eu-south-2",
              "euc2": "eu-central-2", "il1": "il-central-1", "caw1": "ca-west-1"}
REGION_NAMES = {"ap-northeast-1": "도쿄", "ap-northeast-2": "서울", "ap-northeast-3": "오사카", "ap-southeast-1": "싱가포르",
                "ap-southeast-2": "시드니", "ap-south-1": "뭄바이", "ap-east-1": "홍콩", "us-east-1": "버지니아", "us-east-2": "오하이오",
                "us-west-1": "캘리포니아", "us-west-2": "오레곤", "eu-west-1": "아일랜드", "eu-central-1": "프랑크푸르트",
                "eu-west-2": "런던", "eu-west-3": "파리", "eu-north-1": "스톡홀름", "sa-east-1": "상파울루", "ca-central-1": "캐나다",
                "ap-east-2": "타이베이", "ap-south-2": "하이데라바드", "ap-southeast-3": "자카르타", "ap-southeast-4": "멜버른",
                "ap-southeast-5": "말레이시아", "me-south-1": "바레인", "me-central-1": "UAE", "af-south-1": "케이프타운",
                "eu-south-1": "밀라노", "eu-south-2": "스페인", "eu-central-2": "취리히", "il-central-1": "텔아비브", "ca-west-1": "캘거리"}


def aws_config_path():
    return os.environ.get("AWS_CONFIG_FILE") or os.path.join(os.path.expanduser("~"), ".aws", "config")


def aws_profiles():
    """~/.aws/config 의 프로필 이름 목록 (값은 읽지 않음)"""
    names = []
    try:
        with open(aws_config_path(), "r", encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                m = re.match(r"^\s*\[(?:profile\s+)?([^\]\s]+)\]\s*$", line)
                if m and not line.strip().startswith("[sso-session") and not line.strip().startswith("[services"):
                    names.append(m.group(1))
    except OSError:
        pass
    return names


def classify_aws_error(text):
    """AWS CLI 오류 -> (종류, 안내). login_needed: 로그인(SSO) 필요 / denied: 권한 없음 / profile_missing / other"""
    low = (text or "").lower()
    if "could not be found" in low and "profile" in low:
        return "profile_missing", "AWS 프로필을 찾을 수 없습니다. ~/.aws/config 의 프로필 이름을 확인하세요."
    if "certificate_verify_failed" in low or "ssl validation failed" in low:
        return "ssl_error", ("회사 보안 프로그램(SSL 검사, 예: Zscaler)의 인증서를 AWS CLI 가 신뢰하지 못해 접속하지 못했습니다. "
                             "회사 루트 인증서가 들어 있는 .pem 파일을 환경변수 AWS_CA_BUNDLE 로 지정해야 합니다.")
    if "invalidvpcid.notfound" in low or ("vpc" in low and "does not exist" in low):
        return "wrong_account", "선택한 AWS 프로필(계정)에 이 환경의 VPC 가 없습니다. 이 환경이 속한 계정의 프로필을 선택하세요."
    if any(k in low for k in ("token has expired", "sso session", "aws sso login", "expiredtoken", "unable to locate credentials",
                              "error loading sso token", "unauthorizedssotoken", "invalidclienttokenid", "security token included in the request",
                              "refresh failed", "the sso session associated")):
        return "login_needed", "AWS 자격증명이 없거나 만료되었습니다. 로그인(SSO) 승인이 필요합니다."
    if any(k in low for k in ("accessdenied", "unauthorizedoperation", "not authorized", "forbidden", "access denied")):
        return "denied", "이 프로필에는 조회 권한이 없습니다 (Access Denied). 로그인으로는 해결되지 않으니 AWS 권한을 요청하세요."
    return "other", "AWS 조회에 실패했습니다."


def aws_cli_present():
    return bool(shutil.which("aws"))


def aws_start_login(exe, profile):
    """aws sso login 시작 (테스트에서는 이 함수를 바꿔 실제 로그인 창이 열리지 않게 한다)"""
    subprocess.Popen([exe, "sso", "login", "--profile", profile], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


_AWS_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=8)


def aws_par(*fns):
    """서로 관계없는 AWS 조회를 동시에 실행하고 결과를 순서대로 돌려준다 (실패하면 첫 오류를 그대로 던짐)"""
    futs = [_AWS_POOL.submit(f) for f in fns]
    return [f.result() for f in futs]


AWS_CA_LOCK = threading.Lock()


def aws_ca_bundle_path():
    return os.path.join(DATA, "aws_ca_bundle.pem")      # 호출 시점에 읽음 (테스트가 DATA 를 바꿔 쓰므로)


def build_aws_ca_bundle():
    """AWS CLI 용 인증서 묶음을 만든다: 기본 인증서(certifi) + 이 PC(윈도우)가 이미 신뢰하는 루트 인증서(회사 보안 프로그램 인증서 포함).
    브라우저가 신뢰하는 것과 같은 기준이라 인증서 검증은 끄지 않는다. 만들 수 없으면 None."""
    with AWS_CA_LOCK:
        path = aws_ca_bundle_path()
        if os.path.exists(path):
            return path
        try:
            import ssl
            pems, seen = [], set()
            try:
                import certifi
                pems.append(open(certifi.where(), encoding="utf-8").read())
            except Exception:
                pass
            if not hasattr(ssl, "enum_certificates"):      # 윈도우가 아니면 시스템 저장소를 읽을 수 없음
                return None
            for store in ("ROOT", "CA"):
                for der, _enc, _trust in ssl.enum_certificates(store):
                    if der not in seen:
                        seen.add(der)
                        pems.append(ssl.DER_cert_to_PEM_cert(der))
            if len(pems) < 2:
                return None
            os.makedirs(DATA, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(pems))
            log_event("INFO", "AWS CLI 용 인증서 묶음을 만들었습니다 (%d개)" % len(pems))
            return path
        except Exception as e:
            log_event("WARN", "AWS 인증서 묶음 생성 실패: %r" % (e,))
            return None


def aws_exe():
    exe = shutil.which("aws")
    if not exe:
        raise ApiError("AWS CLI 가 설치되어 있지 않습니다. AWS CLI v2 를 설치한 뒤 다시 시도하세요 (https://aws.amazon.com/cli/).", 424, aws_error="cli_missing")
    return exe


def aws_run(profile, service, command, extra=None, region=None, timeout=90):
    if (service, command) not in AWS_READ_ALLOW:
        raise ApiError("허용되지 않는 AWS 명령입니다: %s %s (조회 명령만 사용할 수 있습니다)" % (service, command), 400)
    if not re.match(r"^[A-Za-z0-9_.\-@/]+$", profile or ""):
        raise ApiError("AWS 프로필 이름이 올바르지 않습니다")
    cmd = [aws_exe(), service, command, "--profile", profile, "--output", "json", "--no-cli-pager"]
    if region:
        cmd += ["--region", region]
    cmd += list(extra or [])
    used_bundle = []

    def run_once():
        env_vars = dict(os.environ, AWS_PAGER="")
        if os.path.exists(aws_ca_bundle_path()) and not os.environ.get("AWS_CA_BUNDLE"):
            env_vars["AWS_CA_BUNDLE"] = aws_ca_bundle_path()
            used_bundle.append(1)
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env=env_vars)
    try:
        p = run_once()
        if p.returncode != 0 and classify_aws_error(p.stderr + p.stdout)[0] == "ssl_error" and not used_bundle:
            if build_aws_ca_bundle():   # (다른 조회가 이미 만들었으면 그것을 사용)
                p = run_once()          # 이 PC 가 신뢰하는 인증서를 더해 한 번 다시 시도
    except subprocess.TimeoutExpired:
        raise ApiError("AWS 응답이 없어 중단했습니다 (%d초). 네트워크/VPN 을 확인하세요." % timeout, 504, aws_error="timeout")
    if p.returncode != 0:
        kind, msg = classify_aws_error(p.stderr + p.stdout)
        log_event("WARN", "AWS 조회 실패 profile=%s %s %s: %s" % (profile, service, command, (p.stderr or "").strip()[:300]))
        code = {"login_needed": 401, "denied": 403, "profile_missing": 404, "wrong_account": 422}.get(kind, 502)
        raise ApiError(msg, code, aws_error=kind, profile=profile, detail=(p.stderr or "").strip()[:400])
    try:
        return json.loads(p.stdout or "null")
    except ValueError:
        raise ApiError("AWS 응답을 해석하지 못했습니다", 502, aws_error="other")


def aws_scope(env):
    """sg_dir(aws/<계정폴더>/<...>/<리전코드>/...) 에서 계정 폴더와 리전을 짐작"""
    parts = [x for x in env["sg_dir"].strip("/").split("/") if x]
    if parts and parts[0] == "aws":
        parts = parts[1:]
    account = parts[0] if parts else ""
    region = ""
    for x in parts[1:5]:
        if x in REGION_MAP:
            region = REGION_MAP[x]
            break
        if re.match(r"^[a-z]{2}-[a-z]+-\d$", x):
            region = x
            break
    return account, region


def normalize_region(text):
    """리전 입력을 정리: 'ape1' 같은 짧은 코드는 ap-east-1 로, 이미 ap-east-1 형식이면 그대로. 알 수 없으면 ''"""
    t = (text or "").strip().lower()
    if t in REGION_MAP:
        return REGION_MAP[t]
    return t if re.match(r"^[a-z]{2}-[a-z]+-\d$", t) else ""


def aws_profile_key(env):
    return "%s|%s" % (env.get("group", ""), aws_scope(env)[0])


def suggest_profiles(env, profiles):
    account, _ = aws_scope(env)
    words = [w for w in re.split(r"[^a-z0-9]+", ("%s %s" % (env.get("group", ""), account)).lower()) if len(w) >= 3]
    scored = []
    for pr in profiles:
        low = pr.lower()
        sc = sum(2 for w in set(words) if w in low)
        if account and account.lower() in low:
            sc += 3
        if sc:
            scored.append((-sc, pr))
    return [pr for _, pr in sorted(scored)][:6]


def _tag(tags, key="Name"):
    for t in tags or []:
        if t.get("Key") == key:
            return t.get("Value", "")
    return ""


@app.get("/api/aws/profiles")
def api_aws_profiles():
    return jsonify({"profiles": aws_profiles(), "cli": aws_cli_present()})


@app.get("/api/env/<env_id>/aws/context")
def api_aws_context(env_id):
    env = get_env(env_id)
    profiles = aws_profiles()
    account, region = aws_scope(env)
    key = aws_profile_key(env)
    saved = (load_local().get("aws_profiles") or {}).get(key, "")
    return jsonify({"key": key, "account": account, "region": region, "saved": saved if saved in profiles else "",
                    "suggestions": suggest_profiles(env, profiles), "profiles": profiles, "cli": aws_cli_present(),
                    "profile_info": aws_profile_details(), "regions": [{"code": c, "name": n} for c, n in REGION_NAMES.items()]})


@app.post("/api/aws/profile-map")
def api_aws_profile_map():
    """이 PC 에서 (게임/플랫폼 그룹, 계정 폴더) 별로 쓸 AWS 프로필을 기억 (local.json — 개인 설정이라 공유/배포되지 않음)"""
    b = request.get_json() or {}
    key, profile = (b.get("key") or "").strip(), (b.get("profile") or "").strip()
    if not key or profile not in aws_profiles():
        raise ApiError("키와 ~/.aws/config 에 있는 프로필이 필요합니다")
    with CFG_LOCK:
        loc = load_local()
        loc.setdefault("aws_profiles", {})[key] = profile
        region = normalize_region(b.get("region") or "")
        if region:      # 경로에서 리전을 알 수 없는 환경은 마지막으로 성공한 리전을 기억해 비교 보고서에서 쓴다
            loc.setdefault("aws_regions", {})[key] = region
        write_json(LOCAL_PATH, loc)
    return jsonify({"ok": True})


@app.get("/api/aws/whoami")
def api_aws_whoami():
    """로그인 여부 확인 (sts get-caller-identity, 조회 전용)"""
    profile = request.args.get("profile", "")
    r = aws_run(profile, "sts", "get-caller-identity", timeout=40)
    return jsonify({"ok": True, "account": r.get("Account"), "arn": r.get("Arn")})


@app.post("/api/aws/login")
def api_aws_login():
    """aws sso login 을 시작한다 (브라우저가 열리고 사용자가 직접 승인). 이 서버는 승인 결과를 기다리지 않고, 화면이 whoami 로 확인한다."""
    profile = (request.get_json() or {}).get("profile", "")
    if profile not in aws_profiles():
        raise ApiError("~/.aws/config 에 없는 프로필입니다: %s" % profile, 404, aws_error="profile_missing")
    exe = aws_exe()
    aws_start_login(exe, profile)
    log_event("INFO", "aws sso login 시작 profile=%s" % profile)
    return jsonify({"ok": True, "message": "브라우저에서 AWS 로그인을 승인해 주세요."})


def aws_profile_accounts():
    """~/.aws/config 의 프로필별 SSO 계정 ID (sso_account_id). 같은 계정을 쓰는 프로필을 묶는 데만 사용 (자격증명은 읽지 않음)"""
    out, cur = {}, None
    try:
        with open(aws_config_path(), "r", encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                if re.match(r"^\s*\[", line):           # 새 구역 시작: 프로필이 아닌 구역([sso-session ...] 등)이면 값을 읽지 않는다
                    m = re.match(r"^\s*\[(?:profile\s+)?([^\]\s]+)\]\s*$", line)
                    cur = m.group(1) if m else None
                    if cur:
                        out[cur] = ""
                    continue
                m = re.match(r"^\s*sso_account_id\s*=\s*(\d+)", line)
                if m and cur:
                    out[cur] = m.group(1)
    except OSError:
        pass
    return out


def aws_profile_details():
    """프로필별 {계정 ID, 역할 이름} (~/.aws/config 의 sso_account_id / sso_role_name). 화면의 계정 검색에 사용"""
    out, cur = {}, None
    try:
        with open(aws_config_path(), "r", encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                if re.match(r"^\s*\[", line):
                    m = re.match(r"^\s*\[(?:profile\s+)?([^\]\s]+)\]\s*$", line)
                    cur = m.group(1) if m else None
                    if cur:
                        out[cur] = {"account_id": "", "role": ""}
                    continue
                m = re.match(r"^\s*(sso_account_id|sso_role_name)\s*=\s*(\S+)", line)
                if m and cur:
                    out[cur]["account_id" if m.group(1) == "sso_account_id" else "role"] = m.group(2)
    except OSError:
        pass
    return out


def sg_name_matches(aws_name, name):
    """AWS 의 SG 이름이 파일의 SG 이름과 같은지. 같거나, AWS 쪽이 앞에 환경 접두어를 더 붙이고/끝에 '-sg' 를 더 붙인 형태
    (예: 파일 'external-x' ↔ AWS 'ugc-sandbox-apne1-sip-external-x-sg')도 같은 것으로 본다"""
    a, n = (aws_name or "").lower(), (name or "").lower()
    if not a or not n:
        return False
    for tail in ("", "-sg", "_sg"):
        t = n + tail
        if a == t or (a.endswith(t) and a[-len(t) - 1] in "-_. "):
            return True
    return False


def sg_env_hint(env):
    """sg_dir 에서 리전 코드 다음 폴더 이름 (예: aws/x/apne1/ugc-sandbox/sg/... → 'ugc-sandbox'). 같은 계정에 환경이 여럿일 때 접두어로 구분하는 데 쓴다"""
    parts = [x for x in env["sg_dir"].strip("/").split("/") if x]
    for i, x in enumerate(parts[:-1]):
        if x in REGION_MAP or re.match(r"^[a-z]{2}-[a-z]+-\d$", x):
            return parts[i + 1].lower() if parts[i + 1].lower() not in ("sg", "sg_rule") else ""
    return ""


def aws_probe(profile, region, names, filters=("group-name",), loose=False):
    """이 프로필(계정)에서 이 환경의 SG 이름이 몇 개나 보이는지 확인 (조회 전용). -> (상태, 찾은 개수)
    loose=False: 이름이 정확히 같은 것만 (기존 방식). loose=True: 앞에 접두어/끝에 -sg 가 붙은 이름까지 (정확한 이름으로 못 찾았을 때만 사용)"""
    found = set()
    for flt in filters:
        vals = ["*" + n + t for n in names[:50] for t in ("", "-sg", "_sg")] if loose else list(names[:50])
        try:
            r = aws_run(profile, "ec2", "describe-security-groups", ["--filters", "Name=%s,Values=%s" % (flt, ",".join(vals)),
                        "--query", "SecurityGroups[].GroupName"], region, timeout=30)
        except ApiError as e:
            return (e.extra.get("aws_error") or "error"), 0
        got = [x for x in (r or []) if x]
        if loose:
            found.update(n for n in names if any(sg_name_matches(x, n) for x in got))
        else:
            found.update(got)
        if len(found) >= len(names):
            break
    return "ok", len(found)


def aws_detect(env, region, limit=40):
    """프로필을 자동으로 찾는다: 계정(sso_account_id)별로 대표 프로필 하나씩 이 환경의 SG 이름을 조회해 가장 많이 일치하는 계정을 고른다."""
    names = [x["name"] for x in list_sgs(env)]
    profiles = aws_profiles()
    accounts = aws_profile_accounts()
    sugg = suggest_profiles(env, profiles)
    saved = (load_local().get("aws_profiles") or {}).get(aws_profile_key(env), "")
    groups = {}
    for pr in profiles:
        groups.setdefault(accounts.get(pr) or ("name:" + pr), []).append(pr)

    def rank(pr):      # 대표 프로필: 저장된 것 > 추천 > 나머지
        return (0 if pr == saved else 1, sugg.index(pr) if pr in sugg else 99, pr)
    reps = sorted(((min(m, key=rank), acc, m) for acc, m in groups.items()), key=lambda x: rank(x[0]))[:limit]
    if not names:
        return {"best": None, "results": [], "note": "이 환경에 SG 파일이 없어 계정을 확인할 수 없습니다. 프로필을 직접 선택하세요.", "suggestions": sugg}
    results = []

    def run(wave, filters, loose=False):
        futs = [(_AWS_POOL.submit(aws_probe, rep, region, names, filters, loose), rep, acc, m) for rep, acc, m in wave]
        out = []
        for fut, rep, acc, m in futs:
            try:
                st, n = fut.result(timeout=120)
            except Exception:
                st, n = "error", 0
            out.append({"profile": rep, "account_id": acc if not acc.startswith("name:") else "", "status": st, "found": n,
                        "same_account": [x for x in m if x != rep][:6]})
        return out

    def pick(res):
        hit = [r for r in res if r["status"] == "ok" and r["found"] > 0]
        if not hit:
            return None
        top = max(r["found"] for r in hit)
        cands = [r for r in hit if r["found"] == top]
        return {**sorted(cands, key=lambda r: rank(r["profile"]))[0], "total": len(names), "ambiguous": len(cands) > 1}

    best = None
    # 저장된/추천 프로필이 앞에 오도록 정렬되어 있으므로, 앞쪽 몇 개를 먼저 동시에 확인하고 전부 찾았으면 나머지는 확인하지 않는다
    for wave in (reps[:6], reps[6:]):
        if not wave:
            continue
        results += run(wave, ("group-name",))
        best = pick(results)
        if best and best["found"] >= len(names):
            break
    if not best:       # 이름이 아니라 Name 태그로 붙은 SG 일 수 있어 로그인된 계정만 태그로 한 번 더 확인
        again = [(r["profile"], r.get("account_id") or "name:" + r["profile"], [r["profile"]] + r.get("same_account", [])) for r in results if r["status"] == "ok"][:16]
        if again:
            by_profile = {r["profile"]: r for r in results}
            for r2 in run(again, ("tag:Name",)):
                by_profile[r2["profile"]].update({"status": r2["status"], "found": r2["found"]})
            best = pick(results)
            if not best:   # 그래도 못 찾았으면 마지막으로 접두어/-sg 가 붙은 이름까지 느슨하게 확인 (정확한 이름으로 찾은 경우에는 실행하지 않음)
                for r2 in run(again, ("group-name",), True):
                    by_profile[r2["profile"]].update({"status": r2["status"], "found": r2["found"]})
                best = pick(results)
    return {"best": best, "results": results, "total": len(names),
            "login_needed": [r["profile"] for r in results if r["status"] == "login_needed"],
            "suggestions": sugg}


@app.post("/api/env/<env_id>/aws/detect")
def api_aws_detect(env_id):
    """AWS 프로필 자동 매칭 (읽기 전용): 로그인되어 있는 계정들 중 이 환경의 SG 가 보이는 계정을 찾는다"""
    env = get_env(env_id)
    if not aws_cli_present():
        raise ApiError("AWS CLI 가 설치되어 있지 않습니다.", 424, aws_error="cli_missing")
    region = normalize_region((request.get_json(silent=True) or {}).get("region")) or aws_scope(env)[1]
    if not region:
        raise ApiError("리전을 알 수 없어 자동으로 찾을 수 없습니다. 리전(예: ap-northeast-2 또는 apne2)을 입력하세요")
    res = aws_detect(env, region)
    if res.get("best"):
        with CFG_LOCK:           # 찾았으면 다음부터는 바로 쓰도록 이 PC 에 기억
            loc = load_local()
            loc.setdefault("aws_profiles", {})[aws_profile_key(env)] = res["best"]["profile"]
            write_json(LOCAL_PATH, loc)
    return jsonify(res)


def aws_sg_resource_ips(profile, region, vpc_ids):
    """SG 를 쓰고 있는 리소스(EC2/ALB/RDS/Lambda 등의 네트워크 인터페이스)의 IP.  -> ({SG ID: [IP...]}, 안내문구)
    네트워크 인터페이스 조회 권한이 없으면 이 정보만 빼고 나머지는 그대로 진행한다."""
    try:
        enis = aws_run(profile, "ec2", "describe-network-interfaces",
                       ["--filters", "Name=vpc-id,Values=" + ",".join(vpc_ids), "--query",
                        "NetworkInterfaces[].{ips:PrivateIpAddresses[].PrivateIpAddress,pub:Association.PublicIp,groups:Groups[].GroupId}"], region, timeout=120) or []
    except ApiError as e:
        if e.extra.get("aws_error") == "denied":
            return {}, "네트워크 인터페이스 조회 권한이 없어 리소스 IP 는 가져오지 못했습니다 (ec2:DescribeNetworkInterfaces)."
        raise
    out = {}
    for n in enis:
        ips = [x for x in (n.get("ips") or []) if x] + ([n["pub"]] if n.get("pub") else [])
        for g in n.get("groups") or []:
            bucket = out.setdefault(g, set())
            bucket.update(ips)
    key = lambda ip: tuple(int(p) for p in ip.split(".")) if re.match(r"^\d+\.\d+\.\d+\.\d+$", ip) else (999, ip)
    return {g: sorted(v, key=key) for g, v in out.items()}, ""


def _vpc_calls(profile, region, ids):
    """VPC 가 정해진 뒤 필요한 조회들 (서브넷, VPC 대역, NAT, 라우팅 테이블, 리소스 IP) — 서로 관계없어 동시에 실행할 수 있다"""
    flt = "Name=vpc-id,Values=" + ",".join(ids)
    return [
        lambda: aws_run(profile, "ec2", "describe-subnets", ["--filters", flt, "--query",
                        "Subnets[].{id:SubnetId,vpc:VpcId,cidr:CidrBlock,tags:Tags}"], region) or [],
        lambda: aws_run(profile, "ec2", "describe-vpcs", ["--vpc-ids"] + ids, region) or {},
        lambda: aws_run(profile, "ec2", "describe-nat-gateways", ["--filter", flt, "--query",
                        "NatGateways[].{id:NatGatewayId,state:State,ips:NatGatewayAddresses[].PublicIp}"], region) or [],
        lambda: aws_run(profile, "ec2", "describe-route-tables", ["--filters", flt, "--query",
                        "RouteTables[].{id:RouteTableId,vpc:VpcId,assoc:Associations[].{subnet:SubnetId,main:Main},routes:Routes[].{dest:DestinationCidrBlock,nat:NatGatewayId}}"], region) or [],
        lambda: aws_sg_resource_ips(profile, region, ids),
    ]


def aws_resolve(env, sgs, names, cur_vpcs):
    """파일의 SG 이름들을 AWS 의 SG 와 짝짓는다 -> ({이름: [AWS SG...]}, 환경의 VPC 들).
    정확히 같은 이름(또는 Name 태그)을 먼저 찾고, 없을 때만 접두어/-sg 가 다른 이름으로 찾는다."""
    by_name = {}
    for g in sgs:
        for nm in {g.get("name", ""), _tag(g.get("tags"))}:
            if nm:
                by_name.setdefault(nm.lower(), []).append(g)
    suffix_of = {}      # 파일 이름 → 접두어가 붙은 AWS 이름들 (정확히 같은 이름이 없을 때만 쓴다)

    def lookup(n):
        hit = by_name.get(n.lower(), [])
        if hit:
            return hit
        if n not in suffix_of:
            cand = [(k, g) for k, gs in by_name.items() if sg_name_matches(k, n) for g in gs]
            hint = sg_env_hint(env)
            if hint and len({g["id"] for _, g in cand}) > 1:    # 같은 계정의 다른 환경(sandbox / ugc-sandbox / ugc-live ...)은 폴더 이름 접두어로 거른다
                narrow = [(k, g) for k, g in cand if k.startswith(hint + "-")] or [(k, g) for k, g in cand if ("-" + hint + "-") in k]
                cand = narrow or cand
            suffix_of[n] = [g for _, g in cand]
        return suffix_of[n]
    # 환경의 VPC: 이미 메타에 적힌 VPC 가 있으면 그것, 없으면 이름이 겹치지 않고 찾아진 SG 들이 속한 VPC 중 가장 많은 것
    cnt = {}
    for n in names:
        hit = lookup(n)
        if len({h["vpc"] for h in hit}) == 1:
            cnt[hit[0]["vpc"]] = cnt.get(hit[0]["vpc"], 0) + 1
    vpcs = set(cur_vpcs) or ({max(cnt, key=cnt.get)} if cnt else set())
    hits = {}
    for n in names:
        hit = lookup(n)
        if vpcs:
            hit = [h for h in hit if h["vpc"] in vpcs] or hit
        hits[n] = hit
    return hits, vpcs


def aws_collect(env, profile, region):
    """AWS 에서 읽은 내용을 메타 데이터 형태의 '미리보기'로 정리 (저장은 화면이 사용자의 확인 뒤에 한다)"""
    em = (load_meta().get("envs") or {}).get(env["id"], {})
    cur_vpcs = {x.get("vpc_id") for x in (em.get("subnets") or []) if x.get("vpc_id")}
    sg_call = lambda: aws_run(profile, "ec2", "describe-security-groups",
                              ["--query", "SecurityGroups[].{id:GroupId,name:GroupName,vpc:VpcId,tags:Tags}"], region) or []
    if cur_vpcs:       # 메타에 VPC 가 이미 있으면 SG 조회와 나머지 조회를 한꺼번에 시작한다 (AWS CLI 는 한 번에 3~4초)
        got = aws_par(sg_call, *_vpc_calls(profile, region, sorted(cur_vpcs)))
        sgs, pre = got[0], got[1:]
    else:
        sgs, pre = sg_call(), None
    names = [x["name"] for x in list_sgs(env)]
    hits, vpcs = aws_resolve(env, sgs, names, cur_vpcs)
    rows = []
    for n in names:
        hit = hits[n]
        cur = ((em.get("sgs") or {}).get(n) or {}).get("sg_id", "")
        if not hit:
            rows.append({"name": n, "sg_id": "", "current": cur, "status": "missing"})
        elif len({h["id"] for h in hit}) > 1:
            rows.append({"name": n, "sg_id": "", "current": cur, "status": "ambiguous", "candidates": [h["id"] for h in hit][:5]})
        else:
            sid = hit[0]["id"]
            row = {"name": n, "sg_id": sid, "vpc_id": hit[0]["vpc"], "current": cur,
                   "status": "same" if cur == sid else ("new" if not cur else "diff")}
            if (hit[0].get("name") or "").lower() != n.lower() and _tag(hit[0].get("tags")).lower() != n.lower():
                row["aws_name"] = hit[0].get("name") or ""        # 접두어가 붙은 이름으로 찾은 경우 화면에 보여준다
            rows.append(row)
    out = {"profile": profile, "region": region, "vpc_ids": sorted(vpcs), "sgs": rows, "subnets": [], "vpc_cidrs": [], "nat_ips": []}
    if not vpcs:
        out["note"] = "이름이 일치하는 SG 를 AWS 에서 찾지 못해 VPC 를 정할 수 없어 서브넷/NAT 은 가져오지 않았습니다."
        return out
    ids = sorted(vpcs)
    if pre is None:
        pre = aws_par(*_vpc_calls(profile, region, ids))
    subnets, vinfo, nats, rts, (ips_by_sg, note) = pre
    nat_ip = {n["id"]: [ip for ip in (n.get("ips") or []) if ip] for n in nats if n.get("state") == "available"}
    main_rt, sub_rt = {}, {}
    for rt in rts:
        for a in rt.get("assoc") or []:
            if a.get("main"):
                main_rt[rt["vpc"]] = rt
            elif a.get("subnet"):
                sub_rt[a["subnet"]] = rt

    def nat_for(sn):
        rt = sub_rt.get(sn["id"]) or main_rt.get(sn["vpc"]) or {}
        for r in rt.get("routes") or []:
            if r.get("dest") == "0.0.0.0/0" and r.get("nat") in nat_ip:
                return ", ".join(nat_ip[r["nat"]])
        return "-"
    out["subnets"] = sorted(({"subnet_name": _tag(sn.get("tags")), "vpc_id": sn["vpc"], "ipv4_cidr": sn["cidr"], "nat_ip": nat_for(sn)}
                            for sn in subnets), key=lambda x: (x["vpc_id"], x["ipv4_cidr"]))
    out["vpc_cidrs"] = sorted({a["CidrBlock"] for v in (vinfo.get("Vpcs") or []) for a in (v.get("CidrBlockAssociationSet") or []) if a.get("CidrBlock")}
                              or {v["CidrBlock"] for v in (vinfo.get("Vpcs") or []) if v.get("CidrBlock")})
    out["nat_ips"] = sorted({ip for ips in nat_ip.values() for ip in ips})
    for row in out["sgs"]:
        row["ips"] = ips_by_sg.get(row.get("sg_id"), []) if row.get("sg_id") else []
    if note:
        out["note"] = note
    return out


@app.post("/api/env/<env_id>/aws/fetch")
def api_aws_fetch(env_id):
    """AWS 에서 이 환경의 SG ID / 서브넷 / NAT IP 를 읽어 미리보기로 돌려준다 (읽기 전용, 저장하지 않음)"""
    env = get_env(env_id)
    b = request.get_json() or {}
    profile = (b.get("profile") or "").strip()
    if not profile:
        raise ApiError("AWS 프로필을 선택하세요")
    raw_region = (b.get("region") or "").strip()
    region = normalize_region(raw_region) or ("" if raw_region else aws_scope(env)[1])
    if not region:
        raise ApiError(("리전 형식이 올바르지 않습니다: %s — " % raw_region if raw_region else "리전을 알 수 없습니다. ")
                       + "ap-east-1(홍콩), ap-northeast-1(도쿄), us-east-1(버지니아) 처럼 입력하거나 apne1, ape1 같은 짧은 코드를 쓰세요")
    return jsonify(aws_collect(env, profile, region))
