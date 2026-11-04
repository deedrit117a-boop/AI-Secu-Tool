"""Terraform SG ACL 자동화 Tool - Flask 백엔드.

공유 데이터(JSON): data/config.json (환경/경로 설정), data/meta.json (태그/SG ID/VPC/NAT)
개인 데이터(공유 금지): data/local.json (계정, GitLab 토큰)
"""
import base64
import concurrent.futures
import copy
import csv
import functools
import hashlib
import io
import ipaddress
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime
from urllib.parse import quote, urlparse

import requests
from flask import Flask, jsonify, request, send_from_directory, Response, g, has_request_context

BASE = os.path.dirname(os.path.abspath(__file__))
PARTS_DIR = os.path.join(BASE, "app_parts")


def _include(name):
    """app_parts/<name>.py 를 이 파일과 같은 이름공간에서 실행한다 (파일이 커져서 기능별로 나눈 것. 동작은 같다)"""
    path = os.path.join(PARTS_DIR, name + ".py")
    with open(path, encoding="utf-8") as f:
        exec(compile(f.read(), path, "exec"), globals())


def _code_mtime():
    """서버 코드(app.py + app_parts) 중 가장 늦게 바뀐 시각 - 서버 재시작 필요 여부 판단용"""
    t = os.path.getmtime(os.path.abspath(__file__))
    try:
        for n in os.listdir(PARTS_DIR):
            if n.endswith(".py"):
                t = max(t, os.path.getmtime(os.path.join(PARTS_DIR, n)))
    except OSError:
        pass
    return t
DATA = os.path.join(BASE, "data")
CONFIG_PATH = os.path.join(DATA, "config.json")
META_PATH = os.path.join(DATA, "meta.json")
LOCAL_PATH = os.path.join(DATA, "local.json")
LOCK = threading.Lock()

app = Flask(__name__, static_folder=os.path.join(BASE, "static"), static_url_path="/static")

DEFAULT_CONFIG = {
    "settings": {"host": "127.0.0.1", "port": 8080, "ssl_verify": True, "jira_url": "https://jira.smilegate.net"},
    "sites": {
        "platform": {"label": "플랫폼환경", "base_url": "https://git.sginfra.net"},
        "game": {"label": "게임환경", "base_url": "https://gitlab.game.playstove.com"},
    },
    # 동일 유형(kind)의 환경에 공통 적용되는 기본값. 환경별로 비어 있으면 이 값을 사용.
    "defaults": {
        "platform": {"project": "cloudcenter/cloud-multiverse", "repo_dir": "", "target_branch": "main",
                     "mr_type": "SG 정책 추가/변경/삭제"},
        "game": {"project": "", "target_branch": "main", "mr_type": "SG 정책 추가/변경/삭제"},
    },
    "environments": [],   # 처음 실행하면 비어 있고, 화면의 '시작하기' 안내에 따라 환경설정에서 추가한다
}

MR_TYPE = "SG 정책 추가/변경/삭제"   # MR 생성 시 고정
NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")
GAME_FILE_RE = re.compile(r"^(.+)-(ingress|egress)-rules\.json$")
RULE_KEYS = ["from_port", "to_port", "protocol", "cidr_blocks", "security_groups",
             "prefix_list_ids", "description"]


# ----------------------------------------------------------------- 파일 I/O
def read_json(path, default):
    for attempt in range(6):
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except FileNotFoundError:
            return default
        except (PermissionError, json.JSONDecodeError):
            if attempt == 5:   # 다른 요청이 파일을 교체하는 순간(Windows)에는 잠깐 읽기가 실패할 수 있어 재시도
                raise
            time.sleep(0.03 * (attempt + 1))


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with LOCK:
        tmp = "%s.%d.%d.tmp" % (path, os.getpid(), threading.get_ident())   # 요청마다 다른 임시 파일
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.write("\n")
        for attempt in range(8):   # Windows: 대상 파일을 다른 요청이 읽는 중이면 교체가 잠깐 거부될 수 있음
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 7:
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                    raise
                time.sleep(0.03 * (attempt + 1))


CFG_LOCK = threading.RLock()   # config/meta 를 읽고-고쳐-쓰는 요청들이 서로 덮어쓰지 않도록


def cfg_locked(fn):
    @functools.wraps(fn)
    def wrapper(*a, **k):
        with CFG_LOCK:
            return fn(*a, **k)
    return wrapper


def file_rev(path):
    """파일 내용의 짧은 해시 (화면이 가진 내용이 최신인지 확인하는 용도)"""
    try:
        with open(path, "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()[:12]
    except FileNotFoundError:
        return "0"


def check_rev(path):
    """화면이 보낸 X-Rev 가 현재 파일과 다르면 (다른 창/서버 작업으로 바뀐 것) 저장을 거부"""
    sent = request.headers.get("X-Rev")
    if sent and sent != file_rev(path):
        raise ApiError("설정이 다른 화면이나 서버 작업으로 먼저 변경되었습니다. 이 화면의 변경은 저장하지 않았습니다. 최신 내용을 불러온 뒤 다시 시도하세요.",
                       409, conflict=True, rev=file_rev(path))


# ---- 서버 로그 (data/app.log, 1MB 넘으면 app.log.1 로 교체). 토큰은 가려서 기록
LOG_LOCK = threading.Lock()


def scrub(text):
    try:
        loc = load_local()
        secrets = list((loc.get("tokens") or {}).values()) + [(loc.get("jira") or {}).get("token", "")]
    except Exception:
        secrets = []
    text = str(text)
    for t in secrets:
        if t and len(str(t)) >= 4:
            text = text.replace(str(t), "***")
    return text


def log_event(level, msg):
    try:
        with LOG_LOCK:
            path = os.path.join(DATA, "app.log")
            os.makedirs(DATA, exist_ok=True)
            if os.path.exists(path) and os.path.getsize(path) > 1_000_000:
                os.replace(path, path + ".1")
            with open(path, "a", encoding="utf-8") as f:
                f.write("%s [%s] %s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), level, scrub(msg)))
    except Exception:
        pass   # 로그 기록 실패가 요청을 망치지 않도록


def load_config():
    cfg = read_json(CONFIG_PATH, None)
    if cfg is None:
        write_json(CONFIG_PATH, DEFAULT_CONFIG)
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    return cfg


def load_meta():
    return read_json(META_PATH, {"envs": {}})


def load_local():
    return read_json(LOCAL_PATH, {"account": "", "tokens": {"game": "", "platform": ""}})


class ApiError(Exception):
    def __init__(self, msg, code=400, **extra):
        super().__init__(msg)
        self.code = code
        self.extra = extra


@app.errorhandler(ApiError)
def _api_error(e):
    if e.code >= 500:
        log_event("WARN", "%s %s -> %s %s" % (request.method, request.path, e.code, str(e).splitlines()[0] if str(e) else ""))
    return jsonify({"error": str(e), **e.extra}), e.code


@app.errorhandler(Exception)
def _unhandled(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e
    log_event("ERROR", "%s %s -> %r\n%s" % (request.method, request.path, e, traceback.format_exc()))
    return jsonify({"error": "서버 내부 오류가 발생했습니다: %s\n(자세한 내용은 환경설정의 '서버 로그 보기' 또는 data/app.log)" % str(e)[:200]}), 500


def resolve_repo_dir(path, project):
    """repo 경로가 저장소 자체가 아니라 상위 폴더(예: D:\\GIT\\Infra)여도 동작하도록 보정.
    - path/.git 이 있으면 path
    - path/<저장소명>/.git 이 있으면 그 하위 폴더
    - path 가 비어있지 않은 일반 폴더면 path/<저장소명> 에 clone
    - 그 외(없거나 빈 폴더)는 path 그대로 clone"""
    name = (project or "").strip("/").split("/")[-1]
    if not name or os.path.isdir(os.path.join(path, ".git")):
        return path
    sub = os.path.join(path, name)
    if os.path.isdir(os.path.join(sub, ".git")):
        return sub
    if os.path.isdir(path) and os.listdir(path):
        return sub
    return path


def _resolve_env(e, cfg):
    d = cfg["defaults"].get(e["kind"], {})
    r = dict(e)
    for k in ("project", "target_branch", "mr_type", "repo_dir"):
        r[k] = e.get(k) or d.get(k, "")
    if not r["repo_dir"] and r["project"]:
        # 경로를 따로 정하지 않았으면 이 프로그램 폴더 아래 repos/<프로젝트> 에 저장 (사용자 PC 마다 경로가 달라도 동작)
        r["repo_dir"] = os.path.join(BASE, "repos", r["project"].strip("/").replace("/", "__"))
    if not r["repo_dir"]:
        raise ApiError("repo 로컬 경로가 비어 있습니다 (환경 또는 유형 기본값에 입력)")
    r["repo_dir"] = resolve_repo_dir(r["repo_dir"], r["project"])
    r["site"] = cfg["sites"][e["kind"]]
    r["ssl_verify"] = cfg["settings"].get("ssl_verify", True)
    r["atlantis_dir"] = e.get("atlantis_dir") or os.path.dirname(e["sg_dir"].rstrip("/")).replace("\\", "/")
    return r


def get_env(env_id):
    cfg = load_config()
    for e in cfg["environments"]:
        if e["id"] == env_id:
            return _resolve_env(e, cfg)
    raise ApiError("환경을 찾을 수 없습니다: %s" % env_id, 404)


def sg_path(env):
    return os.path.join(env["repo_dir"], *env["sg_dir"].split("/"))


def check_name(name):
    if not name or not NAME_RE.match(name):
        raise ApiError("이름에는 영문/숫자/-/_/. 만 사용할 수 있습니다: %s" % name)


# ----------------------------------------------------------------- SG 파일 파서/라이터
def norm_rule(r, kind):
    sg = r.get("security_groups")
    if isinstance(sg, list):
        sg = ", ".join(sg)
    if sg is None or str(sg).strip().lower() in ("", "null", "none"):
        sg = ""
    proto = str(r.get("protocol", "")).strip()
    if proto != "-1":
        proto = proto.upper() if kind == "game" else proto.lower()

    def port(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    cidr = r.get("cidr_blocks") or []
    if isinstance(cidr, str):
        cidr = [c.strip() for c in re.split(r"[,\s;]+", cidr) if c.strip()]
    return {
        "from_port": port(r.get("from_port")), "to_port": port(r.get("to_port")),
        "protocol": proto, "cidr_blocks": list(cidr), "security_groups": str(sg).strip(),
        "prefix_list_ids": list(r.get("prefix_list_ids") or []),
        "description": r.get("description", "") or "",
    }


def dump_rule_for_file(r, kind):
    sg = r["security_groups"] or ("null" if kind == "game" else None)
    d = {"from_port": r["from_port"], "to_port": r["to_port"], "protocol": r["protocol"],
         "cidr_blocks": r["cidr_blocks"], "security_groups": sg,
         "prefix_list_ids": r["prefix_list_ids"], "description": r["description"]}
    return d


def dumps_game(rules):
    s = json.dumps(rules, ensure_ascii=False, indent=2)
    # 짧은 문자열 배열은 한 줄로 (기존 파일 양식과 동일: "cidr_blocks": ["10.0.0.1/32"])
    s = re.sub(r"\[\s*\n\s*([^\[\]]*?)\n\s*\]",
               lambda m: "[" + re.sub(r"\s*\n\s*", " ", m.group(1)) + "]", s)
    return s + "\n"


def read_file(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_text(path, text):
    """기존 파일의 줄바꿈(CRLF/LF)·마지막 개행 유무·BOM 을 그대로 유지해서 저장 (불필요한 diff 방지).
    새 파일은 LF + 마지막 개행."""
    eol, final_nl, bom = "\n", True, False
    if os.path.exists(path):
        with open(path, "rb") as f:
            old = f.read()
        if old:
            eol = "\r\n" if b"\r\n" in old else "\n"
            final_nl = old.endswith(b"\n")
            bom = old.startswith(b"\xef\xbb\xbf")
    body = text.replace("\r\n", "\n").rstrip("\n")
    if final_nl:
        body += "\n"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig" if bom else "utf-8", newline="") as f:
        f.write(body.replace("\n", eol))


def game_files(env, name):
    d = sg_path(env)
    return (os.path.join(d, "%s-ingress-rules.json" % name),
            os.path.join(d, "%s-egress-rules.json" % name))


def _is_list_file(path):
    """파일 내용이 배열([ ... ])로 시작하면 True (게임 방식의 입력/출력 분리 파일)"""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return f.read(512).lstrip()[:1] == "["
    except OSError:
        return False


def split_sg(env, name):
    """이 SG 가 '<이름>-ingress-rules.json' / '<이름>-egress-rules.json' 두 파일 방식이면 True.
    게임 환경은 항상 이 방식이고, 플랫폼 환경은 폴더에 이런 파일만 있는 SG 가 섞여 있을 수 있다."""
    if env["kind"] == "game":
        return True
    if os.path.exists(os.path.join(sg_path(env), name + ".json")):
        return False
    return any(os.path.exists(p) for p in game_files(env, name))


def sg_files(env, name):
    return list(game_files(env, name)) if split_sg(env, name) else [os.path.join(sg_path(env), name + ".json")]


def list_sgs(env):
    d = sg_path(env)
    if not os.path.isdir(d):
        return []
    names = {}
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".json"):
            continue
        m = GAME_FILE_RE.match(fn)
        if env["kind"] == "game":
            if m:
                names.setdefault(m.group(1), []).append(fn)
        elif m and _is_list_file(os.path.join(d, fn)):      # 플랫폼 폴더 안의 게임 방식(배열) 파일 → 입력/출력을 한 SG 로 묶음
            names.setdefault(m.group(1), []).append(fn)
        else:
            names.setdefault(fn[:-5], []).append(fn)
    out = []
    for n, files in names.items():
        try:
            sg = _cached_sg(env, n)
            cnt = {"ingress": len(sg["ingress"]), "egress": len(sg["egress"])}
        except Exception as exc:
            log_event("WARN", "SG 파일을 읽지 못했습니다 %s/%s: %r" % (env.get("id"), n, exc))
            cnt = {"ingress": -1, "egress": -1}
        out.append({"name": n, "files": files, **cnt})
    return out


def load_sg(env, name):
    check_name(name)
    kind = env["kind"]
    if split_sg(env, name):
        kind = "game"          # 파일 방식과 규칙 표기(대문자 프로토콜, "null")는 파일을 따른다
        res = {}
        for direction, p in zip(("ingress", "egress"), game_files(env, name)):
            res[direction] = [norm_rule(r, kind) for r in (read_file(p) if os.path.exists(p) else [])]
        if not any(os.path.exists(p) for p in game_files(env, name)):
            raise ApiError("SG 파일이 없습니다: %s" % name, 404)
        return res
    p = os.path.join(sg_path(env), name + ".json")
    if not os.path.exists(p):
        raise ApiError("SG 파일이 없습니다: %s" % name, 404)
    data = read_file(p)
    if not isinstance(data, dict):
        raise ApiError("지원하지 않는 SG 파일 형식입니다 (ingress/egress 항목이 있는 객체여야 함): %s" % os.path.basename(p), 422)
    return {k: [norm_rule(r, kind) for r in data.get(k, [])] for k in ("ingress", "egress")}


def save_sg(env, name, sg):
    invalidate_status(env)
    check_name(name)
    kind = "game" if split_sg(env, name) else env["kind"]
    rules = {}
    for k in ("ingress", "egress"):
        rules[k] = []
        for r in sg.get(k, []):
            n = norm_rule(r, kind)
            if n["security_groups"] and n["cidr_blocks"]:
                raise ApiError("SG ID와 IP(CIDR)는 동시에 지정할 수 없습니다: %s" % n["description"])
            rules[k].append(dump_rule_for_file(n, kind))  # IP 규칙은 security_groups = null
    targets = sg_files(env, name)
    undo_snapshot(env, targets, name)    # 되돌리기용: 바꾸기 직전의 파일 내용
    if kind == "game":
        for direction, p in zip(("ingress", "egress"), game_files(env, name)):
            write_text(p, dumps_game(rules[direction]))
    else:
        write_text(targets[0], json.dumps(rules, ensure_ascii=False, indent=4) + "\n")


def file_name_for(env, resource):
    """신규 SG 이름: 플랫폼은 리소스만, 게임은 접두어(게임명-환경) + 리소스 + -sg"""
    if env["kind"] == "game":
        return "%s%s-sg" % (env.get("file_prefix", ""), resource)
    return resource


# ----------------------------------------------------------------- CSV
RULE_CSV_COLS = ["direction", "protocol", "from_port", "to_port", "source_type", "source", "description"]


def rules_to_csv(sg):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(RULE_CSV_COLS)
    for direction in ("ingress", "egress"):
        for r in sg[direction]:
            if r["security_groups"]:
                st, src = "sg", r["security_groups"]
            else:
                st, src = "cidr", ",".join(r["cidr_blocks"])
            w.writerow([direction, r["protocol"], r["from_port"], r["to_port"], st, src, r["description"]])
    return "\ufeff" + buf.getvalue()


def csv_to_rules(text, kind):
    rd = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    out = {"ingress": [], "egress": []}
    for i, row in enumerate(rd, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        direction = row.get("direction", "ingress").lower()
        if direction not in out:
            raise ApiError("CSV %d행: direction은 ingress/egress 이어야 합니다" % i)
        src = row.get("source", "")
        st = (row.get("source_type") or ("sg" if src.startswith("sg-") else "cidr")).lower()
        rule = {"from_port": row.get("from_port") or 0, "to_port": row.get("to_port") or row.get("from_port") or 0,
                "protocol": row.get("protocol") or "tcp", "description": row.get("description", "")}
        if st == "sg":
            rule["security_groups"] = src
        else:
            rule["cidr_blocks"] = src
        out[direction].append(norm_rule(rule, kind))
    return out


# ----------------------------------------------------------------- Git
def auth_args(env):
    tok = load_local().get("tokens", {}).get(env["kind"], "")
    if not tok:
        return []
    user = load_local().get("account", "").strip() or "oauth2"
    b = base64.b64encode(("%s:%s" % (user, tok)).encode()).decode()
    return ["-c", "http.extraHeader=Authorization: Basic %s" % b]


def run_git(env, *args, cwd=None, auth=False, check=True, strip=True):
    cmd = ["git"]
    if not env["ssl_verify"]:
        cmd += ["-c", "http.sslVerify=false"]
    if auth:
        cmd += auth_args(env)
    cmd += list(args)
    p = subprocess.run(cmd, cwd=cwd or env["repo_dir"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    out = mask_token(env, p.stdout + p.stderr)
    out = out.strip() if strip else out
    if check and p.returncode != 0:
        hint = friendly_git_error(out)
        if hint.startswith("저장소를 찾을 수") and not load_local().get("tokens", {}).get(env["kind"], ""):
            hint += (" 현재 %s 토큰이 입력되어 있지 않아 로그인 없이 접속했습니다. 비공개 저장소는 토큰이 없으면 '없음'으로 보이므로, "
                     "환경설정에서 토큰을 입력한 뒤 다시 시도하세요." % env["site"]["label"])
        raise ApiError(("%s\n\n" % hint if hint else "") + "git %s 실패:\n%s" % (args[0], out), 500, git_hint=hint)
    return out


def friendly_git_error(out):
    """git 원문 오류를 원인과 조치로 바꿔 알려준다 (없으면 빈 문자열)"""
    low = out.lower()
    if re.search(r"authentication failed|http basic: access denied|invalid username or password|could not read username|returned error: 40[13]", low):
        return "GitLab 인증에 실패했습니다 (API 토큰 만료 또는 권한 없음). 환경설정에서 계정과 API 토큰을 확인하세요."
    if "ssl certificate problem" in low or "self-signed certificate" in low:
        return "SSL 인증서 오류입니다. 환경설정의 'SSL 인증서 검증'을 끄거나 사내 인증서를 설치하세요."
    if re.search(r"could not resolve host|failed to connect|connection timed out|timed out|network is unreachable|connection refused", low):
        return "GitLab 서버에 연결하지 못했습니다. 네트워크/VPN 연결을 확인하세요."
    if "repository" in low and "not found" in low:
        return "저장소를 찾을 수 없습니다. GitLab 프로젝트 경로와 접근 권한을 확인하세요."
    return ""


def mask_token(env, text):
    tok = load_local().get("tokens", {}).get(env["kind"], "")
    return text.replace(tok, "***") if tok else text


def clone_url(env, with_auth=False):
    """https://[계정명]:[api키]@host/project.git (with_auth=True) 또는 인증정보 없는 URL"""
    if not env["project"]:
        raise ApiError("환경설정에 GitLab 프로젝트 경로가 비어 있습니다")
    path = "%s/%s.git" % (env["site"]["base_url"].rstrip("/"), env["project"].strip("/"))
    if not with_auth:
        return path
    loc = load_local()
    tok, acct = loc.get("tokens", {}).get(env["kind"], ""), loc.get("account", "").strip()
    if env["kind"] == "game" and not tok:
        return path  # 게임환경은 토큰 없이 clone 가능
    if not tok or not acct:
        raise ApiError("환경설정에서 계정과 %s GitLab 토큰을 먼저 입력하세요" % env["site"]["label"])
    scheme, rest = path.split("://", 1)
    return "%s://%s:%s@%s" % (scheme, quote(acct, safe=""), quote(tok, safe=""), rest)


def clean_branch_suffix(text):
    """브랜치 이름 뒤에 붙일 문자: 공백은 _ 로 바꾸고, 글자/숫자/_ . - 만 남긴다 (git 브랜치 이름 규칙에 맞게)"""
    t = re.sub(r"\s+", "_", (text or "").strip())
    t = re.sub(r"[^\w.\-]", "", t)
    t = re.sub(r"\.{2,}", ".", t).strip("._-")
    if t.lower().endswith(".lock"):
        t = t[:-5].strip("._-")
    if (text or "").strip() and not t:
        raise ApiError("브랜치에 붙일 문자에 사용할 수 있는 글자(영문/숫자/한글/_ . -)가 없습니다")
    return t[:40]


def make_branch_name(env, ticket, suffix=""):
    acct = load_local().get("account", "").strip()
    if not acct:
        raise ApiError("환경설정에서 계정(branch 접두어)을 먼저 입력하세요")
    if not re.match(r"^[A-Za-z0-9\-_]+$", ticket or ""):
        raise ApiError("티켓번호 형식이 올바르지 않습니다 (예: ISRIR-12345)")
    base = "%s/%s_%s" % (acct, datetime.now().strftime("%y%m%d"), ticket)
    suffix = clean_branch_suffix(suffix)
    if suffix:
        base += "_" + suffix
    existing = set()
    for line in run_git(env, "branch", "-a", "--format=%(refname:short)").splitlines():
        existing.add(re.sub(r"^origin/", "", line.strip()))
    for line in run_git(env, "ls-remote", "--heads", "origin", auth=True).splitlines():
        existing.add(line.split("refs/heads/", 1)[-1].strip())
    if base not in existing:
        return base
    n = 1
    while "%s_%02d" % (base, n) in existing:
        n += 1
    return "%s_%02d" % (base, n)


def scope_paths(env):
    """커밋 대상 범위: 같은 저장소를 쓰는 모든 환경의 sg_rule 폴더"""
    root = os.path.normcase(os.path.abspath(env["repo_dir"]))
    paths = set()
    for e in load_config()["environments"]:
        try:
            x = get_env(e["id"])
        except ApiError:
            continue
        if os.path.normcase(os.path.abspath(x["repo_dir"])) == root and os.path.isdir(os.path.join(x["repo_dir"], *x["sg_dir"].strip("/").split("/"))):
            paths.add(x["sg_dir"].strip("/"))   # 저장소에 실제로 있는 폴더만 (없는 경로를 pathspec 으로 넘기면 git add 가 실패함)
    return sorted(paths) or [env["sg_dir"].strip("/")]


def split_changes(files, scope):
    """변경 파일을 (범위 안, 범위 밖) 으로 분리"""
    def inside(p):
        p = p.strip('"').replace("\\", "/")
        return any(p == s or p.startswith(s + "/") for s in scope)
    return [f for f in files if inside(f["path"])], [f for f in files if not inside(f["path"])]


def require_work_branch(env):
    """main/master/기본 브랜치/detached 상태에서는 SG 파일 수정을 막는다 (X-Allow-Main: 1 헤더로 해제)"""
    if request.headers.get("X-Allow-Main") == "1" or not os.path.isdir(os.path.join(env["repo_dir"], ".git")):
        return
    b = run_git(env, "rev-parse", "--abbrev-ref", "HEAD", check=False).strip()
    if b in ("main", "master", "HEAD", env["target_branch"] or "main"):
        raise ApiError("작업 브랜치가 아닙니다 (현재: %s). '작업' 탭에서 브랜치를 먼저 생성하세요" % b, 409, need_branch=True, branch=b)


_STATUS_CACHE = {}
STATUS_TTL = 1.5   # 초: 화면이 여러 곳에서 연달아 상태를 물어도 git 을 한 번만 실행


def _status_key(env):
    return os.path.normcase(os.path.abspath(env["repo_dir"]))


_CHANGED_CACHE = {}


def invalidate_status(env=None):
    if env is None:
        _STATUS_CACHE.clear()
        _CHANGED_CACHE.clear()
    else:
        _STATUS_CACHE.pop(_status_key(env), None)
        _CHANGED_CACHE.pop(_status_key(env), None)


_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=4)


def par(*fns):
    """서로 관계없는 git 호출(프로세스 실행이 느린 Windows 에서 효과가 큼)을 동시에 실행하고 결과를 순서대로 반환"""
    futs = [_POOL.submit(f) for f in fns]
    return [f.result() for f in futs]


def git_status(env, fresh=False):
    """저장소 상태 (브랜치/변경 파일). 화면 표시용은 짧게 캐시, push/MR/브랜치 준비 같은 결정에는 fresh=True"""
    key = _status_key(env)
    hit = _STATUS_CACHE.get(key)
    if not fresh and hit and time.time() - hit[0] < STATUS_TTL:
        return copy.deepcopy(hit[1])
    res = _git_status_raw(env)
    _STATUS_CACHE[key] = (time.time(), copy.deepcopy(res))
    return res


def _git_status_raw(env):
    if not os.path.isdir(os.path.join(env["repo_dir"], ".git")):
        return {"cloned": False}
    branch, porcelain = par(lambda: run_git(env, "rev-parse", "--abbrev-ref", "HEAD"),
                            lambda: run_git(env, "status", "--porcelain", "-uall", strip=False))
    files = []
    for line in porcelain.splitlines():
        code, path = line[:2], line[3:]
        files.append({"path": path, "state": "new" if "?" in code or "A" in code else
                      "deleted" if "D" in code else "modified"})
    return {"cloned": True, "branch": branch, "files": files,
            "is_new": any(f["state"] == "new" for f in files)}


# ----------------------------------------------------------------- GitLab / Atlantis
def gl(env, method, path, **kw):
    tok = load_local().get("tokens", {}).get(env["kind"], "")
    if not tok:
        raise ApiError("환경설정에서 %s GitLab 토큰을 입력하세요" % env["site"]["label"])
    url = "%s/api/v4%s" % (env["site"]["base_url"].rstrip("/"), path)
    try:
        r = requests.request(method, url, headers={"PRIVATE-TOKEN": tok}, timeout=30,
                             verify=env["ssl_verify"], **kw)
    except requests.RequestException as e:
        raise ApiError("GitLab(%s)에 연결하지 못했습니다. 네트워크/VPN 연결을 확인하세요: %s" % (env["site"]["base_url"], str(e).replace(tok, "***")[:160]), 502)
    if r.status_code == 401:
        raise ApiError("GitLab API 인증에 실패했습니다 (API 토큰 만료 또는 권한 없음). 환경설정에서 토큰을 확인하세요.", 502, auth_failed=True)
    if r.status_code == 403:
        raise ApiError("GitLab API 권한이 부족합니다 (토큰 scope 또는 프로젝트 권한 확인): %s %s" % (method, path), 502)
    if r.status_code >= 400:
        raise ApiError("GitLab API %s %s -> %s: %s" % (method, path, r.status_code, r.text[:500]), 502)
    return r.json()


def pid(env):
    return quote(env["project"].strip("/"), safe="")


def atlantis_errors(body):
    """실제 오류 표식만 찾는다 (규칙 설명 등에 'error' 단어가 있어도 오류로 보지 않음)"""
    errs = []
    for ln in body.splitlines():
        s = ln.strip().lstrip("│|").strip()
        if re.match(r"^(\*\*)?(Plan|Apply) (Error|Failed)", s, re.I) or s.startswith("Error:") \
                or re.search(r"exit status [1-9]\d*\s*$", s):
            errs.append(s[:140])
    return errs


def plan_numbers(body):
    m = re.search(r"Plan:\s*(\d+) to add,\s*(\d+) to change,\s*(\d+) to destroy", body)
    add, chg, des = map(int, m.groups()) if m else (0, 0, 0)
    replace = len(re.findall(r"^\s*#.*must be replaced", body, re.M))
    return {"found": bool(m), "add": add, "change": chg, "destroy": des, "replace": replace}


RES_CHG_RE = re.compile(r"^\s*#\s+(\S+)\s+(will be created|will be destroyed|will be updated in-place|must be replaced|will be replaced)", re.M)
RES_KIND = {"will be created": "created", "will be destroyed": "destroyed", "will be updated in-place": "updated", "must be replaced": "replaced", "will be replaced": "replaced"}


def plan_impact(body):
    """plan 결과 글에서 리소스 주소별로 만들기/변경/삭제/교체를 모은다 (apply 전에 범위를 확인하기 위함)"""
    out = {"created": [], "updated": [], "destroyed": [], "replaced": []}
    for m in RES_CHG_RE.finditer(body or ""):
        lst = out[RES_KIND[m.group(2)]]
        if m.group(1) not in lst and len(lst) < 200:
            lst.append(m.group(1))
    return out


def _squash(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def plan_checks(rec, targets=None, expect=None):
    """자동 apply 조건 검사. 항목마다 {id, label, ok, block(참이면 통과해야 apply), detail}"""
    n = rec.get("plan") or {}
    imp = rec.get("impact") or {}
    out = []

    def chk(i, label, ok, block=True, detail=""):
        out.append({"id": i, "label": label, "ok": bool(ok), "block": block, "detail": detail})
    chk("plan", "plan 이 오류 없이 끝남", rec.get("state") in ("ok", "warn") and bool(n.get("found")), True, "상태 %s" % (rec.get("state") or "없음"))
    chk("destroy", "삭제·교체가 없음", not (n.get("destroy") or n.get("replace")), True, "삭제 %d / 교체 %d" % (n.get("destroy", 0), n.get("replace", 0)))
    chk("change", "변경할 내용이 있음", (n.get("add", 0) + n.get("change", 0)) > 0, True, "추가 %d / 변경 %d" % (n.get("add", 0), n.get("change", 0)))
    addrs = [a for k in ("created", "updated", "destroyed", "replaced") for a in imp.get(k, [])]
    keys = [_squash(t) for t in (targets or []) if len(_squash(t)) >= 3]
    if addrs and keys:
        hit = [a for a in addrs if any(k in _squash(a) for k in keys)]
        miss = [a for a in addrs if a not in hit]
        if hit and miss:
            chk("scope", "변경이 대상 SG 안에서만 일어남", False, True, "대상이 아닌 리소스 %d개: %s" % (len(miss), ", ".join(miss[:3])))
        elif hit:
            chk("scope", "변경이 대상 SG 안에서만 일어남", True, True, "리소스 %d개 모두 대상 SG" % len(hit))
        else:
            chk("scope", "리소스 이름으로 대상 SG 를 확인함", False, False, "리소스 이름에서 대상 SG 를 찾지 못했습니다 (확인 불가 — 막지는 않음)")
    if expect:
        chk("expect", "추가하려던 규칙 %d건" % expect, True, False, "plan 추가 %d / 변경 %d" % (n.get("add", 0), n.get("change", 0)))
    return out


def classify_atlantis_failure(body, errs):
    """실패 원인 분류 -> (kind, 안내 문구). kind: branch_missing / clone_auth / lock / timeout / tf_error / unknown"""
    low = body.lower()
    if "not found in upstream origin" in low or ("remote branch" in low and "not found" in low):
        return "branch_missing", "MR 소스 브랜치가 원격에 없습니다. '3. Commit / Push'로 push 한 뒤 plan 을 다시 실행하세요."
    if re.search(r"authentication failed|could not read username|permission denied|access denied", low):
        return "clone_auth", "Atlantis 가 저장소에 접근하지 못했습니다 (인증/권한). 잠시 후 다시 시도하고, 계속되면 Atlantis 관리자에게 문의하세요."
    if "locked by" in low or "lock" in low and "unapplied plan" in low:
        return "lock", "다른 MR/plan 이 같은 프로젝트를 잠그고 있습니다. 해당 MR 에서 apply 하거나 'atlantis unlock' 으로 잠금을 푼 뒤 plan 을 다시 실행하세요."
    if "timed out" in low or "timeout" in low or "context deadline exceeded" in low:
        return "timeout", "시간이 초과되었습니다. 잠시 후 plan 을 다시 실행하세요."
    if any(e.startswith("Error:") for e in errs) or "terraform" in low:
        return "tf_error", "Terraform 오류입니다. 아래 오류 내용을 확인해 규칙을 고친 뒤 Commit/Push 하고 plan 을 다시 실행하세요."
    return "unknown", "원문을 확인하세요. 일시적인 문제일 수 있으니 plan 을 다시 실행해 볼 수 있습니다."


# MR 을 만들면 Atlantis 가 자동으로 plan(autoplan)을 시작한다. 그 사이에 우리가 plan 명령을 보내면
# Atlantis 가 "currently locked for this pull request by plan ... try again" 이라고 거절하는데, 이것은 오류가 아니라
# '이미 plan 이 돌고 있으니 끝날 때까지 기다리라'는 뜻이다. 이 안내 댓글은 결과로 보지 않고 먼저 돌던 plan 의 결과를 기다린다.
ATLANTIS_BUSY_RE = re.compile(r"is currently locked for this pull request by|wait until the previous command is complete", re.I)


def is_atlantis_busy_note(body):
    return bool(ATLANTIS_BUSY_RE.search(body or ""))


def analyze_atlantis(body, action):
    low = body.lower()
    errs = atlantis_errors(body)
    if errs:
        kind, hint = classify_atlantis_failure(body, errs)
        return {"state": "error", "headline": "❌ 오류 %d건: %s" % (len(errs), errs[0][:80]), "errors": errs, "kind": kind, "hint": hint}
    if "locked by" in low and "unapplied plan" in low:
        kind, hint = classify_atlantis_failure(body, [])
        return {"state": "warn", "headline": "🔒 다른 MR/plan 에 의해 잠겨 있습니다. 원문을 확인하세요", "kind": "lock", "hint": hint}
    if action == "plan":
        n = plan_numbers(body)
        if n["found"]:
            head = "Plan: 추가 %d / 변경 %d / 삭제 %d" % (n["add"], n["change"], n["destroy"])
            imp = plan_impact(body)
            if n["replace"]:
                return {"state": "warn", "headline": "⚠️ 교체(삭제 후 재생성) %d건 포함 - 확인 필요. %s" % (n["replace"], head), "plan": n, "impact": imp}
            if n["destroy"]:
                return {"state": "warn", "headline": "⚠️ 삭제 포함 - 확인 필요. " + head, "plan": n, "impact": imp}
            return {"state": "ok", "headline": "✅ 이상 없음. " + head, "plan": n, "impact": imp}
        if "no changes" in low:
            return {"state": "warn", "headline": "⚠️ 변경 사항 없음 (No changes)", "plan": n}
        return {"state": "warn", "headline": "⚠️ 결과를 판별할 수 없습니다. 원문을 확인하세요", "kind": "unknown", "hint": "원문을 확인하세요. plan 을 다시 실행해 볼 수 있습니다."}
    if "apply complete" in low or "applied" in low or "ran apply" in low:
        return {"state": "ok", "headline": "✅ Apply 완료"}
    return {"state": "warn", "headline": "⚠️ 결과를 판별할 수 없습니다. 원문을 확인하세요"}


# ---- plan 기록: apply 전에 "같은 MR 커밋에서 성공한 plan" 이 있었는지 확인하기 위한 런타임 기록
PLANS_PATH = os.path.join(DATA, "plans.json")


def plan_key(env, iid):
    return "%s|%s|%s|%s" % (env["site"]["base_url"], env["project"], iid, env["atlantis_dir"])


def plan_get(env, iid):
    return read_json(PLANS_PATH, {}).get(plan_key(env, iid))


def plan_put(env, iid, rec):
    plans = read_json(PLANS_PATH, {})
    cur = plans.get(plan_key(env, iid), {})
    cur.update(rec)
    plans[plan_key(env, iid)] = cur
    # 오래된 기록 정리 (최근 200개)
    if len(plans) > 200:
        for k in sorted(plans, key=lambda x: plans[x].get("ts", 0))[:len(plans) - 200]:
            plans.pop(k, None)
    write_json(PLANS_PATH, plans)


def mr_sha(mr):
    return mr.get("sha") or (mr.get("diff_refs") or {}).get("head_sha") or ""


def apply_gate(env, iid, mr, confirm_destroy):
    """apply 가능 여부 검사. (가능하면 None / 불가하면 (사유, need_confirm, 요약))"""
    rec = plan_get(env, iid)
    if not rec:
        return "이 MR(!%s)에서 실행한 atlantis plan 결과가 없습니다. 먼저 plan 을 실행하고 결과를 확인하세요" % iid, False, None
    if rec.get("state") == "pending":
        return "plan 결과를 아직 받지 못했습니다. plan 결과가 나온 뒤에 apply 하세요", False, None
    if rec.get("state") == "error":
        return "마지막 plan 이 실패했습니다. 오류를 해결하고 plan 을 다시 실행하세요", False, None
    if rec.get("applied"):
        return "이미 apply 했습니다. 규칙을 바꾸었다면 plan 을 다시 실행하세요", False, None
    if rec.get("sha") and rec["sha"] != mr_sha(mr):
        return "마지막 plan 이후 MR 에 새 커밋이 있습니다. plan 을 다시 실행해서 결과를 확인하세요", False, None
    n = rec.get("plan") or {}
    if n and not (n.get("add") or n.get("change") or n.get("destroy") or n.get("replace")):
        return "plan 결과에 변경 사항이 없습니다. apply 할 내용이 없습니다", False, None
    if (n.get("destroy") or n.get("replace")) and not confirm_destroy:
        return ("plan 에 삭제 %d건 / 교체 %d건이 포함되어 있습니다. 확인이 필요합니다" % (n.get("destroy", 0), n.get("replace", 0)), True, n)
    return None




# ----------------------------------------------------------------- 라우트: 설정
@app.route("/")
def index():
    # 화면 파일(css/js)은 버전을 주소에 붙여 내려보낸다 (버전이 바뀌면 브라우저가 새 파일을 받음)
    with open(os.path.join(app.static_folder, "index.html"), encoding="utf-8") as f:
        html = f.read().replace("__V__", VERSION)
    resp = Response(html, mimetype="text/html")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/api/config")
def api_config():
    loc = load_local()
    masked = {k: bool(v) for k, v in loc.get("tokens", {}).items()}
    j = jira_settings()
    jira = {"base_url": j["base_url"], "auth": j["auth"], "user": j["user"], "ssl_verify": j["ssl_verify"],
            "token_set": bool(j["token"]), "enabled": bool(j["base_url"] and j["token"])}
    return jsonify({"config": load_config(), "rev": file_rev(CONFIG_PATH), "today": datetime.now().strftime("%y%m%d"),
                    "account": loc.get("account", ""), "token_set": masked, "jira": jira,
                    "paths": {"config": CONFIG_PATH, "meta": META_PATH, "local": LOCAL_PATH}})


@app.put("/api/config")
@cfg_locked
def api_config_put():
    check_rev(CONFIG_PATH)
    cfg = request.get_json()
    for e in cfg.get("environments", []):
        if not e.get("id") or not e.get("kind") in ("game", "platform"):
            raise ApiError("환경에는 id와 kind(game/platform)가 필요합니다")
    pres = cfg.get("presets", [])
    if not isinstance(pres, list) or any(not isinstance(x, dict) or not str(x.get("name", "")).strip() or not isinstance(x.get("ips", []), list) for x in pres):
        raise ApiError("프리셋 형식이 올바르지 않습니다 (이름과 IP 목록 필요)")
    for x in pres:
        for ip in x.get("ips", []):
            if _net(ip) is None:
                raise ApiError("프리셋 '%s' 의 IP/CIDR 형식이 올바르지 않습니다: %s" % (x["name"], ip))
    seen_ids, dup = set(), set()
    for e in cfg.get("environments", []):
        (dup if e["id"] in seen_ids else seen_ids).add(e["id"])
    if dup:
        raise ApiError("중복된 환경 ID 가 있어 저장하지 않았습니다: %s (환경설정의 '환경 ID 중복 정리'를 사용하세요)" % ", ".join(sorted(dup)), 409, duplicate_ids=sorted(dup))
    write_json(CONFIG_PATH, cfg)
    return jsonify({"ok": True, "rev": file_rev(CONFIG_PATH)})


@app.put("/api/local")
def api_local_put():
    body = request.get_json()
    loc = load_local()
    loc.setdefault("tokens", {})
    if "account" in body:
        loc["account"] = body["account"].strip()
    for k, v in (body.get("tokens") or {}).items():
        if v == "__clear__":
            loc["tokens"][k] = ""
        elif v:
            loc["tokens"][k] = v.strip()
    if isinstance(body.get("jira"), dict):  # Jira 연동 설정 (토큰은 입력했을 때만 변경, __clear__ 로 삭제)
        jb, j = body["jira"], loc.setdefault("jira", {})
        for k in ("base_url", "auth", "user"):
            if k in jb:
                j[k] = str(jb[k]).strip().rstrip("/") if k == "base_url" else str(jb[k]).strip()
        if "ssl_verify" in jb:
            j["ssl_verify"] = bool(jb["ssl_verify"])
        if jb.get("token") == "__clear__":
            j["token"] = ""
        elif jb.get("token"):
            j["token"] = str(jb["token"]).strip()
    write_json(LOCAL_PATH, loc)
    return jsonify({"ok": True})


@app.get("/api/meta")
def api_meta():
    return jsonify({**load_meta(), "_rev": file_rev(META_PATH)})


@app.put("/api/meta")
@cfg_locked
def api_meta_put():
    check_rev(META_PATH)
    meta = request.get_json()
    meta.pop("_rev", None)
    stamp_meta(meta, load_config())
    write_json(META_PATH, meta)
    return jsonify({"ok": True, "rev": file_rev(META_PATH)})


# ---- 환경 정보 (Subnet name / VPC ID / IPv4 CIDR / NAT IP) : meta.json 의 envs[환경ID].subnets
ENV_CSV_HEAD = ["env_id", "환경", "Subnet name", "VPC ID", "IPv4 CIDR", "NAT IP"]
ENV_FIELDS = {"subnetname": "subnet_name", "vpcid": "vpc_id", "ipv4cidr": "ipv4_cidr", "natip": "nat_ip"}
IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}(/\d{1,2})?$")


def clean_subnet(r):
    return {k: str(r.get(k, "") or "").strip() for k in ("subnet_name", "vpc_id", "ipv4_cidr", "nat_ip")}


@app.get("/api/meta/env-csv")
def api_meta_env_csv():
    """환경 정보 CSV 다운로드. env_id 를 주면 그 환경만(데이터가 없으면 빈 입력 행 1줄), 없으면 전체."""
    only = request.args.get("env_id")
    cfg_envs = {e["id"]: e for e in load_config()["environments"]}
    meta = load_meta().get("envs", {})
    ids = [only] if only else [i for i in meta if i in cfg_envs and meta[i].get("subnets")]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(ENV_CSV_HEAD)
    for eid in ids:
        e = cfg_envs.get(eid, {})
        label = ("%s / %s %s" % (e.get("group", ""), e.get("env", ""), e.get("label", ""))).strip()
        rows = meta.get(eid, {}).get("subnets") or [{}]
        for r in rows:
            r = clean_subnet(r)
            w.writerow([eid, label, r["subnet_name"], r["vpc_id"], r["ipv4_cidr"], r["nat_ip"]])
    return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=env-info.csv"})


@app.post("/api/meta/env-csv")
@cfg_locked
def api_meta_env_csv_post():
    """환경 정보 CSV 업로드: CSV 에 나온 환경은 해당 환경의 기존 목록을 CSV 내용으로 교체."""
    text = request.files["file"].read().decode("utf-8-sig")
    rd = csv.DictReader(io.StringIO(text))
    cols = {re.sub(r"[\s_\-]", "", (h or "").lower()): h for h in (rd.fieldnames or [])}
    if "envid" not in cols or not any(k in cols for k in ENV_FIELDS):
        raise ApiError("헤더가 올바르지 않습니다. 필요한 열: env_id, Subnet name, VPC ID, IPv4 CIDR, NAT IP")
    known = {e["id"] for e in load_config()["environments"]}
    meta = load_meta()
    new, unknown, warnings = {}, set(), []
    for n, row in enumerate(rd, start=2):
        eid = (row.get(cols["envid"]) or "").strip()
        if not eid:
            continue
        if eid not in known:
            unknown.add(eid)
            continue
        rec = clean_subnet({v: row.get(cols[k]) for k, v in ENV_FIELDS.items() if k in cols})
        bucket = new.setdefault(eid, [])
        if not any(rec.values()):
            continue  # 빈 행은 건너뜀(해당 환경을 비우는 용도로는 사용 가능)
        for fld in ("ipv4_cidr", "nat_ip"):
            if rec[fld] and not IP_RE.match(rec[fld]):
                warnings.append("%d행 %s 형식 확인 필요: %s" % (n, fld, rec[fld]))
        bucket.append(rec)
    for eid, rows in new.items():
        meta.setdefault("envs", {}).setdefault(eid, {})["subnets"] = rows
    write_json(META_PATH, meta)
    return jsonify({"ok": True, "envs": len(new), "rows": sum(len(v) for v in new.values()),
                    "unknown_env_ids": sorted(unknown), "warnings": warnings[:20]})


META_COLS = ["env_id", "sg_name", "sg_id", "alias", "tag_type", "tag_value", "owner"]


@app.get("/api/meta/csv")
def api_meta_csv():
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(META_COLS)
    for env_id, em in load_meta().get("envs", {}).items():
        for sg, sm in em.get("sgs", {}).items():
            tags = sm.get("tags") or [{"type": "", "value": ""}]
            for t in tags:
                w.writerow([env_id, sg, sm.get("sg_id", ""), sm.get("alias", ""), t.get("type", ""), t.get("value", ""), sm.get("owner", "")])
    return Response("\ufeff" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=sg-meta.csv"})


@app.post("/api/meta/csv")
@cfg_locked
def api_meta_csv_post():
    text = request.files["file"].read().decode("utf-8-sig")
    meta = load_meta()
    seen = set()
    for row in csv.DictReader(io.StringIO(text)):
        env_id, sg = (row.get("env_id") or "").strip(), (row.get("sg_name") or "").strip()
        if not env_id or not sg:
            continue
        sm = meta.setdefault("envs", {}).setdefault(env_id, {}).setdefault("sgs", {}).setdefault(sg, {})
        if (env_id, sg) not in seen:
            sm["tags"] = []
            seen.add((env_id, sg))
        sm["sg_id"] = (row.get("sg_id") or "").strip()
        sm["alias"] = (row.get("alias") or "").strip()
        if row.get("owner") is not None:      # owner 열이 없는 예전 CSV 는 기존 담당자를 지우지 않는다
            sm["owner"] = row["owner"].strip()
        if (row.get("tag_value") or "").strip():
            sm["tags"].append({"type": (row.get("tag_type") or "").strip(), "value": row["tag_value"].strip()})
    write_json(META_PATH, meta)
    return jsonify({"ok": True, "updated": len(seen)})


# ----------------------------------------------------------------- 규칙 검증
MGMT_PORTS = {22: "SSH", 3389: "RDP", 5985: "WinRM", 5986: "WinRM(HTTPS)"}   # 넓은 대역에 열면 위험한 관리 포트
MGMT_MAX_PREFIX = 24   # 이보다 넓은(숫자가 작은) 대역에 관리 포트를 열면 위험으로 알림
NAMING_RE = re.compile(r"^tf_\d{6}_[A-Za-z]+-\d+_.+ to .+ Connection$")
SGID_RE = re.compile(r"^sg-[0-9a-f]{8,17}$")


def validate_sg(env, new_sg, old_sg=None):
    """(errors, warnings, risks) 반환.
    errors  : 저장할 수 없는 문제 (새로 추가/수정된 규칙만 대상. 기존 규칙의 문제는 warnings 로만 알림)
    warnings: 참고 (중복 규칙, 설명 명명 규칙 불일치, SG ID 형식 등)
    risks   : 새로 생기는 위험 규칙 (인바운드 전체 개방, 광범위 대역, 전체 포트) - 확인 후 저장"""
    kind = env["kind"]
    errors, warnings, risks = [], [], []
    pol = get_policy()
    mgmt = {int(p): n for p, n in pol["mgmt_ports"].items()}
    today = datetime.now().date()
    for d, dl in (("ingress", "인바운드"), ("egress", "아웃바운드")):
        pool = {}
        for r in (old_sg or {}).get(d, []):
            s = rule_sig(norm_rule(r, kind))
            pool[s] = pool.get(s, 0) + 1
        seen = {}
        rng = []
        for i, raw in enumerate(new_sg.get(d, []), start=1):
            r = norm_rule(raw, kind)
            tag = "%s %d번" % (dl, i)
            sig = rule_sig(r)
            is_new = pool.get(sig, 0) == 0
            if not is_new:
                pool[sig] -= 1

            def bad(msg):  # 새/수정 규칙의 문제는 저장 차단, 기존 규칙은 참고만
                (errors if is_new else warnings).append(("" if is_new else "(기존) ") + tag + ": " + msg)

            proto = str(r["protocol"]).strip().lower()
            if not r["cidr_blocks"] and not r["security_groups"] and not r["prefix_list_ids"]:
                bad("소스(IP/SG ID)가 없습니다")
            if r["cidr_blocks"] and r["security_groups"]:
                bad("SG ID와 IP(CIDR)를 함께 지정할 수 없습니다")
            for c in r["cidr_blocks"]:
                try:
                    net = ipaddress.ip_network(c, strict=True)
                except ValueError:
                    try:
                        fix = ipaddress.ip_network(c, strict=False)
                        bad("CIDR 호스트 비트 오류 %s → %s 로 입력하세요" % (c, fix))
                    except ValueError:
                        bad("IP/CIDR 형식 오류: %s" % c)
                    continue
                if is_new and d == "ingress":
                    port = "전체" if proto == "-1" else "%s-%s" % (r["from_port"], r["to_port"])
                    lo, hi = (0, 65535) if proto == "-1" else (r["from_port"], r["to_port"])
                    if policy_exception(pol, env.get("id"), net, lo, hi):
                        continue   # 정책의 '허용 예외'에 해당하는 소스/포트는 위험으로 보지 않는다
                    if net.prefixlen == 0:
                        risks.append("%s: 전체 개방(%s) %s %s" % (tag, c, proto.upper(), port))
                    elif net.version == 4 and net.prefixlen < pol["wide_prefix"]:
                        risks.append("%s: 광범위 대역 %s (/%d) %s %s" % (tag, c, net.prefixlen, proto.upper(), port))
                    if 0 < net.prefixlen < pol["mgmt_max_prefix"] and proto in ("tcp", "udp") and not (r["from_port"] == 0 and r["to_port"] >= 65535):
                        hit = [("%s(%d)" % (nm, p)) for p, nm in mgmt.items() if r["from_port"] <= p <= r["to_port"]]
                        if hit:
                            risks.append("%s: 관리 포트 %s 를 넓은 대역 %s (/%d)에 허용" % (tag, ", ".join(hit), c, net.prefixlen))
            for sgid in [x.strip() for x in r["security_groups"].split(",") if x.strip()]:
                if not SGID_RE.match(sgid):
                    warnings.append("%s: SG ID 형식을 확인하세요: %s" % (tag, sgid))
            if proto not in ("tcp", "udp", "icmp", "icmpv6", "-1") and not proto.isdigit():
                bad("프로토콜을 확인하세요: %s" % r["protocol"])
            lo2, hi2 = (0, 65535) if proto == "-1" else (r["from_port"], r["to_port"])
            all_exc = bool(r["cidr_blocks"]) and all(n is not None and policy_exception(pol, env.get("id"), n, lo2, hi2) for n in (_net(c) for c in r["cidr_blocks"]))
            if proto in ("tcp", "udp"):
                f, t = r["from_port"], r["to_port"]
                if not (0 <= f <= 65535 and 0 <= t <= 65535):
                    bad("포트 범위는 0~65535 입니다 (%s-%s)" % (f, t))
                elif f > t:
                    bad("시작 포트(%s)가 끝 포트(%s)보다 큽니다" % (f, t))
                elif is_new and d == "ingress" and f == 0 and t >= 65535 and not all_exc:
                    risks.append("%s: 전체 포트(0-65535) 허용" % tag)
            if is_new and d == "ingress" and proto == "-1" and not all_exc:
                risks.append("%s: 모든 프로토콜/포트 허용" % tag)
            if is_new:
                ex = rule_expiry(r["description"])
                if ex and ex < today:
                    warnings.append("%s: 설명의 만료일(%s)이 이미 지났습니다" % (tag, ex.isoformat()))
            if not r["description"].strip():
                bad("설명이 비어 있습니다")
            elif is_new and not NAMING_RE.match(r["description"].strip()):
                warnings.append("%s: 설명이 명명 규칙(tf_YYMMDD_티켓_출발지 to 목적지 Connection)과 다릅니다" % tag)
            key = (proto, r["from_port"], r["to_port"], tuple(sorted(r["cidr_blocks"])), r["security_groups"])
            if key in seen:
                warnings.append("%s: %d번과 프로토콜/포트/소스가 같은 중복 규칙입니다" % (tag, seen[key]))
            else:
                seen[key] = i
            rng.append((i, proto, r["from_port"], r["to_port"], frozenset(r["cidr_blocks"]), r["security_groups"], is_new, key))
        # 새 규칙이 이미 있는 다른 규칙의 포트 범위 안에 들어가는지 (같은 프로토콜/소스) - 필요 없는 규칙일 수 있다
        for (i, p, f, t, src, sgs, new_flag, k) in rng:
            if not new_flag or p not in ("tcp", "udp") or not (src or sgs):
                continue
            for (j, p2, f2, t2, src2, sgs2, _n, k2) in rng:
                if j != i and k2 != k and p2 == p and src2 == src and sgs2 == sgs and f2 <= f and t <= t2:
                    warnings.append("%s %d번: %d번 규칙(%s-%s)의 범위에 이미 포함됩니다 - 겹치는 규칙인지 확인하세요" % (dl, i, j, f2, t2))
                    break
    return errors, warnings, risks


# ----------------------------------------------------------------- 라우트: SG
# ---- 적용 전 변경 감지: 마지막 커밋 대비 신규/변경된 SG 파일과 규칙
def base_ref(env):
    """비교 기준 = 마지막 커밋(HEAD). Commit/Push 하면 음영이 사라진다."""
    return "HEAD"


def sg_rel(env, fn):
    return "%s/%s" % (env["sg_dir"].strip("/"), fn)


def changed_files(env):
    """sg_rule 폴더 안에서 마지막 커밋 대비 바뀐 파일 {파일명: 'new'|'modified'}"""
    if not os.path.isdir(os.path.join(env["repo_dir"], ".git")):
        return {}
    key = _status_key(env)
    hit = _CHANGED_CACHE.get(key)
    if hit and time.time() - hit[0] < STATUS_TTL:
        return dict(hit[1])
    d, out = env["sg_dir"].strip("/"), {}
    base = base_ref(env)
    diff, others = par(lambda: run_git(env, "diff", "--name-status", base, "--", d, check=False),
                       lambda: run_git(env, "ls-files", "--others", "--exclude-standard", "--", d, check=False))
    for line in diff.splitlines():
        parts = line.split("	")
        if len(parts) >= 2 and parts[0][0] in "AMR":
            out[os.path.basename(parts[-1])] = "new" if parts[0][0] == "A" else "modified"
    for path in others.splitlines():
        out[os.path.basename(path.strip())] = "new"
    _CHANGED_CACHE[key] = (time.time(), dict(out))
    return out


def sg_change_status(env, files):
    if not files:
        return None
    if env["kind"] == "game" or any(GAME_FILE_RE.match(f) for f in files):
        return "new" if all(v == "new" for v in files.values()) else "modified"
    return files[next(iter(files))]


def rule_sig(r):
    return json.dumps([str(r["protocol"]).lower(), r["from_port"], r["to_port"], sorted(r["cidr_blocks"]),
                       r["security_groups"], r["description"]], ensure_ascii=False)


def base_rules(env, rel, key=None):
    """마지막 커밋의 파일 내용에서 규칙 목록. 파일이 없으면 None"""
    p = subprocess.run(["git", "show", "%s:%s" % (base_ref(env), rel)], cwd=env["repo_dir"], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        return None
    try:
        data = json.loads(p.stdout.lstrip("﻿"))
    except ValueError:
        return None
    items = data.get(key, []) if key else data
    return [norm_rule(r, env["kind"]) for r in items]


@app.get("/api/env/<env_id>/sgs")
def api_sgs(env_id):
    env = get_env(env_id)
    sgs, chg = list_sgs(env), changed_files(env)
    for sg in sgs:
        sg["change"] = sg_change_status(env, {f: chg[f] for f in sg["files"] if f in chg})
    return jsonify({"sgs": sgs, "exists": os.path.isdir(sg_path(env)), "path": sg_path(env)})


@app.get("/api/env/<env_id>/sg/<name>/changes")
def api_sg_changes(env_id, name):
    """마지막 커밋에 없는 규칙(신규/수정된 라인)의 인덱스"""
    env = get_env(env_id)
    cur = load_sg(env, name)
    res = {"ingress": [], "egress": [], "is_new": False}
    if not os.path.isdir(os.path.join(env["repo_dir"], ".git")):
        return jsonify(res)
    for direction in ("ingress", "egress"):
        if split_sg(env, name):
            base = base_rules(env, sg_rel(env, "%s-%s-rules.json" % (name, direction)))
        else:
            base = base_rules(env, sg_rel(env, name + ".json"), direction)
        if base is None:
            base = []
            res["is_new"] = True
        pool = {}
        for r in base:
            pool[rule_sig(r)] = pool.get(rule_sig(r), 0) + 1
        for i, r in enumerate(cur[direction]):
            sig = rule_sig(r)
            if pool.get(sig, 0) > 0:
                pool[sig] -= 1
            else:
                res[direction].append(i)
    return jsonify(res)


@app.post("/api/env/<env_id>/sgs")
def api_sg_create(env_id):
    env = get_env(env_id)
    require_work_branch(env)
    body = request.get_json()
    resource = (body.get("resource") or "").strip()
    check_name(resource)
    name = file_name_for(env, resource)
    exists = (any(os.path.exists(p) for p in game_files(env, name)) if env["kind"] == "game"
              else os.path.exists(os.path.join(sg_path(env), name + ".json")) or any(os.path.exists(p) for p in game_files(env, name)))
    if exists:
        raise ApiError("이미 존재하는 SG 입니다: %s" % name, 409)
    egress = []
    if body.get("egress_allow_all"):
        egress = [{"from_port": 0, "to_port": 0, "protocol": "-1", "cidr_blocks": ["0.0.0.0/0"],
                   "description": "Allow all outbound traffic"}]
    save_sg(env, name, {"ingress": [], "egress": egress})
    return jsonify({"name": name})


@app.get("/api/env/<env_id>/sg/<name>")
def api_sg_get(env_id, name):
    return jsonify(load_sg(get_env(env_id), name))


@app.put("/api/env/<env_id>/sg/<name>")
def api_sg_put(env_id, name):
    env = get_env(env_id)
    require_work_branch(env)
    old = load_sg(env, name)  # 존재 확인
    new = request.get_json()
    errors, warnings, _risks = validate_sg(env, new, old)  # 위험 규칙 확인은 화면에서 이미 거친 것으로 본다
    if errors:
        raise ApiError("저장할 수 없습니다:\n" + "\n".join(errors), 400, errors=errors)
    save_sg(env, name, new)
    return jsonify({"ok": True, "warnings": warnings})


@app.post("/api/env/<env_id>/sg/<name>/validate")
def api_sg_validate(env_id, name):
    """저장 전 검증: errors(저장 불가) / warnings(참고) / risks(새로 생기는 위험 규칙, 확인 필요)"""
    env = get_env(env_id)
    new, old = request.get_json(), load_sg(env, name)
    errors, warnings, risks = validate_sg(env, new, old)
    res = {"errors": errors, "warnings": warnings, "risks": risks, "already": [], "others": []}
    if not errors:
        try:
            res.update(already_open_info(env, name, new, old))   # 새 규칙을 이미 허용하는 규칙이 있는지 (참고용, 실패해도 저장은 막지 않는다)
        except Exception as exc:
            log_event("WARN", "이미 열려 있음 점검 실패: %r" % exc)
    return jsonify(res)


@app.get("/api/env/<env_id>/sg/<name>/csv")
def api_sg_csv(env_id, name):
    return Response(rules_to_csv(load_sg(get_env(env_id), name)), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=%s.csv" % name})


def _csv_merge(cur, new, mode):
    out = json.loads(json.dumps(cur))
    for d in ("ingress", "egress"):
        if mode == "replace":
            out[d] = json.loads(json.dumps(new[d]))
        else:
            key = lambda r: json.dumps([r["from_port"], r["to_port"], r["protocol"], r["cidr_blocks"], r["security_groups"]])
            have = {key(r) for r in out[d]}
            out[d] += [r for r in new[d] if key(r) not in have]
    return out


def _rule_diff(old, merged):
    """(추가된 규칙, 제거된 규칙) 목록 - 규칙 시그니처 기준"""
    added, removed = [], []
    for d in ("ingress", "egress"):
        pool = {}
        for r in old[d]:
            pool[rule_sig(r)] = pool.get(rule_sig(r), 0) + 1
        for r in merged[d]:
            s = rule_sig(r)
            if pool.get(s, 0) > 0:
                pool[s] -= 1
            else:
                added.append({"direction": d, **r})
        pool2 = {}
        for r in merged[d]:
            pool2[rule_sig(r)] = pool2.get(rule_sig(r), 0) + 1
        for r in old[d]:
            s = rule_sig(r)
            if pool2.get(s, 0) > 0:
                pool2[s] -= 1
            else:
                removed.append({"direction": d, **r})
    return added, removed


@app.post("/api/env/<env_id>/sg/<name>/csv")
def api_sg_csv_post(env_id, name):
    """CSV 적용. dry_run=1 이면 저장 없이 '추가/교체' 두 방식의 미리보기(추가·제거 규칙, 오류, 위험)만 돌려준다."""
    env = get_env(env_id)
    cur = load_sg(env, name)
    new = csv_to_rules(request.files["file"].read().decode("utf-8-sig"), env["kind"])
    if request.form.get("dry_run") == "1":
        prev = {}
        for m in ("append", "replace"):
            merged = _csv_merge(cur, new, m)
            errors, warnings, risks = validate_sg(env, merged, cur)
            added, removed = _rule_diff(cur, merged)
            prev[m] = {"added": added, "removed": removed, "errors": errors, "warnings": warnings, "risks": risks}
        return jsonify({"preview": prev, "csv_rows": len(new["ingress"]) + len(new["egress"])})
    require_work_branch(env)
    mode = request.form.get("mode", "append")
    merged = _csv_merge(cur, new, mode)
    errors, warnings, risks = validate_sg(env, merged, cur)
    if errors:
        raise ApiError("CSV를 적용할 수 없습니다 (아무것도 저장되지 않았습니다):\n" + "\n".join(errors), 400, errors=errors)
    if risks and request.form.get("confirm_risk") != "1":
        raise ApiError("위험 규칙이 포함되어 있습니다. 확인이 필요합니다:\n" + "\n".join(risks), 409, need_confirm=True, risks=risks)
    save_sg(env, name, merged)
    return jsonify({"ok": True, "ingress": len(merged["ingress"]), "egress": len(merged["egress"]), "warnings": warnings})


@app.get("/api/env/<env_id>/sg/<name>/diff")
def api_sg_diff(env_id, name):
    """이 SG 파일의 변경 내용(마지막 커밋 대비). 읽기 전용 git 조회만 사용"""
    env = get_env(env_id)
    load_sg(env, name)
    if not os.path.isdir(os.path.join(env["repo_dir"], ".git")):
        return jsonify({"diff": "", "new_file": False, "note": "저장소가 없습니다"})
    names = [os.path.basename(p) for p in sg_files(env, name)]
    rels = [sg_rel(env, n) for n in names]
    diff, new_file = "", False
    for rel in rels:
        tracked = run_git(env, "ls-files", "--error-unmatch", "--", rel, check=False, strip=True)
        full = os.path.join(env["repo_dir"], *rel.split("/"))
        if not tracked.strip() or "error: pathspec" in tracked:
            if os.path.exists(full):
                new_file = True
                with open(full, "r", encoding="utf-8-sig") as f:
                    body = f.read().splitlines()
                diff += "diff --git a/%s b/%s\nnew file\n--- /dev/null\n+++ b/%s\n@@ -0,0 +1,%d @@\n%s\n" % (rel, rel, rel, len(body), "\n".join("+" + l for l in body))
        else:
            diff += run_git(env, "diff", "HEAD", "--", rel, check=False, strip=False)
    return jsonify({"diff": diff, "new_file": new_file})


def _net(text):
    """'10.0.0.5', '10.0.0.0/24' -> ip_network, 아니면 None"""
    try:
        return ipaddress.ip_network(str(text).strip(), strict=False)
    except ValueError:
        return None


_SG_CACHE = {}  # (env_id, name) -> (파일 수정시각 묶음, 규칙 데이터)


def _cached_sg(env, name):
    files = sg_files(env, name)
    stamp = tuple(os.path.getmtime(f) if os.path.exists(f) else 0 for f in files)
    key = (env["id"], name)
    hit = _SG_CACHE.get(key)
    if hit and hit[0] == stamp:
        return hit[1]
    data = load_sg(env, name)
    _SG_CACHE[key] = (stamp, data)
    return data


@app.get("/api/search")
def api_search():
    """IP / CIDR / 도메인 / 태그 / SG ID / SG명 / 서브넷 정보 검색.
    IP·CIDR 로 검색하면 규칙/태그/서브넷의 대역과 겹치는지(포함 관계)까지 찾는다."""
    raw = (request.args.get("q") or "").strip()
    q = raw.lower()
    scope = request.args.get("env_id")
    if not q:
        return jsonify({"results": []})
    qnet = _net(raw)
    meta = load_meta().get("envs", {})
    cfg_envs = [e for e in load_config()["environments"] if not scope or e["id"] == scope]
    results = []

    def text_hit(v):
        if is_any(v) and not query_is_any:
            return False
        return bool(v) and q in str(v).lower()

    # 0.0.0.0/0 (::/0) 는 어떤 IP 와도 겹치므로 검색 결과에서 제외한다 (0.0.0.0/0 자체를 검색한 경우만 표시)
    query_is_any = bool(qnet and qnet.prefixlen == 0)

    def is_any(v):
        return str(v or "").strip() in ("0.0.0.0/0", "::/0")

    def ip_hit(v):
        if is_any(v) and not query_is_any:
            return False
        n = _net(v) if v else None
        return bool(qnet and n and qnet.version == n.version and qnet.overlaps(n))

    for ce in cfg_envs:
        try:
            env = get_env(ce["id"])
        except ApiError:
            continue
        label = " · ".join(x for x in (env.get("group"), env.get("env"), env.get("label")) if x)
        em = meta.get(env["id"], {})
        base = {"env_id": env["id"], "env_label": label, "kind": env["kind"], "group": env.get("group", ""), "env": env.get("env", "")}
        # 서브넷/NAT 정보 (환경 단위)
        sub_hits = []
        for r in em.get("subnets", []) or []:
            for fld, name in (("subnet_name", "Subnet name"), ("vpc_id", "VPC ID"), ("ipv4_cidr", "IPv4 CIDR"), ("nat_ip", "NAT IP")):
                if text_hit(r.get(fld)) or (fld in ("ipv4_cidr", "nat_ip") and ip_hit(r.get(fld))):
                    sub_hits.append("%s: %s (%s)" % (name, r.get(fld), r.get("subnet_name") or "-"))
        if sub_hits:
            results.append({**base, "type": "env", "name": "", "hits": sorted(set(sub_hits))[:5], "score": 1})
        # SG 단위
        for sg in list_sgs(env):
            sm = em.get("sgs", {}).get(sg["name"], {})
            hits, score, best = [], 0, 0
            for k, v in (("이름", sg["name"]), ("별명", sm.get("alias", "")), ("SG ID", sm.get("sg_id", ""))):
                if text_hit(v):
                    hits.append("%s: %s" % (k, v))
                    score += 3 if k != "이름" else 2
            for t in sm.get("tags", []) or []:
                v = t.get("value", "")
                if text_hit(v) or ip_hit(v):
                    hits.append("태그(%s): %s" % (t.get("type", ""), v))
                    score += 4
            try:
                data = _cached_sg(env, sg["name"])
            except Exception as exc:
                log_event("WARN", "검색 중 SG 파일을 읽지 못했습니다 %s/%s: %r" % (env.get("id"), sg["name"], exc))
                data = {"ingress": [], "egress": []}
            for d in ("ingress", "egress"):
                for r in data[d]:
                    for c in r["cidr_blocks"]:
                        if text_hit(c) or ip_hit(c):
                            hits.append("%s: %s %s-%s" % (d, c, r["from_port"], r["to_port"]))
                            n = _net(c)
                            # IP 검색: 같은 대역이 최우선, 좁은 대역일수록 높게 (0.0.0.0/0 은 맨 아래)
                            if qnet and n:
                                best = max(best, 10 if n == qnet else 1 + n.prefixlen / 4)
                            else:
                                score += 3
                    for v, lbl in ((r["security_groups"], d), (r["description"], d + " 설명")):
                        if text_hit(v):
                            hits.append("%s: %s" % (lbl, v))
                            score += 2
                    if text_hit("%s-%s" % (r["from_port"], r["to_port"])) and not qnet:
                        hits.append("%s port: %s-%s" % (d, r["from_port"], r["to_port"]))
            score += best
            hits = list(dict.fromkeys(hits))
            if hits:
                results.append({**base, "type": "sg", "name": sg["name"], "hits": hits[:5], "total_hits": len(hits), "score": score})
    results.sort(key=lambda r: -r["score"])
    return jsonify({"results": results[:200], "query_is_ip": bool(qnet)})


# ----------------------------------------------------------------- 라우트: Git / MR / Atlantis
@app.get("/api/env/<env_id>/git/status")
def api_git_status(env_id):
    env = get_env(env_id)
    st = git_status(env, fresh=request.args.get("fresh") == "1")
    if st.get("cloned"):
        inf, outf = split_changes(st["files"], scope_paths(env))
        st["in_scope"], st["out_of_scope"] = len(inf), outf
        st["on_default"] = st["branch"] in ("main", "master", "HEAD", env["target_branch"] or "main")
    return jsonify(st)


def ensure_repo(env):
    """없으면 clone, 있으면 fetch. 결과 로그 반환."""
    invalidate_status(env)
    if not os.path.isdir(os.path.join(env["repo_dir"], ".git")):
        parent = os.path.dirname(os.path.normpath(env["repo_dir"]))
        os.makedirs(parent, exist_ok=True)
        # git clone https://[계정명]:[api키]@host/project.git
        run_git(env, "clone", clone_url(env, with_auth=True), env["repo_dir"], cwd=parent)
        # 토큰이 .git/config 에 남지 않도록 origin 을 인증정보 없는 URL로 교체
        run_git(env, "remote", "set-url", "origin", clone_url(env))
        return "cloned"
    run_git(env, "fetch", "origin", auth=True)
    return "fetched"


def infer_prefix(dirpath):
    """게임 SG 파일명들의 공통 접두어 (예: s0-sg-bbz-). 못 찾으면 빈 문자열."""
    names = [GAME_FILE_RE.match(f).group(1) for f in os.listdir(dirpath) if GAME_FILE_RE.match(f)]
    if not names:
        return ""
    pre = os.path.commonprefix(names)
    return pre[:pre.rfind("-") + 1] if "-" in pre else ""


REGION_RE = re.compile(r"^(ap|us|eu|sa|ca|me|af|cn)[a-z]{1,3}\d+$")


def split_env_path(rel):
    """aws/sandbox/sb0/apse1/sub/sg/sg_rule -> ("sandbox0", "apse1/sub")
    aws/live/apse1/sub/sg/sg_rule -> ("live", "apse1/sub"), aws/review/review2/... -> ("review2", ...)"""
    parts = [p for p in rel.split("/") if p not in ("sg", "sg_rule")]
    if parts and parts[0] == "aws":
        parts = parts[1:]
    r = next((i for i, p in enumerate(parts) if REGION_RE.match(p)), len(parts))
    before, after = parts[:r], parts[r:]
    if not before:
        return "/".join(parts) or rel, ""
    name = before[0]
    if len(before) > 1:
        second = before[1]
        digits = re.search(r"\d+$", second)
        name = second if second.startswith(name) else (name + digits.group(0) if digits else name + "-" + second)
    return name, "/".join(after)


@app.post("/api/env/<env_id>/discover")
@cfg_locked
def api_discover(env_id):
    """저장소 안의 sg_rule 폴더를 찾아 환경 목록에 자동 등록 (이미 있는 경로는 건너뜀)."""
    src = get_env(env_id)
    root = src["repo_dir"]
    raw = next(x for x in load_config()["environments"] if x["id"] == env_id)
    if not os.path.isdir(root):
        raise ApiError("저장소가 아직 없습니다. 작업 탭에서 먼저 다운로드하세요")
    cfg = load_config()
    have = {(os.path.normcase(os.path.normpath(get_env(e["id"])["repo_dir"])), e["sg_dir"].strip("/"))
            for e in cfg["environments"]}
    added = []
    for cur, dirs, _ in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", ".terraform")]
        if os.path.basename(cur) != "sg_rule":
            continue
        rel = os.path.relpath(cur, root).replace("\\", "/")
        if (os.path.normcase(os.path.normpath(root)), rel) in have:
            continue
        env_name, detail = split_env_path(rel)
        # 플랫폼: 그룹명 = 계정 폴더명(환경명과 동일), 게임: 선택한 행의 그룹 유지
        group = env_name if src["kind"] == "platform" else src["group"]
        taken = {x["id"] for x in cfg["environments"]}
        e = {"id": unique_env_id(env_path_slug(src["kind"], rel), taken),
             "kind": src["kind"], "group": group, "env": env_name, "label": detail,
             "repo_dir": raw.get("repo_dir", ""),
             "sg_dir": rel, "file_prefix": infer_prefix(cur) if src["kind"] == "game" else "",
             "project": raw.get("project", ""), "target_branch": ""}
        cfg["environments"].append(e)
        added.append(e["env"])
    if added:
        write_json(CONFIG_PATH, cfg)
    return jsonify({"added": added})


def backup_repo(env):
    invalidate_status(env)
    """기존 저장소 폴더를 삭제하지 않고 <폴더>_backup_<날짜_시간> 으로 백업. (백업 경로, 방식) 반환.
    방식: 'renamed' = 폴더 이름 변경, 'copied' = 이름 변경이 막혀(사용 중) 복사본으로 백업."""
    d = os.path.abspath(os.path.normpath(env["repo_dir"]))
    if not os.path.isdir(d):
        return None, None
    if len([p for p in d.replace("\\", "/").split("/") if p]) < 3:
        raise ApiError("안전을 위해 너무 상위 경로(%s)는 백업/교체할 수 없습니다" % d)
    dest = "%s_backup_%s" % (d, datetime.now().strftime("%y%m%d_%H%M%S"))
    try:
        os.rename(d, dest)
        return dest, "renamed"
    except OSError:
        pass  # 터미널/편집기/탐색기가 폴더를 잡고 있으면 이름 변경 불가 -> 복사로 대체
    try:
        shutil.copytree(d, dest, symlinks=True)
    except (OSError, shutil.Error) as e:
        shutil.rmtree(dest, ignore_errors=True)
        raise ApiError("백업에 실패했습니다(이름 변경/복사 모두 실패). 해당 폴더를 사용하는 프로그램을 닫고 다시 시도하세요: %s" % e)
    return dest, "copied"


def repo_risk(env):
    """삭제/교체 전 확인용: 커밋 안 된 변경 수, 원격에 push 안 된 커밋 수"""
    if not os.path.isdir(os.path.join(env["repo_dir"], ".git")):
        return None
    dirty = len([l for l in run_git(env, "status", "--porcelain", check=False).splitlines() if l.strip()])
    unpushed = len([l for l in run_git(env, "log", "--branches", "--not", "--remotes", "--oneline", check=False).splitlines() if l.strip()])
    return {"dirty": dirty, "unpushed": unpushed}


def delete_repo(env):
    """기존 저장소 폴더를 완전히 삭제(복구 불가). git 저장소 폴더만 대상."""
    invalidate_status(env)
    d = os.path.abspath(os.path.normpath(env["repo_dir"]))
    if not os.path.isdir(d):
        return
    if len([p for p in d.replace("\\", "/").split("/") if p]) < 3:
        raise ApiError("안전을 위해 너무 상위 경로(%s)는 삭제할 수 없습니다" % d)
    if not os.path.isdir(os.path.join(d, ".git")):
        raise ApiError("git 저장소(.git)가 없는 폴더는 삭제하지 않습니다: %s" % d)

    def _force(func, path, exc):  # git 객체 파일은 읽기 전용이라 속성을 풀고 재시도
        os.chmod(path, stat.S_IWRITE)
        func(path)
    try:
        shutil.rmtree(d, onexc=_force)
    except OSError as e:
        raise ApiError("삭제에 실패했습니다. 해당 폴더를 사용하는 프로그램(터미널/편집기/탐색기)을 닫고 다시 시도하세요: %s" % e)


def reset_repo_in_place(env):
    """폴더를 바꿀 수 없을 때: 백업(복사) 후 원격 기준으로 되돌려 새로 받은 것과 같은 상태로 만든다."""
    tb = env["target_branch"] or "main"
    run_git(env, "fetch", "origin", auth=True)
    run_git(env, "checkout", "-f", tb)
    run_git(env, "reset", "--hard", "origin/%s" % tb)
    run_git(env, "clean", "-fdx")
    return "reset"


@app.post("/api/clone/check")
def api_clone_check():
    """다운로드 전 선택한 저장소들의 로컬 상태(미커밋 변경/미푸시 커밋) 조회"""
    out, done = [], set()
    for eid in (request.get_json() or {}).get("env_ids", []):
        env = get_env(eid)
        key = os.path.normcase(os.path.abspath(env["repo_dir"]))
        if key in done:
            continue
        done.add(key)
        out.append({"env_id": eid, "repo_dir": env["repo_dir"], "risk": repo_risk(env)})
    return jsonify({"results": out})


@app.post("/api/clone")
def api_clone():
    """선택한 환경들의 저장소를 다운로드(clone) / 업데이트(fetch). 같은 저장소는 한 번만.
    fresh=true 이면 기존 폴더를 백업(이름 변경)한 뒤 새로 clone."""
    body = request.get_json() or {}
    mode = body.get("mode") or ("backup" if body.get("fresh") else "keep")   # keep | backup | delete
    if mode not in ("keep", "backup", "delete"):
        raise ApiError("알 수 없는 mode: %s" % mode)
    if mode == "delete" and body.get("confirm") != "delete":
        raise ApiError("삭제 후 다시 받기는 확인(confirm=delete)이 필요합니다")
    done, out = set(), []
    for eid in body.get("env_ids", []):
        env = get_env(eid)
        key = os.path.normcase(os.path.abspath(env["repo_dir"]))
        if key in done:
            continue
        done.add(key)
        try:
            backup, how = backup_repo(env) if mode == "backup" else (None, None)
            if mode == "delete":
                delete_repo(env)
                how = "deleted"
            res = reset_repo_in_place(env) if how == "copied" else ensure_repo(env)
            out.append({"env_id": eid, "project": env["project"], "repo_dir": env["repo_dir"],
                        "result": res, "backup": backup, "backup_mode": how})
        except ApiError as e:
            out.append({"env_id": eid, "project": env["project"], "repo_dir": env["repo_dir"], "error": str(e)})
    return jsonify({"results": out})


@app.post("/api/env/<env_id>/git/prepare")
def api_git_prepare(env_id):
    """clone(없으면) -> 대상 브랜치 최신화 -> 작업 브랜치 생성"""
    env = get_env(env_id)
    body = request.get_json() or {}
    ticket = (body.get("ticket") or "").strip()
    suffix = body.get("suffix") or ""
    clean_branch_suffix(suffix)     # 잘못된 입력이면 clone 하기 전에 먼저 알려준다
    log = []
    if os.path.isdir(os.path.join(env["repo_dir"], ".git")) and git_status(env, fresh=True)["files"]:
        raise ApiError("작업 트리에 커밋되지 않은 변경이 있습니다. 먼저 정리하세요")
    log.append(ensure_repo(env))  # 없으면 clone, 있으면 fetch
    tb = env["target_branch"] or "main"
    log.append(run_git(env, "checkout", tb))
    log.append(run_git(env, "pull", "--ff-only", "origin", tb, auth=True))
    branch = make_branch_name(env, ticket, suffix)
    log.append(run_git(env, "checkout", "-b", branch))
    invalidate_status(env)
    undo_clear(env)
    return jsonify({"branch": branch, "log": "\n".join(x for x in log if x)})


@app.post("/api/env/<env_id>/git/push")
def api_git_push(env_id):
    env = get_env(env_id)
    st = git_status(env, fresh=True)
    if not st.get("cloned"):
        raise ApiError("저장소가 아직 clone 되지 않았습니다")
    if st["branch"] in ("main", "master", env["target_branch"]):
        raise ApiError("작업 브랜치가 아닙니다 (%s). 먼저 브랜치를 생성하세요" % st["branch"])
    if not st["files"]:
        raise ApiError("변경된 파일이 없습니다")
    run_git(env, "fetch", "origin", st["branch"], auth=True, check=False)
    if run_git(env, "rev-parse", "--verify", "-q", "origin/%s" % st["branch"], check=False).strip():
        ahead = int(run_git(env, "rev-list", "--count", "HEAD..origin/%s" % st["branch"], check=False).strip() or 0)
        if ahead:
            raise ApiError("원격 작업 브랜치에 내 PC에 없는 커밋이 %d개 있습니다. 다른 곳에서 같은 브랜치를 push 한 것 같습니다. 먼저 가져오기(pull)로 합친 뒤 다시 시도하세요 (그대로 push 하면 거부됩니다)." % ahead, 409, remote_ahead=ahead)
    # SG 파일(sg_rule 폴더)만 커밋 대상: 저장소의 다른 변경 파일은 add/commit 하지 않는다
    scope = scope_paths(env)
    inf, outf = split_changes(st["files"], scope)
    if not inf:
        raise ApiError("커밋할 SG 파일 변경이 없습니다" + (" (SG 폴더 밖의 변경 %d개는 제외됨)" % len(outf) if outf else ""))
    log = [run_git(env, "add", "-A", "--", *scope)]
    log.append(run_git(env, "commit", "-m", st["branch"], "--", *scope))
    log.append(run_git(env, "push", "origin", "--set-upstream", st["branch"], auth=True))
    invalidate_status(env)
    undo_clear(env)
    return jsonify({"branch": st["branch"], "is_new": any(f["state"] == "new" for f in inf), "files": inf,
                    "skipped": outf, "log": "\n".join(log)})


# ----------------------------------------------------------------- 되돌리기 / 변경 취소 / 작업 브랜치 전환
UNDO_LOCK = threading.RLock()
UNDO_MAX = 30   # 저장소별 보관 개수


def _undo_path():
    return os.path.join(DATA, "undo.json")      # 호출 시점에 읽음 (테스트가 DATA 를 바꿔 쓰므로)


def _undo_load():
    d = read_json(_undo_path(), None)
    return d if isinstance(d, dict) and isinstance(d.get("entries"), list) else {"entries": []}


def _rel_in_repo(env, p):
    return os.path.relpath(p, env["repo_dir"]).replace("\\", "/")


def _repo_path(env, rel):
    root = os.path.abspath(env["repo_dir"])
    p = os.path.abspath(os.path.join(root, *rel.split("/")))
    if p != root and not p.startswith(root + os.sep):
        raise ApiError("저장소 밖의 경로는 되돌릴 수 없습니다: %s" % rel)
    return p


def _undo_label(names):
    return "규칙 변경: " + ", ".join(names[:3]) + (" 외 %d개" % (len(names) - 3) if len(names) > 3 else "")


def undo_snapshot(env, paths, name, label=None):
    """파일을 바꾸기 직전의 내용을 보관한다. 한 번의 요청(예: 여러 SG 일괄 적용) 안의 저장은 하나로 묶인다.
    파일이 원래 없었으면 '없음'으로 기록해 되돌릴 때 삭제한다. 저장소가 아니면 아무것도 하지 않는다."""
    if not os.path.isdir(os.path.join(env["repo_dir"], ".git")):
        return
    key = _status_key(env)
    with UNDO_LOCK:
        data = _undo_load()
        ids = getattr(g, "_undo_ids", None) if has_request_context() else None
        if has_request_context() and ids is None:
            ids = g._undo_ids = {}
        entry = None
        if ids and key in ids:
            entry = next((e for e in data["entries"] if e["id"] == ids[key]), None)
        if entry is None:
            br = run_git(env, "rev-parse", "--abbrev-ref", "HEAD", check=False).strip()
            entry = {"id": uuid.uuid4().hex[:12], "repo": key, "branch": br, "ts": time.time(), "names": [], "items": [], "label": ""}
            data["entries"].append(entry)
            if ids is not None:
                ids[key] = entry["id"]
        if name and name not in entry["names"]:
            entry["names"].append(name)
        entry["label"] = label or _undo_label(entry["names"])
        have = {i["path"] for i in entry["items"]}
        for p in paths:
            rel = _rel_in_repo(env, p)
            if rel in have:
                continue
            try:
                with open(p, "rb") as f:
                    entry["items"].append({"path": rel, "b64": base64.b64encode(f.read()).decode()})
            except FileNotFoundError:
                entry["items"].append({"path": rel, "b64": None})
        mine = [e for e in data["entries"] if e["repo"] == key]
        while len(mine) > UNDO_MAX:
            data["entries"].remove(mine.pop(0))
        write_json(_undo_path(), data)


def undo_clear(env):
    with UNDO_LOCK:
        data = _undo_load()
        key = _status_key(env)
        data["entries"] = [e for e in data["entries"] if e["repo"] != key]
        write_json(_undo_path(), data)


def _undo_entries(env):
    key = _status_key(env)
    return [e for e in _undo_load()["entries"] if e["repo"] == key]


def _cur_branch(env):
    return run_git(env, "rev-parse", "--abbrev-ref", "HEAD", check=False).strip()


@app.get("/api/env/<env_id>/undo")
def api_undo_list(env_id):
    env = get_env(env_id)
    br = _cur_branch(env) if os.path.isdir(os.path.join(env["repo_dir"], ".git")) else ""
    items = [{"id": e["id"], "label": e["label"], "ts": e["ts"], "files": len(e["items"]), "branch": e["branch"]}
             for e in reversed(_undo_entries(env))]
    return jsonify({"items": items, "branch": br, "usable": bool(items) and items[0]["branch"] == br})


@app.post("/api/env/<env_id>/undo")
def api_undo(env_id):
    """가장 최근 변경 하나를 되돌린다 (저장 직전 상태로 복원). Commit/Push 전의 변경만 대상"""
    env = get_env(env_id)
    with UNDO_LOCK:
        ents = _undo_entries(env)
        if not ents:
            raise ApiError("되돌릴 변경 기록이 없습니다 (Commit/Push 하면 기록은 비워집니다)")
        e = ents[-1]
        br = _cur_branch(env)
        if e["branch"] != br:
            raise ApiError("변경 기록은 브랜치 %s 의 것입니다 (현재: %s). 해당 브랜치로 돌아간 뒤 되돌려 주세요" % (e["branch"], br), 409)
        for it in e["items"]:
            p = _repo_path(env, it["path"])
            if it["b64"] is None:
                try:
                    os.remove(p)
                except FileNotFoundError:
                    pass
            else:
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "wb") as f:
                    f.write(base64.b64decode(it["b64"]))
        data = _undo_load()
        data["entries"] = [x for x in data["entries"] if x["id"] != e["id"]]
        write_json(_undo_path(), data)
    invalidate_status(env)
    return jsonify({"ok": True, "label": e["label"], "files": len(e["items"])})


def _revert_files(env, rels):
    """파일들을 마지막 커밋(HEAD) 상태로 되돌린다. 커밋에 없던 새 파일은 삭제"""
    done = []
    for rel in rels:
        p = _repo_path(env, rel)
        in_head = subprocess.run(["git", "cat-file", "-e", "HEAD:%s" % rel], cwd=env["repo_dir"], capture_output=True).returncode == 0
        if in_head:
            run_git(env, "checkout", "HEAD", "--", rel)
        elif os.path.exists(p):
            os.remove(p)
        done.append(rel)
    invalidate_status(env)
    return done


@app.post("/api/env/<env_id>/sg/<name>/revert")
def api_sg_revert(env_id, name):
    """이 SG 의 아직 Commit 하지 않은 변경을 취소 (되돌리기로 다시 살릴 수 있음)"""
    env = get_env(env_id)
    if not (request.get_json(silent=True) or {}).get("confirm"):
        raise ApiError("변경 취소 확인(confirm)이 필요합니다")
    check_name(name)
    files = sg_files(env, name)
    st = git_status(env, fresh=True)
    changed = {f["path"].strip('"').replace("\\", "/") for f in st.get("files", [])}
    rels = [_rel_in_repo(env, p) for p in files if _rel_in_repo(env, p) in changed]
    if not rels:
        raise ApiError("이 SG 에는 취소할 변경이 없습니다")
    undo_snapshot(env, [_repo_path(env, r) for r in rels], name, label="변경 취소: %s" % name)
    _revert_files(env, rels)
    return jsonify({"ok": True, "files": rels})


@app.post("/api/env/<env_id>/git/revert-all")
def api_revert_all(env_id):
    """SG 폴더 안의 Commit 하지 않은 변경 전체를 취소 (SG 폴더 밖의 파일은 건드리지 않음)"""
    env = get_env(env_id)
    if not (request.get_json(silent=True) or {}).get("confirm"):
        raise ApiError("변경 취소 확인(confirm)이 필요합니다")
    st = git_status(env, fresh=True)
    if not st.get("cloned"):
        raise ApiError("저장소가 아직 clone 되지 않았습니다")
    inf, _outf = split_changes(st["files"], scope_paths(env))
    rels = [f["path"].strip('"').replace("\\", "/") for f in inf]
    if not rels:
        raise ApiError("취소할 변경이 없습니다")
    undo_snapshot(env, [_repo_path(env, r) for r in rels], "", label="변경 전체 취소 (%d개 파일)" % len(rels))
    _revert_files(env, rels)
    return jsonify({"ok": True, "files": rels})


@app.post("/api/env/<env_id>/git/finish")
def api_git_finish(env_id):
    """Atlantis apply 가 끝난 뒤 정리: 대상 브랜치(main)로 전환하고 최신화. 저장하지 않은 변경이 있으면 하지 않는다"""
    env = get_env(env_id)
    if not os.path.isdir(os.path.join(env["repo_dir"], ".git")):
        raise ApiError("저장소가 아직 clone 되지 않았습니다")
    tb = env["target_branch"] or "main"
    st = git_status(env, fresh=True)
    if st["files"]:
        raise ApiError("현재 브랜치(%s)에 Commit 하지 않은 변경 %d개가 있어 %s 로 전환하지 않았습니다. 먼저 정리하세요." % (st["branch"], len(st["files"]), tb), 409)
    prev = st["branch"]
    log = []
    if prev != tb:
        log.append(run_git(env, "checkout", tb))
    pulled = True
    try:
        log.append(run_git(env, "pull", "--ff-only", "origin", tb, auth=True))
    except ApiError as e:       # 오프라인/인증 문제여도 전환 자체는 유지하고 알려준다
        pulled = False
        log.append("최신화 실패: %s" % str(e).splitlines()[0])
    undo_clear(env)
    invalidate_status(env)
    return jsonify({"ok": True, "branch": tb, "previous": prev, "pulled": pulled, "log": "\n".join(x for x in log if x)})


@app.get("/api/env/<env_id>/git/branches")
def api_branches(env_id):
    """이 저장소의 로컬 작업 브랜치 목록 (여러 티켓을 번갈아 작업할 때 전환용)"""
    env = get_env(env_id)
    if not os.path.isdir(os.path.join(env["repo_dir"], ".git")):
        return jsonify({"branches": [], "current": ""})
    cur = _cur_branch(env)
    tb = env["target_branch"] or "main"
    out = []
    for line in run_git(env, "for-each-ref", "--sort=-committerdate", "--format=%(refname:short)\t%(committerdate:short)\t%(subject)", "refs/heads").splitlines():
        parts = line.split("\t")
        if parts[0] in (tb, "main", "master"):
            continue
        m = re.search(r"([A-Za-z][A-Za-z0-9]*-\d+)", parts[0])
        out.append({"name": parts[0], "date": parts[1] if len(parts) > 1 else "", "subject": parts[2] if len(parts) > 2 else "",
                    "ticket": m.group(1) if m else "", "current": parts[0] == cur})
    return jsonify({"branches": out, "current": cur})


@app.post("/api/env/<env_id>/git/switch")
def api_switch_branch(env_id):
    """다른 작업 브랜치로 전환. 저장하지 않은 변경이 있으면 거부 (먼저 Commit/Push 하거나 변경 취소)"""
    env = get_env(env_id)
    target = (request.get_json(silent=True) or {}).get("branch", "").strip()
    names = {b["name"] for b in api_branches(env_id).get_json()["branches"]}
    if target not in names:
        raise ApiError("로컬에 없는 작업 브랜치입니다: %s" % target)
    st = git_status(env, fresh=True)
    if st.get("files"):
        raise ApiError("현재 브랜치(%s)에 Commit 하지 않은 변경 %d개가 있어 전환할 수 없습니다. 먼저 Commit/Push 하거나 '변경 취소' 를 하세요." % (st["branch"], len(st["files"])), 409)
    log = run_git(env, "checkout", target)
    invalidate_status(env)
    undo_clear(env)
    return jsonify({"ok": True, "branch": target, "log": log})


@app.get("/api/env/<env_id>/git/diff")
def api_git_diff(env_id):
    """Commit/Push 전 확인용: 커밋 대상(SG 파일) 변경 diff 와 범위 밖 변경 목록"""
    env = get_env(env_id)
    st = git_status(env, fresh=True)
    if not st.get("cloned"):
        raise ApiError("저장소가 아직 clone 되지 않았습니다")
    scope = scope_paths(env)
    inf, outf = split_changes(st["files"], scope)
    diff = ""
    if inf:
        run_git(env, "add", "-N", "--", *scope, check=False)  # 새 파일도 diff 에 보이도록 (intent-to-add)
        diff = run_git(env, "diff", "HEAD", "--", *scope, check=False)
    note = ""
    if len(diff) > 200000:
        diff, note = diff[:200000], "\n... (diff 가 길어 일부만 표시)"
    return jsonify({"branch": st["branch"], "files": inf, "skipped": outf, "diff": diff + note, "scope": scope,
                    "freshness": check_freshness(env, st["branch"])})


# ---- MR 설명: 프로젝트의 기본 MR 템플릿을 사용 (못 가져오면 아래 기본 양식)
DEFAULT_MR_TEMPLATE = """## 🛠️ MR Type

- [ ] 신규 서비스 추가
- [ ] 서비스 수정/변경
- [ ] SG 정책 추가/변경/삭제
- [ ] 서비스 삭제
- [ ] 코드 리팩토링 (Terraform 모듈 버전 업그레이드 등)
- [ ] 버그 픽스
- [ ] 기타

## 🔎 Pre-Workflow

- [ ] CP/Account/Region/Env 정상 체크
- [ ] terraform backend 변경 체크
- [ ] 다른 리소스 영향도 체크

## 📚 Sumamry

- [추가 또는 변경 사항에 대해 간단하게 작성해 주세요.]

## 🔗 Linked Jira ticket

- 관련된 JIRA Ticket 또는 Issue를 연결해 주세요.

## 💭 Reviewers

- 승인 및 리뷰어를 지정해주세요. (하단 Approved by 사용자 추가/변경/제거)
- 리뷰어를 지정해 주세요. (/assign_reviewer @사용자 추가/변경/제거)
- 리뷰어에게 공유가 필요한 부분을 함께 기재해 주세요.
"""


def fetch_mr_template(env):
    """GitLab 프로젝트의 MR 템플릿(Default 우선)을 가져온다. 실패하면 None."""
    try:
        items = gl(env, "GET", "/projects/%s/templates/merge_requests" % pid(env))
        if not items:
            return None
        pick = next((i for i in items if str(i.get("name", "")).lower() == "default"), items[0])
        data = gl(env, "GET", "/projects/%s/templates/merge_requests/%s" % (pid(env), quote(pick["name"], safe="")))
        return data.get("content") or None
    except (ApiError, requests.RequestException, KeyError, ValueError):
        return None


def ticket_from_branch(branch):
    """계정/YYMMDD_티켓[_01] -> 티켓"""
    m = re.search(r"/\d{6}_([A-Za-z]+-\d+)", branch or "")
    return m.group(1) if m else ""


# 게임환경 전용 MR 양식 (Pre-Workflow 사전 체크, Reviewers 항목 + Approved by 표기)
GAME_MR_TEMPLATE = """## 🛠️ MR Type

- [ ] 신규 서비스 추가
- [ ] 서비스 수정/변경
- [ ] SG 정책 추가/변경/삭제
- [ ] 서비스 삭제
- [ ] 코드 리팩토링 (Terraform 모듈 버전 업그레이드 등)
- [ ] 버그 픽스
- [ ] 기타

## 🔎 Pre-Workflow

- [x] CP/Account/Region/Env 정상 체크
- [x] terraform backend 변경 체크
- [x] 다른 리소스 영향도 체크

## 📚 Sumamry

- [추가 또는 변경 사항에 대해 간단하게 작성해 주세요.]

## 🔗 Linked Jira ticket

- 관련된 JIRA Ticket 또는 Issue를 연결해 주세요.

## 💭 Reviewers

- 승인 및 리뷰어를 지정해주세요. (하단 Approved by 사용자 추가/변경/제거)

- 리뷰어를 지정해 주세요. (/assign_reviewer @사용자 추가/변경/제거)

- 리뷰어에게 공유가 필요한 부분을 함께 기재해 주세요.

{{APPROVED}}
"""


def build_mr_description(env, summary, mr_type, ticket, approvers=()):
    """플랫폼: 프로젝트 MR 템플릿(없으면 기본 양식) / 게임: 게임 전용 양식"""
    if env["kind"] == "game":
        tpl = GAME_MR_TEMPLATE.replace("{{APPROVED}}", "\n".join("- [x] Approved by @%s" % a for a in approvers))
    else:
        tpl = fetch_mr_template(env) or DEFAULT_MR_TEMPLATE
    lines = tpl.replace("\r\n", "\n").split("\n")
    out, i, kind = [], 0, ""
    while i < len(lines):
        ln = lines[i]
        if re.match(r"^#{1,6}\s", ln):
            h = ln.lower()
            kind = "type" if "mr type" in h else "summary" if re.search(r"sum\w*ry", h) else \
                   "jira" if "jira" in h and ticket else ""
            out.append(ln)
            i += 1
            if kind in ("summary", "jira"):  # 본문(안내 문구)을 실제 내용으로 교체
                while i < len(lines) and not re.match(r"^#{1,6}\s", lines[i]):
                    i += 1
                out.append("")
                if kind == "summary":
                    out += ["- %s" % t.strip() for t in summary.splitlines() if t.strip()]
                else:
                    out.append("- %s" % ticket)
                out.append("")
            continue
        if kind == "type":  # MR Type 체크박스: 해당 항목만 체크
            m = re.match(r"^(\s*[-*]\s*)\[[ xX]\](\s*)(.*)$", ln)
            if m:
                ln = "%s[%s]%s%s" % (m.group(1), "x" if mr_type in m.group(3) else " ", m.group(2), m.group(3))
        out.append(ln)
        i += 1
    return "\n".join(out).rstrip() + "\n"


def find_open_mr(env, branch):
    """같은 소스 브랜치로 이미 열려 있는 MR (없으면 None)"""
    items = gl(env, "GET", "/projects/%s/merge_requests" % pid(env), params={"source_branch": branch, "state": "opened", "per_page": 5})
    return items[0] if isinstance(items, list) and items else None


@app.get("/api/env/<env_id>/mr/existing")
def api_mr_existing(env_id):
    """현재 작업 브랜치로 이미 열린 MR 이 있는지 조회 (읽기 전용)"""
    env = get_env(env_id)
    st = git_status(env, fresh=True)
    branch = st.get("branch")
    if not st.get("cloned") or not branch or branch in ("main", "master", "HEAD", env["target_branch"] or "main"):
        return jsonify({"exists": False, "branch": branch})
    mr = find_open_mr(env, branch)
    if not mr:
        return jsonify({"exists": False, "branch": branch})
    return jsonify({"exists": True, "branch": branch, "iid": mr["iid"], "url": mr["web_url"], "title": mr.get("title", "")})


@app.post("/api/env/<env_id>/mr")
def api_mr(env_id):
    env = get_env(env_id)
    body = request.get_json()
    st = git_status(env, fresh=True)
    branch = st.get("branch")
    if not branch or not run_git(env, "ls-remote", "--heads", "origin", branch, auth=True, check=False).strip():
        raise ApiError("원격(GitLab)에 브랜치가 없습니다: %s\n먼저 '3. Commit / Push'로 push 하세요" % branch)
    # MR 중복 방지: 같은 브랜치로 열린 MR 이 이미 있으면 새로 만들지 않고 그 MR 을 돌려준다 (기존 MR 은 수정하지 않음)
    existing = find_open_mr(env, branch)
    if existing:
        return jsonify({"iid": existing["iid"], "url": existing["web_url"], "existing": True, "title": existing.get("title", "")})
    summary = (body.get("summary") or "").strip()
    if not summary:
        raise ApiError("Summary(작업 내용 요약)를 입력하세요")
    mr_type = MR_TYPE  # MR Type 은 고정
    # 게임 양식의 "Approved by": 리뷰어 → (없으면) 담당자 → (없으면) 내 계정
    approvers = [str(x).strip().lstrip("@") for x in (body.get("reviewers") or body.get("assignees") or []) if str(x).strip()] \
        or [load_local().get("account", "").strip()]
    desc = build_mr_description(env, summary, mr_type, ticket_from_branch(branch), [a for a in approvers if a])
    if body.get("include_checks", True):
        desc = desc.rstrip("\n") + "\n" + mr_check_section(env)
    payload = {"source_branch": branch, "target_branch": env["target_branch"] or "main",
               "title": branch, "description": desc, "remove_source_branch": True}
    def user_ids(names):
        ids = []
        for n in names:
            n = str(n).strip().lstrip("@")
            if not n:
                continue
            users = gl(env, "GET", "/users", params={"username": n})
            if not users:
                raise ApiError("GitLab 사용자를 찾을 수 없습니다: %s" % n)
            if users[0]["id"] not in ids:
                ids.append(users[0]["id"])
        return ids

    assignees = body.get("assignees")
    if assignees is None:  # 이전 방식(단일 assignee) 호환
        assignees = [body.get("assignee") or ""]
    a_ids, r_ids = user_ids(assignees), user_ids(body.get("reviewers") or [])
    if a_ids:
        payload["assignee_ids"] = a_ids
    if r_ids:
        payload["reviewer_ids"] = r_ids
    mr = gl(env, "POST", "/projects/%s/merge_requests" % pid(env), json=payload)
    return jsonify({"iid": mr["iid"], "url": mr["web_url"]})


@app.get("/api/env/<env_id>/assignees")
def api_assignees(env_id):
    env = get_env(env_id)
    q = request.args.get("q", "")
    users = gl(env, "GET", "/projects/%s/users" % pid(env), params={"search": q, "per_page": 20})
    return jsonify([{"username": u["username"], "name": u["name"]} for u in users])


@app.post("/api/env/<env_id>/atlantis")
def api_atlantis(env_id):
    env = get_env(env_id)
    body = request.get_json()
    action, iid = body.get("action"), body.get("iid")
    if action not in ("plan", "apply", "unlock") or not iid:
        raise ApiError("action(plan/apply/unlock)과 MR iid가 필요합니다")
    if action == "unlock" and not body.get("confirm_unlock"):
        raise ApiError("atlantis unlock 은 확인(confirm_unlock)이 필요합니다", 409, need_confirm=True)
    try:
        mr = gl(env, "GET", "/projects/%s/merge_requests/%s" % (pid(env), iid))
    except ApiError as e:
        raise ApiError("MR !%s 를 찾을 수 없습니다. MR iid를 확인하세요. (%s)" % (iid, str(e)[:120]))
    if mr.get("state") in ("merged", "closed"):
        raise ApiError("MR !%s 는 이미 %s 상태입니다. 새 MR 을 만들거나 열린 MR iid를 입력하세요" % (iid, mr["state"]))
    try:
        gl(env, "GET", "/projects/%s/repository/branches/%s" % (pid(env), quote(mr["source_branch"], safe="")))
    except ApiError:
        raise ApiError("MR !%s 의 소스 브랜치가 원격에 없습니다: %s\n브랜치가 삭제되었거나 push 되지 않았습니다. Commit/Push 후 다시 시도하거나, 현재 열린 MR 을 사용하세요" % (iid, mr["source_branch"]))
    if action == "apply":
        gate = apply_gate(env, iid, mr, bool(body.get("confirm_destroy")))
        if gate:
            reason, need_confirm, summary = gate
            raise ApiError(reason, 409, need_confirm=need_confirm, summary=summary)
    cmd = "atlantis unlock" if action == "unlock" else ("atlantis plan -d %s" % env["atlantis_dir"] if action == "plan" else "atlantis apply -d %s" % env["atlantis_dir"])
    note = gl(env, "POST", "/projects/%s/merge_requests/%s/notes" % (pid(env), iid), json={"body": cmd})
    if action == "plan":
        plan_put(env, iid, {"state": "pending", "sha": mr_sha(mr), "ts": time.time(), "note_id": note["id"], "applied": False, "plan": None})
    return jsonify({"note_id": note["id"], "command": cmd})


@app.get("/api/env/<env_id>/atlantis/plan-status")
def api_atlantis_plan_status(env_id):
    """apply 버튼 활성화/확인창용: 같은 MR 커밋에서 성공한 plan 이 있는지, 삭제·교체가 포함됐는지"""
    env = get_env(env_id)
    iid = request.args["iid"]
    mr = gl(env, "GET", "/projects/%s/merge_requests/%s" % (pid(env), iid))
    rec = plan_get(env, iid) or {}
    gate = apply_gate(env, iid, mr, False)
    tg = [t.strip() for t in request.args.get("targets", "").split(",") if t.strip()]
    try:
        expect = int(request.args.get("expect") or 0)
    except ValueError:
        expect = 0
    checks = plan_checks(rec, tg, expect) if rec else []
    failed = [c for c in checks if c["block"] and not c["ok"]]
    imp = rec.get("impact") or {}
    auto_ok = bool(rec) and rec.get("state") == "ok" and gate is None and not failed
    why = (gate[0] if gate else "") or ("%s (%s)" % (failed[0]["label"], failed[0]["detail"]) if failed else "") or ("" if auto_ok else "plan 결과가 '이상 없음'이 아닙니다")
    return jsonify({"exists": bool(rec), "state": rec.get("state"), "plan": rec.get("plan"),
                    "sha_match": (not rec.get("sha")) or rec.get("sha") == mr_sha(mr), "applied": bool(rec.get("applied")),
                    "can_apply": gate is None or bool(gate[1]), "need_confirm": bool(gate and gate[1]),
                    "reason": None if gate is None else gate[0],
                    "impact": {k: v[:30] for k, v in imp.items()}, "checks": checks, "auto_ok": auto_ok, "auto_reason": "" if auto_ok else why})


@app.get("/api/env/<env_id>/atlantis/output")
def api_atlantis_output(env_id):
    env = get_env(env_id)
    iid, since, action = request.args["iid"], int(request.args["since"]), request.args.get("action", "plan")
    notes = gl(env, "GET", "/projects/%s/merge_requests/%s/notes" % (pid(env), iid),
               params={"sort": "asc", "order_by": "created_at", "per_page": 100})
    new = [n for n in notes if n["id"] > since and not n["body"].lstrip().lower().startswith("atlantis ")]
    busy = [n for n in new if is_atlantis_busy_note(n["body"])]
    new = [n for n in new if not is_atlantis_busy_note(n["body"])]
    if busy and not new:
        return jsonify({"state": "pending", "busy": True, "body": "",
                        "headline": "⏳ 이미 실행 중인 plan(MR 생성 시 자동 실행)이 끝나기를 기다리는 중... 끝나면 그 결과를 표시합니다"})
    if not new:
        return jsonify({"state": "pending", "headline": "⏳ Atlantis 응답 대기 중...", "body": ""})
    body = "\n\n".join(n["body"] for n in new)
    res = analyze_atlantis(body, action)
    if action == "plan":
        plan_put(env, iid, {"state": res["state"], "plan": res.get("plan"), "impact": res.get("impact"), "ts": time.time()})
    elif res["state"] == "ok":
        plan_put(env, iid, {"applied": True})
    return jsonify({**res, "body": body})


# ----------------------------------------------------------------- 환경 ID 유일성 / 설정 정리
def env_slug(*parts):
    return re.sub(r"[^A-Za-z0-9_-]+", "-", "-".join(str(p) for p in parts if p)).strip("-")


def env_path_slug(kind, sg_dir):
    """kind + sg_rule 상위 경로 기준 ID 후보 (예: platform-megaport-sip-live-apne2-live)"""
    parts = [p for p in sg_dir.strip("/").split("/") if p not in ("sg", "sg_rule")]
    if parts and parts[0] == "aws":
        parts = parts[1:]
    return env_slug(kind, *parts)


def unique_env_id(base, taken):
    cand, i = base, 1
    while cand in taken:
        i += 1
        cand = "%s-%d" % (base, i)
    return cand


def stamp_meta(meta, cfg):
    """meta.envs[환경ID] 에 그 환경의 sg_dir/표시 이름을 함께 기록 (환경 ID 가 바뀌거나 환경이 지워져도 어느 환경 것인지 알 수 있게)"""
    byid = {e["id"]: e for e in cfg["environments"]}
    for eid, em in (meta.get("envs") or {}).items():
        if eid in byid and isinstance(em, dict):
            em["_sg_dir"] = byid[eid]["sg_dir"]
            em["_label"] = " · ".join(x for x in (byid[eid].get("group"), byid[eid].get("env"), byid[eid].get("label")) if x)
    return meta


def backup_data():
    """config.json / meta.json 을 data/backup/<날짜_시간>/ 에 복사 (토큰이 든 local.json 은 복사하지 않음)"""
    dest = os.path.join(DATA, "backup", datetime.now().strftime("%y%m%d_%H%M%S"))
    os.makedirs(dest, exist_ok=True)
    for p in (CONFIG_PATH, META_PATH):
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(dest, os.path.basename(p)))
    prune_backups()
    return dest


def prune_backups(keep=20):
    """data/backup 아래 날짜_시간 폴더 중 오래된 것을 지운다 (최근 keep 개 유지)"""
    root = os.path.join(DATA, "backup")
    if not os.path.isdir(root):
        return []
    dirs = sorted(d for d in os.listdir(root) if re.match(r"^\d{6}_\d{6}$", d) and os.path.isdir(os.path.join(root, d)))
    gone = dirs[:-keep] if len(dirs) > keep else []
    for d in gone:
        shutil.rmtree(os.path.join(root, d), ignore_errors=True)
    return gone


def plan_env_repair(cfg, meta, remove_stale=False, remove_orphans=False):
    """중복 환경 ID 정리 계획: 첫 번째 환경은 ID 유지, 나머지는 경로 기반 새 ID 부여.
    중복 ID 에 붙어 있던 메타(SG 별명/태그)는 SG 파일이 실제로 있는 환경으로 옮긴다. (설정/메타는 복사본에 계산, 저장은 호출자)"""
    envs = cfg["environments"]
    counts = {}
    for e in envs:
        counts[e["id"]] = counts.get(e["id"], 0) + 1
    taken, seen, changes = set(counts), set(), []
    owners = {}  # 중복 ID -> [(환경 dict, 새 ID)]
    for e in envs:
        old = e["id"]
        if counts[old] > 1:
            if old not in seen:
                seen.add(old)
                owners.setdefault(old, []).append((e, old))
                continue
            new = unique_env_id(env_path_slug(e["kind"], e["sg_dir"]), taken)
            taken.add(new)
            changes.append({"old": old, "new": new, "sg_dir": e["sg_dir"], "env": e.get("env"), "label": e.get("label", "")})
            e["id"] = new
            owners.setdefault(old, []).append((e, new))
    # 메타 이동
    moved, ambiguous = [], []
    menvs = meta.setdefault("envs", {})
    for old, lst in owners.items():
        if len(lst) < 2 or old not in menvs:
            continue
        names = {}
        for e, nid in lst:
            try:
                r = _resolve_env(e, cfg)
                names[nid] = {x["name"] for x in list_sgs(r)}
            except ApiError:
                names[nid] = set()
        for sg, val in list((menvs[old].get("sgs") or {}).items()):
            own = [nid for nid, n in names.items() if sg in n]
            if len(own) == 1 and own[0] != old:
                menvs.setdefault(own[0], {}).setdefault("sgs", {})[sg] = val
                del menvs[old]["sgs"][sg]
                moved.append({"sg": sg, "to": own[0]})
            elif len(own) != 1:
                ambiguous.append({"sg": sg, "kept_on": old})
        if menvs[old].get("subnets"):
            ambiguous.append({"sg": "(환경 정보: 서브넷/VPC/NAT)", "kept_on": old})
    # 저장소에 폴더가 없는 환경 (저장소가 이미 내려받아져 있는 경우만 판정)
    stale = []
    for e in envs:
        try:
            r = _resolve_env(e, cfg)
        except ApiError:
            continue
        if os.path.isdir(os.path.join(r["repo_dir"], ".git")) and not os.path.isdir(sg_path(r)):
            stale.append({"id": e["id"], "env": e.get("env"), "label": e.get("label", ""), "sg_dir": e["sg_dir"], "group": e.get("group")})
    if remove_stale:
        gone = {s["id"] for s in stale}
        cfg["environments"] = [e for e in envs if e["id"] not in gone]
    # 고아 메타: 환경 목록에 없는 ID 의 메타. 기록된 sg_dir 와 같은 경로의 환경이 있으면 그 환경으로 옮기고, 없으면 목록만 보고(선택 삭제)
    valid = {e["id"] for e in cfg["environments"]}
    by_dir = {}
    for e in cfg["environments"]:
        by_dir.setdefault((e["kind"], e["sg_dir"]), []).append(e["id"])
    rekey, orphans = [], []
    for eid, em in list(menvs.items()):
        if eid in valid or not isinstance(em, dict):
            continue
        has_data = bool(em.get("sgs") or em.get("subnets"))
        targets = [t for (k, d), ids in by_dir.items() if d == em.get("_sg_dir") for t in ids]
        if has_data and len(targets) == 1:
            dest = menvs.setdefault(targets[0], {})
            for sgn, val in (em.get("sgs") or {}).items():
                dest.setdefault("sgs", {}).setdefault(sgn, val)
            if em.get("subnets") and not dest.get("subnets"):
                dest["subnets"] = em["subnets"]
            del menvs[eid]
            rekey.append({"from": eid, "to": targets[0], "sgs": len(em.get("sgs") or {})})
        elif has_data:
            orphans.append({"id": eid, "label": em.get("_label", ""), "sg_dir": em.get("_sg_dir", ""), "sgs": len(em.get("sgs") or {}), "subnets": len(em.get("subnets") or [])})
        elif remove_orphans:
            del menvs[eid]
    removed_orphans = []
    if remove_orphans:
        for o in orphans:
            menvs.pop(o["id"], None)
            removed_orphans.append(o["id"])
    stamp_meta(meta, cfg)
    return {"changes": changes, "meta_moved": moved, "meta_ambiguous": ambiguous, "stale": stale, "meta_rekey": rekey,
            "meta_orphans": orphans, "orphans_removed": removed_orphans,
            "duplicate_ids": sorted(k for k, v in counts.items() if v > 1)}


@app.post("/api/config/repair")
@cfg_locked
def api_config_repair():
    """중복 환경 ID 정리(+선택: 폴더가 없는 환경 제거). dry_run=true 면 계획만 계산. 적용 전에 data/backup 에 백업."""
    body = request.get_json() or {}
    cfg, meta = load_config(), load_meta()
    report = plan_env_repair(cfg, meta, remove_stale=bool(body.get("remove_stale")), remove_orphans=bool(body.get("remove_orphans")))
    if body.get("dry_run", True):
        return jsonify({"dry_run": True, **report})
    changed = bool(report["changes"] or report["meta_moved"] or report["meta_rekey"] or report["orphans_removed"] or (body.get("remove_stale") and report["stale"]))
    if not changed:
        return jsonify({"dry_run": False, "backup": None, **report})
    dest = backup_data()
    write_json(CONFIG_PATH, cfg)
    write_json(META_PATH, meta)
    return jsonify({"dry_run": False, "backup": dest, **report})


# ----------------------------------------------------------------- 로컬 접근 보호 (Host / Origin 검사)
def _host_only(hostport):
    h = (hostport or "").strip().lower()
    if h.startswith("["):
        return h[1:h.find("]")] if "]" in h else h
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


def allowed_hosts():
    hosts = {"127.0.0.1", "localhost", "::1"}
    hosts |= {x.strip().lower() for x in os.environ.get("TF_ACL_ALLOWED_HOSTS", "").split(",") if x.strip()}
    return hosts


@app.before_request
def _guard_local_only():
    """다른 웹페이지가 내 PC 의 이 도구 API 를 몰래 호출하지 못하도록 Host/Origin 을 검사한다 (DNS rebinding / CSRF 방어)"""
    if not request.path.startswith("/api/") or os.environ.get("TF_ACL_DISABLE_HOST_CHECK") == "1":
        return None
    host = _host_only(request.host)
    if host not in allowed_hosts():
        return jsonify({"error": "허용되지 않은 접속 주소입니다 (%s). 다른 주소로 접속하려면 환경변수 TF_ACL_ALLOWED_HOSTS 에 추가하세요" % host}), 403
    origin = request.headers.get("Origin")
    if origin and urlparse(origin).netloc.lower() != (request.host or "").lower():
        return jsonify({"error": "다른 출처(Origin)에서 온 요청은 허용되지 않습니다"}), 403
    if request.headers.get("Sec-Fetch-Site") == "cross-site":
        return jsonify({"error": "다른 사이트에서 온 요청은 허용되지 않습니다"}), 403
    return None


# ----------------------------------------------------------------- 서버 재시작
def _spawn_restart():
    """2초 뒤 같은 명령으로 서버를 다시 띄우는 보조 프로세스를 시작 (이 프로세스가 먼저 종료되어 포트를 비움)"""
    code = ("import subprocess,sys,time;time.sleep(2);"
            "subprocess.Popen([sys.executable,sys.argv[1]],cwd=sys.argv[2],creationflags=int(sys.argv[3]))")
    subprocess.Popen([sys.executable, "-c", code, os.path.abspath(__file__), BASE, str(getattr(subprocess, "CREATE_NEW_CONSOLE", 0))],
                     cwd=BASE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _do_restart():
    _spawn_restart()
    os._exit(0)


@app.post("/api/restart")
def api_restart():
    if not (request.get_json(silent=True) or {}).get("confirm"):
        raise ApiError("재시작 확인(confirm)이 필요합니다")
    threading.Timer(0.8, lambda: _do_restart()).start()
    return jsonify({"ok": True})


# ----------------------------------------------------------------- push 전 최신 여부 확인
def check_freshness(env, branch):
    """대상 브랜치가 앞서 있는지, 같은 SG 파일이 서로 바뀌었는지(충돌 가능), 원격 작업 브랜치가 앞서 있는지 확인.
    git fetch 로 원격 정보만 갱신한다 (파일/브랜치는 바꾸지 않음)."""
    try:
        run_git(env, "fetch", "origin", auth=True)
    except ApiError as e:
        return {"checked": False, "error": str(e).splitlines()[0][:200]}
    tb = env["target_branch"] or "main"
    base = "origin/%s" % tb
    if not run_git(env, "rev-parse", "--verify", "-q", base, check=False).strip():
        return {"checked": True, "target": tb, "behind": 0, "overlap": [], "remote_ahead": 0, "note": "대상 브랜치를 찾지 못함"}
    behind = int(run_git(env, "rev-list", "--count", "HEAD..%s" % base, check=False).strip() or 0)
    scope = scope_paths(env)
    mb = run_git(env, "merge-base", "HEAD", base, check=False).strip()
    theirs, mine = set(), set()
    if mb and behind:
        theirs = {x.strip() for x in run_git(env, "diff", "--name-only", mb, base, "--", *scope, check=False).splitlines() if x.strip()}
        mine = {x.strip() for x in run_git(env, "diff", "--name-only", mb, "--", *scope, check=False).splitlines() if x.strip()}
        mine |= {x.strip() for x in run_git(env, "ls-files", "--others", "--exclude-standard", "--", *scope, check=False).splitlines() if x.strip()}
    remote_ahead = 0
    if branch and run_git(env, "rev-parse", "--verify", "-q", "origin/%s" % branch, check=False).strip():
        remote_ahead = int(run_git(env, "rev-list", "--count", "HEAD..origin/%s" % branch, check=False).strip() or 0)
    return {"checked": True, "target": tb, "behind": behind, "overlap": sorted(theirs & mine), "remote_ahead": remote_ahead}


# ----------------------------------------------------------------- IP/대역으로 규칙 일괄 삭제
def _targets_for_scope(env, name, scope):
    if scope == "sg":
        return [(env, name)]
    if scope == "env":
        return [(env, s["name"]) for s in list_sgs(env)]
    if scope == "repo":
        root = os.path.normcase(os.path.abspath(env["repo_dir"]))
        out, seen = [], set()
        for e in load_config()["environments"]:
            try:
                x = _resolve_env(e, load_config())
            except ApiError:
                continue
            if os.path.normcase(os.path.abspath(x["repo_dir"])) != root or (x["sg_dir"], x["kind"]) in seen:
                continue
            seen.add((x["sg_dir"], x["kind"]))
            out += [(x, s["name"]) for s in list_sgs(x)]
        return out
    raise ApiError("scope 는 sg/env/repo 중 하나여야 합니다")


@app.post("/api/bulk-delete")
def api_bulk_delete():
    """IP/대역이 소스인 규칙을 SG/환경/저장소 범위에서 찾아 삭제 (dry_run=true 면 미리보기만).
    규칙 하나에 CIDR 이 여러 개면 일치하는 CIDR 만 빼고, 모두 빠지면 규칙을 삭제. SG ID 소스 규칙은 건드리지 않음."""
    body = request.get_json() or {}
    env = get_env(body.get("env_id", ""))
    nets = []
    for q in body.get("ips") or []:
        n = _net(q)
        if n is None:
            raise ApiError("IP/CIDR 형식이 올바르지 않습니다: %s" % q)
        nets.append(n)
    if not nets:
        raise ApiError("삭제할 IP/대역을 입력하세요")
    mode = body.get("match", "exact")
    dirs = [d for d in (body.get("directions") or ["ingress", "egress"]) if d in ("ingress", "egress")]
    dry = bool(body.get("dry_run", True))
    if not dry:
        require_work_branch(env)   # 삭제는 작업 브랜치에서만 (변경 대상이 없어도 먼저 확인)

    def hit(c):
        n = _net(c)
        return bool(n) and any(q.version == n.version and (n == q if mode == "exact" else n.overlaps(q)) for q in nets)
    plans, out = [], []
    if body.get("targets"):   # 마법사: 선택한 여러 SG (같은 저장소의 환경들)
        pairs = []
        for t in body["targets"][:100]:
            check_name(t.get("name", ""))
            pairs.append((get_env(t.get("env_id", env["id"])), t["name"]))
    else:
        pairs = _targets_for_scope(env, body.get("name", ""), body.get("scope", "sg"))
    for e, name in pairs:
        old = load_sg(e, name)
        new = json.loads(json.dumps(old))
        removed, modified = [], []
        for d in dirs:
            keep = []
            for r in new[d]:
                cidrs = r["cidr_blocks"]
                rest = [c for c in cidrs if not hit(c)] if cidrs and not r["security_groups"] else cidrs
                if len(rest) == len(cidrs):
                    keep.append(r)
                elif rest:
                    modified.append({"direction": d, **r, "removed_cidrs": [c for c in cidrs if c not in rest]})
                    keep.append(dict(r, cidr_blocks=rest))
                else:
                    removed.append({"direction": d, **r})
            new[d] = keep
        if removed or modified:
            errors, warnings, risks = validate_sg(e, new, old)
            plans.append((e, name, new))
            out.append({"env_id": e["id"], "name": name, "removed": removed, "modified": modified, "errors": errors})
    if dry:
        return jsonify({"results": out, "total_removed": sum(len(x["removed"]) for x in out), "total_modified": sum(len(x["modified"]) for x in out)})
    if any(x["errors"] for x in out):
        raise ApiError("검증 오류가 있어 아무것도 삭제하지 않았습니다", 400, results=out)
    for e, _n, _new in plans:
        require_work_branch(e)
    for e, name, new in plans:
        save_sg(e, name, new)
    return jsonify({"ok": True, "results": out, "total_removed": sum(len(x["removed"]) for x in out), "total_modified": sum(len(x["modified"]) for x in out)})


# ----------------------------------------------------------------- 영향 분석 보고서
def _file_to_sg(env, rel):
    """저장소 상대 경로 -> (환경, SG 이름). 같은 저장소의 환경들 중 sg_dir 가 맞는 것"""
    root = os.path.normcase(os.path.abspath(env["repo_dir"]))
    for e in load_config()["environments"]:
        try:
            x = _resolve_env(e, load_config())
        except ApiError:
            continue
        sd = x["sg_dir"].strip("/")
        if os.path.normcase(os.path.abspath(x["repo_dir"])) == root and rel.startswith(sd + "/"):
            fn = rel[len(sd) + 1:]
            if "/" in fn:
                continue
            m = GAME_FILE_RE.match(fn)
            if x["kind"] == "game":
                return (x, m.group(1)) if m else None
            if m and _is_list_file(os.path.join(x["repo_dir"], *rel.split("/"))):
                return (x, m.group(1))
            return (x, fn[:-5]) if fn.endswith(".json") else None
    return None


def _branch_base(env):
    tb = env["target_branch"] or "main"
    for ref in ("origin/%s" % tb, tb):
        if run_git(env, "rev-parse", "--verify", "-q", ref, check=False).strip():
            mb = run_git(env, "merge-base", "HEAD", ref, check=False).strip()
            if mb:
                return mb, ref
    return "HEAD", "HEAD"


def _rules_at(env, ref, rel, key=None):
    p = subprocess.run(["git", "show", "%s:%s" % (ref, rel)], cwd=env["repo_dir"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        return []
    try:
        data = json.loads(p.stdout.lstrip("﻿"))
    except ValueError:
        return []
    return [norm_rule(r, env["kind"]) for r in (data.get(key, []) if key else data)]


def change_summary(env):
    st = git_status(env, fresh=True)
    if not st.get("cloned"):
        raise ApiError("저장소가 아직 clone 되지 않았습니다")
    mb, ref = _branch_base(env)
    scope = scope_paths(env)
    files = {x.strip() for x in run_git(env, "diff", "--name-only", mb, "--", *scope, check=False).splitlines() if x.strip()}
    files |= {x.strip() for x in run_git(env, "ls-files", "--others", "--exclude-standard", "--", *scope, check=False).splitlines() if x.strip()}
    groups = {}
    for rel in sorted(files):
        t = _file_to_sg(env, rel)
        if t:
            groups.setdefault((t[0]["id"], t[1]), t)
    sgs, risks_all = [], []
    for (eid, name), (e, _n) in sorted(groups.items()):
        try:
            cur = load_sg(e, name)
        except ApiError:
            cur = {"ingress": [], "egress": []}
        if split_sg(e, name):
            old = {d: _rules_at(e, mb, sg_rel(e, "%s-%s-rules.json" % (name, d))) for d in ("ingress", "egress")}
        else:
            old = {d: _rules_at(e, mb, sg_rel(e, name + ".json"), d) for d in ("ingress", "egress")}
        added, removed = _rule_diff(old, cur)
        if not added and not removed:
            continue
        errors, warnings, risks = validate_sg(e, cur, old)
        risks_all += ["%s: %s" % (name, r) for r in risks]
        sgs.append({"env_id": eid, "env": "%s · %s%s" % (e.get("group", ""), e.get("env", ""), (" · " + e["label"]) if e.get("label") else ""),
                    "name": name, "added": added, "removed": removed, "risks": risks, "warnings": warnings})
    totals = {"sgs": len(sgs), "added": sum(len(s["added"]) for s in sgs), "removed": sum(len(s["removed"]) for s in sgs), "risks": len(risks_all)}
    return {"branch": st["branch"], "base": ref, "sgs": sgs, "totals": totals, "risks": risks_all, "markdown": _change_markdown(st["branch"], ref, sgs, totals, risks_all)}


def _rule_cells(r):
    port = "전체" if str(r["protocol"]) == "-1" else (str(r["from_port"]) if r["from_port"] == r["to_port"] else "%s-%s" % (r["from_port"], r["to_port"]))
    src = r["security_groups"] or ", ".join(r["cidr_blocks"]) or "-"
    return str(r["protocol"]).upper() if str(r["protocol"]) != "-1" else "ALL", port, src, (r["description"] or "").replace("|", "/")


def _change_markdown(branch, base, sgs, totals, risks):
    lines = ["### SG 변경 요약", "", "- 브랜치: `%s` (기준 `%s`)" % (branch, base),
             "- 변경된 SG %d개 · 규칙 추가 %d건 / 삭제 %d건 · 위험 규칙 %d건" % (totals["sgs"], totals["added"], totals["removed"], totals["risks"]), ""]
    if sgs:
        lines += ["| 환경 | SG | 구분 | 방향 | 프로토콜 | 포트 | 소스 | 설명 |", "|---|---|---|---|---|---|---|---|"]
        for s in sgs:
            for kind, items in (("➕ 추가", s["added"]), ("➖ 삭제", s["removed"])):
                for r in items:
                    pr, port, src, desc = _rule_cells(r)
                    lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (s["env"], s["name"], kind, "인바운드" if r["direction"] == "ingress" else "아웃바운드", pr, port, src, desc))
    else:
        lines.append("(변경된 SG 규칙이 없습니다)")
    if risks:
        lines += ["", "**⚠ 위험 규칙**"] + ["- " + r for r in risks]
    return "\n".join(lines) + "\n"


@app.get("/api/env/<env_id>/report/changes")
def api_report_changes(env_id):
    """이번 작업(브랜치)의 변경 요약: 추가/삭제 규칙, 영향받는 SG·환경, 위험 규칙 + MR/Jira 에 붙일 마크다운"""
    return jsonify(change_summary(get_env(env_id)))


def usage_rows(q):
    q = (q or "").strip()
    if not q:
        return []
    ql, qnet = q.lower(), _net(q)
    meta = load_meta().get("envs", {})
    sgids = set()
    if q.lower().startswith("sg-"):
        sgids.add(ql)
    rows = []
    cfg = load_config()
    seen_dirs = set()
    envs = []
    for ce in cfg["environments"]:
        try:
            envs.append(_resolve_env(ce, cfg))
        except ApiError:
            continue
    for env in envs:                       # SG 이름으로 검색하면 그 SG 의 SG ID 를 소스로 쓰는 규칙(참조 관계)도 찾는다
        for sg in list_sgs(env):
            m = meta.get(env["id"], {}).get("sgs", {}).get(sg["name"], {})
            if ql in (sg["name"].lower(), short_name(env, sg["name"]).lower()) and m.get("sg_id"):
                sgids.add(m["sg_id"].lower())
    for env in envs:
        key = (os.path.normcase(os.path.abspath(env["repo_dir"])), env["sg_dir"], env["kind"])
        if key in seen_dirs:
            continue
        seen_dirs.add(key)
        label = " · ".join(x for x in (env.get("group"), env.get("env"), env.get("label")) if x)
        for sg in list_sgs(env):
            try:
                data = _cached_sg(env, sg["name"])
            except Exception as exc:
                log_event("WARN", "사용처 조회 중 SG 파일을 읽지 못했습니다 %s/%s: %r" % (env.get("id"), sg["name"], exc))
                continue
            for d in ("ingress", "egress"):
                for r in data[d]:
                    why = []
                    for c in r["cidr_blocks"]:
                        n = _net(c)
                        if qnet and n and qnet.version == n.version and qnet.overlaps(n):
                            why.append("IP/대역 겹침 (%s)" % c)
                        elif ql in c.lower():
                            why.append("IP 문자열 일치")
                    if r["security_groups"] and (r["security_groups"].lower() in sgids or ql in r["security_groups"].lower()):
                        why.append("SG 참조")
                    if ql in (r["description"] or "").lower():
                        why.append("설명 일치")
                    if why:
                        pr, port, src, desc = _rule_cells(r)
                        rows.append({"env_id": env["id"], "env": label, "sg": sg["name"], "direction": d, "protocol": pr, "port": port,
                                     "source": src, "description": r["description"], "match": " / ".join(dict.fromkeys(why))})
    return rows


@app.get("/api/report/usage")
def api_report_usage():
    """IP/대역/SG(이름·ID)/문구가 쓰이는 모든 규칙 목록 (format=json|csv|md). SG 이름·ID 로 검색하면 참조 관계도 포함"""
    q, fmt = request.args.get("q", ""), request.args.get("format", "json")
    rows = usage_rows(q)
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["환경", "SG", "방향", "프로토콜", "포트", "소스", "설명", "일치 이유"])
        for r in rows:
            w.writerow([r["env"], r["sg"], r["direction"], r["protocol"], r["port"], r["source"], r["description"], r["match"]])
        return Response("﻿" + buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=usage-report.csv"})
    if fmt == "md":
        md = ["### 사용처 보고서: `%s` (%d건)" % (q, len(rows)), "", "| 환경 | SG | 방향 | 프로토콜 | 포트 | 소스 | 설명 | 일치 |", "|---|---|---|---|---|---|---|---|"]
        md += ["| %s | %s | %s | %s | %s | %s | %s | %s |" % (r["env"], r["sg"], r["direction"], r["protocol"], r["port"], r["source"], (r["description"] or "").replace("|", "/"), r["match"]) for r in rows]
        return Response("\n".join(md) + "\n", mimetype="text/markdown")
    return jsonify({"q": q, "count": len(rows), "rows": rows[:2000]})


@app.get("/api/log")
def api_log():
    """data/app.log 의 마지막 줄들 (최대 1000줄). 토큰은 기록 단계에서 가려짐"""
    n = max(10, min(int(request.args.get("lines", 300)), 1000))
    path = os.path.join(DATA, "app.log")
    if not os.path.exists(path):
        return jsonify({"lines": [], "path": path})
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    return jsonify({"lines": lines[-n:], "path": path, "total": len(lines)})


# ----------------------------------------------------------------- 엑셀 연동 / AWS / 자가점검 / 백업 은 app_parts/ 에 있다
_include("excel")
_include("aws_info")
_include("aws_compare")
_include("selfcheck")


# ----------------------------------------------------------------- 배포용 zip (화면의 '배포' 메뉴)
def _dist_module():
    import importlib.util
    path = os.path.join(BASE, "make_dist.py")
    if not os.path.exists(path):
        raise ApiError("make_dist.py 가 없어 배포 파일을 만들 수 없습니다", 404)
    spec = importlib.util.spec_from_file_location("make_dist_mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@app.get("/api/dist/info")
def api_dist_info():
    md = _dist_module()
    cfg = load_config()
    return jsonify({"version": VERSION, "files": len(md.collect()), "filename": "Traform-ACL-Tool-%s.zip" % VERSION,
                    "environments": len(cfg.get("environments", [])), "has_meta": os.path.exists(META_PATH),
                    "excluded": ["data/local.json (토큰)", "data/history.json (작업 이력)", "data/plans.json", "data/undo.json", "data/backup/", "data/app.log", "repos/ (받은 저장소)"]})


@app.get("/api/dist/zip")
def api_dist_zip():
    """배포용 zip 을 만들어 내려보낸다 (토큰/이력은 들어가지 않음, 내 PC 경로는 비움)"""
    md = _dist_module()
    try:
        name, data = md.build_bytes(request.args.get("with_config") == "1", DATA, request.args.get("with_meta") == "1")
    except md.DistError as e:
        raise ApiError(str(e), 400)
    log_event("INFO", "배포용 zip 생성: %s (%d bytes, config=%s, meta=%s)" % (name, len(data), request.args.get("with_config"), request.args.get("with_meta")))
    return Response(data, mimetype="application/zip", headers={"Content-Disposition": 'attachment; filename="%s"' % name})


_include("policy")
_include("review")
_include("objects")
_include("jira_auto")
_include("audit")
_include("backup")


# ----------------------------------------------------------------- 버전 / 서버 코드 변경 감지
VERSION = "1.17.0"
START_TIME = time.time()
_START_MTIME = _code_mtime()


@app.get("/api/version")
def api_version():
    """화면이 서버 코드의 변경/버전 불일치(=서버 재시작 필요)를 알 수 있게 한다"""
    cur = _code_mtime()
    return jsonify({"version": VERSION, "started": START_TIME, "stale": cur > _START_MTIME + 1, "today": datetime.now().strftime("%y%m%d"),
                    "demo": os.environ.get("TF_ACL_DEMO") == "1"})


# ----------------------------------------------------------------- 작업 이력 (서버 보관: 새로고침/다른 PC·브라우저에서도 유지)
HISTORY_PATH = os.path.join(DATA, "history.json")
HIST_LOCK = threading.Lock()
HIST_FIELDS = ("id", "ts", "t", "step", "kind", "state", "headline", "text", "poll", "user", "meta", "hint", "ekind")


def _hist_clean(e):
    out = {k: e.get(k) for k in HIST_FIELDS if k in e}
    if not out.get("id"):
        raise ApiError("이력 항목에 id 가 필요합니다")
    out["text"] = str(out.get("text") or "")[:80000]
    out["user"] = out.get("user") or load_local().get("account", "")
    return out


def _hist_key(v):
    k = str(v or "").strip()
    if not k or len(k) > 300:
        raise ApiError("이력 key 가 올바르지 않습니다")
    return k


@app.get("/api/history")
def api_history_get():
    return jsonify({"entries": read_json(HISTORY_PATH, {}).get(_hist_key(request.args.get("key")), [])})


@app.post("/api/history")
def api_history_add():
    body = request.get_json() or {}
    key, entry = _hist_key(body.get("key")), _hist_clean(body.get("entry") or {})
    with HIST_LOCK:
        h = read_json(HISTORY_PATH, {})
        lst = h.setdefault(key, [])
        lst.append(entry)
        h[key] = lst[-200:]
        if len(h) > 100:
            for k in sorted(h, key=lambda x: (h[x][-1].get("ts") or 0) if h[x] else 0)[:len(h) - 100]:
                h.pop(k, None)
        write_json(HISTORY_PATH, h)
    return jsonify({"ok": True, "id": entry["id"]})


@app.patch("/api/history/<hid>")
def api_history_patch(hid):
    body = request.get_json() or {}
    key, patch = _hist_key(body.get("key")), body.get("patch") or {}
    with HIST_LOCK:
        h = read_json(HISTORY_PATH, {})
        x = next((e for e in h.get(key, []) if e.get("id") == hid), None)
        if x is None:
            raise ApiError("이력 항목을 찾을 수 없습니다", 404)
        for k, v in patch.items():
            if k in HIST_FIELDS and k != "id":
                x[k] = str(v)[:80000] if k == "text" else v
        write_json(HISTORY_PATH, h)
    return jsonify({"ok": True})


@app.delete("/api/history")
def api_history_clear():
    key = _hist_key(request.args.get("key"))
    with HIST_LOCK:
        h = read_json(HISTORY_PATH, {})
        h.pop(key, None)
        write_json(HISTORY_PATH, h)
    return jsonify({"ok": True})


@app.post("/api/history/import")
def api_history_import():
    """브라우저(localStorage)에 있던 예전 이력을 서버가 비어 있을 때 한 번 가져온다"""
    body = request.get_json() or {}
    key = _hist_key(body.get("key"))
    with HIST_LOCK:
        h = read_json(HISTORY_PATH, {})
        if h.get(key):
            return jsonify({"ok": True, "imported": 0})
        items = [_hist_clean(e) for e in (body.get("entries") or []) if e.get("id")]
        h[key] = items[-200:]
        write_json(HISTORY_PATH, h)
    return jsonify({"ok": True, "imported": len(items)})


# ----------------------------------------------------------------- Jira 연동 (선택 기능: 환경설정에서 주소/토큰을 입력해야 활성화)
JIRA_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]+-\d+$")


DEFAULT_JIRA_URL = "https://jira.smilegate.net"


def jira_settings():
    """주소는 GitLab 주소처럼 config.json(공유)의 settings.jira_url, 인증정보(API 키 등)는 local.json(개인)"""
    j = load_local().get("jira") or {}
    url = (load_config().get("settings", {}).get("jira_url") or j.get("base_url") or DEFAULT_JIRA_URL).strip().rstrip("/")
    return {"base_url": url, "auth": j.get("auth") or "bearer", "user": j.get("user") or "",
            "token": j.get("token") or "", "ssl_verify": j.get("ssl_verify", True)}


def jira_call(method, path, **kw):
    j = jira_settings()
    if not j["base_url"] or not j["token"]:
        raise ApiError("환경설정에서 Jira 주소와 토큰을 먼저 입력하세요")
    headers, auth = {"Accept": "application/json"}, None
    if j["auth"] == "basic":
        auth = (j["user"], j["token"])
    else:
        headers["Authorization"] = "Bearer " + j["token"]
    try:
        r = requests.request(method, j["base_url"] + "/rest/api/2" + path, headers=headers, auth=auth, timeout=20,
                             verify=j["ssl_verify"], **kw)
    except requests.RequestException as e:
        raise ApiError("Jira 에 연결하지 못했습니다: %s" % str(e).replace(j["token"], "***")[:200], 502)
    if r.status_code in (401, 403):
        raise ApiError("Jira 인증/권한 오류(%s). 토큰과 인증 방식을 확인하세요" % r.status_code, 502)
    if r.status_code == 404:
        raise ApiError("Jira 에서 찾을 수 없습니다 (이슈 키 또는 주소 확인)", 404)
    if r.status_code >= 400:
        raise ApiError("Jira 오류 %s: %s" % (r.status_code, r.text[:200].replace(j["token"], "***")), 502)
    return r.json() if r.text.strip() else {}


@app.get("/api/jira/test")
def api_jira_test():
    """연결 테스트 (읽기 전용): 입력한 API 키로 인증되는 사용자 정보를 조회"""
    d = jira_call("GET", "/myself")
    return jsonify({"ok": True, "name": d.get("name") or d.get("accountId", ""), "displayName": d.get("displayName", ""),
                    "email": d.get("emailAddress", ""), "base_url": jira_settings()["base_url"]})


@app.get("/api/jira/issue")
def api_jira_issue():
    """티켓번호 확인 (읽기 전용): 제목/상태/담당자"""
    key = (request.args.get("key") or "").strip().upper()
    if not JIRA_KEY_RE.match(key):
        raise ApiError("티켓번호 형식이 올바르지 않습니다 (예: ISRIR-12345)")
    d = jira_call("GET", "/issue/%s" % key, params={"fields": "summary,status,assignee,issuetype"})
    f = d.get("fields") or {}
    return jsonify({"key": d.get("key", key), "summary": f.get("summary", ""), "status": (f.get("status") or {}).get("name", ""),
                    "assignee": (f.get("assignee") or {}).get("displayName", ""), "type": (f.get("issuetype") or {}).get("name", ""),
                    "url": "%s/browse/%s" % (jira_settings()["base_url"], key)})


@app.post("/api/jira/comment")
def api_jira_comment():
    """Jira 이슈에 코멘트 작성 — 화면에서 사용자가 내용을 확인하고 누른 경우에만 호출된다"""
    body = request.get_json() or {}
    key, text = str(body.get("key", "")).strip().upper(), str(body.get("body", "")).strip()
    if not JIRA_KEY_RE.match(key):
        raise ApiError("티켓번호 형식이 올바르지 않습니다")
    if not text or len(text) > 8000:
        raise ApiError("코멘트 내용이 비어 있거나 너무 깁니다 (최대 8000자)")
    jira_call("POST", "/issue/%s/comment" % key, json={"body": text})
    return jsonify({"ok": True, "url": "%s/browse/%s" % (jira_settings()["base_url"], key)})


# ----------------------------------------------------------------- 같은 규칙을 여러 SG(환경)에 한 번에 적용
DEST_RE = re.compile(r"^(tf_\d{6}_[A-Za-z]+-\d+_.+?) to (.+) Connection$")


def short_name(env, name):
    n = name
    if env["kind"] == "game":
        p = env.get("file_prefix") or ""
        if p and n.startswith(p):
            n = n[len(p):]
        n = re.sub(r"-sg$", "", n)
    return n


def _rule_key(r):
    return json.dumps([str(r["protocol"]).lower(), r["from_port"], r["to_port"], sorted(r["cidr_blocks"]), r["security_groups"]])


@app.post("/api/bulk-apply")
def api_bulk_apply():
    """선택한 규칙을 여러 SG(같은 저장소의 다른 환경 포함)에 추가. dry_run=1 이면 저장 없이 대상별 결과만 계산.
    - 이미 같은 규칙(프로토콜/포트/소스)이 있으면 건너뜀, retarget_desc 이면 설명의 '목적지'를 대상 SG 이름으로 변경
    - 대상 중 하나라도 검증 오류가 있으면 아무것도 저장하지 않음 / 위험 규칙은 confirm_risk 필요"""
    body = request.get_json() or {}
    rules, targets = body.get("rules") or [], body.get("targets") or []
    dry, retarget = bool(body.get("dry_run")), bool(body.get("retarget_desc"))
    if not rules or len(rules) > 50 or not targets or len(targets) > 100:
        raise ApiError("규칙(1~50개)과 대상 SG(1~100개)를 선택하세요")
    plans = []
    for t in targets:
        env = get_env(t.get("env_id", ""))
        check_name(t.get("name", ""))
        if not dry:
            require_work_branch(env)
        old = load_sg(env, t["name"])
        new = json.loads(json.dumps(old))
        have = {d: {_rule_key(r) for r in new[d]} for d in ("ingress", "egress")}
        added = skipped = 0
        for raw in rules:
            d = raw.get("direction", "ingress")
            if d not in ("ingress", "egress"):
                raise ApiError("direction 은 ingress/egress 이어야 합니다")
            r = norm_rule(raw, env["kind"])
            if retarget:
                m = DEST_RE.match(r["description"])
                if m:
                    r["description"] = "%s to %s Connection" % (m.group(1), short_name(env, t["name"]))
            if _rule_key(r) in have[d]:
                skipped += 1
                continue
            have[d].add(_rule_key(r))
            new[d].append(r)
            added += 1
        errors, warnings, risks = validate_sg(env, new, old)
        try:
            already = already_open_info(env, t["name"], new, old)["already"] if dry else []
        except Exception:
            already = []
        plans.append({"env_id": env["id"], "name": t["name"], "added": added, "skipped": skipped,
                      "errors": errors, "warnings": warnings, "risks": risks, "already": already, "_env": env, "_new": new})
    out = [{k: v for k, v in p.items() if not k.startswith("_")} for p in plans]
    if dry:
        return jsonify({"results": out})
    if any(p["errors"] for p in plans):
        raise ApiError("검증 오류가 있어 아무것도 저장하지 않았습니다", 400, results=out)
    if any(p["risks"] for p in plans) and not body.get("confirm_risk"):
        raise ApiError("위험 규칙이 포함되어 있어 확인이 필요합니다", 409, need_confirm=True, results=out)
    for p in plans:
        if p["added"]:
            save_sg(p["_env"], p["name"], p["_new"])
    return jsonify({"ok": True, "results": out})


if __name__ == "__main__":
    cfg = load_config()
    s = cfg["settings"]
    host = os.environ.get("TF_ACL_HOST", s.get("host", "127.0.0.1"))
    port = int(os.environ.get("TF_ACL_PORT", s.get("port", 8080)))
    print("Traform ACL Tool: http://%s:%d" % (host, port))
    dev = os.environ.get("TF_ACL_DEV") == "1"   # 개발 중: 코드가 바뀌면 서버 자동 재시작
    app.run(host=host, port=port, debug=dev, use_reloader=dev)
