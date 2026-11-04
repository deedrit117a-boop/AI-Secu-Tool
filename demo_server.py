"""가짜 데이터 서버: 임시 폴더의 가짜 git 저장소(+로컬 bare remote), 가짜 GitLab/Jira/AWS 응답으로 앱을 실행한다.
실제 저장소/GitLab/Jira/AWS 에는 접속하지 않으며 실제 data/ 폴더도 쓰지 않는다.

시연 모드:  python demo_server.py --demo [포트]   (demo.bat)  기본 포트 8090. 화면 위에 '시연 모드' 안내가 뜨고, 창을 닫으면 만든 내용은 사라진다.
화면 테스트:  python tests/ui_server.py [포트]    (tests/ui/run_ui_tests.js 가 자동으로 실행/종료. 이 파일을 그대로 실행한다)
제어 플래그(임시 폴더 안의 빈 파일): mr.flag = 열린 MR 있음, note.flag = Atlantis plan 성공 응답, noteerr.flag = plan 실패(브랜치 없음) 응답, apply.flag = Atlantis apply 완료 응답
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

DEMO = "--demo" in sys.argv
if DEMO:
    sys.argv.remove("--demo")
    os.environ["TF_ACL_DEMO"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app as A  # noqa: E402

tmp = tempfile.mkdtemp(prefix="tfacl_demo_" if DEMO else "tfacl_ui_")
if DEMO:
    atexit.register(lambda: shutil.rmtree(tmp, ignore_errors=True))
A.DATA = tmp
A.CONFIG_PATH, A.META_PATH, A.LOCAL_PATH = (os.path.join(tmp, n) for n in ("config.json", "meta.json", "local.json"))
A.PLANS_PATH, A.HISTORY_PATH = os.path.join(tmp, "plans.json"), os.path.join(tmp, "history.json")


def sh(*a, cwd=None):
    subprocess.run(a, cwd=cwd, check=True, capture_output=True)


def put(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


bare, work = os.path.join(tmp, "remote.git"), os.path.join(tmp, "seed")
sh("git", "init", "--bare", "-b", "main", bare)
sh("git", "clone", bare, work)
g = os.path.join(work, "aws", "live", "sub", "sg", "sg_rule")
p = os.path.join(work, "aws", "plat", "sg", "sg_rule")
os.makedirs(g)
os.makedirs(p)
base = [{"from_port": 80, "to_port": 80, "protocol": "TCP", "cidr_blocks": ["10.1.1.1/32"], "security_groups": "null", "prefix_list_ids": [],
         "description": "tf_261020_ISRIR-1_a to x Connection"}]
put(os.path.join(g, "l-sg-bbz-x-sg-ingress-rules.json"), json.dumps(base, indent=2) + "\n")
put(os.path.join(g, "l-sg-bbz-x-sg-egress-rules.json"), "[]\n")
put(os.path.join(g, "l-sg-bbz-y-sg-ingress-rules.json"), "[]\n")
put(os.path.join(g, "l-sg-bbz-y-sg-egress-rules.json"), "[]\n")
put(os.path.join(p, "sip-docdb.json"), '{\n    "ingress": [],\n    "egress": []\n}\n')
put(os.path.join(work, "other.txt"), "base\n")
for c in (["config", "user.email", "a@b"], ["config", "user.name", "t"], ["add", "-A"], ["commit", "-m", "init"], ["push", "origin", "main"]):
    sh("git", *c, cwd=work)

repo = os.path.join(tmp, "clone")
cfg = json.loads(json.dumps(A.DEFAULT_CONFIG))
cfg["environments"] = [
    {"id": "g", "kind": "game", "group": "bbz", "env": "live", "label": "apse1/sub", "repo_dir": repo, "sg_dir": "aws/live/sub/sg/sg_rule",
     "file_prefix": "l-sg-bbz-", "project": "p", "target_branch": ""},
    {"id": "p", "kind": "platform", "group": "plat", "env": "plat", "label": "apne2/dev", "repo_dir": repo, "sg_dir": "aws/plat/sg/sg_rule",
     "project": "cloudcenter/cloud-multiverse", "target_branch": ""}]
A.write_json(A.CONFIG_PATH, cfg)
if DEMO:   # 시연: 토큰/Jira/AWS 프로필이 이미 설정된 것처럼 보이게 한다 (모두 가짜 값)
    A.write_json(A.LOCAL_PATH, {"account": "demo", "tokens": {"game": "demo-token", "platform": "demo-token"}, "jira": {"auth": "bearer", "token": "demo"},
                                "aws_profiles": {"bbz|live": "qa-bbz-global", "plat|plat": "qa-bbz-global"},
                                "aws_regions": {"bbz|live": "ap-northeast-2", "plat|plat": "ap-northeast-2"}})
    A.write_json(A.META_PATH, {"envs": {"g": {"sgs": {"l-sg-bbz-x-sg": {"alias": "게임 서버 (시연)", "sg_id": "sg-0aaa111", "tags": [{"type": "domain", "value": "demo.example.net"}]}}}}})
else:
    A.write_json(A.LOCAL_PATH, {"account": "heejim", "tokens": {"game": "", "platform": "t"}, "jira": {"auth": "bearer", "token": "x"}})
A.clone_url = lambda env, with_auth=False: bare
A.app.test_client().post("/api/clone", json={"env_ids": ["g"]})
sh("git", "config", "user.email", "a@b", cwd=repo)
sh("git", "config", "user.name", "t", cwd=repo)


def flag(n):
    return os.path.exists(os.path.join(tmp, n))


def fake_gl(env, method, path, **kw):
    if method == "GET" and path.endswith("/merge_requests/9"):
        return {"sha": "aaa", "state": "opened", "source_branch": "x"}
    if "/repository/branches/" in path:
        return {}
    if method == "GET" and path.endswith("/merge_requests"):
        return [{"iid": 9, "web_url": "http://x/9", "title": "existing"}] if flag("mr.flag") else []
    if method == "GET" and path == "/users":
        return [{"id": 1}]
    if method == "POST" and path.endswith("/merge_requests"):
        return {"iid": 9, "web_url": "http://x/9"}
    if method == "POST":
        if (DEMO or flag("autoflip.flag")) and path.endswith("/notes"):      # 시연(또는 UI 테스트): plan → apply 순서로 Atlantis 가 답하는 것처럼 보이게 한다
            body = str((kw.get("json") or {}).get("body", ""))
            if "atlantis apply" in body:
                open(os.path.join(tmp, "apply.flag"), "w").close()
            elif "atlantis plan" in body:
                open(os.path.join(tmp, "note.flag"), "w").close()
                try:
                    os.unlink(os.path.join(tmp, "apply.flag"))
                except OSError:
                    pass
        return {"id": 100}
    if path.endswith("/notes"):
        if flag("noteerr.flag"):
            return [{"id": 200, "body": "**Plan Error**running git clone --branch b: fatal: Remote branch b not found in upstream origin: exit status 128"}]
        if flag("apply.flag"):
            return [{"id": 300, "body": "Ran Apply for dir: `aws/x` workspace: `default`\n\nApply complete! Resources: 1 added, 0 changed, 0 destroyed."}]
        if flag("note.flag"):
            return [{"id": 200, "body": "```diff\n+ resource \"a\" \"b\" {\n```\nPlan: 1 to add, 0 to change, 0 to destroy."}]
    return []


JIRA_POSTS = []


def fake_jira(method, path, **kw):
    if method == "GET":
        if path.endswith("/transitions"):
            return {"transitions": [{"id": 71, "name": "완료 처리", "to": {"name": "완료"}}]}
        return {"key": path.split("/")[-1], "fields": {"summary": "테스트 티켓 제목", "status": {"name": "진행중"},
                                                       "assignee": {"displayName": "임희재"}, "issuetype": {"name": "Task"}}}
    JIRA_POSTS.append((method, path, kw.get("json")))
    return {}


A.gl = fake_gl

# 엑셀 연동: 임시 폴더의 가짜 엑셀 파일 사용. 폴더 선택 창과 변경 규칙 계산(미리보기)만 가짜로 바꾸고, 쓰기는 진짜 코드가 임시 파일에 한다
import openpyxl
xdir = os.path.join(tmp, "xls")
os.makedirs(xdir, exist_ok=True)
_wb = openpyxl.Workbook()
_ws = _wb.active
_ws.title = "ACL 적용내역"
for _j, _h in enumerate(A.EXCEL_HEADERS):
    _ws.cell(row=2, column=3 + _j, value=_h)
for _j in range(12):
    _ws.cell(row=3, column=3 + _j, value="AWS" if _j == 0 else "old")
_wb.save(os.path.join(xdir, "acl.xlsx"))
A.excel_pick_folder = lambda initial="": xdir
def fake_excel_rows(env, ticket):
    mk = lambda ip, act, d: {"cells": ["AWS", "qa-bbz", "홍콩", "-", ip, "l-sg-bbz-x", "l-sg-bbz-x-sg(sg-0aaa111)", "TCP", "80", act, ticket or "ISRIR-1", "임희재"],
                             "direction": d, "sg": "l-sg-bbz-x-sg", "env_id": env["id"], "dup": False, "checked": d == "ingress",
                             "key": "%s|%s|%s" % (ticket, ip, act), "note": ""}
    return {"branch": "heejim/261027_ISRIR-1_x", "ticket": ticket or "ISRIR-1", "rows": [mk("10.7.7.7", "허용", "ingress"), mk("10.7.7.8", "삭제", "ingress"), mk("10.7.7.9", "허용", "egress")]}
A.excel_build_rows = fake_excel_rows

# AWS: 실제 CLI 를 부르지 않고 가짜 응답. login.flag = 로그인 필요, denied.flag = 권한 없음 (승인되면 login.flag 가 지워짐)
A.aws_cli_present = lambda: True
A.aws_exe = lambda: "aws"
A.aws_profiles = lambda: ["qa-bbz-global", "dev-other"]
def fake_aws_start_login(exe, profile):
    try:
        os.unlink(os.path.join(tmp, "login.flag"))
    except OSError:
        pass
    open(os.path.join(tmp, "login.started"), "w").close()
A.aws_start_login = fake_aws_start_login
def fake_aws_run(profile, service, command, extra=None, region=None, timeout=90):
    if flag("login.flag"):
        raise A.ApiError("AWS 자격증명이 없거나 만료되었습니다. 로그인(SSO) 승인이 필요합니다.", 401, aws_error="login_needed", profile=profile, detail="Token has expired")
    if flag("denied.flag"):
        raise A.ApiError("이 프로필에는 조회 권한이 없습니다 (Access Denied).", 403, aws_error="denied", profile=profile, detail="AccessDenied")
    if extra and "SecurityGroups[].GroupName" in extra:      # 프로필 자동 매칭용 조회: qa-bbz-global 계정에만 이 환경의 SG 가 있음
        return ["l-sg-bbz-x-sg", "l-sg-bbz-y-sg"] if profile == "qa-bbz-global" else []
    if service == "sts":
        return {"Account": "111122223333", "Arn": "arn:aws:sts::111122223333:assumed-role/x/y"}
    if command == "describe-security-groups" and any("IpPermissions" in str(x) for x in (extra or [])):   # AWS 규칙 비교 보고서: x 는 AWS 에만 있는 규칙이 있고 y 는 일치
        tcp = lambda port, cidr, d="": {"IpProtocol": "tcp", "FromPort": port, "ToPort": port, "IpRanges": [{"CidrIp": cidr, "Description": d}], "Ipv6Ranges": [], "UserIdGroupPairs": [], "PrefixListIds": []}
        allow = {"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}], "Ipv6Ranges": [], "UserIdGroupPairs": [], "PrefixListIds": []}
        return [{"id": "sg-0aaa111", "ingress": [tcp(80, "10.1.1.1/32", "tf_261020_ISRIR-1_a to x Connection"), tcp(22, "10.9.9.9/32", "콘솔에서 직접 추가")], "egress": [allow]},
                {"id": "sg-0bbb222", "ingress": [], "egress": []}]
    if command == "describe-security-groups":
        return [{"id": "sg-0aaa111", "name": "l-sg-bbz-x-sg", "vpc": "vpc-1", "tags": []}, {"id": "sg-0bbb222", "name": "other", "vpc": "vpc-1", "tags": [{"Key": "Name", "Value": "l-sg-bbz-y-sg"}]}]
    if command == "describe-network-interfaces":
        return [{"ips": ["10.1.0.10", "10.1.0.9"], "pub": "52.0.0.1", "groups": ["sg-0aaa111"]}, {"ips": ["10.1.1.20"], "pub": None, "groups": ["sg-0aaa111", "sg-0bbb222"]}]
    if command == "describe-subnets":
        return [{"id": "subnet-1", "vpc": "vpc-1", "cidr": "10.1.0.0/24", "tags": [{"Key": "Name", "Value": "pub-a"}]}, {"id": "subnet-2", "vpc": "vpc-1", "cidr": "10.1.1.0/24", "tags": [{"Key": "Name", "Value": "pri-a"}]}]
    if command == "describe-vpcs":
        return {"Vpcs": [{"CidrBlock": "10.1.0.0/16", "CidrBlockAssociationSet": [{"CidrBlock": "10.1.0.0/16"}]}]}
    if command == "describe-nat-gateways":
        return [{"id": "nat-1", "state": "available", "ips": ["3.3.3.3"]}]
    if command == "describe-route-tables":
        return [{"id": "rtb-main", "vpc": "vpc-1", "assoc": [{"subnet": None, "main": True}], "routes": [{"dest": "0.0.0.0/0", "nat": "nat-1"}]},
                {"id": "rtb-pub", "vpc": "vpc-1", "assoc": [{"subnet": "subnet-1", "main": False}], "routes": [{"dest": "0.0.0.0/0", "nat": None}]}]
    return {}
A.aws_run = fake_aws_run
A.jira_call = fake_jira
port = int(sys.argv[1]) if len(sys.argv) > 1 else (8090 if DEMO else 8093)
print("READY", tmp, flush=True)
if DEMO:
    print("시연 모드 서버: http://127.0.0.1:%d  (가짜 데이터, 이 창을 닫으면 종료됩니다)" % port, flush=True)
A.app.run(port=port)
