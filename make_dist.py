"""다른 사용자에게 배포할 압축 파일(zip)을 만든다.

    python make_dist.py                  -> dist/Traform-ACL-Tool-<버전>.zip  (프로그램만, 환경 목록 비어 있음)
    python make_dist.py --with-config    -> 현재 data/config.json 의 환경 목록을 정리해서 함께 넣음
                                            (repo 로컬 경로는 비워서 각 사용자 PC 의 기본 위치를 쓰게 함)

들어가는 것은 아래 허용 목록뿐이며, data/ 폴더(토큰, 작업 이력, 백업, 로그 등)는 절대 넣지 않는다.
만든 뒤 zip 안에 토큰 값이 섞여 있지 않은지도 한 번 더 검사한다.
"""
import argparse
import json
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
TOP_FILES = ["app.py", "make_dist.py", "make_dist.bat", "run.bat", "requirements.txt", "README.md", "ARCHITECTURE.md", "CHANGELOG.md", "run_tests.bat", "run_ui_tests.bat", ".gitignore", "demo.bat", "demo_server.py", "update.bat"]
TOP_DIRS = ["static", "tests", "app_parts"]
SKIP_DIRS = {"__pycache__", ".git", "node_modules"}
SKIP_SUFFIX = (".pyc", ".tmp", ".log")


def app_version():
    m = re.search(r'^VERSION = "([^"]+)"', open(os.path.join(ROOT, "app.py"), encoding="utf-8").read(), re.M)
    return m.group(1) if m else "x"


def sanitize_config(cfg):
    """공유용 설정: 환경 목록/기본값은 유지하되 내 PC 경로(repo_dir)는 비운다"""
    cfg = json.loads(json.dumps(cfg))
    for e in cfg.get("environments", []):
        e["repo_dir"] = ""
    for d in (cfg.get("defaults") or {}).values():
        d["repo_dir"] = ""
    return cfg


def collect():
    files = [f for f in TOP_FILES if os.path.exists(os.path.join(ROOT, f))]
    for d in TOP_DIRS:
        for cur, dirs, names in os.walk(os.path.join(ROOT, d)):
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
            for n in names:
                if not n.endswith(SKIP_SUFFIX):
                    files.append(os.path.relpath(os.path.join(cur, n), ROOT).replace("\\", "/"))
    return sorted(files)


def secrets_in_local(data_dir):
    try:
        loc = json.load(open(os.path.join(data_dir, "local.json"), encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    vals = list((loc.get("tokens") or {}).values()) + [(loc.get("jira") or {}).get("token", "")]
    return [str(v) for v in vals if v and len(str(v)) >= 6]


class DistError(Exception):
    pass


def write_zip(fileobj, with_config=False, data_dir=None, with_meta=False):
    """zip 을 fileobj(파일 또는 메모리)에 쓰고 zip 안의 폴더 이름을 돌려준다"""
    data_dir = data_dir or os.path.join(ROOT, "data")
    name = "Traform-ACL-Tool-%s" % app_version()
    secrets = secrets_in_local(data_dir)
    with zipfile.ZipFile(fileobj, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in collect():
            p = os.path.join(ROOT, rel)
            if rel.startswith("data/") or rel.endswith("local.json"):
                raise DistError("배포 목록에 데이터 파일이 섞였습니다: " + rel)
            body = open(p, "rb").read()
            for s in secrets:
                if s.encode("utf-8") in body:
                    raise DistError("파일 %s 에 토큰 값이 들어 있어 중단합니다" % rel)
            z.writestr("%s/%s" % (name, rel), body)
        z.writestr("%s/data/README.txt" % name, "이 폴더에 설정/작업 이력이 자동으로 만들어집니다 (config.json 은 공유 가능, local.json 은 개인 토큰이라 공유 금지).\n")
        for flag, fn, clean in ((with_config, "config.json", sanitize_config), (with_meta, "meta.json", lambda x: x)):
            if not flag:
                continue
            path = os.path.join(data_dir, fn)
            if not os.path.exists(path):
                raise DistError("%s 파일이 아직 없습니다 (환경을 먼저 등록하세요)" % fn)
            text = json.dumps(clean(json.load(open(path, encoding="utf-8-sig"))), ensure_ascii=False, indent=2) + "\n"
            for s in secrets:
                if s in text:
                    raise DistError("%s 에 토큰 값이 들어 있어 중단합니다" % fn)
            z.writestr("%s/data/%s" % (name, fn), text)
    return name


def build(out_dir, with_config=False, data_dir=None, with_meta=False):
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "Traform-ACL-Tool-%s.zip" % app_version())
    with open(out, "wb") as f:
        write_zip(f, with_config, data_dir, with_meta)
    return out


def build_bytes(with_config=False, data_dir=None, with_meta=False):
    import io
    buf = io.BytesIO()
    name = write_zip(buf, with_config, data_dir, with_meta)
    return name + ".zip", buf.getvalue()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-config", action="store_true", help="현재 환경 목록(경로 제거)을 함께 넣기")
    ap.add_argument("--with-meta", action="store_true", help="메타 데이터(meta.json)도 함께 넣기")
    ap.add_argument("--out", default=os.path.join(ROOT, "dist"))
    a = ap.parse_args()
    try:
        path = build(a.out, a.with_config, with_meta=a.with_meta)
    except DistError as e:
        raise SystemExit(str(e))
    with zipfile.ZipFile(path) as z:
        n = len(z.namelist())
    print("만들었습니다: %s (%d개 파일, %.0f KB)" % (path, n, os.path.getsize(path) / 1024))
    print("환경 목록 포함: %s / 토큰·작업 이력·로그: 포함 안 됨" % ("예 (repo 경로 제거)" if a.with_config else "아니오"))
