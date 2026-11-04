"""Traform ACL 자동화 Tool 자동 테스트 (표준 라이브러리 unittest 만 사용)

실행:  python -m unittest discover -s tests -v      (또는 run_tests.bat)

주의: 모든 테스트는 임시 폴더의 가짜 git 저장소(로컬 bare remote)와 가짜 GitLab 응답만 사용합니다.
      실제 저장소/GitLab 에는 접속하거나 쓰지 않습니다.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as A  # noqa: E402

RULE = {"from_port": 6001, "to_port": 6001, "protocol": "tcp", "cidr_blocks": ["10.1.1.1/32"],
        "description": "tf_261020_ISRIR-1_a to x Connection"}


def put(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def sh(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


class TempEnv(unittest.TestCase):
    """임시 가짜 저장소 + 격리된 data 폴더. 클래스마다 새로 만든다."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        t = cls.tmp
        cls._saved = {k: getattr(A, k) for k in ("DATA", "CONFIG_PATH", "META_PATH", "LOCAL_PATH", "PLANS_PATH", "HISTORY_PATH", "clone_url", "gl")}
        A.DATA = t
        A.STATUS_TTL = 0
        A.CONFIG_PATH, A.META_PATH, A.LOCAL_PATH = (os.path.join(t, n) for n in ("config.json", "meta.json", "local.json"))
        A.PLANS_PATH, A.HISTORY_PATH = os.path.join(t, "plans.json"), os.path.join(t, "history.json")
        bare, work = os.path.join(t, "remote.git"), os.path.join(t, "seed")
        sh("git", "init", "--bare", "-b", "main", bare)
        sh("git", "clone", bare, work)
        g = os.path.join(work, "aws", "live", "sub", "sg", "sg_rule")
        p = os.path.join(work, "aws", "plat", "sg", "sg_rule")
        os.makedirs(g)
        os.makedirs(p)
        base = [{"from_port": 80, "to_port": 80, "protocol": "TCP", "cidr_blocks": ["10.1.1.1/32"], "security_groups": "null",
                 "prefix_list_ids": [], "description": "tf_261020_ISRIR-1_a to x Connection"}]
        put(os.path.join(g, "l-sg-bbz-x-sg-ingress-rules.json"), json.dumps(base, indent=2) + "\n")
        put(os.path.join(g, "l-sg-bbz-x-sg-egress-rules.json"), "[]\n")
        put(os.path.join(p, "sip-docdb.json"), '{\n    "ingress": [],\n    "egress": []\n}\n')
        put(os.path.join(work, "other.txt"), "base\n")
        for c in (["config", "user.email", "a@b"], ["config", "user.name", "t"], ["add", "-A"], ["commit", "-m", "init"], ["push", "origin", "main"]):
            sh("git", *c, cwd=work)
        cls.repo = os.path.join(t, "clone")
        cfg = json.loads(json.dumps(A.DEFAULT_CONFIG))
        cfg["environments"] = [
            {"id": "g", "kind": "game", "group": "bbz", "env": "live", "label": "apse1/sub", "repo_dir": cls.repo,
             "sg_dir": "aws/live/sub/sg/sg_rule", "file_prefix": "l-sg-bbz-", "project": "p", "target_branch": ""},
            {"id": "p", "kind": "platform", "group": "x", "env": "x", "repo_dir": cls.repo, "sg_dir": "aws/plat/sg/sg_rule",
             "project": "cloudcenter/cloud-multiverse", "target_branch": ""}]
        A.write_json(A.CONFIG_PATH, cfg)
        A.write_json(A.LOCAL_PATH, {"account": "heejim", "tokens": {"game": "", "platform": "t"}})
        A.clone_url = lambda env, with_auth=False: bare
        cls.c = A.app.test_client()
        cls.c.post("/api/clone", json={"env_ids": ["g"]})
        sh("git", "config", "user.email", "a@b", cwd=cls.repo)
        sh("git", "config", "user.name", "t", cwd=cls.repo)

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._saved.items():
            setattr(A, k, v)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):  # 테스트마다 저장소를 깨끗한 main 으로 되돌린다 (임시 저장소)
        git = lambda *a: subprocess.run(["git", *a], cwd=self.repo, capture_output=True)
        git("checkout", "-f", "main")
        git("reset", "--hard", "origin/main")
        git("clean", "-fd")
        for b in subprocess.run(["git", "branch", "--format=%(refname:short)"], cwd=self.repo, capture_output=True, text=True).stdout.split():
            if b != "main":
                git("branch", "-D", b)
        for f in ("plans.json", "history.json", "meta.json", "undo.json"):
            p = os.path.join(self.tmp, f)
            if os.path.exists(p):
                os.remove(p)
        A._SG_CACHE.clear()

    def J(self, r):
        return r.get_json()

    def work_branch(self, ticket="ISRIR-7"):
        r = self.c.post("/api/env/g/git/prepare", json={"ticket": ticket})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return self.J(r)["branch"]


class FileFormatTests(TempEnv):
    def test_game_format_roundtrip(self):
        self.work_branch()
        sg = self.J(self.c.get("/api/env/g/sg/l-sg-bbz-x-sg"))
        sg["ingress"].append(dict(RULE, cidr_blocks="10.2.2.2/32", protocol="tcp"))
        self.assertEqual(self.c.put("/api/env/g/sg/l-sg-bbz-x-sg", json=sg).status_code, 200)
        text = open(os.path.join(self.repo, "aws/live/sub/sg/sg_rule/l-sg-bbz-x-sg-ingress-rules.json"), encoding="utf-8").read()
        self.assertIn('"cidr_blocks": ["10.2.2.2/32"]', text)      # 한 줄 배열
        self.assertIn('"security_groups": "null"', text)             # IP 규칙은 "null" 문자열
        self.assertIn('"protocol": "TCP"', text)                     # 게임: 대문자
        self.assertTrue(text.endswith("\n"))

    def test_platform_format(self):
        self.work_branch()
        sg = self.J(self.c.get("/api/env/p/sg/sip-docdb"))
        sg["ingress"].append(dict(RULE, protocol="TCP"))
        self.assertEqual(self.c.put("/api/env/p/sg/sip-docdb", json=sg).status_code, 200)
        text = open(os.path.join(self.repo, "aws/plat/sg/sg_rule/sip-docdb.json"), encoding="utf-8").read()
        self.assertIn('"security_groups": null', text)               # 플랫폼: null
        self.assertIn('"protocol": "tcp"', text)                     # 플랫폼: 소문자
        self.assertTrue(text.startswith('{\n    "ingress": ['))       # 들여쓰기 4칸

    def test_new_sg_names(self):
        self.work_branch()
        self.assertEqual(self.J(self.c.post("/api/env/p/sgs", json={"resource": "new-res"}))["name"], "new-res")
        self.assertEqual(self.J(self.c.post("/api/env/g/sgs", json={"resource": "auto-lambda"}))["name"], "l-sg-bbz-auto-lambda-sg")


class ValidationTests(unittest.TestCase):
    env = {"kind": "game"}

    def v(self, rules, old=None, d="ingress"):
        return A.validate_sg(self.env, {d: rules, ("egress" if d == "ingress" else "ingress"): []}, old)

    def test_ok(self):
        e, w, k = self.v([dict(RULE)])
        self.assertFalse(e or k)

    def test_errors(self):
        self.assertTrue(any("호스트 비트" in x for x in self.v([dict(RULE, cidr_blocks=["10.0.0.1/24"])])[0]))
        self.assertTrue(any("형식" in x for x in self.v([dict(RULE, cidr_blocks=["10.0.0.999/32"])])[0]))
        self.assertTrue(any("보다 큽니다" in x for x in self.v([dict(RULE, from_port=500, to_port=80)])[0]))
        self.assertTrue(any("0~65535" in x for x in self.v([dict(RULE, to_port=70000)])[0]))
        self.assertTrue(any("설명" in x for x in self.v([dict(RULE, description="")])[0]))
        self.assertTrue(any("소스" in x for x in self.v([dict(RULE, cidr_blocks=[], security_groups="")])[0]))
        self.assertTrue(any("함께" in x for x in self.v([dict(RULE, security_groups="sg-0123456789abcdef0")])[0]))

    def test_risks(self):
        self.assertEqual(len(self.v([dict(RULE, cidr_blocks=["0.0.0.0/0"])])[2]), 1)
        self.assertTrue(any("광범위" in x for x in self.v([dict(RULE, cidr_blocks=["10.0.0.0/8"])])[2]))
        self.assertTrue(any("전체 포트" in x for x in self.v([dict(RULE, from_port=0, to_port=65535)])[2]))
        self.assertTrue(any("모든 프로토콜" in x for x in self.v([dict(RULE, protocol="-1", from_port=0, to_port=0)])[2]))
        self.assertFalse(self.v([dict(RULE, cidr_blocks=["0.0.0.0/0"])], d="egress")[2])   # 아웃바운드는 위험 아님

    def test_warnings_and_existing_rules(self):
        e, w, k = self.v([dict(RULE), dict(RULE)])
        self.assertTrue(any("중복" in x for x in w) and not e)
        e, w, k = self.v([dict(RULE, description="임의")])
        self.assertTrue(any("명명 규칙" in x for x in w) and not e)
        old = {"ingress": [dict(RULE, cidr_blocks=["0.0.0.0/0"], description="")], "egress": []}
        e, w, k = self.v([dict(RULE, cidr_blocks=["0.0.0.0/0"], description="")], old=old)   # 기존 규칙의 문제는 차단하지 않음
        self.assertFalse(e or k)
        self.assertTrue(any("(기존)" in x for x in w))


class AtlantisTests(TempEnv):
    def test_analyze(self):
        ok = "```diff\n+ resource \"a\" \"b\" {\n      + description = \"fix error handling failed\"\n    }\nPlan: 1 to add, 0 to change, 0 to destroy.\n```"
        self.assertEqual(A.analyze_atlantis(ok, "plan")["state"], "ok")        # 설명 속 error/failed 단어는 무시
        self.assertEqual(A.analyze_atlantis("**Plan Error**running git clone: exit status 128", "plan")["state"], "error")
        self.assertEqual(A.analyze_atlantis("╷\n│ Error: Invalid CIDR\n╵", "plan")["state"], "error")
        r = A.analyze_atlantis("# x must be replaced\n-/+ resource \"a\" \"b\" {\nPlan: 1 to add, 0 to change, 1 to destroy.", "plan")
        self.assertEqual((r["state"], r["plan"]["replace"]), ("warn", 1))
        self.assertEqual(A.analyze_atlantis("Plan: 0 to add, 0 to change, 2 to destroy.", "plan")["plan"]["destroy"], 2)
        self.assertEqual(A.analyze_atlantis("Apply complete! Resources: 1 added", "apply")["state"], "ok")

    def test_apply_gate(self):
        mr = {"sha": "aaa", "state": "opened", "source_branch": "heejim/261020_T"}
        posts = []

        def fake(env, method, path, **kw):
            if method == "GET" and path.endswith("/merge_requests/9"):
                return dict(mr)
            if "/repository/branches/" in path:
                return {}
            if method == "POST":
                posts.append(kw["json"]["body"])
                return {"id": 100}
        A.gl = fake
        env = A.get_env("p")
        ap = lambda **kw: self.c.post("/api/env/p/atlantis", json=dict({"action": "apply", "iid": 9}, **kw))
        r = ap()
        self.assertEqual(r.status_code, 409)
        self.assertIn("plan", self.J(r)["error"])                                  # plan 없음
        self.c.post("/api/env/p/atlantis", json={"action": "plan", "iid": 9})
        self.assertIn("아직", self.J(ap())["error"])                                # plan 대기 중
        A.plan_put(env, 9, {"state": "warn", "plan": {"add": 1, "change": 0, "destroy": 1, "replace": 0}})
        r = ap()
        self.assertTrue(self.J(r).get("need_confirm"))                             # 삭제 포함 -> 확인 요구
        ps = self.J(self.c.get("/api/env/p/atlantis/plan-status?iid=9"))
        self.assertTrue(ps["need_confirm"] and ps["sha_match"])
        mr["sha"] = "bbb"
        self.assertIn("새 커밋", self.J(ap(confirm_destroy=True))["error"])         # plan 이후 커밋 변경
        mr["sha"] = "aaa"
        self.assertEqual(ap(confirm_destroy=True).status_code, 200)               # 확인 후 허용
        self.assertTrue(posts[-1].startswith("atlantis apply"))
        A.plan_put(env, 9, {"state": "error"})
        self.assertIn("실패", self.J(ap(confirm_destroy=True))["error"])
        A.plan_put(env, 9, {"state": "ok", "plan": {"add": 1, "change": 0, "destroy": 0, "replace": 0}, "applied": True})
        self.assertIn("이미", self.J(ap())["error"])
        A.plan_put(env, 9, {"state": "ok", "plan": {"add": 0, "change": 0, "destroy": 0, "replace": 0}, "applied": False})
        self.assertIn("변경 사항이 없", self.J(ap())["error"])
        A.plan_put(env, 9, {"state": "ok", "plan": {"add": 1, "change": 0, "destroy": 0, "replace": 0}})
        self.assertEqual(ap().status_code, 200)


class GitScopeTests(TempEnv):
    def test_branch_guard_scope_push_diff(self):
        sg = {"ingress": [dict(RULE)], "egress": []}
        r = self.c.put("/api/env/g/sg/l-sg-bbz-x-sg", json=sg)                    # main 에서는 차단
        self.assertEqual(r.status_code, 409)
        self.assertTrue(self.J(r).get("need_branch"))
        self.assertEqual(self.c.put("/api/env/g/sg/l-sg-bbz-x-sg", json=sg, headers={"X-Allow-Main": "1"}).status_code, 200)
        sh("git", "checkout", "--", ".", cwd=self.repo)
        sh("git", "clean", "-fd", cwd=self.repo)
        self.work_branch()
        self.assertEqual(self.c.put("/api/env/g/sg/l-sg-bbz-x-sg", json=sg).status_code, 200)
        put(os.path.join(self.repo, "other.txt"), "changed\n")
        put(os.path.join(self.repo, "new_unrelated.txt"), "x\n")
        st = self.J(self.c.get("/api/env/g/git/status"))
        self.assertEqual(len(st["out_of_scope"]), 2)
        self.assertFalse(st["on_default"])
        d = self.J(self.c.get("/api/env/g/git/diff"))
        self.assertIn("6001", d["diff"])
        self.assertNotIn("other.txt", d["diff"])
        sd = self.J(self.c.get("/api/env/g/sg/l-sg-bbz-x-sg/diff"))                # SG 단위 변경 보기(읽기 전용)
        self.assertIn("6001", sd["diff"])
        pj = self.J(self.c.post("/api/env/g/git/push", json={}))
        self.assertEqual(len(pj["skipped"]), 2)
        files = subprocess.run(["git", "show", "--name-only", "--format=", "HEAD"], cwd=self.repo, capture_output=True, text=True).stdout.split()
        self.assertTrue(files and all(f.startswith("aws/live/sub/sg/sg_rule/") for f in files))
        left = subprocess.run(["git", "status", "--porcelain"], cwd=self.repo, capture_output=True, text=True).stdout
        self.assertIn("other.txt", left)
        self.assertEqual(self.c.post("/api/env/g/git/push", json={}).status_code, 400)   # 커밋할 SG 변경 없음
        self.assertEqual(self.J(self.c.get("/api/env/g/sg/l-sg-bbz-x-sg/changes"))["ingress"], [])   # push 후 음영 해제

    def test_scope_ignores_configured_envs_whose_folder_does_not_exist(self):
        """설정에는 있지만 저장소에 폴더가 없는 환경(예: 잘못 등록된 경로)이 있어도 push 가 실패하지 않아야 한다"""
        cfg = A.load_config()
        cfg["environments"].append({"id": "ghost", "kind": "game", "group": "bbz", "env": "ghost", "repo_dir": self.repo,
                                    "sg_dir": "aws/does/not/exist/sg/sg_rule", "file_prefix": "x-", "project": "p", "target_branch": ""})
        A.write_json(A.CONFIG_PATH, cfg)
        self.work_branch()
        sg = {"ingress": [dict(RULE)], "egress": []}
        self.assertEqual(self.c.put("/api/env/g/sg/l-sg-bbz-x-sg", json=sg).status_code, 200)
        self.assertNotIn("aws/does/not/exist/sg/sg_rule", A.scope_paths(A.get_env("g")))
        self.assertEqual(self.c.post("/api/env/g/git/push", json={}).status_code, 200)

    def test_branch_name_increment(self):
        b1 = self.work_branch("ISRIR-55")
        sh("git", "checkout", "main", cwd=self.repo)
        b2 = self.work_branch("ISRIR-55")
        self.assertTrue(b2.startswith(b1) and b2.endswith("_01"), (b1, b2))


class CsvTests(TempEnv):
    HEAD = "direction,protocol,from_port,to_port,source_type,source,description\n"

    def upload(self, text, **form):
        data = {"file": (io.BytesIO(text.encode()), "a.csv")}
        data.update(form)
        return self.c.post("/api/env/g/sg/l-sg-bbz-x-sg/csv", data=data, content_type="multipart/form-data")

    def test_dry_run_and_apply(self):
        self.work_branch()
        good = self.HEAD + "ingress,tcp,22,22,cidr,10.3.3.3/32,tf_261020_ISRIR-1_a to x Connection\n"
        r = self.J(self.upload(good, dry_run="1"))
        self.assertEqual(len(r["preview"]["append"]["added"]), 1)
        self.assertEqual(len(r["preview"]["replace"]["removed"]), 1)               # 교체하면 기존 1건이 사라짐
        self.assertEqual(len(self.J(self.c.get("/api/env/g/sg/l-sg-bbz-x-sg"))["ingress"]), 1)   # 미리보기는 저장하지 않음
        self.assertEqual(self.upload(good, mode="append").status_code, 200)
        self.assertEqual(len(self.J(self.c.get("/api/env/g/sg/l-sg-bbz-x-sg"))["ingress"]), 2)

    def test_errors_and_risk_confirm(self):
        self.work_branch()
        bad = self.HEAD + "ingress,tcp,80,80,cidr,10.0.0.1/24,tf_261020_ISRIR-1_a to x Connection\n"
        self.assertEqual(self.upload(bad, mode="append").status_code, 400)
        risky = self.HEAD + "ingress,tcp,22,22,cidr,0.0.0.0/0,tf_261020_ISRIR-1_a to x Connection\n"
        r = self.upload(risky, mode="append")
        self.assertEqual(r.status_code, 409)
        self.assertTrue(self.J(r).get("need_confirm"))
        self.assertEqual(self.upload(risky, mode="append", confirm_risk="1").status_code, 200)


class HistoryTests(TempEnv):
    def test_crud(self):
        e = {"id": "h1", "ts": 1, "t": "now", "step": "브랜치 준비", "kind": "prep", "state": "ok", "headline": "ok", "text": "x" * 90000}
        self.assertEqual(self.c.post("/api/history", json={"key": "k1", "entry": e}).status_code, 200)
        got = self.J(self.c.get("/api/history?key=k1"))["entries"]
        self.assertEqual((len(got), got[0]["user"], len(got[0]["text"])), (1, "heejim", 80000))   # 사용자 기록 / 길이 제한
        self.c.post("/api/history", json={"key": "k1", "entry": dict(e, id="h2", state="pending", poll={"iid": 9})})
        self.assertEqual(self.c.patch("/api/history/h2", json={"key": "k1", "patch": {"state": "ok", "headline": "done", "id": "evil"}}).status_code, 200)
        got = self.J(self.c.get("/api/history?key=k1"))["entries"]
        self.assertEqual((got[1]["state"], got[1]["id"]), ("ok", "h2"))            # id 는 수정 불가
        self.assertEqual(self.c.patch("/api/history/nope", json={"key": "k1", "patch": {}}).status_code, 404)
        self.assertEqual(self.c.get("/api/history?key=").status_code, 400)
        self.c.delete("/api/history?key=k1")
        self.assertEqual(self.J(self.c.get("/api/history?key=k1"))["entries"], [])

    def test_import_only_when_empty(self):
        items = [{"id": "a%d" % i, "step": "s", "text": ""} for i in range(3)]
        self.assertEqual(self.J(self.c.post("/api/history/import", json={"key": "k2", "entries": items}))["imported"], 3)
        self.assertEqual(self.J(self.c.post("/api/history/import", json={"key": "k2", "entries": items}))["imported"], 0)

    def test_cap_200(self):
        for i in range(205):
            self.c.post("/api/history", json={"key": "k3", "entry": {"id": "c%d" % i, "step": "s"}})
        self.assertEqual(len(self.J(self.c.get("/api/history?key=k3"))["entries"]), 200)

    def test_concurrent_writes_do_not_fail(self):
        """여러 요청이 동시에 이력을 저장/조회해도 (Windows 파일 교체 충돌 없이) 모두 성공해야 한다"""
        import threading
        codes = []

        def worker(i):
            c = A.app.test_client()
            codes.append(c.post("/api/history", json={"key": "kc", "entry": {"id": "t%d" % i, "step": "s"}}).status_code)
            codes.append(c.get("/api/history?key=kc").status_code)
        ts = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(set(codes), {200})
        self.assertEqual(len(self.J(self.c.get("/api/history?key=kc"))["entries"]), 12)


class SearchAndMetaTests(TempEnv):
    def test_ip_containment_and_tags(self):
        A.write_json(A.META_PATH, {"envs": {"g": {"sgs": {"l-sg-bbz-x-sg": {"sg_id": "sg-0abc", "alias": "match3", "tags": [{"type": "domain", "value": "a.example.com"}]}},
                                              "subnets": [{"subnet_name": "sub-a", "vpc_id": "vpc-1", "ipv4_cidr": "10.9.0.0/24", "nat_ip": "3.3.3.3"}]}}})
        r = self.J(self.c.get("/api/search?q=10.1.1.1"))                            # 같은 IP
        self.assertTrue(r["query_is_ip"] and r["results"][0]["name"] == "l-sg-bbz-x-sg")
        self.assertTrue(self.J(self.c.get("/api/search?q=10.1.0.0/16"))["results"])   # 대역 겹침
        self.assertTrue(self.J(self.c.get("/api/search?q=a.example.com"))["results"])  # 태그(도메인)
        self.assertTrue(self.J(self.c.get("/api/search?q=sg-0abc"))["results"])       # SG ID
        sub = [x for x in self.J(self.c.get("/api/search?q=3.3.3.3"))["results"] if x["type"] == "env"]
        self.assertTrue(sub and "NAT IP" in sub[0]["hits"][0])                      # 환경 정보(NAT IP)
        self.assertEqual(self.J(self.c.get("/api/search?q=zzzqqq"))["results"], [])

    def test_env_info_csv_roundtrip(self):
        csvtxt = "env_id,Subnet name,VPC ID,IPv4 CIDR,NAT IP\ng,sub-a,vpc-1,10.0.1.0/24,3.3.3.3\ng,sub-b,vpc-1,10.0.2.0/24,\nnope,x,y,z,w\n"
        r = self.J(self.c.post("/api/meta/env-csv", data={"file": (io.BytesIO(csvtxt.encode()), "a.csv")}, content_type="multipart/form-data"))
        self.assertEqual((r["envs"], r["rows"], r["unknown_env_ids"]), (1, 2, ["nope"]))
        down = self.c.get("/api/meta/env-csv").get_data()
        r2 = self.J(self.c.post("/api/meta/env-csv", data={"file": (io.BytesIO(down), "b.csv")}, content_type="multipart/form-data"))
        self.assertEqual(r2["rows"], 2)

    def test_split_env_path(self):
        self.assertEqual(A.split_env_path("aws/sandbox/sb0/apse1/sub/sg/sg_rule"), ("sandbox0", "apse1/sub"))
        self.assertEqual(A.split_env_path("aws/live/apse1/sub/sg/sg_rule"), ("live", "apse1/sub"))
        self.assertEqual(A.split_env_path("aws/review/review2/apne1/main/sg/sg_rule"), ("review2", "apne1/main"))


class MrDescriptionTests(TempEnv):
    def test_game_and_platform(self):
        A.fetch_mr_template = lambda env: None
        g, p = A.get_env("g"), A.get_env("p")
        d = A.build_mr_description(g, "요약1\n요약2", "SG 정책 추가/변경/삭제", "ISRIR-12355", ["heejim", "kim"])
        self.assertIn("- [x] SG 정책 추가/변경/삭제", d)
        self.assertIn("- [ ] 기타", d)
        self.assertIn("- [x] CP/Account/Region/Env 정상 체크", d)                  # 게임: Pre-Workflow 사전 체크
        self.assertIn("- 요약1\n- 요약2", d)
        self.assertIn("- ISRIR-12355", d)
        self.assertIn("- [x] Approved by @heejim", d)
        dp = A.build_mr_description(p, "요약", "SG 정책 추가/변경/삭제", "ISRIR-1", ["heejim"])
        self.assertIn("- [ ] CP/Account/Region/Env 정상 체크", dp)                 # 플랫폼: 사전 체크 없음
        self.assertNotIn("- [x] Approved by @", dp)
        self.assertEqual(A.ticket_from_branch("heejim/261019_ISRIR-12355_01"), "ISRIR-12355")


class JiraTests(TempEnv):
    def test_settings_masking_and_issue(self):
        conf = A.load_config()
        conf["settings"]["jira_url"] = "https://jira.example.com/"
        A.write_json(A.CONFIG_PATH, conf)
        r = self.c.put("/api/local", json={"jira": {"auth": "bearer", "token": "SECRET-TOKEN"}})
        self.assertEqual(r.status_code, 200)
        cfg = self.J(self.c.get("/api/config"))
        self.assertTrue(cfg["jira"]["enabled"] and cfg["jira"]["token_set"])
        self.assertEqual(cfg["jira"]["base_url"], "https://jira.example.com")          # 끝의 / 제거
        self.assertNotIn("SECRET-TOKEN", json.dumps(cfg))                              # 토큰은 화면으로 내보내지 않음
        calls = []

        def fake(method, path, **kw):
            calls.append((method, path, kw))
            if method == "GET":
                return {"key": "ISRIR-1", "fields": {"summary": "SG 추가", "status": {"name": "진행중"}, "assignee": {"displayName": "임희재"}, "issuetype": {"name": "Task"}}}
            return {}
        orig, A.jira_call = A.jira_call, fake
        try:
            d = self.J(self.c.get("/api/jira/issue?key=isrir-1"))
            self.assertEqual((d["summary"], d["status"], d["url"]), ("SG 추가", "진행중", "https://jira.example.com/browse/ISRIR-1"))
            self.assertEqual(self.c.get("/api/jira/issue?key=bad").status_code, 400)
            self.assertEqual(self.c.post("/api/jira/comment", json={"key": "ISRIR-1", "body": ""}).status_code, 400)
            self.assertEqual(self.c.post("/api/jira/comment", json={"key": "ISRIR-1", "body": "x" * 9000}).status_code, 400)
            self.assertEqual(self.c.post("/api/jira/comment", json={"key": "ISRIR-1", "body": "MR !7"}).status_code, 200)
            self.assertEqual(calls[-1][0:2], ("POST", "/issue/ISRIR-1/comment"))
        finally:
            A.jira_call = orig
        self.c.put("/api/local", json={"jira": {"token": "__clear__"}})
        self.assertEqual(self.c.get("/api/jira/issue?key=ISRIR-1").status_code, 400)   # 토큰 없으면 안내

    def test_http_errors_are_mapped_and_masked(self):
        from unittest import mock
        conf = A.load_config()
        conf["settings"]["jira_url"] = "https://jira.example.com"
        A.write_json(A.CONFIG_PATH, conf)
        self.c.put("/api/local", json={"jira": {"auth": "basic", "user": "u", "token": "SECRET-TOKEN"}})

        class R:
            def __init__(self, code, text=""):
                self.status_code, self.text = code, text
            def json(self):
                return {}
        for code, expect in ((401, "인증"), (404, "찾을 수 없습니다"), (500, "Jira 오류 500")):
            with mock.patch.object(A.requests, "request", return_value=R(code, "boom SECRET-TOKEN")):
                r = self.c.get("/api/jira/issue?key=ISRIR-1")
                self.assertIn(expect, self.J(r)["error"])
                self.assertNotIn("SECRET-TOKEN", self.J(r)["error"])
        self.c.put("/api/local", json={"jira": {"token": "__clear__"}})


class JiraConfigTests(TempEnv):
    def test_default_url_shared_config_and_connection_test(self):
        cfg = self.J(self.c.get("/api/config"))
        self.assertEqual(cfg["jira"]["base_url"], "https://jira.smilegate.net")        # 기본 주소
        self.assertFalse(cfg["jira"]["enabled"])                                        # API 키가 없으면 비활성
        conf = A.load_config()
        conf.setdefault("settings", {})["jira_url"] = "https://jira.example.org/"       # 주소는 config.json(공유)에 저장
        A.write_json(A.CONFIG_PATH, conf)
        self.c.put("/api/local", json={"jira": {"auth": "bearer", "token": "KEY123"}})
        cfg = self.J(self.c.get("/api/config"))
        self.assertEqual(cfg["jira"]["base_url"], "https://jira.example.org")
        self.assertTrue(cfg["jira"]["enabled"])
        self.assertNotIn("KEY123", json.dumps(cfg))
        self.assertNotIn("KEY123", open(A.CONFIG_PATH, encoding="utf-8").read())        # 공유 파일에는 키가 없음
        orig, A.jira_call = A.jira_call, lambda m, p, **kw: {"name": "heejim", "displayName": "임희재", "emailAddress": "h@x.com"}
        try:
            r = self.J(self.c.get("/api/jira/test"))
            self.assertEqual((r["ok"], r["displayName"], r["base_url"]), (True, "임희재", "https://jira.example.org"))
        finally:
            A.jira_call = orig
        self.c.put("/api/local", json={"jira": {"token": "__clear__"}})
        self.assertEqual(self.c.get("/api/jira/test").status_code, 400)               # 키 삭제 후에는 안내


class BulkApplyTests(TempEnv):
    DESC = "tf_261020_ISRIR-1_a to x Connection"

    def setUp(self):
        super().setUp()
        self.work_branch()
        self.c.post("/api/env/g/sgs", json={"resource": "y"})            # l-sg-bbz-y-sg
        self.rule = {"direction": "ingress", "protocol": "tcp", "from_port": 443, "to_port": 443, "cidr_blocks": ["10.5.5.5/32"], "description": self.DESC}
        self.targets = [{"env_id": "g", "name": "l-sg-bbz-x-sg"}, {"env_id": "g", "name": "l-sg-bbz-y-sg"}, {"env_id": "p", "name": "sip-docdb"}]

    def post(self, **kw):
        return self.c.post("/api/bulk-apply", json=dict({"rules": [self.rule], "targets": self.targets}, **kw))

    def test_dry_run_then_apply_with_retarget(self):
        r = self.J(self.post(dry_run=True, retarget_desc=True))["results"]
        self.assertEqual([x["added"] for x in r], [1, 1, 1])
        self.assertEqual(len(self.J(self.c.get("/api/env/g/sg/l-sg-bbz-y-sg"))["ingress"]), 0)    # dry-run 은 저장하지 않음
        self.assertEqual(self.post(retarget_desc=True).status_code, 200)
        y = self.J(self.c.get("/api/env/g/sg/l-sg-bbz-y-sg"))["ingress"][0]
        self.assertEqual(y["description"], "tf_261020_ISRIR-1_a to y Connection")                 # 목적지가 대상 SG로 변경
        p = self.J(self.c.get("/api/env/p/sg/sip-docdb"))["ingress"][0]
        self.assertEqual((p["protocol"], p["description"].endswith("to sip-docdb Connection")), ("tcp", True))   # 플랫폼 양식
        again = self.J(self.post(dry_run=True, retarget_desc=True))["results"]
        self.assertEqual([(x["added"], x["skipped"]) for x in again], [(0, 1), (0, 1), (0, 1)])      # 중복은 건너뜀

    def test_error_aborts_everything_and_risk_needs_confirm(self):
        bad = dict(self.rule, cidr_blocks=["10.5.5.5/24"])
        r = self.c.post("/api/bulk-apply", json={"rules": [bad], "targets": self.targets})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(len(self.J(self.c.get("/api/env/g/sg/l-sg-bbz-x-sg"))["ingress"]), 1)     # 아무것도 저장되지 않음
        risky = dict(self.rule, cidr_blocks=["0.0.0.0/0"])
        r = self.c.post("/api/bulk-apply", json={"rules": [risky], "targets": self.targets})
        self.assertEqual(r.status_code, 409)
        self.assertTrue(self.J(r)["need_confirm"])
        self.assertEqual(self.c.post("/api/bulk-apply", json={"rules": [risky], "targets": self.targets, "confirm_risk": True}).status_code, 200)

    def test_main_branch_blocked_and_bad_input(self):
        sh("git", "checkout", "-f", "main", cwd=self.repo)
        self.assertEqual(self.post().status_code, 409)
        self.assertEqual(self.post(dry_run=True).status_code, 200)                                # 미리보기는 허용
        self.assertEqual(self.c.post("/api/bulk-apply", json={"rules": [], "targets": self.targets}).status_code, 400)
        self.assertEqual(self.c.post("/api/bulk-apply", json={"rules": [self.rule], "targets": [{"env_id": "g", "name": "../x"}]}).status_code, 400)


class RepairTests(TempEnv):
    def cfg_with_dups(self):
        cfg = A.load_config()
        base = {"repo_dir": self.repo, "project": "p", "target_branch": ""}
        cfg["environments"] = [
            dict(base, id="dup", kind="game", group="bbz", env="live", label="a", sg_dir="aws/live/sub/sg/sg_rule", file_prefix="l-sg-bbz-"),
            dict(base, id="dup", kind="platform", group="x", env="x", label="b", sg_dir="aws/plat/sg/sg_rule", project="cloudcenter/cloud-multiverse"),
            dict(base, id="ok", kind="game", group="bbz", env="ok", label="c", sg_dir="aws/live/sub/sg/sg_rule", file_prefix="l-sg-bbz-"),
            dict(base, id="stale1", kind="game", group="bbz", env="gone", label="d", sg_dir="aws/gone/sg/sg_rule", file_prefix="z-")]
        A.write_json(A.CONFIG_PATH, cfg)
        A.write_json(A.META_PATH, {"envs": {"dup": {"sgs": {"l-sg-bbz-x-sg": {"alias": "x"}, "sip-docdb": {"alias": "docdb"}},
                                                    "subnets": [{"subnet_name": "s"}]}}})

    def test_config_put_rejects_duplicate_ids(self):
        self.cfg_with_dups()
        r = self.c.put("/api/config", json=A.load_config())
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.J(r)["duplicate_ids"], ["dup"])

    def test_dry_run_then_apply_with_backup(self):
        self.cfg_with_dups()
        d = self.J(self.c.post("/api/config/repair", json={"dry_run": True}))
        self.assertEqual(d["duplicate_ids"], ["dup"])
        self.assertEqual(len(d["changes"]), 1)
        self.assertEqual(d["changes"][0]["old"], "dup")
        self.assertTrue(d["changes"][0]["new"].startswith("platform-plat"))                    # 경로 기반 새 ID
        self.assertEqual([x["id"] for x in d["stale"]], ["stale1"])                            # 저장소에 폴더가 없는 환경
        self.assertEqual(len([e for e in A.load_config()["environments"] if e["id"] == "dup"]), 2)   # dry-run 은 저장하지 않음
        r = self.J(self.c.post("/api/config/repair", json={"dry_run": False, "remove_stale": True}))
        self.assertTrue(r["backup"] and os.path.exists(os.path.join(r["backup"], "config.json")) and os.path.exists(os.path.join(r["backup"], "meta.json")))
        self.assertFalse(os.path.exists(os.path.join(r["backup"], "local.json")))               # 토큰 파일은 백업하지 않음
        ids = [e["id"] for e in A.load_config()["environments"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn("stale1", ids)
        meta = A.load_meta()["envs"]
        self.assertIn("l-sg-bbz-x-sg", meta["dup"]["sgs"])                                      # 게임 SG 는 첫 번째(게임) 환경에 유지
        new_id = d["changes"][0]["new"]
        self.assertEqual(meta[new_id]["sgs"]["sip-docdb"]["alias"], "docdb")                    # 플랫폼 SG 메타는 플랫폼 환경으로 이동
        self.assertTrue(any("환경 정보" in x["sg"] for x in r["meta_ambiguous"]))                # 서브넷 정보는 모호함으로 보고
        again = self.J(self.c.post("/api/config/repair", json={"dry_run": False}))              # 다시 실행해도 변경 없음 (백업 없음)
        self.assertEqual((again["changes"], again["backup"]), ([], None))

    def test_discover_generates_unique_ids(self):
        cfg = A.load_config()
        cfg["environments"] = [{"id": "src", "kind": "platform", "group": "x", "env": "x", "repo_dir": self.repo,
                                "sg_dir": "aws/plat/sg/sg_rule", "project": "cloudcenter/cloud-multiverse", "target_branch": ""}]
        A.write_json(A.CONFIG_PATH, cfg)
        for reg in ("apne1/a", "apne2/a"):                      # 같은 계정 폴더에 리전/티어만 다른 sg_rule 두 개
            os.makedirs(os.path.join(self.repo, "aws", "acct", *reg.split("/"), "sg", "sg_rule"), exist_ok=True)
        added = self.J(self.c.post("/api/env/src/discover"))["added"]
        self.assertEqual(len(added), 3)                          # 시드의 live 폴더 + acct 두 개
        ids = [e["id"] for e in A.load_config()["environments"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("platform-acct-apne1-a", ids)


class SaveFormatPreservationTests(TempEnv):
    def test_trailing_newline_and_eol_preserved(self):
        d = os.path.join(self.tmp, "fmt")
        os.makedirs(d, exist_ok=True)
        no_nl, crlf, new = (os.path.join(d, n) for n in ("a.json", "b.json", "c.json"))
        with open(no_nl, "wb") as f:
            f.write(b"[]")                                       # 마지막 개행 없음
        with open(crlf, "wb") as f:
            f.write(b'[\r\n  {"a": 1}\r\n]\r\n')                 # CRLF + 마지막 개행
        A.write_text(no_nl, "[\n  1\n]\n")
        A.write_text(crlf, "[\n  2\n]\n")
        A.write_text(new, "[\n  3\n]\n")
        self.assertEqual(open(no_nl, "rb").read(), b"[\n  1\n]")              # 마지막 개행이 없던 파일은 없는 채로
        self.assertEqual(open(crlf, "rb").read(), b"[\r\n  2\r\n]\r\n")       # CRLF 유지
        self.assertEqual(open(new, "rb").read(), b"[\n  3\n]\n")              # 새 파일: LF + 마지막 개행

    def test_bom_preserved(self):
        p = os.path.join(self.tmp, "bom.json")
        with open(p, "wb") as f:
            f.write(b"\xef\xbb\xbf[]\n")
        A.write_text(p, "[1]\n")
        self.assertTrue(open(p, "rb").read().startswith(b"\xef\xbb\xbf"))


class MrDuplicateTests(TempEnv):
    def test_existing_open_mr_is_reused(self):
        branch = self.work_branch("ISRIR-69281")
        sg = self.J(self.c.get("/api/env/g/sg/l-sg-bbz-x-sg"))
        sg["ingress"].append(dict(RULE, cidr_blocks="10.9.9.9/32"))
        self.assertEqual(self.c.put("/api/env/g/sg/l-sg-bbz-x-sg", json=sg).status_code, 200)
        self.assertEqual(self.c.post("/api/env/g/git/push", json={}).status_code, 200)
        state = {"open": []}
        creates = []

        def fake(env, method, path, **kw):
            if method == "GET" and path.endswith("/merge_requests"):
                assert kw["params"]["source_branch"] == branch and kw["params"]["state"] == "opened"
                return list(state["open"])
            if method == "GET" and path == "/users":
                return [{"id": 1}]
            if method == "POST" and path.endswith("/merge_requests"):
                creates.append(kw["json"])
                return {"iid": 11, "web_url": "http://x/11", "title": branch}
            return []
        A.gl = fake
        self.assertFalse(self.J(self.c.get("/api/env/g/mr/existing"))["exists"])
        r = self.J(self.c.post("/api/env/g/mr", json={"summary": "첫 MR"}))                    # 열린 MR 이 없으면 새로 생성
        self.assertEqual((r["iid"], r.get("existing")), (11, None))
        state["open"] = [{"iid": 11, "web_url": "http://x/11", "title": branch}]
        ex = self.J(self.c.get("/api/env/g/mr/existing"))
        self.assertEqual((ex["exists"], ex["iid"], ex["branch"]), (True, 11, branch))
        r = self.J(self.c.post("/api/env/g/mr", json={"summary": "두 번째 시도"}))               # 이미 열린 MR 이 있으면 새로 만들지 않음
        self.assertEqual((r["iid"], r["existing"], len(creates)), (11, True, 1))
        r = self.c.post("/api/env/g/mr", json={})                                                 # 기존 MR 연결에는 Summary 가 필요 없음
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(creates), 1)

    def test_default_branch_has_no_mr_lookup(self):
        A.gl = lambda *a, **k: (_ for _ in ()).throw(AssertionError("GitLab 조회가 없어야 함"))
        self.assertFalse(self.J(self.c.get("/api/env/g/mr/existing"))["exists"])               # main 에서는 조회하지 않음


class SecurityAndOpsTests(TempEnv):
    def test_host_and_origin_checks(self):
        ok = self.c.get("/api/version", headers={"Host": "127.0.0.1:8080"})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(self.c.get("/api/version", headers={"Host": "evil.example.com"}).status_code, 403)       # DNS rebinding
        r = self.c.post("/api/history", json={"key": "k", "entry": {"id": "x"}}, headers={"Origin": "http://evil.example.com", "Host": "127.0.0.1:8080"})
        self.assertEqual(r.status_code, 403)                                                                         # 다른 출처
        r = self.c.post("/api/history", json={"key": "k", "entry": {"id": "x"}}, headers={"Origin": "http://127.0.0.1:8080", "Host": "127.0.0.1:8080"})
        self.assertEqual(r.status_code, 200)                                                                         # 같은 출처
        self.assertEqual(self.c.get("/api/version", headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
        self.assertEqual(self.c.get("/api/version", headers={"Host": "[::1]:8080"}).status_code, 200)
        os.environ["TF_ACL_ALLOWED_HOSTS"] = "mypc.local"
        try:
            self.assertEqual(self.c.get("/api/version", headers={"Host": "mypc.local:8080"}).status_code, 200)
        finally:
            del os.environ["TF_ACL_ALLOWED_HOSTS"]

    def test_restart_requires_confirm_and_is_deferred(self):
        calls = []
        orig, A._do_restart = A._do_restart, lambda: calls.append(1)
        try:
            self.assertEqual(self.c.post("/api/restart", json={}).status_code, 400)
            self.assertEqual(self.c.post("/api/restart", json={"confirm": True}).status_code, 200)
            import time
            time.sleep(1.3)
            self.assertEqual(calls, [1])
        finally:
            A._do_restart = orig

    def test_backup_pruning(self):
        root = os.path.join(A.DATA, "backup")
        os.makedirs(root, exist_ok=True)
        for i in range(25):
            os.makedirs(os.path.join(root, "2610%02d_000000" % (i + 1)), exist_ok=True)
        os.makedirs(os.path.join(root, "keep-me"), exist_ok=True)        # 형식이 다른 폴더는 건드리지 않음
        gone = A.prune_backups(keep=20)
        self.assertEqual(len(gone), 5)
        self.assertEqual(len([d for d in os.listdir(root) if d != "keep-me"]), 20)
        self.assertTrue(os.path.isdir(os.path.join(root, "keep-me")))

    def test_not_found_without_token_mentions_token(self):
        """토큰 없이 접속해서 '저장소 없음'이 나오면 비공개 저장소일 수 있다는 안내가 붙어야 한다"""
        from types import SimpleNamespace
        from unittest import mock
        fail = SimpleNamespace(stdout="", returncode=128,
                               stderr="remote: The project you were looking for could not be found or you don't have permission to view it.\nfatal: repository 'https://x/y.git/' not found")
        env = A.get_env("g")
        A.write_json(A.LOCAL_PATH, {"account": "heejim", "tokens": {"game": "", "platform": ""}})
        with mock.patch.object(A.subprocess, "run", return_value=fail):
            with self.assertRaises(A.ApiError) as cm:
                A.run_git(env, "clone", "https://x/y.git", cwd=self.tmp)
        self.assertIn("저장소를 찾을 수 없습니다", str(cm.exception))
        self.assertIn("토큰이 입력되어 있지 않아", str(cm.exception))
        A.write_json(A.LOCAL_PATH, {"account": "heejim", "tokens": {"game": "tok", "platform": ""}})
        with mock.patch.object(A.subprocess, "run", return_value=fail):
            with self.assertRaises(A.ApiError) as cm:
                A.run_git(env, "clone", "https://x/y.git", cwd=self.tmp)
        self.assertNotIn("토큰이 입력되어 있지 않아", str(cm.exception))              # 토큰이 있으면 권한/경로 문제로만 안내

    def test_friendly_git_errors(self):
        f = A.friendly_git_error
        self.assertIn("토큰", f("fatal: Authentication failed for 'https://x/y.git'"))
        self.assertIn("토큰", f("remote: HTTP Basic: Access denied"))
        self.assertIn("토큰", f("fatal: unable to access 'https://x': The requested URL returned error: 403"))
        self.assertIn("네트워크", f("fatal: unable to access 'https://x': Could not resolve host: x"))
        self.assertIn("SSL", f("fatal: SSL certificate problem: self-signed certificate"))
        self.assertIn("저장소를 찾을 수", f("fatal: repository 'https://x/y.git' not found"))
        self.assertEqual(f("some other failure"), "")


class FreshnessTests(TempEnv):
    def test_behind_overlap_and_remote_ahead(self):
        branch = self.work_branch("ISRIR-9")
        sg = self.J(self.c.get("/api/env/g/sg/l-sg-bbz-x-sg"))
        sg["ingress"].append(dict(RULE, cidr_blocks="10.7.7.7/32"))
        self.assertEqual(self.c.put("/api/env/g/sg/l-sg-bbz-x-sg", json=sg).status_code, 200)
        f0 = self.J(self.c.get("/api/env/g/git/diff"))["freshness"]
        self.assertEqual((f0["checked"], f0["behind"], f0["overlap"], f0["remote_ahead"]), (True, 0, [], 0))   # 최신 상태
        # 다른 사람이 main 의 같은 SG 파일을 먼저 바꿔 push
        seed = os.path.join(self.tmp, "seed")
        sh("git", "pull", "origin", "main", cwd=seed)
        p = os.path.join(seed, "aws", "live", "sub", "sg", "sg_rule", "l-sg-bbz-x-sg-ingress-rules.json")
        with open(p, "a", encoding="utf-8") as fh:
            fh.write("\n")
        sh("git", "commit", "-am", "other change", cwd=seed)
        sh("git", "push", "origin", "main", cwd=seed)
        f1 = self.J(self.c.get("/api/env/g/git/diff"))["freshness"]
        self.assertEqual(f1["behind"], 1)
        self.assertEqual(f1["overlap"], ["aws/live/sub/sg/sg_rule/l-sg-bbz-x-sg-ingress-rules.json"])         # 같은 파일 -> 충돌 가능
        # 같은 작업 브랜치를 다른 곳에서 먼저 push 하면 push 를 막고 안내
        self.assertEqual(self.c.post("/api/env/g/git/push", json={}).status_code, 200)
        sh("git", "fetch", "origin", cwd=seed)
        sh("git", "checkout", "-b", branch, "origin/" + branch, cwd=seed)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write("\n")
        sh("git", "commit", "-am", "remote work", cwd=seed)
        sh("git", "push", "origin", branch, cwd=seed)
        sg["ingress"].append(dict(RULE, cidr_blocks="10.7.7.8/32"))
        self.c.put("/api/env/g/sg/l-sg-bbz-x-sg", json=sg)
        r = self.c.post("/api/env/g/git/push", json={})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.J(r)["remote_ahead"], 1)
        sh("git", "checkout", "main", cwd=seed)


class AtlantisFailureTests(TempEnv):
    def test_classification_and_unlock(self):
        c = A.classify_atlantis_failure
        self.assertEqual(A.analyze_atlantis("**Plan Error**running git clone --branch x: fatal: Remote branch x not found in upstream origin: exit status 128", "plan")["kind"], "branch_missing")
        self.assertEqual(A.analyze_atlantis("**Plan Error**fatal: Authentication failed for repo", "plan")["kind"], "clone_auth")
        r = A.analyze_atlantis("╷\n│ Error: Invalid CIDR address\n╵\nterraform plan failed", "plan")
        self.assertEqual((r["state"], r["kind"]), ("error", "tf_error"))
        self.assertIn("규칙", r["hint"])
        r = A.analyze_atlantis("This project is currently locked by an unapplied plan from pull #12", "plan")
        self.assertEqual((r["state"], r["kind"]), ("warn", "lock"))
        self.assertEqual(A.analyze_atlantis("**Plan Error** context deadline exceeded", "plan")["kind"], "timeout")
        self.assertEqual(A.analyze_atlantis("**Plan Error** something odd", "plan")["kind"], "unknown")
        self.assertNotIn("kind", A.analyze_atlantis("Plan: 1 to add, 0 to change, 0 to destroy.", "plan"))
        posts = []

        def fake(env, method, path, **kw):
            if method == "GET" and path.endswith("/merge_requests/9"):
                return {"sha": "a", "state": "opened", "source_branch": "b"}
            if "/repository/branches/" in path:
                return {}
            posts.append(kw["json"]["body"])
            return {"id": 5}
        A.gl = fake
        r = self.c.post("/api/env/p/atlantis", json={"action": "unlock", "iid": 9})
        self.assertEqual(r.status_code, 409)
        self.assertTrue(self.J(r)["need_confirm"])                       # 확인 없이는 unlock 하지 않음
        self.assertEqual(self.c.post("/api/env/p/atlantis", json={"action": "unlock", "iid": 9, "confirm_unlock": True}).status_code, 200)
        self.assertEqual(posts[-1], "atlantis unlock")


class BulkDeleteTests(TempEnv):
    def setUp(self):
        super().setUp()
        self.work_branch()
        sg = self.J(self.c.get("/api/env/g/sg/l-sg-bbz-x-sg"))
        sg["ingress"] += [dict(RULE, cidr_blocks=["10.9.9.9/32"], from_port=1001, to_port=1001),
                          dict(RULE, cidr_blocks=["10.9.9.9/32", "10.9.9.10/32"], from_port=1002, to_port=1002),
                          dict(RULE, cidr_blocks=["10.8.0.0/24"], from_port=1003, to_port=1003)]
        self.assertEqual(self.c.put("/api/env/g/sg/l-sg-bbz-x-sg", json=sg).status_code, 200)

    def test_exact_match_dry_run_then_apply(self):
        body = {"env_id": "g", "name": "l-sg-bbz-x-sg", "scope": "sg", "ips": ["10.9.9.9"]}
        d = self.J(self.c.post("/api/bulk-delete", json=dict(body, dry_run=True)))
        self.assertEqual((d["total_removed"], d["total_modified"]), (1, 1))                # 1001 삭제, 1002 는 CIDR 하나만 제거
        self.assertEqual(len(self.J(self.c.get("/api/env/g/sg/l-sg-bbz-x-sg"))["ingress"]), 4)   # 미리보기는 저장하지 않음
        r = self.J(self.c.post("/api/bulk-delete", json=dict(body, dry_run=False)))
        self.assertTrue(r["ok"])
        ing = self.J(self.c.get("/api/env/g/sg/l-sg-bbz-x-sg"))["ingress"]
        ports = {x["from_port"]: x["cidr_blocks"] for x in ing}
        self.assertNotIn(1001, ports)
        self.assertEqual(ports[1002], ["10.9.9.10/32"])                                    # 나머지 CIDR 은 유지
        self.assertEqual(ports[1003], ["10.8.0.0/24"])                                     # exact 모드는 포함 관계 대역을 건드리지 않음

    def test_explicit_targets_list(self):
        self.c.post("/api/env/g/sgs", json={"resource": "y"})
        y = self.J(self.c.get("/api/env/g/sg/l-sg-bbz-y-sg"))
        y["ingress"].append(dict(RULE, cidr_blocks=["10.9.9.9/32"], from_port=2001, to_port=2001))
        self.assertEqual(self.c.put("/api/env/g/sg/l-sg-bbz-y-sg", json=y).status_code, 200)
        body = {"env_id": "g", "targets": [{"env_id": "g", "name": "l-sg-bbz-x-sg"}, {"env_id": "g", "name": "l-sg-bbz-y-sg"}], "ips": ["10.9.9.9"], "dry_run": True}
        r = self.J(self.c.post("/api/bulk-delete", json=body))
        self.assertEqual((len(r["results"]), r["total_removed"], r["total_modified"]), (2, 2, 1))
        self.assertEqual(self.c.post("/api/bulk-delete", json=dict(body, targets=[{"env_id": "g", "name": "../x"}])).status_code, 400)

    def test_overlap_mode_and_scopes_and_guards(self):
        r = self.J(self.c.post("/api/bulk-delete", json={"env_id": "g", "scope": "env", "ips": ["10.8.0.5"], "match": "overlap", "dry_run": True}))
        self.assertEqual(r["total_removed"], 1)                                            # 10.8.0.0/24 가 10.8.0.5 를 포함
        r = self.J(self.c.post("/api/bulk-delete", json={"env_id": "g", "scope": "repo", "ips": ["10.9.9.9"], "dry_run": True}))
        self.assertGreaterEqual(r["total_removed"], 1)
        self.assertEqual(self.c.post("/api/bulk-delete", json={"env_id": "g", "scope": "sg", "name": "l-sg-bbz-x-sg", "ips": ["bad"]}).status_code, 400)
        self.assertEqual(self.c.post("/api/bulk-delete", json={"env_id": "g", "scope": "sg", "name": "l-sg-bbz-x-sg", "ips": []}).status_code, 400)
        sh("git", "checkout", "-f", "main", cwd=self.repo)
        r = self.c.post("/api/bulk-delete", json={"env_id": "g", "scope": "sg", "name": "l-sg-bbz-x-sg", "ips": ["10.9.9.9"], "dry_run": False})
        self.assertEqual(r.status_code, 409)                                               # main 에서는 삭제 거부


class ReportTests(TempEnv):
    def test_change_summary_and_markdown(self):
        self.work_branch("ISRIR-5")
        sg = self.J(self.c.get("/api/env/g/sg/l-sg-bbz-x-sg"))
        sg["ingress"].append(dict(RULE, cidr_blocks=["0.0.0.0/0"], from_port=22, to_port=22))       # 위험 규칙
        sg["ingress"] = [r for r in sg["ingress"] if r["from_port"] != 80]                           # 기존 규칙 삭제
        self.assertEqual(self.c.put("/api/env/g/sg/l-sg-bbz-x-sg", json=dict(sg), headers={"X-Allow-Main": "1"}).status_code, 200)
        r = self.J(self.c.get("/api/env/g/report/changes"))
        self.assertEqual((r["totals"]["sgs"], r["totals"]["added"], r["totals"]["removed"], r["totals"]["risks"]), (1, 1, 1, 1))
        self.assertIn("| ➕ 추가 |", r["markdown"])
        self.assertIn("| ➖ 삭제 |", r["markdown"])
        self.assertIn("전체 개방", r["markdown"])
        self.assertTrue(r["branch"].endswith("ISRIR-5"))

    def test_usage_report_ip_sg_reference_and_csv(self):
        self.work_branch("ISRIR-6")
        A.write_json(A.META_PATH, {"envs": {"g": {"sgs": {"l-sg-bbz-y-sg": {"sg_id": "sg-0abc1234"}}}}})
        self.c.post("/api/env/g/sgs", json={"resource": "y"})
        sg = self.J(self.c.get("/api/env/g/sg/l-sg-bbz-x-sg"))
        sg["ingress"].append(dict(RULE, cidr_blocks=[], security_groups="sg-0abc1234", from_port=3306, to_port=3306, description="tf_261020_ISRIR-6_y to x Connection"))
        self.c.put("/api/env/g/sg/l-sg-bbz-x-sg", json=sg)
        ip = self.J(self.c.get("/api/report/usage?q=10.1.1.1"))
        self.assertEqual(ip["count"], 1)
        self.assertIn("IP/대역", ip["rows"][0]["match"])
        ref = self.J(self.c.get("/api/report/usage?q=l-sg-bbz-y-sg"))                     # SG 이름으로 -> 그 SG 의 SG ID 를 쓰는 규칙(참조 관계)
        self.assertTrue(any(r["match"].startswith("SG 참조") and r["sg"] == "l-sg-bbz-x-sg" for r in ref["rows"]))
        self.assertEqual(self.J(self.c.get("/api/report/usage?q=sg-0abc1234"))["count"], 1)
        csvr = self.c.get("/api/report/usage?q=10.1.1.1&format=csv")
        self.assertTrue(csvr.get_data(as_text=True).startswith("\ufeff환경,SG,방향"))
        self.assertIn("| 환경 | SG |", self.c.get("/api/report/usage?q=10.1.1.1&format=md").get_data(as_text=True))
        self.assertEqual(self.J(self.c.get("/api/report/usage?q="))["count"], 0)


class OrphanMetaTests(TempEnv):
    def test_stamp_rekey_and_orphans(self):
        A.write_json(A.META_PATH, {"envs": {"g": {"sgs": {"l-sg-bbz-x-sg": {"alias": "x"}}}}})
        self.assertEqual(self.c.put("/api/meta", json=A.load_meta()).status_code, 200)
        self.assertEqual(A.load_meta()["envs"]["g"]["_sg_dir"], "aws/live/sub/sg/sg_rule")        # 저장 시 환경 경로 스냅샷 기록
        cfg = A.load_config()
        cfg["environments"][0]["id"] = "g-renamed"                                                  # 환경 ID 가 바뀐 상황
        A.write_json(A.CONFIG_PATH, cfg)
        d = self.J(self.c.post("/api/config/repair", json={"dry_run": True}))
        self.assertEqual([x["to"] for x in d["meta_rekey"]], ["g-renamed"])                          # 같은 경로의 환경으로 자동 이동
        self.J(self.c.post("/api/config/repair", json={"dry_run": False}))
        meta = A.load_meta()["envs"]
        self.assertNotIn("g", meta)
        self.assertEqual(meta["g-renamed"]["sgs"]["l-sg-bbz-x-sg"]["alias"], "x")
        meta["gone"] = {"sgs": {"zzz": {"alias": "z"}}, "_sg_dir": "aws/nowhere", "_label": "old env"}   # 어디에도 연결할 수 없는 메타
        A.write_json(A.META_PATH, {"envs": meta})
        d = self.J(self.c.post("/api/config/repair", json={"dry_run": True}))
        self.assertEqual([o["id"] for o in d["meta_orphans"]], ["gone"])
        self.assertIn("gone", A.load_meta()["envs"])                                                 # 점검만 하면 지우지 않음
        self.J(self.c.post("/api/config/repair", json={"dry_run": False, "remove_orphans": True}))
        self.assertNotIn("gone", A.load_meta()["envs"])


class PresetTests(TempEnv):
    def test_presets_validation(self):
        cfg = A.load_config()
        cfg["presets"] = [{"name": "SGP Office", "ips": ["211.34.57.0/24", "10.0.0.1"]}]
        self.assertEqual(self.c.put("/api/config", json=cfg).status_code, 200)
        cfg["presets"] = [{"name": "bad", "ips": ["999.1.1.1"]}]
        self.assertEqual(self.c.put("/api/config", json=cfg).status_code, 400)
        cfg["presets"] = [{"name": "", "ips": []}]
        self.assertEqual(self.c.put("/api/config", json=cfg).status_code, 400)


class VersionTests(TempEnv):
    def test_version(self):
        v = self.J(self.c.get("/api/version"))
        self.assertEqual(v["version"], A.VERSION)
        self.assertFalse(v["stale"])
        self.assertGreater(v["started"], 0)


class UndoAndBranchTests(TempEnv):
    F = "aws/live/sub/sg/sg_rule/l-sg-bbz-x-sg-ingress-rules.json"

    def read(self):
        with open(os.path.join(self.repo, self.F), "rb") as f:
            return f.read()

    def add_rule(self, ip):
        sg = self.J(self.c.get("/api/env/g/sg/l-sg-bbz-x-sg"))
        sg["ingress"].append(dict(RULE, cidr_blocks=ip, protocol="tcp"))
        r = self.c.put("/api/env/g/sg/l-sg-bbz-x-sg", json=sg)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))

    def test_undo_restores_exact_bytes_in_order(self):
        self.work_branch()
        before = self.read()
        self.add_rule("10.8.8.1/32")
        mid = self.read()
        self.add_rule("10.8.8.2/32")
        self.assertNotEqual(mid, self.read())
        items = self.J(self.c.get("/api/env/g/undo"))
        self.assertEqual(len(items["items"]), 2)
        self.assertTrue(items["usable"])
        self.assertEqual(self.c.post("/api/env/g/undo").status_code, 200)
        self.assertEqual(self.read(), mid)
        self.assertEqual(self.c.post("/api/env/g/undo").status_code, 200)
        self.assertEqual(self.read(), before)
        self.assertEqual(self.c.post("/api/env/g/undo").status_code, 400)       # 더 이상 없음

    def test_undo_new_sg_deletes_file(self):
        self.work_branch()
        r = self.J(self.c.post("/api/env/g/sgs", json={"resource": "undo-me"}))
        p = os.path.join(self.repo, "aws/live/sub/sg/sg_rule/%s-ingress-rules.json" % r["name"])
        self.assertTrue(os.path.exists(p))
        self.assertEqual(self.c.post("/api/env/g/undo").status_code, 200)
        self.assertFalse(os.path.exists(p))

    def test_undo_cleared_after_push_prepare(self):
        self.work_branch()
        self.add_rule("10.8.8.3/32")
        self.assertEqual(len(self.J(self.c.get("/api/env/g/undo"))["items"]), 1)
        A.undo_clear(A.get_env("g"))
        self.assertEqual(self.J(self.c.get("/api/env/g/undo"))["items"], [])

    def test_revert_sg_and_undo_the_revert(self):
        self.work_branch()
        before = self.read()
        self.add_rule("10.8.8.4/32")
        changed = self.read()
        self.assertEqual(self.c.post("/api/env/g/sg/l-sg-bbz-x-sg/revert", json={}).status_code, 400)   # 확인 필요
        r = self.c.post("/api/env/g/sg/l-sg-bbz-x-sg/revert", json={"confirm": True})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(self.read(), before)
        self.assertEqual(self.c.post("/api/env/g/sg/l-sg-bbz-x-sg/revert", json={"confirm": True}).status_code, 400)   # 변경 없음
        self.assertEqual(self.c.post("/api/env/g/undo").status_code, 200)       # 취소도 되돌릴 수 있다
        self.assertEqual(self.read(), changed)

    def test_revert_all_removes_new_files(self):
        self.work_branch()
        self.add_rule("10.8.8.5/32")
        n = self.J(self.c.post("/api/env/g/sgs", json={"resource": "revert-new"}))["name"]
        p = os.path.join(self.repo, "aws/live/sub/sg/sg_rule/%s-ingress-rules.json" % n)
        self.assertTrue(os.path.exists(p))
        r = self.c.post("/api/env/g/git/revert-all", json={"confirm": True})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertFalse(os.path.exists(p))
        self.assertEqual(self.J(self.c.get("/api/env/g/git/status?fresh=1"))["files"], [])

    def test_switch_branch_between_tickets(self):
        b1 = self.work_branch("ISRIR-11")
        env = A.get_env("g")
        A.run_git(env, "checkout", "main")                  # 다른 티켓 작업을 위해 main 으로
        A.invalidate_status()
        b2 = self.work_branch("ISRIR-12")
        names = {b["name"]: b for b in self.J(self.c.get("/api/env/g/git/branches"))["branches"]}
        self.assertIn(b1, names); self.assertIn(b2, names)
        self.assertEqual(names[b1]["ticket"], "ISRIR-11")
        self.assertTrue(names[b2]["current"])
        self.add_rule("10.8.8.6/32")
        bad = self.c.post("/api/env/g/git/switch", json={"branch": b1})
        self.assertEqual(bad.status_code, 409)               # 저장 안 된 변경이 있으면 전환 불가
        self.c.post("/api/env/g/git/revert-all", json={"confirm": True})
        ok = self.c.post("/api/env/g/git/switch", json={"branch": b1})
        self.assertEqual(ok.status_code, 200, ok.get_data(as_text=True))
        self.assertEqual(self.J(self.c.get("/api/env/g/git/status?fresh=1"))["branch"], b1)
        self.assertEqual(self.c.post("/api/env/g/git/switch", json={"branch": "nope"}).status_code, 400)

    def test_undo_wrong_branch_refused(self):
        b1 = self.work_branch("ISRIR-21")
        self.add_rule("10.8.8.7/32")
        env = A.get_env("g")
        A.run_git(env, "stash")                              # 브랜치 전환을 흉내내기 위해 변경을 치움
        A.run_git(env, "checkout", "main"); A.invalidate_status()
        self.assertEqual(self.c.post("/api/env/g/undo").status_code, 409)
        A.run_git(env, "checkout", b1); A.run_git(env, "stash", "drop"); A.invalidate_status()


class ExcelTests(TempEnv):
    SHEET = "ACL 적용내역"

    def setUp(self):
        super().setUp()
        import shutil as _sh
        for sub in ("xls", "excel_backup"):
            _sh.rmtree(os.path.join(self.tmp, sub), ignore_errors=True)
        for f in ("excel_log.json", "excel_pending.json"):
            if os.path.exists(os.path.join(A.DATA, f)):
                os.remove(os.path.join(A.DATA, f))
        A.write_json(A.LOCAL_PATH, {"account": "heejim", "tokens": {"game": "", "platform": ""}})

    def make_book(self, name="acl.xlsx", extra_rows=3, filt=True):
        import openpyxl
        from openpyxl.styles import Border, Side, Font, PatternFill
        d = os.path.join(self.tmp, "xls")
        os.makedirs(d, exist_ok=True)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = self.SHEET
        ws["A1"], ws["B1"] = "메모A", "메모B"
        for j, h in enumerate(A.EXCEL_HEADERS):
            ws.cell(row=2, column=3 + j, value=h)
        side = Side(style="thin", color="FF0000")
        for i in range(extra_rows):
            for j in range(12):
                c = ws.cell(row=3 + i, column=3 + j, value=("AWS" if j == 0 else "x%d" % i))
                c.border = Border(left=side, right=side, top=side, bottom=side)
                c.font = Font(bold=True, color="0000FF")
                c.fill = PatternFill("solid", fgColor="FFFF00")
        ws.cell(row=3 + extra_rows + 5, column=1, value="아래쪽 A열 메모")              # C열 아래에 다른 열 내용이 있어도 C 기준
        if filt:
            ws.auto_filter.ref = "C2:N%d" % (2 + extra_rows)
        ws2 = wb.create_sheet("다른 시트")
        ws2["A1"] = "그대로"
        path = os.path.join(d, name)
        wb.save(path)
        return d, path

    def configure(self, d, name="acl.xlsx", writer="임희재"):
        r = self.c.put("/api/excel/settings", json={"folder": d, "file": name, "sheet": self.SHEET, "writer": writer})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))

    def test_cells_follow_the_spreadsheet_format(self):
        A.write_json(A.META_PATH, {"envs": {"z": {"sgs": {"q0-hk-l9-log-api-alb-sg": {"sg_id": "sg-080911a3ac57eec11"}}}}})
        env = {"id": "z", "sg_dir": "aws/live/ape1/sg/sg_rule", "group": "Lordnine-Asia", "env": "review"}
        rule = {"protocol": "tcp", "from_port": 80, "to_port": 80, "cidr_blocks": ["10.250.40.145/32"], "security_groups": "", "description": ""}
        cells = A.excel_cells_for_rule(env, "q0-hk-l9-log-api-alb-sg", rule, "ingress", "허용", "ISRIR-68062", "임희재")
        self.assertEqual(cells, ["AWS", "Lordnine-Asia-review", "홍콩", "-", "10.250.40.145", "q0-hk-l9-log-api-alb",
                                 "q0-hk-l9-log-api-alb-sg(sg-080911a3ac57eec11)", "TCP", "80", "허용", "ISRIR-68062", "임희재"])
        rng = dict(rule, from_port=8000, to_port=8100, cidr_blocks=["10.0.0.0/24", "10.0.1.5/32"])
        c2 = A.excel_cells_for_rule(env, "q0-hk-l9-log-api-alb-sg", rng, "ingress", "삭제", "T-1", "w")
        self.assertEqual((c2[1], c2[4], c2[8], c2[9]), ("Lordnine-Asia-review", "10.0.0.0/24, 10.0.1.5", "8000-8100", "삭제"))
        allr = dict(rule, protocol="-1", from_port=0, to_port=0, cidr_blocks=["0.0.0.0/0"])
        c3 = A.excel_cells_for_rule(env, "x-sg", allr, "ingress", "허용", "T-1", "w")
        self.assertEqual((c3[7], c3[8], c3[6]), ("ALL", "ALL", "x-sg"))                                        # SG ID 가 없으면 이름만
        sgsrc = dict(rule, cidr_blocks=[], security_groups="sg-0aaa")
        self.assertEqual(A.excel_cells_for_rule(env, "x-sg", sgsrc, "ingress", "허용", "T", "w")[4], "sg-0aaa")
        eg = A.excel_cells_for_rule(env, "x-sg", rule, "egress", "허용", "T", "w")                      # 아웃바운드는 출발지/목적지를 바꿔 기록
        self.assertEqual((eg[3], eg[4], eg[5], eg[6]), ("x", "x-sg", "-", "10.250.40.145"))

    def test_account_column_is_group_dash_env(self):
        n = A.excel_account_name
        self.assertEqual(n({"group": "Lordnine-Asia", "env": "review"}), "Lordnine-Asia-review")
        self.assertEqual(n({"group": "bubblyz", "env": "live"}), "bubblyz-live")
        self.assertEqual(n({"group": "mgmt", "env": "mgmt"}), "mgmt")                          # 종류와 환경 이름이 같으면 한 번만
        self.assertEqual(n({"group": "stove-platform-live", "env": "live"}), "stove-platform-live")   # 이미 환경이 들어 있으면 겹치지 않음
        self.assertEqual(n({"group": "megaport-sip-dev", "env": "dev"}), "megaport-sip-dev")

    def test_append_below_last_c_cell_keeps_everything_else(self):
        import openpyxl
        d, path = self.make_book()
        res = A.excel_append(path, self.SHEET, [["AWS", "qa", "홍콩", "-", "1.1.1.1", "z", "z-sg(sg-1)", "TCP", "80", "허용", "ISRIR-1", "나"],
                                               ["AWS", "qa", "홍콩", "-", "2.2.2.2", "z", "z-sg(sg-1)", "TCP", "443", "삭제", "ISRIR-1", "나"]])
        self.assertEqual((res["first_row"], res["last_row"], res["written"]), (6, 7, 2))                # C열 마지막(5행) 바로 아래
        self.assertTrue(os.path.exists(res["backup"]))
        wb = openpyxl.load_workbook(path)
        ws = wb[self.SHEET]
        self.assertEqual([ws.cell(row=6, column=3 + j).value for j in range(12)],
                         ["AWS", "qa", "홍콩", "-", "1.1.1.1", "z", "z-sg(sg-1)", "TCP", 80, "허용", "ISRIR-1", "나"])   # 포트는 숫자
        self.assertEqual(ws.cell(row=7, column=11).value, 443)
        self.assertEqual(ws.cell(row=7, column=12).value, "삭제")
        self.assertEqual(ws["C3"].value, "AWS")                                                           # 기존 줄은 그대로
        self.assertEqual(ws["A1"].value, "메모A")
        self.assertEqual(ws.cell(row=11, column=1).value, "아래쪽 A열 메모")                                  # 다른 열 내용은 건드리지 않음
        self.assertEqual(ws["C6"].border.left.style, "thin")                                              # 이전 줄의 서식 복사
        self.assertTrue(ws["D6"].font.bold)
        self.assertEqual(ws["C6"].fill.fgColor.rgb, ws["C5"].fill.fgColor.rgb)
        self.assertEqual(ws.auto_filter.ref, "C2:N7")                                                     # 필터 범위도 새 줄까지
        self.assertEqual(wb["다른 시트"]["A1"].value, "그대로")
        res2 = A.excel_append(path, self.SHEET, [["AWS"] + ["a"] * 11])
        self.assertEqual(res2["first_row"], 8)                                                            # 다음에는 그 아래부터 이어서

    def test_append_works_when_open_in_excel_but_sheet_missing_is_error(self):
        d, path = self.make_book()
        lock = os.path.join(d, "~$acl.xlsx")
        open(lock, "w").close()
        orig_com = A.excel_com
        A.excel_com = lambda *a, **k: {"ok": False, "code": "not_open"}           # 실행 중인 엑셀에는 이 파일이 없다고 가정 (실제 엑셀을 건드리지 않음)
        try:
            res = A.excel_append(path, self.SHEET, [["AWS"] + ["a"] * 11])           # 그러면 파일에 직접 기록한다
        finally:
            A.excel_com = orig_com
        self.assertTrue(res["open_in_excel"])
        self.assertEqual((res["first_row"], res["via"]), (6, "file"))
        os.remove(lock)
        with self.assertRaises(A.ApiError) as cm:
            A.excel_append(path, "없는시트", [["AWS"] + ["a"] * 11])
        self.assertEqual(cm.exception.extra["excel_error"], "sheet_missing")
        self.assertIn(self.SHEET, cm.exception.extra["sheets"])
        import openpyxl
        self.assertEqual(openpyxl.load_workbook(path)[self.SHEET].max_row >= 5, True)                    # 실패해도 파일은 그대로

    def test_settings_files_check_and_pick_folder(self):
        d, path = self.make_book()
        open(os.path.join(d, "~$acl.xlsx"), "w").close()
        open(os.path.join(d, "memo.txt"), "w").close()
        self.make_book("other.xlsm") if False else None
        st = self.J(self.c.get("/api/excel/settings"))
        self.assertFalse(st["configured"])
        self.assertEqual(self.J(self.c.get("/api/excel/files?folder=" + d))["files"], ["acl.xlsx"])        # 임시/비엑셀 파일 제외
        self.assertEqual(self.c.put("/api/excel/settings", json={"folder": d, "file": "nope.xlsx"}).status_code, 400)
        self.assertEqual(self.c.put("/api/excel/settings", json={"folder": d, "file": "../acl.xlsx"}).status_code, 400)
        self.assertEqual(self.c.put("/api/excel/settings", json={"folder": os.path.join(d, "x"), "file": ""}).status_code, 400)
        os.remove(os.path.join(d, "~$acl.xlsx"))
        self.configure(d)
        st = self.J(self.c.get("/api/excel/settings"))
        self.assertTrue(st["configured"])
        self.assertEqual((st["sheet"], st["writer"]), (self.SHEET, "임희재"))
        chk = self.J(self.c.get("/api/excel/check"))
        self.assertEqual((chk["last_row"], chk["next_row"], chk["header_row"], chk["mismatch"]), (5, 6, 2, []))
        orig = A.excel_pick_folder
        A.excel_pick_folder = lambda initial="": d
        try:
            r = self.J(self.c.post("/api/excel/pick-folder", json={}))
        finally:
            A.excel_pick_folder = orig
        self.assertEqual((r["folder"], r["files"]), (d, ["acl.xlsx"]))

    def test_shared_read_while_excel_holds_the_file(self):
        """엑셀이 파일을 열고 있어(공유 위반) 파이썬 기본 open 은 실패해도, 공유 읽기로는 읽을 수 있다 (윈도우 전용)"""
        if os.name != "nt":
            self.skipTest("윈도우 전용")
        import ctypes
        from ctypes import wintypes
        d, path = self.make_book()
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateFileW.restype = wintypes.HANDLE
        k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        h = k.CreateFileW(path, 0xC0010000, 1, None, 3, 0x80, None)                 # 엑셀(OneDrive 파일)처럼: 읽기+쓰기+삭제 접근으로 열고 읽기만 공유
        self.assertNotEqual(h, wintypes.HANDLE(-1).value)
        try:
            with self.assertRaises(PermissionError):
                open(path, "rb").read()                                              # 예전 방식: 권한 없음
            self.assertTrue(A.excel_locked_by_excel(path))                           # ~$ 파일이 없어도 열려 있음을 감지
            self.assertEqual(A.read_shared(path)[:2], b"PK")
            wb = A.excel_open(path)
            self.assertEqual(wb[self.SHEET]["C3"].value, "AWS")
            self.assertTrue(os.path.exists(A.excel_backup(path)))                    # 백업도 만들어진다
        finally:
            k.CloseHandle(h)
        self.assertFalse(A.excel_locked_by_excel(path))                              # 닫으면 다시 열려 있지 않음

    def test_append_goes_to_running_excel_when_open(self):
        import openpyxl
        d, path = self.make_book()
        sent = {}
        orig_l, orig_c = A.excel_locked_by_excel, A.excel_com
        A.excel_locked_by_excel = lambda p: True

        def fake_com(mode, p, sheet, rows=None):
            sent.update(mode=mode, path=p, sheet=sheet, rows=rows)
            return {"ok": True, "first": 1037, "last": 1038, "written": len(rows)}
        A.excel_com = fake_com
        try:
            res = A.excel_append(path, self.SHEET, [["AWS", "g-live", "홍콩", "-", "1.1.1.1", "z", "z-sg(sg-1)", "TCP", "80", "허용", "T-1", "나"],
                                                   ["AWS", "g-live", "홍콩", "-", "2.2.2.2", "z", "z-sg(sg-1)", "TCP", "8000-8100", "삭제", "T-1", "나"]])
        finally:
            A.excel_locked_by_excel, A.excel_com = orig_l, orig_c
        self.assertEqual((res["via"], res["first_row"], res["last_row"], res["written"]), ("excel", 1037, 1038, 2))
        self.assertEqual((sent["mode"], sent["sheet"]), ("append", self.SHEET))
        self.assertEqual(sent["rows"][0][8], 80)                                     # 포트는 숫자로 전달
        self.assertEqual(sent["rows"][1][8], "8000-8100")
        self.assertEqual(openpyxl.load_workbook(path)[self.SHEET].max_row, 11)       # 파일은 바꾸지 않음 (엑셀에 직접 기록했으므로)

    def test_running_excel_errors_are_reported(self):
        d, path = self.make_book()
        orig_l, orig_c = A.excel_locked_by_excel, A.excel_com
        A.excel_locked_by_excel = lambda p: True
        try:
            for code, word in (("readonly", "읽기 전용"), ("protected", "보호"), ("sheet_missing", "시트")):
                A.excel_com = lambda *a, code=code, **k: {"ok": False, "code": code, "sheets": ["A"]}
                with self.assertRaises(A.ApiError) as cm:
                    A.excel_append(path, self.SHEET, [["AWS"] + ["a"] * 11])
                self.assertIn(word, str(cm.exception))
        finally:
            A.excel_locked_by_excel, A.excel_com = orig_l, orig_c

    def test_check_reads_live_excel_when_open(self):
        d, path = self.make_book()
        self.configure(d)
        orig_l, orig_c = A.excel_locked_by_excel, A.excel_com
        A.excel_locked_by_excel = lambda p: True
        A.excel_com = lambda mode, p, sheet, rows=None: {"ok": True, "last": 1036, "header_row": 2, "headers": list(A.EXCEL_HEADERS),
                                                         "sheets": [self.SHEET], "readonly": False, "protected": False}
        try:
            chk = self.J(self.c.get("/api/excel/check"))
        finally:
            A.excel_locked_by_excel, A.excel_com = orig_l, orig_c
        self.assertEqual((chk["via"], chk["last_row"], chk["next_row"], chk["mismatch"], chk["locked"]), ("excel", 1036, 1037, [], True))

    def test_powershell_script_parses(self):
        """엑셀 연동용 PowerShell 스크립트에 문법 오류가 없는지 (실행하지 않고 구문만 검사)"""
        if os.name != "nt":
            self.skipTest("윈도우 전용")
        import subprocess as sp
        f = os.path.join(self.tmp, "x.ps1")
        with open(f, "w", encoding="utf-8-sig") as fh:
            fh.write(A.EXCEL_COM_PS1)
        cmd = ("$e=$null;$t=$null;[void][System.Management.Automation.Language.Parser]::ParseFile('%s',[ref]$t,[ref]$e);"
               "if($e.Count){$e|%%{$_.Message};exit 1}" % f.replace("'", "''"))
        r = sp.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd], capture_output=True, timeout=60)
        self.assertEqual(r.returncode, 0, (r.stdout + r.stderr).decode("utf-8", "replace")[:400])

    def test_pick_folder_keeps_korean_path(self):
        """폴더 선택 창을 띄우는 자식 프로세스의 출력이 한글 경로여도 깨지거나 None 이 되지 않는다 (가짜 tkinter 사용, 창은 열리지 않음)"""
        stub = os.path.join(self.tmp, "tkstub")
        os.makedirs(os.path.join(stub, "tkinter"), exist_ok=True)
        with open(os.path.join(stub, "tkinter", "__init__.py"), "w", encoding="utf-8") as f:
            f.write("class Tk:\n    def withdraw(self): pass\n    def attributes(self, *a): pass\n")
        with open(os.path.join(stub, "tkinter", "filedialog.py"), "w", encoding="utf-8") as f:
            f.write("def askdirectory(**kw):\n    return 'C:/Users/희재/OneDrive - 회사/엑셀 폴더'\n")
        old = os.environ.get("PYTHONPATH")
        os.environ["PYTHONPATH"] = stub + (os.pathsep + old if old else "")
        try:
            got = A.excel_pick_folder("")
        finally:
            if old is None:
                os.environ.pop("PYTHONPATH", None)
            else:
                os.environ["PYTHONPATH"] = old
        self.assertEqual(got, os.path.normpath("C:/Users/희재/OneDrive - 회사/엑셀 폴더"))

    def test_pick_folder_cancel_and_cp949_output(self):
        from types import SimpleNamespace
        from unittest import mock
        with mock.patch.object(A.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=b"", stderr=b"")):
            self.assertEqual(A.excel_pick_folder(""), "")                                      # 취소하면 빈 값
        with mock.patch.object(A.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=None, stderr=None)):
            self.assertEqual(A.excel_pick_folder(""), "")                                      # None 이어도 오류 없이
        cp = "D:/엑셀".encode("cp949")
        with mock.patch.object(A.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=cp, stderr=b"")):
            self.assertEqual(A.excel_pick_folder(""), os.path.normpath("D:/엑셀"))              # 옛 방식(cp949)으로 나와도 해석
        with mock.patch.object(A.subprocess, "run", return_value=SimpleNamespace(returncode=1, stdout=b"", stderr=b"No module named tkinter")):
            with self.assertRaises(A.ApiError):
                A.excel_pick_folder("")

    def test_check_warns_when_headers_differ(self):
        import openpyxl
        d, path = self.make_book()
        wb = openpyxl.load_workbook(path)
        wb[self.SHEET]["F2"] = "엉뚱한 제목"
        wb.save(path)
        self.configure(d)
        chk = self.J(self.c.get("/api/excel/check"))
        self.assertEqual([x[0] for x in chk["mismatch"]], ["출발지 (Zone)"])

    def test_preview_append_duplicates_and_pending(self):
        import openpyxl
        d, path = self.make_book()
        self.configure(d)
        rule = lambda ip, port: {"direction": "ingress", "protocol": "tcp", "from_port": port, "to_port": port, "cidr_blocks": [ip],
                                 "security_groups": "", "prefix_list_ids": [], "description": "d"}
        state = {"sgs": [{"env_id": "g", "name": "l-sg-bbz-x-sg", "added": [rule("10.9.9.1/32", 80), dict(rule("10.9.9.2/32", 443), direction="egress")],
                          "removed": [rule("10.9.9.3/32", 22)]}]}
        A.write_json(A.META_PATH, {"envs": {"g": {"sgs": {"l-sg-bbz-x-sg": {"sg_id": "sg-0abc"}}}}})
        A.write_json(A.LOCAL_PATH, {"account": "heejim", "tokens": {"game": "", "platform": ""}, "excel": A.excel_settings()})
        orig = A.change_summary
        A.change_summary = lambda env: {"branch": "heejim/261027_ISRIR-68062_x", "base": "main", "sgs": state["sgs"], "totals": {}, "risks": [], "markdown": ""}
        try:
            pv = self.J(self.c.get("/api/env/g/excel/preview?ticket="))
            self.assertEqual(pv["ticket"], "ISRIR-68062")                                                 # 브랜치 이름에서 티켓번호
            self.assertEqual(len(pv["rows"]), 3)
            by = {(r["direction"], r["cells"][9]): r for r in pv["rows"]}
            self.assertTrue(by[("ingress", "허용")]["checked"])
            self.assertTrue(by[("ingress", "삭제")]["checked"])
            self.assertFalse(by[("egress", "허용")]["checked"])                                           # 아웃바운드는 기본 꺼짐
            c = by[("ingress", "허용")]["cells"]
            self.assertEqual((c[1], c[4], c[6], c[7], c[8], c[11]), ("bbz-live", "10.9.9.1", "l-sg-bbz-x-sg(sg-0abc)", "TCP", "80", "임희재"))
            send = [r for r in pv["rows"] if r["checked"]]
            r = self.c.post("/api/excel/append", json={"rows": send})
            self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
            self.assertEqual((self.J(r)["first_row"], self.J(r)["written"]), (6, 2))
            ws = openpyxl.load_workbook(path)[self.SHEET]
            self.assertEqual([ws.cell(row=6, column=11).value, ws.cell(row=7, column=12).value], [80, "삭제"])
            pv2 = self.J(self.c.get("/api/env/g/excel/preview"))
            self.assertTrue(all(x["dup"] for x in pv2["rows"] if x["direction"] == "ingress"))            # 같은 건은 이미 기록됨 표시
            self.assertFalse(any(x["checked"] for x in pv2["rows"]))
            # main 으로 돌아가 변경이 없어진 뒤에도 (apply 직전에 계산해 둔) 남은 줄은 다시 볼 수 있다
            state["sgs"] = []
            pv3 = self.J(self.c.get("/api/env/g/excel/preview"))
            self.assertTrue(pv3["from_pending"])
            self.assertEqual(len(pv3["rows"]), 1)                                                         # 기록하지 않은 아웃바운드 1줄만 남음
            self.assertEqual(pv3["rows"][0]["direction"], "egress")
            pv4 = self.J(self.c.get("/api/env/g/excel/preview?ticket=ISRIR-1"))                          # 티켓번호를 바꾸면 다른 건이므로 모두 다시 보임
            self.assertEqual(pv4["rows"][0]["cells"][10], "ISRIR-1")
        finally:
            A.change_summary = orig

    def test_append_rejects_bad_rows_and_unconfigured(self):
        self.assertEqual(self.c.post("/api/excel/append", json={"rows": [["a"] * 12]}).status_code, 400)   # 설정 전
        d, path = self.make_book()
        self.configure(d)
        self.assertEqual(self.c.post("/api/excel/append", json={"rows": []}).status_code, 400)
        self.assertEqual(self.c.post("/api/excel/append", json={"rows": [{"cells": ["a", "b"]}]}).status_code, 400)


class SearchExcludesAnyTests(TempEnv):
    def put_any_rules(self):
        self.work_branch()
        sg = self.J(self.c.get("/api/env/g/sg/l-sg-bbz-x-sg"))
        sg["ingress"].append(dict(RULE, cidr_blocks="10.162.142.0/24", protocol="tcp", from_port=9091, to_port=9091))
        sg["egress"] = [dict(RULE, cidr_blocks="0.0.0.0/0", protocol="-1", from_port=0, to_port=0, description="all out")]
        r = self.c.put("/api/env/g/sg/l-sg-bbz-x-sg", json=sg)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))

    def hits(self, q):
        res = self.J(self.c.get("/api/search?q=" + q))["results"]
        return [h for x in res for h in x["hits"]]

    def test_ip_search_skips_anywhere_rules(self):
        self.put_any_rules()
        h = self.hits("10.162.142.198")
        self.assertTrue(any("10.162.142.0/24" in x for x in h), h)       # 실제로 겹치는 대역은 나옴
        self.assertFalse(any("0.0.0.0/0" in x for x in h), h)            # 0.0.0.0/0 은 제외

    def test_searching_anywhere_itself_still_works(self):
        self.put_any_rules()
        self.assertTrue(any("0.0.0.0/0" in x for x in self.hits("0.0.0.0/0")))

    def test_sg_with_only_anywhere_match_is_not_listed(self):
        self.put_any_rules()
        A.write_json(A.META_PATH, {"envs": {}})
        res = self.J(self.c.get("/api/search?q=10.99.99.99"))["results"]
        self.assertEqual([x for x in res if x["type"] == "sg"], [])      # 이 IP 와 겹치는 건 0.0.0.0/0 뿐 -> 결과 없음


class AwsTests(TempEnv):
    def tearDown(self):
        for n in ("aws_run", "aws_profiles", "aws_cli_present", "aws_start_login"):
            if hasattr(self, "_orig_" + n):
                setattr(A, n, getattr(self, "_orig_" + n))

    def patch(self, **fns):
        for n, f in fns.items():
            if not hasattr(self, "_orig_" + n):
                setattr(self, "_orig_" + n, getattr(A, n))
            setattr(A, n, f)

    def test_classify_errors(self):
        k = lambda t: A.classify_aws_error(t)[0]
        self.assertEqual(k("Error when retrieving token from sso: Token has expired and refresh failed"), "login_needed")
        self.assertEqual(k("Unable to locate credentials. You can configure credentials by running aws configure"), "login_needed")
        self.assertEqual(k("The SSO session associated with this profile has expired or is otherwise invalid. To refresh this SSO session run aws sso login"), "login_needed")
        self.assertEqual(k("An error occurred (UnauthorizedOperation) when calling the DescribeSubnets operation: You are not authorized to perform this operation."), "denied")
        self.assertEqual(k("An error occurred (AccessDenied) when calling the X operation"), "denied")
        self.assertEqual(k("The config profile (x) could not be found"), "profile_missing")
        self.assertEqual(k("An error occurred (InvalidVpcID.NotFound) when calling the DescribeVpcs operation: The vpc ID 'vpc-1' does not exist"), "wrong_account")
        self.assertEqual(k("something else"), "other")

    def test_only_read_commands_allowed(self):
        for svc, cmd in (("ec2", "delete-security-group"), ("ec2", "authorize-security-group-ingress"), ("iam", "list-users"), ("s3", "rm")):
            with self.assertRaises(A.ApiError):
                A.aws_run("p", svc, cmd)
        self.assertTrue(all(c.startswith(("describe-", "get-")) for _s, c in A.AWS_READ_ALLOW))

    def test_profiles_scope_and_suggestions(self):
        cfgp = os.path.join(self.tmp, "aws_config")
        with open(cfgp, "w") as f:
            f.write("[default]\nregion = x\n\n[profile live-bubblyz-global]\nsso_session = a\n\n[profile qa-bubblyz-global]\n\n[sso-session a]\nsso_start_url = https://x\n\n[profile dev-sip]\n")
        old = os.environ.get("AWS_CONFIG_FILE")
        os.environ["AWS_CONFIG_FILE"] = cfgp
        try:
            self.assertEqual(A.aws_profiles(), ["default", "live-bubblyz-global", "qa-bubblyz-global", "dev-sip"])
            env = {"group": "bubblyz", "sg_dir": "aws/review/review2/apne1/main/sg/sg_rule"}
            self.assertEqual(A.aws_scope(env), ("review", "ap-northeast-1"))
            self.assertEqual(A.aws_scope({"sg_dir": "aws/mgmt/apne2/sg/sg_rule"}), ("mgmt", "ap-northeast-2"))
            self.assertEqual(A.suggest_profiles(env, A.aws_profiles())[:2], ["live-bubblyz-global", "qa-bubblyz-global"])
        finally:
            if old is None:
                os.environ.pop("AWS_CONFIG_FILE", None)
            else:
                os.environ["AWS_CONFIG_FILE"] = old

    def test_fetch_preview_builds_meta_shape(self):
        def fake(profile, service, command, extra=None, region=None, timeout=90):
            self.assertEqual(region, "ap-northeast-2")
            if command == "describe-security-groups":
                return [{"id": "sg-0aaa", "name": "l-sg-bbz-x-sg", "vpc": "vpc-1", "tags": None},
                        {"id": "sg-0bbb", "name": "zzz", "vpc": "vpc-1", "tags": [{"Key": "Name", "Value": "l-sg-bbz-y-sg"}]},
                        {"id": "sg-dup1", "name": "dup", "vpc": "vpc-1", "tags": None}]
            if command == "describe-subnets":
                return [{"id": "s1", "vpc": "vpc-1", "cidr": "10.1.1.0/24", "tags": [{"Key": "Name", "Value": "pri-a"}]},
                        {"id": "s0", "vpc": "vpc-1", "cidr": "10.1.0.0/24", "tags": [{"Key": "Name", "Value": "pub-a"}]}]
            if command == "describe-vpcs":
                return {"Vpcs": [{"CidrBlock": "10.1.0.0/16", "CidrBlockAssociationSet": [{"CidrBlock": "10.1.0.0/16"}]}]}
            if command == "describe-nat-gateways":
                return [{"id": "nat-1", "state": "available", "ips": ["3.3.3.3"]}, {"id": "nat-2", "state": "deleted", "ips": ["9.9.9.9"]}]
            if command == "describe-route-tables":
                return [{"id": "rm", "vpc": "vpc-1", "assoc": [{"subnet": None, "main": True}], "routes": [{"dest": "0.0.0.0/0", "nat": "nat-1"}]},
                        {"id": "rp", "vpc": "vpc-1", "assoc": [{"subnet": "s0", "main": False}], "routes": [{"dest": "0.0.0.0/0", "nat": None}]}]
        self.patch(aws_run=fake)
        r = self.c.post("/api/env/g/aws/fetch", json={"profile": "p1", "region": "ap-northeast-2"})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        d = self.J(r)
        st = {x["name"]: x for x in d["sgs"]}
        self.assertEqual(st["l-sg-bbz-x-sg"]["sg_id"], "sg-0aaa")
        self.assertEqual(st["l-sg-bbz-x-sg"]["status"], "new")                    # 메타에 아직 없음
        self.assertEqual(d["vpc_ids"], ["vpc-1"])
        subs = {x["subnet_name"]: x for x in d["subnets"]}
        self.assertEqual(subs["pri-a"]["nat_ip"], "3.3.3.3")                      # 기본 라우팅 테이블 -> NAT
        self.assertEqual(subs["pub-a"]["nat_ip"], "-")                            # NAT 을 쓰지 않는 서브넷
        self.assertEqual(d["nat_ips"], ["3.3.3.3"])                               # 삭제된 NAT 은 제외
        self.assertEqual(d["vpc_cidrs"], ["10.1.0.0/16"])
        self.assertEqual([x["ipv4_cidr"] for x in d["subnets"]], ["10.1.0.0/24", "10.1.1.0/24"])

    def test_fetch_matches_names_with_env_prefix(self):
        """파일의 SG 이름에는 환경 접두어가 없고 AWS 에만 붙어 있어도 같은 SG 로 찾는다 (플랫폼 폴더)"""
        self.assertTrue(A.sg_name_matches("ugc-sandbox-apne1-sip-external-x-sg", "external-x-sg"))
        self.assertTrue(A.sg_name_matches("External-X-SG", "external-x-sg"))
        self.assertFalse(A.sg_name_matches("myexternal-x-sg", "external-x-sg"))          # 단어 중간부터 일치는 제외
        self.assertFalse(A.sg_name_matches("external-x-sg-old", "external-x-sg"))
        self.assertTrue(A.sg_name_matches("ugc-sandbox-apne1-sip-external-x-sg", "external-x"))     # 파일 이름에 -sg 가 없어도
        self.assertEqual(A.sg_env_hint({"sg_dir": "aws/megaport-sip-live/apne1/ugc-sandbox/sg/sg_rule"}), "ugc-sandbox")

        def fake(profile, service, command, extra=None, region=None, timeout=90):
            if command == "describe-security-groups":
                return [{"id": "sg-0aaa", "name": "ugc-sandbox-apne1-sip-l-sg-bbz-x-sg", "vpc": "vpc-1", "tags": None},
                        {"id": "sg-0bbb", "name": "other", "vpc": "vpc-1", "tags": [{"Key": "Name", "Value": "pre-l-sg-bbz-y-sg"}]}]
            return {"Vpcs": []} if command == "describe-vpcs" else []
        self.patch(aws_run=fake)
        d = self.J(self.c.post("/api/env/g/aws/fetch", json={"profile": "p1", "region": "ap-northeast-2"}))
        st = {x["name"]: x for x in d["sgs"]}
        self.assertEqual((st["l-sg-bbz-x-sg"]["sg_id"], st["l-sg-bbz-x-sg"]["status"]), ("sg-0aaa", "new"))
        self.assertEqual(st["l-sg-bbz-x-sg"]["aws_name"], "ugc-sandbox-apne1-sip-l-sg-bbz-x-sg")

    def test_fetch_picks_env_prefix_among_same_account_envs(self):
        """같은 계정에 sandbox / ugc-sandbox / ugc-live 가 같이 있어도 sg_dir 의 폴더 이름(ugc-sandbox)으로 구분하고, 파일 이름에 -sg 가 없어도 찾는다"""
        env = {"sg_dir": "aws/acct/apne1/ugc-sandbox/sg/sg_rule"}
        self.assertEqual(A.sg_env_hint(env), "ugc-sandbox")
        by = {"sandbox-apne1-sip-ext-alloy-sg": "sg-1", "ugc-live-apne1-sip-ext-alloy-sg": "sg-2", "ugc-sandbox-apne1-sip-ext-alloy-sg": "sg-3"}
        cand = [(k, v) for k, v in by.items() if A.sg_name_matches(k, "ext-alloy")]
        self.assertEqual(len(cand), 3)
        self.assertEqual([v for k, v in cand if k.startswith("ugc-sandbox-")], ["sg-3"])

    def test_fetch_errors_reach_client_with_kind(self):
        def login(*a, **k):
            raise A.ApiError("로그인 필요", 401, aws_error="login_needed", profile="p1", detail="x")
        self.patch(aws_run=login)
        r = self.c.post("/api/env/g/aws/fetch", json={"profile": "p1", "region": "ap-northeast-2"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self.J(r)["aws_error"], "login_needed")
        self.assertEqual(self.c.post("/api/env/g/aws/fetch", json={"region": "ap-northeast-2"}).status_code, 400)
        self.assertEqual(self.c.post("/api/env/g/aws/fetch", json={"profile": "p1", "region": "mars"}).status_code, 400)

    def test_cli_error_text_becomes_login_needed(self):
        from types import SimpleNamespace
        from unittest import mock
        res = SimpleNamespace(returncode=255, stdout="", stderr="Error when retrieving token from sso: Token has expired and refresh failed")
        with mock.patch.object(A.shutil, "which", return_value="aws"), mock.patch.object(A.subprocess, "run", return_value=res):
            with self.assertRaises(A.ApiError) as cm:
                A.aws_run("p1", "ec2", "describe-subnets")
        self.assertEqual(cm.exception.extra["aws_error"], "login_needed")
        self.assertEqual(cm.exception.code, 401)

    def test_detect_picks_account_that_has_the_sgs(self):
        calls = []

        def fake(profile, service, command, extra=None, region=None, timeout=90):
            calls.append(profile)
            if profile == "no-login":
                raise A.ApiError("로그인 필요", 401, aws_error="login_needed", profile=profile, detail="x")
            if profile == "denied":
                raise A.ApiError("권한", 403, aws_error="denied", profile=profile, detail="x")
            if profile in ("right", "right-readonly"):
                return ["l-sg-bbz-x-sg", "l-sg-bbz-y-sg"]
            return ["l-sg-bbz-x-sg"] if profile == "partial" else []
        self.patch(aws_run=fake, aws_profiles=lambda: ["other", "no-login", "denied", "partial", "right", "right-readonly"], aws_cli_present=lambda: True)
        orig_acc = A.aws_profile_accounts
        A.aws_profile_accounts = lambda: {"other": "111", "no-login": "222", "denied": "333", "partial": "444", "right": "555", "right-readonly": "555"}
        try:
            r = self.c.post("/api/env/g/aws/detect", json={"region": "ap-northeast-1"})
            self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
            d = self.J(r)
            self.assertEqual(d["best"]["profile"], "right")                      # 같은 계정(555)은 대표 하나만 조회
            self.assertEqual(d["best"]["found"], 2)
            self.assertNotIn("right-readonly", calls)
            self.assertEqual(d["login_needed"], ["no-login"])
            st = {x["profile"]: x["status"] for x in d["results"]}
            self.assertEqual(st["denied"], "denied")
            self.assertEqual(self.J(self.c.get("/api/env/g/aws/context"))["saved"], "right")   # 다음부터는 바로 사용
        finally:
            A.aws_profile_accounts = orig_acc

    def test_detect_without_match_or_region(self):
        self.patch(aws_run=lambda *a, **k: [], aws_profiles=lambda: ["a", "b"], aws_cli_present=lambda: True)
        d = self.J(self.c.post("/api/env/g/aws/detect", json={"region": "ap-northeast-1"}))
        self.assertIsNone(d["best"])
        self.assertEqual(self.c.post("/api/env/g/aws/detect", json={}).status_code, 400)        # 이 환경 경로에서 리전을 알 수 없음

    def test_profile_accounts_parsed(self):
        cfgp = os.path.join(self.tmp, "aws_config2")
        with open(cfgp, "w") as f:
            f.write("[profile a]\nsso_account_id = 123456789012\nsso_role_name = x\n\n[profile b]\nsso_account_id=123456789012\n\n[profile c]\nregion = x\n\n[sso-session s]\nsso_account_id = 999\n")
        old = os.environ.get("AWS_CONFIG_FILE")
        os.environ["AWS_CONFIG_FILE"] = cfgp
        try:
            self.assertEqual(A.aws_profile_accounts(), {"a": "123456789012", "b": "123456789012", "c": ""})
        finally:
            if old is None:
                os.environ.pop("AWS_CONFIG_FILE", None)
            else:
                os.environ["AWS_CONFIG_FILE"] = old

    def test_resource_ips_per_sg(self):
        def fake(profile, service, command, extra=None, region=None, timeout=90):
            if command == "describe-network-interfaces":
                return [{"ips": ["10.1.0.10", "10.1.0.9"], "pub": "52.0.0.1", "groups": ["sg-0aaa"]},
                        {"ips": ["10.1.1.20"], "pub": None, "groups": ["sg-0aaa", "sg-0bbb"]}, {"ips": None, "pub": None, "groups": None}]
            if command == "describe-security-groups":
                return [{"id": "sg-0aaa", "name": "l-sg-bbz-x-sg", "vpc": "vpc-1", "tags": None}, {"id": "sg-0bbb", "name": "l-sg-bbz-y-sg", "vpc": "vpc-1", "tags": None}]
            return [] if command != "describe-vpcs" else {}
        self.patch(aws_run=fake)
        d = self.J(self.c.post("/api/env/g/aws/fetch", json={"profile": "p1", "region": "ap-northeast-2"}))
        st = {x["name"]: x for x in d["sgs"]}
        self.assertEqual(st["l-sg-bbz-x-sg"]["ips"], ["10.1.0.9", "10.1.0.10", "10.1.1.20", "52.0.0.1"])   # 숫자 순서
        self.assertEqual(len(st), 1)

    def test_resource_ips_denied_does_not_break_fetch(self):
        def fake(profile, service, command, extra=None, region=None, timeout=90):
            if command == "describe-network-interfaces":
                raise A.ApiError("권한", 403, aws_error="denied", profile=profile, detail="x")
            if command == "describe-security-groups":
                return [{"id": "sg-0aaa", "name": "l-sg-bbz-x-sg", "vpc": "vpc-1", "tags": None}]
            return [] if command != "describe-vpcs" else {}
        self.patch(aws_run=fake)
        r = self.c.post("/api/env/g/aws/fetch", json={"profile": "p1", "region": "ap-northeast-2"})
        self.assertEqual(r.status_code, 200)
        d = self.J(r)
        self.assertIn("네트워크 인터페이스", d["note"])
        self.assertEqual(d["sgs"][0]["sg_id"], "sg-0aaa")
        self.assertEqual(d["sgs"][0]["ips"], [])

    def test_detect_stops_early_when_all_sgs_found(self):
        calls = []
        profs = ["p%02d" % i for i in range(30)]

        def fake(profile, service, command, extra=None, region=None, timeout=90):
            calls.append(profile)
            return ["l-sg-bbz-x-sg"] if profile == "p02" else []          # 앞쪽 프로필에서 전부 찾음
        self.patch(aws_run=fake, aws_profiles=lambda: profs, aws_cli_present=lambda: True)
        orig_acc = A.aws_profile_accounts
        A.aws_profile_accounts = lambda: {p: str(1000 + i) for i, p in enumerate(profs)}
        try:
            d = self.J(self.c.post("/api/env/g/aws/detect", json={"region": "ap-northeast-1"}))
        finally:
            A.aws_profile_accounts = orig_acc
        self.assertEqual(d["best"]["profile"], "p02")
        self.assertEqual(len(calls), 6)                                       # 첫 묶음(6개)만 확인하고 끝냄 (30개 전부 확인하지 않음)

    def test_detect_uses_prefix_match_only_when_exact_finds_nothing(self):
        calls = []

        def fake(profile, service, command, extra=None, region=None, timeout=90):
            vals = extra[1]
            calls.append((profile, vals))
            if "*" in vals:       # 접두어/-sg 가 붙은 이름으로만 있는 계정
                return ["ugc-sandbox-apne1-sip-l-sg-bbz-x-sg"] if profile == "sip" else []
            return ["l-sg-bbz-x-sg"] if profile == "exact" else []
        self.patch(aws_run=fake, aws_profiles=lambda: ["exact", "sip"], aws_cli_present=lambda: True)
        orig_acc = A.aws_profile_accounts
        A.aws_profile_accounts = lambda: {"exact": "111", "sip": "222"}
        try:
            d = self.J(self.c.post("/api/env/g/aws/detect", json={"region": "ap-northeast-1"}))
            self.assertEqual(d["best"]["profile"], "exact")
            self.assertFalse([c for c in calls if "*" in c[1]])                    # 정확한 이름으로 찾았으면 느슨한 조회는 하지 않는다
            calls.clear()
            self.patch(aws_profiles=lambda: ["sip", "other"])
            A.aws_profile_accounts = lambda: {"sip": "222", "other": "333"}
            d = self.J(self.c.post("/api/env/g/aws/detect", json={"region": "ap-northeast-1"}))
            self.assertEqual(d["best"]["profile"], "sip")                         # 정확한 이름으로 아무도 못 찾으면 접두어 이름으로 찾는다
        finally:
            A.aws_profile_accounts = orig_acc

    def test_detect_falls_back_to_name_tag(self):
        seen = []

        def fake(profile, service, command, extra=None, region=None, timeout=90):
            flt = extra[1] if extra and extra[0] == "--filters" else ""
            seen.append((profile, flt.split(",")[0]))
            return ["l-sg-bbz-x-sg"] if (profile == "b" and flt.startswith("Name=tag:Name")) else []
        self.patch(aws_run=fake, aws_profiles=lambda: ["a", "b"], aws_cli_present=lambda: True)
        orig_acc = A.aws_profile_accounts
        A.aws_profile_accounts = lambda: {"a": "1", "b": "2"}
        try:
            d = self.J(self.c.post("/api/env/g/aws/detect", json={"region": "ap-northeast-1"}))
        finally:
            A.aws_profile_accounts = orig_acc
        self.assertEqual(d["best"]["profile"], "b")                           # 이름이 아니라 Name 태그로 붙은 SG
        self.assertTrue(any(f == "Name=tag:Name" for _p, f in seen))

    def test_fetch_runs_independent_calls_in_parallel(self):
        import threading, time as _t
        active, peak, lock = [0], [0], threading.Lock()

        def fake(profile, service, command, extra=None, region=None, timeout=90):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            _t.sleep(0.15)
            with lock:
                active[0] -= 1
            if command == "describe-security-groups":
                return [{"id": "sg-0aaa", "name": "l-sg-bbz-x-sg", "vpc": "vpc-1", "tags": None}]
            return {} if command == "describe-vpcs" else []
        self.patch(aws_run=fake)
        A.write_json(A.META_PATH, {"envs": {"g": {"subnets": [{"vpc_id": "vpc-1", "ipv4_cidr": "10.0.0.0/24"}], "sgs": {}}}})
        t0 = _t.time()
        r = self.c.post("/api/env/g/aws/fetch", json={"profile": "p1", "region": "ap-northeast-2"})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertGreaterEqual(peak[0], 4)                                   # 여러 조회가 동시에 실행됨
        self.assertLess(_t.time() - t0, 0.15 * 6)                             # 순서대로 했다면 0.9초 이상

    def test_region_codes_and_normalize(self):
        self.assertEqual(A.REGION_MAP["ape1"], "ap-east-1")                       # 홍콩 (로드나인 아시아)
        self.assertEqual(A.aws_scope({"sg_dir": "aws/live/ape1/sg/sg_rule"}), ("live", "ap-east-1"))
        self.assertEqual(A.normalize_region("APE1"), "ap-east-1")
        self.assertEqual(A.normalize_region(" apne1 "), "ap-northeast-1")
        self.assertEqual(A.normalize_region("us-east-1"), "us-east-1")
        self.assertEqual(A.normalize_region("east-1"), "")                        # 모호한 입력은 추측하지 않음
        r = self.c.post("/api/env/g/aws/fetch", json={"profile": "p1", "region": "east-1"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("ap-east-1", self.J(r)["error"])                            # 올바른 입력 예시를 알려줌

    def test_short_region_code_accepted_by_fetch(self):
        seen = []

        def fake(profile, service, command, extra=None, region=None, timeout=90):
            seen.append(region)
            return [] if command != "describe-vpcs" else {}
        self.patch(aws_run=fake)
        self.assertEqual(self.c.post("/api/env/g/aws/fetch", json={"profile": "p1", "region": "ape1"}).status_code, 200)
        self.assertEqual(set(seen), {"ap-east-1"})

    def test_ssl_error_classified_and_retried_with_system_certs(self):
        from types import SimpleNamespace
        from unittest import mock
        self.assertEqual(A.classify_aws_error("SSL validation failed for https://ec2.ap-east-1.amazonaws.com/ [SSL: CERTIFICATE_VERIFY_FAILED]")[0], "ssl_error")
        bad = SimpleNamespace(returncode=255, stdout="", stderr="SSL validation failed for https://x [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")
        good = SimpleNamespace(returncode=0, stdout='["ok"]', stderr="")
        calls, envs = [], []

        def fake_run(cmd, **kw):
            envs.append(kw["env"].get("AWS_CA_BUNDLE"))
            calls.append(1)
            return good if len(calls) > 1 else bad
        bundle = A.aws_ca_bundle_path()
        if os.path.exists(bundle):
            os.remove(bundle)
        with mock.patch.object(A.shutil, "which", return_value="aws"), mock.patch.object(A.subprocess, "run", side_effect=fake_run), \
                mock.patch.object(A, "build_aws_ca_bundle", side_effect=lambda: (open(bundle, "w").write("x"), bundle)[1]):
            r = A.aws_run("p1", "ec2", "describe-subnets", region="ap-east-1")
        self.assertEqual(r, ["ok"])
        self.assertEqual(len(calls), 2)                                            # 한 번 실패 -> 인증서 묶음을 더해 한 번 다시
        self.assertEqual(envs, [None, bundle])
        os.remove(bundle)

    def test_ssl_error_without_bundle_reports_clear_message(self):
        from types import SimpleNamespace
        from unittest import mock
        bad = SimpleNamespace(returncode=255, stdout="", stderr="SSL validation failed [SSL: CERTIFICATE_VERIFY_FAILED]")
        bundle = A.aws_ca_bundle_path()
        if os.path.exists(bundle):
            os.remove(bundle)
        with mock.patch.object(A.shutil, "which", return_value="aws"), mock.patch.object(A.subprocess, "run", return_value=bad), \
                mock.patch.object(A, "build_aws_ca_bundle", return_value=None):
            with self.assertRaises(A.ApiError) as cm:
                A.aws_run("p1", "ec2", "describe-subnets", region="ap-east-1")
        self.assertEqual(cm.exception.extra["aws_error"], "ssl_error")
        self.assertIn("AWS_CA_BUNDLE", str(cm.exception))

    def test_profile_details_for_account_search(self):
        cfgp = os.path.join(self.tmp, "aws_config3")
        with open(cfgp, "w") as f:
            f.write("[profile live-lord-asia]\nsso_account_id = 370571234567\nsso_role_name = ReadOnly\n\n[profile dev-sip]\nsso_account_id = 111122223333\n\n[sso-session x]\nsso_account_id = 999\n")
        old = os.environ.get("AWS_CONFIG_FILE")
        os.environ["AWS_CONFIG_FILE"] = cfgp
        try:
            d = A.aws_profile_details()
            self.assertEqual(d["live-lord-asia"], {"account_id": "370571234567", "role": "ReadOnly"})
            self.assertEqual(d["dev-sip"], {"account_id": "111122223333", "role": ""})
            self.assertNotIn("x", d)
            ctx = self.J(self.c.get("/api/env/g/aws/context"))
            self.assertEqual(ctx["profile_info"]["live-lord-asia"]["account_id"], "370571234567")
            self.assertTrue(any(x["code"] == "ap-east-1" for x in ctx["regions"]))
        finally:
            if old is None:
                os.environ.pop("AWS_CONFIG_FILE", None)
            else:
                os.environ["AWS_CONFIG_FILE"] = old

    def test_login_endpoint_and_profile_map(self):
        started = []
        self.patch(aws_profiles=lambda: ["p1"], aws_start_login=lambda exe, pr: started.append(pr), aws_cli_present=lambda: True)
        from unittest import mock
        with mock.patch.object(A.shutil, "which", return_value="aws"):
            self.assertEqual(self.c.post("/api/aws/login", json={"profile": "nope"}).status_code, 404)
            self.assertEqual(started, [])
            self.assertEqual(self.c.post("/api/aws/login", json={"profile": "p1"}).status_code, 200)
        self.assertEqual(started, ["p1"])
        self.assertEqual(self.c.post("/api/aws/profile-map", json={"key": "bbz|live", "profile": "p1"}).status_code, 200)
        ctx = self.J(self.c.get("/api/env/g/aws/context"))
        self.assertEqual(ctx["key"], "bbz|live")
        self.assertEqual(ctx["saved"], "p1")
        self.assertEqual(self.c.post("/api/aws/profile-map", json={"key": "k", "profile": "zzz"}).status_code, 400)


class AwsCompareTests(TempEnv):
    """AWS 규칙 ↔ 저장소 파일 규칙 비교 보고서와 'AWS 자격인증' 표시"""

    def patch(self, **fns):
        for n, f in fns.items():
            if not hasattr(self, "_orig_" + n):
                setattr(self, "_orig_" + n, getattr(A, n))
            setattr(A, n, f)

    def perm(self, port, cidr, proto="tcp", desc=""):
        return {"IpProtocol": proto, "FromPort": port, "ToPort": port, "IpRanges": [{"CidrIp": cidr, "Description": desc}],
                "Ipv6Ranges": [], "UserIdGroupPairs": [], "PrefixListIds": []}

    def setUp(self):
        super().setUp()
        A._AWS_ST.clear()
        loc = A.read_json(A.LOCAL_PATH, {})
        loc["aws_profiles"] = {"bbz|live": "qa-bbz"}
        A.write_json(A.LOCAL_PATH, loc)
        self.calls = []

        def fake(profile, service, command, extra=None, region=None, timeout=90):
            self.calls.append((service, command))
            if service == "sts":
                return {"Account": "111122223333"}
            if any("IpPermissions" in str(x) for x in (extra or [])):
                return [{"id": "sg-1", "ingress": [self.perm(80, "10.1.1.1/32"), self.perm(22, "10.9.9.9/32", desc="콘솔")], "egress": []}]
            return [{"id": "sg-1", "name": "l-sg-bbz-x-sg", "vpc": "vpc-1", "tags": []}]
        self.patch(aws_run=fake, aws_profiles=lambda: ["qa-bbz"], aws_cli_present=lambda: True)

    def tearDown(self):
        for n in ("aws_run", "aws_profiles", "aws_cli_present"):
            if hasattr(self, "_orig_" + n):
                setattr(A, n, getattr(self, "_orig_" + n))
        loc = A.read_json(A.LOCAL_PATH, {})
        loc.pop("aws_profiles", None)
        loc.pop("aws_regions", None)
        A.write_json(A.LOCAL_PATH, loc)
        A._AWS_ST.clear()

    def test_rule_keys_normalize_both_sides(self):
        f = A.file_rule_keys([{"protocol": "TCP", "from_port": 443, "to_port": 443, "cidr_blocks": ["10.0.0.1"], "security_groups": "sg-a, sg-b",
                               "prefix_list_ids": ["pl-1"], "description": "d"}], "ingress")
        a = A.aws_rule_keys([{"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443, "IpRanges": [{"CidrIp": "10.0.0.1/32"}],
                              "UserIdGroupPairs": [{"GroupId": "sg-a"}, {"GroupId": "sg-b"}], "PrefixListIds": [{"PrefixListId": "pl-1"}]}], "ingress")
        self.assertEqual(set(f), set(a))
        self.assertEqual(len(f), 4)
        allp = A.aws_rule_keys([{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}], "Ipv6Ranges": [{"CidrIpv6": "::/0"}]}], "egress")
        fall = A.file_rule_keys([{"protocol": "-1", "from_port": 0, "to_port": 0, "cidr_blocks": ["0.0.0.0/0", "::/0"], "security_groups": "", "prefix_list_ids": []}], "egress")
        self.assertEqual(set(allp), set(fall))

    def test_compare_reports_differences(self):
        r = self.J(self.c.post("/api/env/g/aws/compare", json={"region": "ap-northeast-2"}))
        self.assertFalse(r["skipped"])
        row = r["sgs"][0]
        self.assertEqual((row["name"], row["sg_id"], row["status"]), ("l-sg-bbz-x-sg", "sg-1", "diff"))
        self.assertEqual(row["same"], 1)
        self.assertEqual([(x["port"], x["source"]) for x in row["aws_only"]], [("22", "10.9.9.9/32")])
        self.assertEqual(row["file_only"], [])
        self.assertEqual(r["aws_only_total"], 1)
        self.assertTrue(all(c[1] in ("describe-security-groups",) for c in self.calls if c[0] == "ec2"))   # 조회만

    def test_compare_skips_with_notice_when_not_authenticated(self):
        def need_login(profile, service, command, extra=None, region=None, timeout=90):
            raise A.ApiError("로그인 필요", 401, aws_error="login_needed", profile=profile)
        self.patch(aws_run=need_login)
        r = self.J(self.c.post("/api/env/g/aws/compare", json={"region": "ap-northeast-2"}))
        self.assertTrue(r["skipped"])
        self.assertEqual(r["reason"], "login_needed")
        self.assertIn("AWS 인증이 되어 있지 않아", r["message"])
        self.assertEqual(r["profile"], "qa-bbz")

    def test_compare_skips_without_profile_or_cli_or_region(self):
        loc = A.read_json(A.LOCAL_PATH, {})
        loc["aws_profiles"] = {}
        A.write_json(A.LOCAL_PATH, loc)
        self.assertEqual(self.J(self.c.post("/api/env/g/aws/compare", json={"region": "ap-northeast-2"}))["reason"], "no_profile")
        loc["aws_profiles"] = {"bbz|live": "qa-bbz"}
        A.write_json(A.LOCAL_PATH, loc)
        self.assertEqual(self.J(self.c.post("/api/env/g/aws/compare", json={}))["reason"], "no_region")
        self.patch(aws_cli_present=lambda: False)
        self.assertEqual(self.J(self.c.post("/api/env/g/aws/compare", json={"region": "ap-northeast-2"}))["reason"], "no_cli")

    def test_compare_uses_region_remembered_from_aws_fetch(self):
        self.assertEqual(self.J(self.c.post("/api/env/g/aws/compare", json={}))["reason"], "no_region")
        r = self.c.post("/api/aws/profile-map", json={"key": "bbz|live", "profile": "qa-bbz", "region": "apne2"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(A.read_json(A.LOCAL_PATH, {})["aws_regions"]["bbz|live"], "ap-northeast-2")
        out = self.J(self.c.post("/api/env/g/aws/compare", json={}))
        self.assertFalse(out["skipped"])
        self.assertEqual(out["region"], "ap-northeast-2")

    def test_status_states_and_cache(self):
        s = self.J(self.c.get("/api/aws/status?env_id=g"))
        self.assertEqual((s["state"], s["profile"], s["account"]), ("ok", "qa-bbz", "111122223333"))
        n = len(self.calls)
        self.c.get("/api/aws/status?env_id=g")
        self.assertEqual(len(self.calls), n)                       # 잠깐은 기억한 값을 쓴다
        self.c.get("/api/aws/status?env_id=g&force=1")
        self.assertEqual(len(self.calls), n + 1)
        self.assertEqual(self.J(self.c.get("/api/aws/status"))["state"], "no_env")

        def need_login(profile, service, command, extra=None, region=None, timeout=90):
            raise A.ApiError("로그인 필요", 401, aws_error="login_needed", profile=profile)
        self.patch(aws_run=need_login)
        self.assertEqual(self.J(self.c.get("/api/aws/status?env_id=g&force=1"))["state"], "login_needed")
        loc = A.read_json(A.LOCAL_PATH, {})
        loc["aws_profiles"] = {}
        A.write_json(A.LOCAL_PATH, loc)
        self.assertEqual(self.J(self.c.get("/api/aws/status?env_id=g&force=1"))["state"], "no_profile")
        self.patch(aws_cli_present=lambda: False)
        self.assertEqual(self.J(self.c.get("/api/aws/status?env_id=g&force=1"))["state"], "no_cli")


class SelfcheckAndSupportTests(TempEnv):
    TOK = "glpat-" + "ABCDEF1234567890"

    def test_selfcheck_lists_checks(self):
        r = self.J(self.c.get("/api/selfcheck"))
        ids = {c["id"]: c for c in r["checks"]}
        for k in ("python", "flask", "requests", "git", "data", "envs", "token_game"):
            self.assertIn(k, ids)
        self.assertEqual(ids["python"]["status"], "ok")
        self.assertEqual(ids["envs"]["status"], "ok")
        self.assertTrue(all(c["status"] in ("ok", "warn", "fail", "info") for c in r["checks"]))
        self.assertFalse(r["online"])

    def test_selfcheck_online_reports_gitlab_failure(self):
        loc = A.read_json(A.LOCAL_PATH, {})
        loc["tokens"] = {"game": "abcd1234", "platform": ""}
        A.write_json(A.LOCAL_PATH, loc)
        old = A.gl

        def boom(env, method, path, **kw):
            raise A.ApiError("GitLab 에 연결하지 못했습니다", 502)
        A.gl = boom
        try:
            ids = {c["id"]: c for c in self.J(self.c.get("/api/selfcheck?online=1"))["checks"]}
        finally:
            A.gl = old
        self.assertEqual(ids["gitlab_game"]["status"], "fail")
        self.assertTrue(ids["gitlab_game"]["fix"])

    def test_support_bundle_has_no_secrets(self):
        loc = A.read_json(A.LOCAL_PATH, {})
        loc["tokens"] = {"game": self.TOK, "platform": ""}
        loc["jira"] = {"token": "JIRA-" + "SECRET-9876"}
        A.write_json(A.LOCAL_PATH, loc)
        A.log_event("ERROR", "boom PRIVATE-TOKEN: %s at C:\\Users\\hong\\x token=abcdef123456 glpat-ZZZZZZZZZZZZ" % self.TOK)
        r = self.c.get("/api/support/bundle")
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r.headers["Content-Disposition"])
        txt = r.get_data(as_text=True)
        for secret in (self.TOK, "JIRA-" + "SECRET-9876", "abcdef123456", "glpat-ZZZZ", "\\hong\\"):
            self.assertNotIn(secret, txt)
        b = json.loads(txt)
        self.assertEqual(b["format"], "traform-acl-support")
        self.assertEqual(b["settings"]["tokens_set"], ["game"])
        self.assertTrue(b["settings"]["jira_token_set"])
        self.assertTrue(any("boom" in x for x in b["log_tail"]))
        self.assertIn("app_version", b["info"])

    def test_version_reports_demo_flag(self):
        self.assertFalse(self.J(self.c.get("/api/version"))["demo"])
        os.environ["TF_ACL_DEMO"] = "1"
        try:
            self.assertTrue(self.J(self.c.get("/api/version"))["demo"])
        finally:
            os.environ.pop("TF_ACL_DEMO", None)


class AtlantisBusyTests(TempEnv):
    BUSY = 'cannot run "plan": the default workspace at path . is currently locked for this pull request by "plan".\nWait until the previous command is complete and try again'
    PLAN = "```diff\n+ resource \"a\" \"b\" {\n```\nPlan: 1 to add, 0 to change, 0 to destroy."

    def out(self, notes):
        A.gl = lambda env, method, path, **kw: notes
        return self.J(self.c.get("/api/env/p/atlantis/output?iid=9&since=100&action=plan"))

    def test_busy_reply_is_not_an_error(self):
        self.assertTrue(A.is_atlantis_busy_note(self.BUSY))
        self.assertFalse(A.is_atlantis_busy_note(self.PLAN))
        r = self.out([{"id": 101, "body": self.BUSY}])
        self.assertEqual(r["state"], "pending")                          # 오류가 아니라 기다림
        self.assertTrue(r["busy"])
        self.assertIn("기다리는", r["headline"])

    def test_busy_then_autoplan_result_is_shown(self):
        r = self.out([{"id": 101, "body": self.BUSY}, {"id": 102, "body": self.PLAN}])
        self.assertEqual(r["state"], "ok")
        self.assertEqual(r["plan"]["add"], 1)
        self.assertNotIn("locked for this pull request", r["body"])     # 거절 안내는 결과에 섞이지 않음

    def test_real_lock_by_other_mr_still_warns(self):
        r = self.out([{"id": 101, "body": "This project is locked by an unapplied plan from pull #5. To continue, delete the lock"}])
        self.assertEqual(r["state"], "warn")
        self.assertEqual(r["kind"], "lock")


class BranchSuffixAndFinishTests(TempEnv):
    def test_suffix_in_branch_name(self):
        r = self.c.post("/api/env/g/git/prepare", json={"ticket": "ISRIR-69431", "suffix": " 입력 문자/x "})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        b = self.J(r)["branch"]
        self.assertRegex(b, r"^[^/]+/\d{6}_ISRIR-69431_입력_문자x$")     # 공백은 _ , 사용할 수 없는 글자는 제거
        env = A.get_env("g")
        A.run_git(env, "checkout", "main"); A.invalidate_status()
        r2 = self.c.post("/api/env/g/git/prepare", json={"ticket": "ISRIR-69431", "suffix": "입력 문자x"})
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(self.J(r2)["branch"], b + "_01")                  # 같은 이름이 있으면 번호가 붙는다

    def test_no_suffix_keeps_old_format(self):
        b = self.work_branch("ISRIR-5")
        self.assertRegex(b, r"^[^/]+/\d{6}_ISRIR-5$")

    def test_bad_suffix_rejected_before_clone(self):
        r = self.c.post("/api/env/g/git/prepare", json={"ticket": "ISRIR-5", "suffix": "///"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(A.clean_branch_suffix(""), "")
        self.assertEqual(A.clean_branch_suffix("a..b.lock"), "a.b")
        self.assertEqual(len(A.clean_branch_suffix("x" * 100)), 40)

    def test_finish_switches_to_main(self):
        self.work_branch("ISRIR-9")
        r = self.c.post("/api/env/g/git/finish")
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        d = self.J(r)
        self.assertEqual(d["branch"], "main")
        self.assertRegex(d["previous"], r"ISRIR-9$")
        self.assertEqual(self.J(self.c.get("/api/env/g/git/status?fresh=1"))["branch"], "main")
        self.assertEqual(self.J(self.c.get("/api/env/g/undo"))["items"], [])
        chg = [x["change"] for x in self.J(self.c.get("/api/env/g/sgs"))["sgs"]]
        self.assertEqual(chg, [None] * len(chg))                          # 변경 음영/표시 해제

    def test_finish_refuses_when_dirty(self):
        self.work_branch("ISRIR-10")
        sg = self.J(self.c.get("/api/env/g/sg/l-sg-bbz-x-sg"))
        sg["ingress"].append(dict(RULE, cidr_blocks="10.6.6.6/32", protocol="tcp"))
        self.assertEqual(self.c.put("/api/env/g/sg/l-sg-bbz-x-sg", json=sg).status_code, 200)
        r = self.c.post("/api/env/g/git/finish")
        self.assertEqual(r.status_code, 409)
        self.assertRegex(self.J(self.c.get("/api/env/g/git/status?fresh=1"))["branch"], "ISRIR-10")   # 전환되지 않음


class DistApiTests(TempEnv):
    def test_info_and_zip_endpoints(self):
        import zipfile, io
        info = self.J(self.c.get("/api/dist/info"))
        self.assertEqual(info["version"], A.VERSION)
        self.assertGreater(info["files"], 10)
        self.assertTrue(any("local.json" in x for x in info["excluded"]))
        r = self.c.get("/api/dist/zip?with_config=1")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "application/zip")
        self.assertIn(A.VERSION, r.headers["Content-Disposition"])
        with zipfile.ZipFile(io.BytesIO(r.get_data())) as z:
            names = z.namelist()
            self.assertTrue(any(n.endswith("/app.py") for n in names))
            self.assertTrue(any(n.endswith("/make_dist.py") for n in names))
            self.assertFalse(any(n.endswith("local.json") for n in names))
            cfgs = [n for n in names if n.endswith("data/config.json")]
            self.assertEqual(len(cfgs), 1)
            for e in json.loads(z.read(cfgs[0]))["environments"]:
                self.assertEqual(e["repo_dir"], "")                    # 내 PC 경로는 제거
        plain = self.c.get("/api/dist/zip")
        with zipfile.ZipFile(io.BytesIO(plain.get_data())) as z:
            self.assertFalse(any(n.endswith("data/config.json") for n in z.namelist()))

    def test_zip_never_contains_token(self):
        import zipfile, io
        tok = "TOKEN-" + "ABCDEF123456"
        A.write_json(A.LOCAL_PATH, {"account": "a", "tokens": {"game": tok, "platform": ""}})
        r = self.c.get("/api/dist/zip?with_config=1&with_meta=1")
        if r.status_code == 200:
            with zipfile.ZipFile(io.BytesIO(r.get_data())) as z:
                self.assertNotIn(tok.encode(), b"".join(z.read(n) for n in z.namelist()))
        else:
            self.assertEqual(r.status_code, 400)


class BackupRestoreTests(TempEnv):
    TOK = "TOK-" + "ZZZ987654"

    def setUp(self):
        super().setUp()
        A.write_json(A.LOCAL_PATH, {"account": "heejim", "tokens": {"game": self.TOK, "platform": ""}, "jira": {"token": "JIRA-" + "SECRET99"}})
        A.write_json(A.META_PATH, {"envs": {"g": {"sgs": {"x": {"alias": "별명"}}}}})

    def download(self, q=""):
        r = self.c.get("/api/backup/download" + q)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertIn("attachment", r.headers["Content-Disposition"])
        return json.loads(r.get_data(as_text=True))

    def test_download_contains_selected_groups_only(self):
        bk = self.download("?groups=settings")
        self.assertEqual(bk["format"], A.BACKUP_FORMAT)
        self.assertEqual(sorted(bk["files"]), ["config.json", "meta.json"])
        self.assertFalse(bk["contains_secrets"])
        self.assertNotIn(self.TOK, json.dumps(bk))
        full = self.download()
        self.assertTrue(full["contains_secrets"])
        self.assertEqual(full["files"]["local.json"]["tokens"]["game"], self.TOK)
        self.assertEqual(self.c.get("/api/backup/download?groups=nope").status_code, 400)

    def test_restore_roundtrip_and_snapshot(self):
        bk = self.download()
        A.write_json(A.LOCAL_PATH, {"account": "other", "tokens": {"game": "", "platform": ""}})
        A.write_json(A.META_PATH, {"envs": {}})
        cfg = A.read_json(A.CONFIG_PATH, {})
        cfg["environments"] = cfg["environments"][:1]
        A.write_json(A.CONFIG_PATH, cfg)
        r = self.c.post("/api/backup/restore", json={"backup": bk, "dry_run": True})
        self.assertEqual(r.status_code, 200)
        items = self.J(r)["items"]
        self.assertTrue(any(i["name"] == "local.json" for i in items))
        self.assertNotIn(self.TOK, json.dumps(self.J(r)))           # 미리보기에는 토큰 값이 없다
        self.assertEqual(A.read_json(A.LOCAL_PATH, {})["account"], "other")   # dry_run 은 아무것도 바꾸지 않는다
        r = self.c.post("/api/backup/restore", json={"backup": bk, "dry_run": False})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        self.assertEqual(A.read_json(A.LOCAL_PATH, {})["tokens"]["game"], self.TOK)
        self.assertEqual(len(A.read_json(A.CONFIG_PATH, {})["environments"]), 2)
        self.assertEqual(A.read_json(A.META_PATH, {})["envs"]["g"]["sgs"]["x"]["alias"], "별명")
        snap = self.J(r)["backup"]
        self.assertEqual(A.read_json(os.path.join(snap, "local.json"), {})["account"], "other")   # 교체 전 파일이 남는다

    def test_restore_selected_group_and_clear_repo_dirs(self):
        bk = self.download()
        A.write_json(A.LOCAL_PATH, {"account": "other", "tokens": {"game": "", "platform": ""}})
        r = self.c.post("/api/backup/restore", json={"backup": bk, "groups": ["settings"], "clear_repo_dirs": True})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(A.read_json(A.LOCAL_PATH, {})["account"], "other")      # 선택하지 않은 항목은 그대로
        cfg = A.read_json(A.CONFIG_PATH, {})
        self.assertTrue(all(e["repo_dir"] == "" for e in cfg["environments"]))

    def test_restore_rejects_bad_files(self):
        before = A.read_json(A.CONFIG_PATH, {})
        for bad in ({}, {"format": "x", "files": {}}, {"format": A.BACKUP_FORMAT, "format_version": 99, "files": {}},
                    {"format": A.BACKUP_FORMAT, "files": {"config.json": {"environments": "oops"}}},
                    {"format": A.BACKUP_FORMAT, "files": {"config.json": {"environments": [{"id": "a"}], "sites": {}, "defaults": {}}}},
                    {"format": A.BACKUP_FORMAT, "files": {"meta.json": []}},
                    {"format": A.BACKUP_FORMAT, "files": {"evil.json": {}}}):
            r = self.c.post("/api/backup/restore", json={"backup": bad})
            self.assertEqual(r.status_code, 400, bad)
        self.assertEqual(A.read_json(A.CONFIG_PATH, {}), before)

    def test_backup_not_in_log(self):
        self.download()
        path = os.path.join(A.DATA, "app.log")
        txt = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
        self.assertNotIn(self.TOK, txt)


class MixedLayoutTests(TempEnv):
    """플랫폼 폴더 안에 게임 방식(입력/출력 분리 배열) 파일이 섞여 있는 경우"""
    D = "aws/plat/sg/sg_rule"

    def put_split(self):
        base = [{"from_port": 80, "to_port": 80, "protocol": "TCP", "cidr_blocks": ["10.3.3.3/32"], "security_groups": "null",
                 "prefix_list_ids": [], "description": "tf_261020_ISRIR-1_a to mix Connection"}]
        d = os.path.join(self.repo, *self.D.split("/"))
        with open(os.path.join(d, "mix-sg-ingress-rules.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(base, f, indent=2); f.write("\n")
        with open(os.path.join(d, "mix-sg-egress-rules.json"), "w", encoding="utf-8", newline="\n") as f:
            f.write("[]\n")
        A._SG_CACHE.clear()

    def test_list_load_save_and_undo(self):
        self.work_branch()
        self.put_split()
        lst = {x["name"]: x for x in self.J(self.c.get("/api/env/p/sgs"))["sgs"]}
        self.assertIn("mix-sg", lst)                                    # 두 파일이 SG 하나로 묶임
        self.assertNotIn("mix-sg-ingress-rules", lst)
        self.assertIn("sip-docdb", lst)                                 # 기존 플랫폼 방식 파일도 그대로
        self.assertEqual(lst["mix-sg"]["ingress"], 1)
        sg = self.J(self.c.get("/api/env/p/sg/mix-sg"))
        self.assertEqual(sg["ingress"][0]["protocol"], "TCP")           # 표기는 파일을 따름
        sg["ingress"].append(dict(RULE, cidr_blocks="10.4.4.4/32", protocol="tcp"))
        r = self.c.put("/api/env/p/sg/mix-sg", json=sg)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        text = open(os.path.join(self.repo, *self.D.split("/"), "mix-sg-ingress-rules.json"), encoding="utf-8").read()
        self.assertTrue(text.lstrip().startswith("["))                  # 배열 형식 유지
        self.assertIn('"security_groups": "null"', text)
        self.assertIn('"protocol": "TCP"', text)
        self.assertEqual(self.c.post("/api/env/p/undo").status_code, 200)
        self.assertEqual(len(self.J(self.c.get("/api/env/p/sg/mix-sg"))["ingress"]), 1)

    def test_old_name_gives_clear_message(self):
        self.put_split()
        r = self.c.get("/api/env/p/sg/mix-sg-ingress-rules")
        self.assertIn(r.status_code, (404, 422))                        # 500 이 아니라 안내


class DistributionTests(TempEnv):
    def test_first_run_defaults_are_empty_and_portable(self):
        d = A.DEFAULT_CONFIG
        self.assertEqual(d["environments"], [])
        for v in d["defaults"].values():
            self.assertNotIn(":\\", v.get("repo_dir", ""))          # 작성자 PC 경로가 들어 있지 않음

    def test_repo_dir_falls_back_to_app_folder(self):
        cfg = {"defaults": {"game": {"project": "", "target_branch": "main"}}, "sites": {"game": {"label": "g", "base_url": "https://x"}}, "settings": {}}
        e = {"id": "z", "kind": "game", "group": "g", "env": "e", "sg_dir": "a/sg_rule", "project": "sgp-infra/bbz/infra-deploy", "repo_dir": ""}
        r = A._resolve_env(e, cfg)
        self.assertEqual(r["repo_dir"], os.path.join(A.BASE, "repos", "sgp-infra__bbz__infra-deploy"))
        with self.assertRaises(A.ApiError):
            A._resolve_env(dict(e, project=""), cfg)                 # 경로도 프로젝트도 없으면 안내

    def test_make_dist_excludes_data_and_secrets(self):
        import importlib.util, zipfile
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        spec = importlib.util.spec_from_file_location("make_dist", os.path.join(root, "make_dist.py"))
        md = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(md)
        data = os.path.join(self.tmp, "distdata")
        os.makedirs(data, exist_ok=True)
        with open(os.path.join(data, "local.json"), "w") as f:
            json.dump({"account": "me", "tokens": {"game": "", "platform": "SECRET-" + "PLATFORM-TOKEN"}}, f)
        cfg = json.loads(json.dumps(A.DEFAULT_CONFIG))
        cfg["defaults"]["platform"]["repo_dir"] = "D:/GIT/x"
        cfg["environments"] = [{"id": "e1", "kind": "platform", "group": "g", "env": "e", "repo_dir": "D:/GIT/x", "sg_dir": "a/sg_rule"}]
        with open(os.path.join(data, "config.json"), "w") as f:
            json.dump(cfg, f)
        out = md.build(os.path.join(self.tmp, "distout"), with_config=True, data_dir=data)
        with zipfile.ZipFile(out) as z:
            names = z.namelist()
            self.assertTrue(any(n.endswith("/app.py") for n in names))
            self.assertFalse(any(n.endswith("local.json") or "/history.json" in n or "/backup/" in n for n in names))
            blob = b"".join(z.read(n) for n in names)
            self.assertNotIn(b"SECRET-" + b"PLATFORM-TOKEN", blob)
            c = json.loads(z.read([n for n in names if n.endswith("data/config.json")][0]))
            self.assertEqual(c["environments"][0]["repo_dir"], "")
            self.assertEqual(c["defaults"]["platform"]["repo_dir"], "")


class QualityTests(unittest.TestCase):
    """코드/문서가 서로 어긋나지 않았는지 확인하는 점검 (임시 데이터 불필요)"""
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_python_compiles(self):
        import py_compile
        py_compile.compile(os.path.join(self.ROOT, "app.py"), doraise=True)
        parts = os.path.join(self.ROOT, "app_parts")
        for n in sorted(os.listdir(parts)):
            if n.endswith(".py"):
                py_compile.compile(os.path.join(parts, n), doraise=True)

    def test_scripts_listed_in_index_exist_and_parse(self):
        import re as _re, shutil as _sh
        html = open(os.path.join(self.ROOT, "static", "index.html"), encoding="utf-8").read()
        srcs = _re.findall(r'src="/static/(js/[^"?]+)', html)
        self.assertGreaterEqual(len(srcs), 9)
        files = {f for f in os.listdir(os.path.join(self.ROOT, "static", "js")) if f.endswith(".js")}
        self.assertEqual({os.path.basename(x) for x in srcs}, files, "index.html 에 없는 js 파일이 있거나 그 반대")
        node = _sh.which("node")
        if node:
            for x in srcs:
                r = subprocess.run([node, "--check", os.path.join(self.ROOT, "static", x)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, x + " " + r.stderr)

    def test_versions_match_docs(self):
        import re as _re
        cv = _re.search(r"CLIENT_VERSION='([^']+)'", open(os.path.join(self.ROOT, "static", "js", "search_version.js"), encoding="utf-8").read()).group(1)
        self.assertEqual(cv, A.VERSION, "app.py VERSION 과 화면 CLIENT_VERSION 이 다름")
        self.assertIn("## " + A.VERSION, open(os.path.join(self.ROOT, "CHANGELOG.md"), encoding="utf-8").read())
        self.assertIn("v" + A.VERSION, open(os.path.join(self.ROOT, "README.md"), encoding="utf-8").read())

    def test_no_duplicate_html_ids_in_static_markup(self):
        import re as _re, collections
        html = open(os.path.join(self.ROOT, "static", "index.html"), encoding="utf-8").read()
        ids = collections.Counter(_re.findall(r'\sid="([^"$]+)"', html))
        self.assertEqual([k for k, v in ids.items() if v > 1], [])

    def test_requirements_pinned(self):
        for line in open(os.path.join(self.ROOT, "requirements.txt"), encoding="utf-8").read().split():
            self.assertRegex(line, r"~=|==")


class Robustness131Tests(TempEnv):
    def test_config_conflict_409(self):
        r = self.J(self.c.get("/api/config"))
        cfg, rev = r["config"], r["rev"]
        self.assertRegex(r["today"], r"^\d{6}$")
        ok = self.c.put("/api/config", json=cfg, headers={"X-Rev": rev})
        self.assertEqual(ok.status_code, 200)
        new_rev = ok.get_json()["rev"]
        self.assertNotEqual(new_rev, "")
        # 예전 rev 로 저장하면 거부 (다른 화면이 먼저 저장한 상황)
        bad = self.c.put("/api/config", json=cfg, headers={"X-Rev": "deadbeef0000"})
        self.assertEqual(bad.status_code, 409)
        self.assertTrue(bad.get_json()["conflict"])
        # 헤더가 없으면 기존처럼 저장 (하위 호환)
        self.assertEqual(self.c.put("/api/config", json=cfg).status_code, 200)

    def test_meta_conflict_409(self):
        m = self.J(self.c.get("/api/meta"))
        rev = m["_rev"]
        self.assertEqual(self.c.put("/api/meta", json=m, headers={"X-Rev": rev}).status_code, 200)
        self.assertNotIn("_rev", A.load_meta())          # 파일에는 rev 가 저장되지 않는다
        self.assertEqual(self.c.put("/api/meta", json=m, headers={"X-Rev": "deadbeef0000"}).status_code, 409)

    def test_unhandled_error_logged_and_token_scrubbed(self):
        A.write_json(A.LOCAL_PATH, {"account": "a", "tokens": {"game": "SECRET-TOKEN-123", "platform": ""}})
        path = os.path.join(A.DATA, "app.log")
        if os.path.exists(path):
            os.remove(path)

        from unittest import mock
        with mock.patch.object(A, "get_env", side_effect=RuntimeError("fail with SECRET-TOKEN-123")):
            r = self.c.get("/api/env/g/sgs")
        self.assertEqual(r.status_code, 500)
        self.assertIn("error", r.get_json())
        text = open(path, encoding="utf-8").read()
        self.assertIn("RuntimeError", text)
        self.assertNotIn("SECRET-TOKEN-123", text)
        lg = self.J(self.c.get("/api/log?lines=50"))
        self.assertTrue(any("RuntimeError" in x for x in lg["lines"]))

    def test_status_cache(self):
        env = A.get_env("g")
        calls = []
        orig = A._git_status_raw
        A._git_status_raw = lambda e: (calls.append(1), orig(e))[1]
        old = A.STATUS_TTL
        A.STATUS_TTL = 30
        try:
            A.invalidate_status()
            A.git_status(env); A.git_status(env)
            self.assertEqual(len(calls), 1)                 # 두 번째는 캐시
            A.git_status(env, fresh=True)
            self.assertEqual(len(calls), 2)                 # 결정용은 항상 새로
            A.invalidate_status(env)
            A.git_status(env)
            self.assertEqual(len(calls), 3)
        finally:
            A.STATUS_TTL = old
            A._git_status_raw = orig
            A.invalidate_status()

    def test_restart_helper_spawns(self):
        """재시작 보조 프로세스 시작 코드가 NameError 없이 실행되어야 한다 (실제 프로세스는 띄우지 않음)"""
        from unittest import mock
        with mock.patch.object(A.subprocess, "Popen") as po:
            A._spawn_restart()
        self.assertEqual(po.call_args[0][0][0], A.sys.executable)

    def test_index_serves_versioned_assets(self):
        r = self.c.get("/")
        html = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("__V__", html)
        self.assertIn("/static/app.css?v=" + A.VERSION, html)
        import re as _re
        srcs = _re.findall(r'src="(/static/js/[^"?]+)', html)
        self.assertGreaterEqual(len(srcs), 8)
        for u in srcs + ["/static/app.css"]:
            rr = self.c.get(u)
            self.assertEqual(rr.status_code, 200, u)
            rr.close()

    def test_parallel_git_helpers_same_result(self):
        env = A.get_env("g")
        a = A.git_status(env, fresh=True)
        self.assertTrue(a["cloned"])
        self.assertIsInstance(A.changed_files(env), dict)
        self.assertEqual(A.par(lambda: 1, lambda: 2), [1, 2])

    def test_version_has_today(self):
        self.assertRegex(self.J(self.c.get("/api/version"))["today"], r"^\d{6}$")


class MoreRiskChecksTests(unittest.TestCase):
    """관리 포트/겹치는 규칙 경고"""
    env = {"kind": "game"}
    v = ValidationTests.v

    def test_mgmt_port_wide_cidr_is_risk(self):
        k = self.v([dict(RULE, cidr_blocks=["10.0.0.0/20"], from_port=22, to_port=22)])[2]
        self.assertTrue(any("관리 포트" in x and "SSH" in x for x in k), k)
        k = self.v([dict(RULE, cidr_blocks=["10.0.0.0/20"], from_port=3380, to_port=3400)])[2]
        self.assertTrue(any("RDP" in x for x in k), k)

    def test_mgmt_port_narrow_or_other_port_is_not_risk(self):
        self.assertFalse(self.v([dict(RULE, cidr_blocks=["10.0.0.0/24"], from_port=22, to_port=22)])[2])
        self.assertFalse(self.v([dict(RULE, cidr_blocks=["10.0.0.0/20"], from_port=443, to_port=443)])[2])
        self.assertFalse(self.v([dict(RULE, cidr_blocks=["10.0.0.0/20"], from_port=22, to_port=22)], old=[])[0])

    def test_open_to_world_is_not_reported_twice(self):
        k = self.v([dict(RULE, cidr_blocks=["0.0.0.0/0"], from_port=22, to_port=22)])[2]
        self.assertEqual(len(k), 1, k)

    def test_overlapping_new_rule_warns(self):
        a = dict(RULE, cidr_blocks=["10.1.1.1/32"], from_port=1000, to_port=2000)
        b = dict(RULE, cidr_blocks=["10.1.1.1/32"], from_port=1500, to_port=1600)
        w = self.v([a, b])[1]
        self.assertTrue(any("이미 포함" in x and "2번" in x for x in w), w)
        c = dict(RULE, cidr_blocks=["10.9.9.9/32"], from_port=1500, to_port=1600)   # 소스가 다르면 겹침 아님
        self.assertFalse(any("이미 포함" in x for x in self.v([a, c])[1]))


class UpdateAndBackupNudgeTests(TempEnv):
    def test_parts_are_loaded_and_tracked(self):
        for fn in ("aws_compare", "aws_run", "run_selfcheck", "api_backup_download"):
            self.assertTrue(hasattr(A, fn), fn)
        self.assertTrue(os.path.isdir(A.PARTS_DIR))
        self.assertGreaterEqual(A._code_mtime(), os.path.getmtime(os.path.join(A.BASE, "app.py")))

    def test_backup_due_until_downloaded(self):
        A.write_json(A.LOCAL_PATH, {"account": "x", "tokens": {"game": "tok-123456", "platform": ""}})
        st = self.J(self.c.get("/api/backup/info"))["status"]
        self.assertTrue(st["due"] and st["last"] is None)
        self.assertEqual(self.c.get("/api/backup/download?groups=settings").status_code, 200)
        st = self.J(self.c.get("/api/backup/info"))["status"]
        self.assertFalse(st["due"])
        self.assertEqual(st["days"], 0)
        loc = A.read_json(A.LOCAL_PATH, {})
        loc["last_backup"]["at"] = (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d %H:%M:%S")
        A.write_json(A.LOCAL_PATH, loc)
        st = self.J(self.c.get("/api/backup/info"))["status"]
        self.assertTrue(st["due"])
        self.assertEqual(st["days"], 20)

    def test_backup_not_due_on_fresh_install(self):
        for p in (A.LOCAL_PATH, A.META_PATH):
            if os.path.exists(p):
                os.remove(p)
        self.assertFalse(self.J(self.c.get("/api/backup/info"))["status"]["due"])

    def test_selfcheck_has_new_rows(self):
        A.write_json(A.LOCAL_PATH, {"account": "x", "tokens": {"game": "tok-123456", "platform": ""}})
        ids = {c["id"]: c for c in self.J(self.c.get("/api/selfcheck"))["checks"]}
        self.assertEqual(ids["backup_file"]["status"], "warn")
        self.assertIn("datasize", ids)
        self.assertIn("logsize", ids)

    def test_update_bat_shipped_and_crlf(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "update.bat"), "rb") as f:
            raw = f.read()
        self.assertIn(b"\r\n", raw)
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        import make_dist
        self.assertIn("update.bat", make_dist.TOP_FILES)
        self.assertIn("app_parts", make_dist.TOP_DIRS)
        self.assertTrue(any(f.startswith("app_parts/") for f in make_dist.collect()))


class CompareXlsxTests(TempEnv):
    REPORT = {"profile": "p", "region": "ap-northeast-2", "sgs": [
        {"name": "l-sg-a", "sg_id": "sg-1", "status": "diff", "same": 1, "aws_only_count": 1, "file_only_count": 0,
         "aws_only": [{"direction": "ingress", "protocol": "tcp", "port": "22", "source_type": "cidr", "source": "10.9.9.9/32", "description": "d"}],
         "file_only": []},
        {"name": "l-sg-b", "status": "missing"}]}

    def test_xlsx_has_summary_and_diff_rows(self):
        import io
        from openpyxl import load_workbook
        r = self.c.post("/api/aws/compare/xlsx", json={"report": self.REPORT})
        self.assertEqual(r.status_code, 200)
        wb = load_workbook(io.BytesIO(r.get_data()))
        self.assertEqual(wb.sheetnames, ["요약", "차이 목록"])
        rows = [[c.value for c in row] for row in wb["차이 목록"].iter_rows()]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][2:8], ["AWS에만 있음", "ingress", "tcp", "22", "cidr", "10.9.9.9/32"])
        self.assertEqual(wb["요약"]["C5"].value, "AWS에서 못 찾음")

    def test_xlsx_rejects_bad_body(self):
        self.assertEqual(self.c.post("/api/aws/compare/xlsx", json={"report": "x"}).status_code, 400)
        self.assertEqual(self.c.post("/api/aws/compare/xlsx", json={}).status_code, 400)


class PolicyTests(TempEnv):
    def rule(self, cidr, f, t, **kw):
        return dict(RULE, cidr_blocks=[cidr], from_port=f, to_port=t, **kw)

    def risks(self, rules, env_id="g"):
        return A.validate_sg({"kind": "game", "id": env_id}, {"ingress": rules, "egress": []}, {"ingress": [], "egress": []})[2]

    def put_policy(self, pol):
        r = self.c.put("/api/policy", json={"policy": pol})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return self.J(r)["policy"]

    def tearDown(self):
        A.write_json(A.CONFIG_PATH, {**A.read_json(A.CONFIG_PATH, {}), "policy": A.POLICY_DEFAULT})

    def test_defaults_and_persist_in_config(self):
        d = self.J(self.c.get("/api/policy"))
        self.assertEqual(d["policy"]["mgmt_max_prefix"], 24)
        self.assertIn("22", d["policy"]["mgmt_ports"])
        self.put_policy({"mgmt_ports": "22, 2222", "wide_prefix": 20, "exceptions": []})
        pol = self.J(self.c.get("/api/policy"))["policy"]
        self.assertEqual(sorted(pol["mgmt_ports"], key=int), ["22", "2222"])
        self.assertEqual(self.J(self.c.get("/api/config"))["config"]["policy"]["wide_prefix"], 20)    # 환경설정 저장 시에도 유지된다

    def test_exception_suppresses_risk_for_matching_source_and_port_only(self):
        self.assertTrue(self.risks([self.rule("10.0.0.0/20", 22, 22)]))
        self.put_policy({"exceptions": [{"name": "office", "cidrs": "10.0.0.0/20", "ports": "22"}]})
        self.assertFalse(self.risks([self.rule("10.0.0.0/20", 22, 22)]))
        self.assertFalse(self.risks([self.rule("10.0.1.0/24", 22, 22)]))                              # 예외 대역 안에 들어가는 더 작은 대역
        self.assertTrue(self.risks([self.rule("10.0.0.0/20", 3389, 3389)]))                           # 다른 포트는 그대로 위험
        self.assertTrue(self.risks([self.rule("10.16.0.0/20", 22, 22)]))                              # 다른 대역은 그대로 위험

    def test_exception_limited_to_environment(self):
        self.put_policy({"exceptions": [{"name": "office", "cidrs": "10.0.0.0/20", "ports": "22", "env": "g"}]})
        self.assertFalse(self.risks([self.rule("10.0.0.0/20", 22, 22)], "g"))
        self.assertTrue(self.risks([self.rule("10.0.0.0/20", 22, 22)], "other"))

    def test_all_open_exception_needs_explicit_cidr_and_all_ports(self):
        self.put_policy({"exceptions": [{"name": "lab", "cidrs": "0.0.0.0/0", "ports": "*"}]})
        self.assertFalse(self.risks([self.rule("0.0.0.0/0", 0, 65535)]))
        self.assertFalse(self.risks([dict(self.rule("0.0.0.0/0", 0, 0), protocol="-1")]))
        self.put_policy({"exceptions": [{"name": "ssh", "cidrs": "0.0.0.0/0", "ports": "22"}]})
        self.assertFalse(self.risks([self.rule("0.0.0.0/0", 22, 22)]))
        self.assertTrue(self.risks([self.rule("0.0.0.0/0", 80, 80)]))

    def test_custom_wide_prefix_and_mgmt_ports(self):
        self.assertFalse(self.risks([self.rule("10.0.0.0/20", 443, 443)]))
        self.put_policy({"wide_prefix": 21})
        self.assertTrue(any("광범위" in x for x in self.risks([self.rule("10.0.0.0/20", 443, 443)])))
        self.put_policy({"mgmt_ports": "9000"})
        self.assertTrue(any("관리 포트" in x for x in self.risks([self.rule("10.0.0.0/20", 9000, 9000)])))
        self.assertFalse(any("관리 포트" in x for x in self.risks([self.rule("10.0.0.0/20", 22, 22)])))

    def test_bad_policy_is_rejected(self):
        for bad in ({"wide_prefix": 99}, {"mgmt_ports": "ssh"}, {"exceptions": [{"name": "x", "cidrs": "nope", "ports": "22"}]},
                    {"exceptions": [{"name": "x", "cidrs": "10.0.0.0/24", "ports": "99999"}]}, {"exceptions": [{"name": "x", "cidrs": "", "ports": "22"}]}):
            self.assertEqual(self.c.put("/api/policy", json={"policy": bad}).status_code, 400, bad)

    def test_broken_policy_in_config_falls_back_to_defaults(self):
        cfg = A.read_json(A.CONFIG_PATH, {})
        cfg["policy"] = {"wide_prefix": "abc"}
        A.write_json(A.CONFIG_PATH, cfg)
        self.assertEqual(A.get_policy()["wide_prefix"], 16)
        self.assertTrue(self.risks([self.rule("10.0.0.0/20", 22, 22)]))


class RuleHygieneReportTests(TempEnv):
    def setUp(self):
        super().setUp()
        self.today = A.datetime.now().date()

    def write_rules(self, ingress, egress=None):
        d = os.path.join(self.repo, "aws", "live", "sub", "sg", "sg_rule")
        put(os.path.join(d, "l-sg-bbz-x-sg-ingress-rules.json"), json.dumps(ingress, indent=2) + "\n")
        put(os.path.join(d, "l-sg-bbz-x-sg-egress-rules.json"), json.dumps(egress or [], indent=2) + "\n")
        A._SG_CACHE.clear()

    def r(self, cidr, f, t=None, desc="d", proto="TCP"):
        return {"from_port": f, "to_port": t if t is not None else f, "protocol": proto, "cidr_blocks": [cidr], "security_groups": "null",
                "prefix_list_ids": [], "description": desc}

    def test_expiry_formats(self):
        self.assertEqual(A.rule_expiry("tf_1 만료:2026-12-31").isoformat(), "2026-12-31")
        self.assertEqual(A.rule_expiry("x expire=20261231").isoformat(), "2026-12-31")
        self.assertEqual(A.rule_expiry("x 만료 261231").isoformat(), "2026-12-31")
        self.assertIsNone(A.rule_expiry("만료:2026-13-40"))
        self.assertIsNone(A.rule_expiry("그냥 설명"))

    def test_expiry_report_lists_expired_and_soon_only(self):
        iso = lambda n: (self.today + timedelta(days=n)).isoformat()
        self.write_rules([self.r("10.1.1.1/32", 80, desc="a 만료:" + iso(-3)), self.r("10.1.1.2/32", 81, desc="b 만료:" + iso(10)),
                          self.r("10.1.1.3/32", 82, desc="c 만료:" + iso(200)), self.r("10.1.1.4/32", 83, desc="만료 없음")])
        r = self.J(self.c.get("/api/report/expiry?days=30"))
        self.assertEqual((r["expired"], r["count"], r["with_expiry"]), (1, 2, 3))
        self.assertEqual([x["status"] for x in r["rows"]], ["expired", "soon"])
        self.assertEqual(r["rows"][0]["days_left"], -3)
        self.assertEqual(self.J(self.c.get("/api/report/expiry?days=0"))["count"], 1)
        self.assertTrue(self.c.get("/api/report/expiry?format=csv").get_data(as_text=True).startswith("\ufeff환경,SG"))
        self.assertEqual(self.c.get("/api/report/expiry?days=x").status_code, 400)

    def test_new_rule_with_past_expiry_warns(self):
        old = (self.today - timedelta(days=1)).isoformat()
        w = A.validate_sg({"kind": "game", "id": "g"}, {"ingress": [dict(RULE, description="tf_261020_ISRIR-1_a to x Connection 만료:" + old)], "egress": []},
                          {"ingress": [], "egress": []})[1]
        self.assertTrue(any("만료일" in x and "지났" in x for x in w), w)

    def test_cleanup_finds_duplicate_and_covered(self):
        self.write_rules([self.r("10.1.1.0/24", 22), self.r("10.1.1.5/32", 22), self.r("10.1.1.0/24", 22, desc="dup"),
                          self.r("10.2.2.2/32", 1000), self.r("10.2.2.2/32", 1001), self.r("10.2.2.2/32", 1002), self.r("10.3.3.3/32", 443, 450), self.r("10.3.3.3/32", 445)],
                         [{"from_port": 0, "to_port": 0, "protocol": "-1", "cidr_blocks": ["0.0.0.0/0"], "security_groups": "null", "prefix_list_ids": [], "description": "all"},
                          self.r("10.9.9.9/32", 53, proto="UDP")])
        r = self.J(self.c.get("/api/report/cleanup"))
        mine = [x for x in r["rows"] if x["sg"] == "l-sg-bbz-x-sg"]
        kinds = [(x["kind"], x["direction"], x["port"], x["source"]) for x in mine]
        self.assertIn(("duplicate", "ingress", "22", "10.1.1.0/24"), kinds)
        self.assertIn(("covered", "ingress", "22", "10.1.1.5/32"), kinds)
        self.assertIn(("covered", "ingress", "445", "10.3.3.3/32"), kinds)
        self.assertFalse(any(k[0] == "merge" for k in kinds), kinds)             # 묶기 검토는 제안하지 않는다
        self.assertFalse(any(k[1] == "egress" for k in kinds), kinds)             # 아웃바운드 전체 허용에 포함되는 것은 제외
        self.assertFalse(any(k[0] == "covered" and k[3] == "10.1.1.0/24" for k in kinds))
        self.assertTrue(self.c.get("/api/report/cleanup?format=csv").get_data(as_text=True).startswith("\ufeff환경,SG"))

    def test_covers_logic(self):
        n = lambda *a, **k: A.norm_rule(self.r(*a, **k), "game")
        self.assertTrue(A._covers(n("10.0.0.0/8", 0, 65535), n("10.1.1.1/32", 80)))
        self.assertFalse(A._covers(n("10.1.1.1/32", 80), n("10.0.0.0/8", 80)))
        self.assertFalse(A._covers(n("10.0.0.0/8", 80, proto="UDP"), n("10.1.1.1/32", 80)))
        self.assertTrue(A._covers(dict(n("10.0.0.0/8", 0), protocol="-1"), n("10.1.1.1/32", 80, proto="UDP")))

    def test_reach_groups_full_and_partial(self):
        self.write_rules([self.r("10.1.1.0/24", 22), self.r("10.1.1.0/24", 443), self.r("10.1.1.5/32", 3306)])
        A.write_json(A.META_PATH, {"envs": {"g": {"sgs": {"l-sg-bbz-x-sg": {"sg_id": "sg-0aaa", "alias": "웹", "tags": [{"type": "Name", "value": "web"}]}}}}})
        r = self.J(self.c.get("/api/report/reach?q=10.1.1.9"))
        g = [x for x in r["rows"] if x["sg"] == "l-sg-bbz-x-sg"][0]
        self.assertEqual((g["access"], sorted(g["ports"]), g["alias"], g["sg_id"]), ("full", ["TCP 22", "TCP 443"], "웹", "sg-0aaa"))
        self.assertIn("Name:web", g["tags"])
        part = [x for x in self.J(self.c.get("/api/report/reach?q=10.1.0.0/16"))["rows"] if x["sg"] == "l-sg-bbz-x-sg"][0]
        self.assertEqual(part["access"], "part")
        self.assertEqual(sorted(part["ports"]), ["TCP 22", "TCP 3306", "TCP 443"])
        self.assertFalse([x for x in self.J(self.c.get("/api/report/reach?q=192.168.0.1"))["rows"] if x["sg"] == "l-sg-bbz-x-sg"])
        self.assertEqual(self.c.get("/api/report/reach?q=nope").status_code, 400)
        self.assertIn("\ufeff환경", self.c.get("/api/report/reach?q=10.1.1.9&format=csv").get_data(as_text=True))


class AuditAndMrCheckTests(TempEnv):
    def add_rules(self):
        sg = self.J(self.c.get("/api/env/g/sg/l-sg-bbz-x-sg"))
        sg["ingress"].append(dict(RULE, cidr_blocks=["0.0.0.0/0"], from_port=22, to_port=22))
        self.assertEqual(self.c.put("/api/env/g/sg/l-sg-bbz-x-sg", json=sg).status_code, 200)

    def test_audit_record_markdown_json_and_download(self):
        self.work_branch("ISRIR-8")
        self.add_rules()
        A.gl = lambda env, method, path, **kw: []
        r = self.J(self.c.get("/api/env/g/report/audit?ticket=ISRIR-8"))
        rec = r["record"]
        self.assertEqual((rec["ticket"], rec["totals"]["added"], rec["totals"]["risks"]), ("ISRIR-8", 1, 1))
        self.assertIsNone(rec["mr"])
        self.assertIn("# SG 변경 기록 - ISRIR-8", r["markdown"])
        self.assertIn("전체 개방", r["markdown"])
        self.assertIn("| MR | 아직 없음 |", r["markdown"])
        self.assertIn("| plan 결과 | 이 도구에 기록이 없음 |", r["markdown"])
        dl = self.c.get("/api/env/g/report/audit?download=1")                                    # 티켓을 안 주면 브랜치에서 읽는다
        self.assertIn(".md", dl.headers["Content-Disposition"])
        self.assertIn("ISRIR-8", dl.get_data(as_text=True))
        js = self.c.get("/api/env/g/report/audit?format=json")
        self.assertEqual(json.loads(js.get_data(as_text=True))["ticket"], "ISRIR-8")

    def test_audit_includes_mr_and_plan_when_known(self):
        branch = self.work_branch("ISRIR-9")
        self.add_rules()
        A.gl = lambda env, method, path, **kw: [{"iid": 21, "web_url": "http://x/21", "title": branch, "state": "opened"}] if path.endswith("/merge_requests") else []
        env = A.get_env("g")
        A.plan_put(env, 21, {"state": "done", "plan": {"add": 1, "change": 0, "destroy": 0, "replace": 0}, "ts": 1})
        md = self.J(self.c.get("/api/env/g/report/audit"))["markdown"]
        self.assertIn("!21 http://x/21", md)
        self.assertIn("추가 1 / 변경 0 / 삭제 0 / 교체 0", md)

    def test_audit_needs_cloned_repo_branch(self):
        r = self.c.get("/api/env/p/report/audit")
        self.assertIn(r.status_code, (200, 400))

    def test_mr_description_has_auto_check_section(self):
        branch = self.work_branch("ISRIR-10")
        self.add_rules()
        self.assertEqual(self.c.post("/api/env/g/git/push", json={}).status_code, 200)
        creates = []

        def fake(env, method, path, **kw):
            if method == "GET" and path.endswith("/merge_requests"):
                return []
            if method == "POST" and path.endswith("/merge_requests"):
                creates.append(kw["json"])
                return {"iid": 31, "web_url": "http://x/31", "title": branch}
            return []
        A.gl = fake
        self.assertEqual(self.c.post("/api/env/g/mr", json={"summary": "점검"}).status_code, 200)
        d = creates[0]["description"]
        self.assertIn("### 자동 점검 결과 (Traform ACL Tool)", d)
        self.assertIn("위험 규칙 1건", d)
        self.assertIn("전체 개방", d)
        self.assertEqual(self.c.post("/api/env/g/mr", json={"summary": "점검", "include_checks": False}).status_code, 200)
        self.assertNotIn("자동 점검 결과", creates[1]["description"])

    def test_mr_check_section_never_blocks(self):
        orig = A.change_summary
        A.change_summary = lambda env: (_ for _ in ()).throw(A.ApiError("읽을 수 없음"))
        try:
            self.assertEqual(A.mr_check_section(A.get_env("g")), "")
        finally:
            A.change_summary = orig


class ReviewToolsTests(TempEnv):
    D = ("aws", "live", "sub", "sg", "sg_rule")

    def write_rules(self, ingress, egress=None, name="l-sg-bbz-x-sg"):
        d = os.path.join(self.repo, *self.D)
        put(os.path.join(d, name + "-ingress-rules.json"), json.dumps(ingress, indent=2) + "\n")
        put(os.path.join(d, name + "-egress-rules.json"), json.dumps(egress or [], indent=2) + "\n")
        A._SG_CACHE.clear()

    def r(self, cidr, f, t=None, desc="d", proto="TCP", sg="null"):
        return {"from_port": f, "to_port": t if t is not None else f, "protocol": proto, "cidr_blocks": [cidr] if cidr else [], "security_groups": sg,
                "prefix_list_ids": [], "description": desc}

    def test_risk_approval_reason_is_required_and_flows_into_record_and_mr(self):
        branch = self.work_branch("ISRIR-31")
        sg = self.J(self.c.get("/api/env/g/sg/l-sg-bbz-x-sg"))
        sg["ingress"].append(dict(RULE, cidr_blocks=["0.0.0.0/0"], from_port=22, to_port=22))
        v = self.J(self.c.post("/api/env/g/sg/l-sg-bbz-x-sg/validate", json=sg))
        self.assertTrue(v["risks"])
        self.assertEqual(self.c.put("/api/env/g/sg/l-sg-bbz-x-sg", json=sg).status_code, 200)
        self.assertEqual(self.c.post("/api/env/g/risk-approval", json={"sg": "l-sg-bbz-x-sg", "risks": v["risks"], "reason": " "}).status_code, 400)
        self.assertEqual(self.c.post("/api/env/g/risk-approval", json={"sg": "l-sg-bbz-x-sg", "risks": [], "reason": "사유"}).status_code, 400)
        r = self.J(self.c.post("/api/env/g/risk-approval", json={"sg": "l-sg-bbz-x-sg", "risks": v["risks"], "reason": "사무실 이전 팀장 승인"}))
        self.assertEqual((r["approval"]["branch"], r["approval"]["ticket"]), (branch, "ISRIR-31"))
        self.assertEqual(len(self.J(self.c.get("/api/env/g/risk-approvals?branch=" + branch))["approvals"]), 1)
        A.gl = lambda env, method, path, **kw: []
        a = self.J(self.c.get("/api/env/g/report/audit"))
        self.assertTrue(a["record"]["risk_notes"][0]["approved"])
        self.assertIn("승인 사유: 사무실 이전 팀장 승인", a["markdown"])
        self.assertIn("승인 사유: 사무실 이전 팀장 승인", A.mr_check_section(A.get_env("g")))

    def test_audit_marks_unapproved_risk(self):
        self.work_branch("ISRIR-32")
        sg = self.J(self.c.get("/api/env/g/sg/l-sg-bbz-x-sg"))
        sg["ingress"].append(dict(RULE, cidr_blocks=["0.0.0.0/0"], from_port=22, to_port=22))
        self.c.put("/api/env/g/sg/l-sg-bbz-x-sg", json=sg)
        A.gl = lambda env, method, path, **kw: []
        self.assertIn("승인 기록 없음", self.J(self.c.get("/api/env/g/report/audit"))["markdown"])

    def test_validate_reports_already_open(self):
        self.write_rules([self.r("10.1.1.0/24", 22)])
        sg = self.J(self.c.get("/api/env/g/sg/l-sg-bbz-x-sg"))
        sg["ingress"].append(self.r("10.1.1.5/32", 22, desc="tf_261020_ISRIR-1_a to x Connection"))
        v = self.J(self.c.post("/api/env/g/sg/l-sg-bbz-x-sg/validate", json=sg))
        self.assertTrue(any("이미 열려 있습니다" in x for x in v["already"]), v)
        sg["ingress"][-1] = self.r("10.9.9.9/32", 22, desc="tf_261020_ISRIR-1_a to x Connection")
        self.assertEqual(self.J(self.c.post("/api/env/g/sg/l-sg-bbz-x-sg/validate", json=sg))["already"], [])

    def test_validate_reports_open_in_other_sg(self):
        self.write_rules([self.r("10.1.1.0/24", 22)], name="l-sg-bbz-y-sg")
        self.write_rules([], name="l-sg-bbz-x-sg")
        sg = self.J(self.c.get("/api/env/g/sg/l-sg-bbz-x-sg"))
        sg["ingress"].append(self.r("10.1.1.5/32", 22, desc="tf_261020_ISRIR-1_a to x Connection"))
        v = self.J(self.c.post("/api/env/g/sg/l-sg-bbz-x-sg/validate", json=sg))
        self.assertTrue(any("l-sg-bbz-y-sg" in x for x in v["others"]), v)

    def test_score_counts_and_grades(self):
        self.write_rules([self.r("0.0.0.0/0", 22, desc="a"), self.r("10.0.0.0/8", 3389, desc="b"), self.r("10.1.1.1/32", 80, desc=""), self.r("10.1.1.2/32", 81, proto="-1")])
        envs, rows = A.score_report()
        e = [x for x in envs if x["counts"]["open_all"]][0]
        self.assertEqual((e["counts"]["open_all"], e["counts"]["mgmt"], e["counts"]["no_desc"]), (1, 1, 1))
        self.assertLess(e["score"], 100)
        self.assertIn(e["grade"], "ABCD")
        self.assertTrue(self.J(self.c.get("/api/report/score"))["envs"])
        self.assertTrue(self.c.get("/api/report/score?format=csv").get_data(as_text=True).startswith("﻿환경,SG"))

    def test_score_respects_policy_exception(self):
        self.write_rules([self.r("0.0.0.0/0", 22)])
        self.c.put("/api/policy", json={"policy": {"exceptions": [{"name": "x", "cidrs": "0.0.0.0/0", "ports": "22"}]}})
        envs, _rows = A.score_report()
        self.assertEqual(sum(x["counts"]["open_all"] for x in envs), 0)

    def test_ticket_finder_rules_and_validation(self):
        self.write_rules([self.r("10.1.1.1/32", 80, desc="tf_261020_ISRIR-77_a to x Connection"), self.r("10.1.1.2/32", 81, desc="other")])
        r = self.J(self.c.get("/api/ticket/ISRIR-77?mr=0"))
        self.assertEqual((r["rule_count"], r["rules"][0]["port"]), (1, "80"))
        self.assertEqual(self.c.get("/api/ticket/a%20b?mr=0").status_code, 400)
        self.assertEqual(self.J(self.c.get("/api/ticket/ISRIR-99?mr=0"))["rule_count"], 0)

    def test_ticket_finder_branch_and_mr(self):
        branch = self.work_branch("ISRIR-78")
        A.gl = lambda env, method, path, **kw: [{"iid": 5, "title": "t ISRIR-78", "state": "opened", "web_url": "http://x/5", "source_branch": branch}] if path.endswith("/merge_requests") else []
        r = self.J(self.c.get("/api/ticket/ISRIR-78"))
        self.assertTrue(any("ISRIR-78" in b["branch"] for b in r["branches"]), r["branches"])
        self.assertEqual(r["mrs"][0]["iid"], 5)

    def test_cleanup_apply_deletes_selected_rules_only_on_work_branch(self):
        self.work_branch("ISRIR-33")
        self.write_rules([self.r("10.1.1.0/24", 22), self.r("10.1.1.5/32", 22), self.r("10.2.2.2/32", 443)])
        rows = [x for x in self.J(self.c.get("/api/report/cleanup"))["rows"] if x["sg"] == "l-sg-bbz-x-sg"]
        cov = [x for x in rows if x["kind"] == "covered"][0]
        item = {k: cov[k] for k in ("env_id", "sg", "direction", "idx", "sig")}
        pv = self.J(self.c.post("/api/cleanup/apply", json={"items": [item], "dry_run": True}))
        self.assertEqual((pv["removed"], pv["skipped"]), (1, 0))
        self.assertEqual(len(self.J(self.c.get("/api/env/g/sg/l-sg-bbz-x-sg"))["ingress"]), 3)   # 미리보기는 바꾸지 않는다
        self.assertEqual(self.J(self.c.post("/api/cleanup/apply", json={"items": [item]}))["removed"], 1)
        left = self.J(self.c.get("/api/env/g/sg/l-sg-bbz-x-sg"))["ingress"]
        self.assertEqual(sorted(x["cidr_blocks"][0] for x in left), ["10.1.1.0/24", "10.2.2.2/32"])
        stale = self.J(self.c.post("/api/cleanup/apply", json={"items": [item]}))                  # 같은 항목을 다시 보내도 다른 규칙을 지우지 않는다
        self.assertEqual((stale["removed"], stale["skipped"]), (0, 1))
        self.assertEqual(len(self.J(self.c.get("/api/env/g/sg/l-sg-bbz-x-sg"))["ingress"]), 2)
        self.assertEqual(self.c.post("/api/cleanup/apply", json={"items": []}).status_code, 400)

    def test_sg_refs_and_reach_via(self):
        self.write_rules([self.r("10.1.1.0/24", 443, desc="in")], name="l-sg-bbz-x-sg")
        self.write_rules([self.r(None, 8080, desc="from x", sg="sg-0aaa111")], name="l-sg-bbz-y-sg")
        orig = A.load_meta
        A.load_meta = lambda: {"envs": {"g": {"sgs": {"l-sg-bbz-x-sg": {"sg_id": "sg-0aaa111"}, "l-sg-bbz-y-sg": {"sg_id": "sg-0bbb222"}}}}}
        try:
            g = self.J(self.c.get("/api/report/sgrefs?q=sg-0aaa111"))
            s = g["starts"][0]
            self.assertEqual([e["to"]["name"] for e in s["down"]], ["l-sg-bbz-y-sg"])
            up = self.J(self.c.get("/api/report/sgrefs?q=l-sg-bbz-y-sg"))["starts"][0]["up"]
            self.assertEqual(up[0]["from"]["name"], "l-sg-bbz-x-sg")
            self.assertEqual(self.c.get("/api/report/sgrefs?q=nope-zzz").status_code, 404)
            self.assertTrue(self.c.get("/api/report/sgrefs?q=sg-0aaa111&format=csv").get_data(as_text=True).startswith("﻿기준 SG"))
            direct = self.J(self.c.get("/api/report/reach?q=10.1.1.5"))
            self.assertEqual([x["sg"] for x in direct["rows"]], ["l-sg-bbz-x-sg"])
            via = self.J(self.c.get("/api/report/reach?q=10.1.1.5&via=1"))
            by = {x["sg"]: x for x in via["rows"]}
            self.assertEqual(by["l-sg-bbz-y-sg"]["access"], "via")
            self.assertIn("l-sg-bbz-x-sg → l-sg-bbz-y-sg", by["l-sg-bbz-y-sg"]["via"])
            self.assertEqual(by["l-sg-bbz-x-sg"]["access"], "full")
        finally:
            A.load_meta = orig

    def test_services_dictionary_validation(self):
        r = self.J(self.c.put("/api/services", json={"services": [{"name": "웹", "protocol": "tcp", "ports": "443"}, {"name": "범위", "protocol": "UDP", "ports": "1000-2000"}]}))
        self.assertEqual([x["protocol"] for x in r["services"]], ["TCP", "UDP"])
        self.assertEqual(len(self.J(self.c.get("/api/services"))["services"]), 2)
        for bad in ([{"name": "a b", "ports": "80"}], [{"name": "x", "ports": "80,443"}], [{"name": "x", "ports": "99999"}], [{"name": "x", "protocol": "ICMP", "ports": "1"}],
                    [{"name": "d", "ports": "1"}, {"name": "D", "ports": "2"}]):
            self.assertEqual(self.c.put("/api/services", json={"services": bad}).status_code, 400, bad)
        self.assertEqual(len(self.J(self.c.get("/api/services"))["services"]), 2)

    def test_compare_history_reports_new_and_resolved(self):
        env = A.get_env("g")
        res = {"profile": "p", "region": "r", "counts": {}, "aws_only_total": 1, "file_only_total": 0}
        k1 = ("ingress", "tcp", 22, 22, "cidr", "10.0.0.1/32")
        k2 = ("ingress", "tcp", 80, 80, "cidr", "10.0.0.2/32")
        h1 = A.compare_history_add(env, res, {"s": {"a": [k1], "f": []}})
        self.assertIsNone(h1["previous"])
        h2 = A.compare_history_add(env, res, {"s": {"a": [k1, k2], "f": []}})
        self.assertEqual((h2["new"], h2["resolved"], h2["unchanged"]), (1, 0, 1))
        self.assertEqual(h2["new_items"][0]["port"], "80")
        h3 = A.compare_history_add(env, res, {"s": {"a": [k2], "f": []}})
        self.assertEqual((h3["new"], h3["resolved"]), (0, 1))
        self.assertEqual(len(self.J(self.c.get("/api/env/g/aws/compare/history"))["history"]), 3)


class TicketAutoAndDomainTests(TempEnv):
    TEXT = ("요약: 게임서버 접근 요청\n출발지: 211.34.57.10, 10.1.1.0/24\n목적지: x 서버 10.2.2.5\n포트: TCP 443, 8080-8090\n"
            "도메인 game.example.com 접속 필요. 참고 file.json\n")

    def setUp(self):
        super().setUp()
        self.orig = (A.jira_call, A._resolve, A.load_meta)
        A._resolve = lambda d, timeout=4: (["10.2.2.5"], "")

    def tearDown(self):
        A.jira_call, A._resolve, A.load_meta = self.orig
        super().tearDown()

    def set_meta(self, tags, alias="게임 서버"):
        A.load_meta = self.orig[2]
        A.write_json(A.META_PATH, {"envs": {"g": {"sgs": {"l-sg-bbz-x-sg": {"alias": alias, "sg_id": "sg-0aaa111", "tags": tags}}}}})

    def test_parse_ticket_text(self):
        p = A.parse_ticket_text(self.TEXT)
        self.assertEqual(p["ips"], ["211.34.57.10/32", "10.1.1.0/24"])
        self.assertEqual(p["dst_ips"], ["10.2.2.5/32"])
        self.assertEqual([(x["from"], x["to"]) for x in p["ports"]], [(443, 443), (8080, 8090)])
        self.assertEqual((p["protocol"], p["direction"], p["domains"], p["warnings"]), ("TCP", "ingress", ["game.example.com"], []))

    def test_parse_without_labels_warns_and_handles_udp_and_bad_values(self):
        p = A.parse_ticket_text("10.0.0.1 에서 10.0.0.2 로 UDP 5000 오픈 요청, 999.1.1.1 은 무시, 아웃바운드")
        self.assertEqual(p["ips"], ["10.0.0.1/32", "10.0.0.2/32"])
        self.assertEqual((p["protocol"], p["direction"], [(x["from"], x["to"]) for x in p["ports"]]), ("UDP", "egress", [(5000, 5000)]))
        self.assertTrue(any("출발지로 표시된 줄이 없어" in w for w in p["warnings"]))
        e = A.parse_ticket_text("내용 없음")
        self.assertTrue(any("출발지 IP" in w for w in e["warnings"]) and any("포트" in w for w in e["warnings"]))

    def test_norm_domain(self):
        self.assertEqual(A.norm_domain("https://Game.Example.com:8443/path"), "game.example.com")
        for bad in ("10.1.1.1", "localhost", "a_b.example.com", "", "x.123"):
            self.assertEqual(A.norm_domain(bad), "", bad)

    def test_plan_reads_ticket_and_suggests_target_from_domain_tag(self):
        self.set_meta([{"type": "domain", "value": "game.example.com"}])
        A.jira_call = lambda method, path, **kw: {"key": "ISRIR-5", "names": {"customfield_1": "출발지 IP"},
                                                  "fields": {"summary": "접근 요청", "status": {"name": "Open"}, "issuetype": {"name": "Task"}, "description": "포트: 443\n도메인 game.example.com",
                                                             "customfield_1": "211.34.57.10"}}
        r = self.J(self.c.get("/api/jira/plan?key=isrir-5&env_id=g"))
        self.assertEqual((r["key"], r["summary"], r["status"]), ("ISRIR-5", "접근 요청", "Open"))
        self.assertEqual(r["parsed"]["ips"], ["211.34.57.10/32"])
        self.assertEqual(r["parsed"]["ports"], [{"from": 443, "to": 443}])
        self.assertEqual(r["suggested"], ["l-sg-bbz-x-sg"])
        self.assertTrue(r["domains"][0]["registered"])
        self.assertEqual(self.c.get("/api/jira/plan?key=bad").status_code, 400)

    def test_plan_does_not_guess_when_nothing_matches(self):
        self.set_meta([])
        A.jira_call = lambda method, path, **kw: {"key": "ISRIR-6", "fields": {"summary": "s", "description": "출발지: 1.2.3.4\n포트: 80"}}
        r = self.J(self.c.get("/api/jira/plan?key=ISRIR-6&env_id=g"))
        self.assertEqual(r["suggested"], [])

    def test_domain_lookup_registered_candidates_and_dns(self):
        self.set_meta([{"type": "domain", "value": "game.example.com"}])
        r = self.J(self.c.get("/api/domain/lookup?d=game.example.com"))
        self.assertEqual((r["registered"][0]["sg"], r["ips"]), ("l-sg-bbz-x-sg", ["10.2.2.5"]))
        self.set_meta([{"type": "", "value": "10.2.2.0/24"}])
        r = self.J(self.c.get("/api/domain/lookup?d=new.example.com"))
        self.assertEqual(r["registered"], [])
        self.assertEqual(r["candidates"][0]["sg"], "l-sg-bbz-x-sg")
        self.assertIn("DNS 결과", r["candidates"][0]["reason"])
        self.set_meta([], alias="match3 게임 서버")
        r = self.J(self.c.get("/api/domain/lookup?d=match3.example.com&dns=0"))
        self.assertIn("match3", r["candidates"][0]["reason"])
        self.assertEqual(self.c.get("/api/domain/lookup?d=1.2.3.4").status_code, 400)

    def test_domain_lookup_reports_dns_failure(self):
        A._resolve = lambda d, timeout=4: ([], "DNS 조회 실패: x")
        self.set_meta([])
        r = self.J(self.c.get("/api/domain/lookup?d=nope.example.com"))
        self.assertEqual((r["ips"], r["dns_error"]), ([], "DNS 조회 실패: x"))

    def test_domain_apply_adds_tag_only_when_meta_exists(self):
        self.set_meta([{"type": "domain", "value": "old.example.com"}])
        r = self.J(self.c.post("/api/domain/apply", json={"domain": "New.Example.com", "env_id": "g", "sg": "l-sg-bbz-x-sg"}))
        self.assertFalse(r["already"])
        tags = self.J(self.c.get("/api/meta"))["envs"]["g"]["sgs"]["l-sg-bbz-x-sg"]["tags"]
        self.assertEqual([t["value"] for t in tags], ["old.example.com", "new.example.com"])
        self.assertEqual(tags[1]["type"], "domain")
        again = self.J(self.c.post("/api/domain/apply", json={"domain": "new.example.com", "env_id": "g", "sg": "l-sg-bbz-x-sg"}))
        self.assertTrue(again["already"])
        self.assertEqual(len(self.J(self.c.get("/api/meta"))["envs"]["g"]["sgs"]["l-sg-bbz-x-sg"]["tags"]), 2)
        self.assertEqual(self.c.post("/api/domain/apply", json={"domain": "x.example.com", "env_id": "g", "sg": "no-such-sg"}).status_code, 400)
        self.assertEqual(self.c.post("/api/domain/apply", json={"domain": "bad", "env_id": "g", "sg": "l-sg-bbz-x-sg"}).status_code, 400)
        self.assertNotIn("no-such-sg", self.J(self.c.get("/api/meta"))["envs"]["g"]["sgs"])


class TicketFormAndFinishTests(TempEnv):
    HEAD = ("<tr><td>no</td><td>구분<br>(application type)</td><td>Project</td><td>Source IP</td><td>Source Env</td><td>Destination IP</td><td>Destination Env</td>"
            "<td>Service Port</td><td>용도<br>(purpose of use)</td><td>사용 기간<br>(period of use)</td><td>비고<br>(note)</td></tr>")

    def row(self, no, act, proj, src, dst, port, purpose="용도", period="서비스 운영 기간<br>(영구)"):
        return "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>LIVE</td><td>%s</td><td>LIVE</td><td>%s</td><td>%s</td><td>%s</td><td>&nbsp;</td></tr>" % (no, act, proj, src, dst, port, purpose, period)

    def html(self, rows, section="[ 정책 등록 (new policies) ]"):
        return ('<table><tbody><tr><td colspan="11"><p>%s</p></td></tr>%s'
                '<tr><td>(예시/eg)</td><td>등록</td><td>Ppool</td><td>10.5.X.X<br>10.2.X.X</td><td>Dev</td><td>10.130.X.X</td><td>Dev</td><td>443 TCP</td><td>x</td><td>~2023.12.31</td><td>y</td></tr>%s</tbody></table><p>설명</p>'
                % (section, self.HEAD, "".join(rows)))

    def setUp(self):
        super().setUp()
        self.orig = (A.jira_call, A._resolve, A.load_meta, A.gl)

    def tearDown(self):
        A.jira_call, A._resolve, A.load_meta, A.gl = self.orig
        super().tearDown()

    def test_table_rows_merge_into_groups_and_skip_example(self):
        h = self.html([self.row(1, "등록&#12288;", "&#12288;Drive", "10.140.101.13&#12288;", "10.140.21.61&#12288;", "443 TCP"),
                       self.row(2, "등록", "Drive", "10.140.101.14<br>10.140.101.15", "10.140.21.61", "443 TCP&#12288;"),
                       self.row(3, "등록", "Drive", "10.140.101.13", "10.140.21.62", "8080-8090 TCP, 53 UDP", period="~2026.12.31")])
        g, warns, found = A.parse_request_table(h)
        self.assertTrue(found)
        self.assertEqual(len(g), 3)                                   # (21.61:443) / (21.62:8080-8090 TCP) / (21.62:53 UDP)
        self.assertEqual(g[0]["ips"], ["10.140.101.13/32", "10.140.101.14/32", "10.140.101.15/32"])
        self.assertEqual((g[0]["dst_ips"], g[0]["protocol"], g[0]["rows"], g[0]["project"]), (["10.140.21.61/32"], "TCP", ["1", "2"], "Drive"))
        self.assertEqual({(x["protocol"], x["ports"][0]["from"]) for x in g[1:]}, {("TCP", 8080), ("UDP", 53)})
        self.assertEqual([x for x in g if x["expires"]][0]["expires"], "2026-12-31")
        self.assertTrue(any("묶음" in w for w in warns))
        self.assertFalse(any("10.5" in ",".join(x["ips"]) for x in g))   # 예시 행은 읽지 않음

    def test_delete_section_change_and_missing_values(self):
        h = self.html([self.row(1, "", "Drive", "10.9.9.1", "10.140.21.61", "443 TCP"), self.row(2, "변경", "Drive", "10.9.9.2", "10.140.21.61", "80 TCP"),
                       self.row(3, "등록", "Drive", "", "10.140.21.61", "80 TCP"), self.row(4, "등록", "Drive", "10.9.9.3", "10.140.21.61", "ALL")], section="[ 정책 삭제 (delete policies) ]")
        g, warns, _f = A.parse_request_table(h)
        self.assertEqual([x["action"] for x in g], ["del", "add"])        # 구분 칸이 비면 구역(삭제), 변경은 추가로 채우고 경고
        self.assertTrue(any("변경" in w for w in warns) and any("출발지 IP 가 없어" in w for w in warns) and any("포트를 읽지 못" in w for w in warns))

    def test_wiki_table_is_read_too(self):
        wiki = ("h3. [ 정책 등록 ]\n||no||구분||Project||Source IP||Source Env||Destination IP||Destination Env||Service Port||용도||\n"
                "|1|등록|Drive|10.1.1.1\\\\10.1.1.2|LIVE|10.2.2.2|LIVE|443 TCP|테스트|\n")
        g, _w, found = A.parse_request_table(wiki)
        self.assertTrue(found)
        self.assertEqual((g[0]["ips"], g[0]["dst_ips"], g[0]["ports"]), (["10.1.1.1/32", "10.1.1.2/32"], ["10.2.2.2/32"], [{"from": 443, "to": 443}]))

    def test_plan_endpoint_returns_groups_with_targets(self):
        A.load_meta = self.orig[2]
        A.write_json(A.META_PATH, {"envs": {"g": {"sgs": {"l-sg-bbz-x-sg": {"alias": "Drive 모니터 10.140.21.61", "sg_id": "sg-0aaa111", "tags": []}}}}})
        h = self.html([self.row(1, "등록", "Drive", "10.140.101.13", "10.140.21.61", "443 TCP"), self.row(2, "등록", "Drive", "10.140.101.13", "10.150.1.1", "80 TCP")])
        A.jira_call = lambda method, path, **kw: {"key": "ISRIR-9", "names": {"customfield_1": "프로젝트"}, "fields": {"summary": "[ACL 요청] Drive", "status": {"name": "접수"}, "description": h, "customfield_1": {"value": "Drive"}}}
        r = self.J(self.c.get("/api/jira/plan?key=ISRIR-9&env_id=g&light=1"))
        self.assertEqual(len(r["parsed"]["groups"]), 2)
        self.assertEqual(r["project"], "Drive")
        g0, g1 = r["parsed"]["groups"]
        self.assertEqual(g0["suggested"], ["l-sg-bbz-x-sg"])           # 목적지 IP 가 별명에 있음 + 프로젝트
        self.assertEqual(g1["suggested"], [])                           # 못 찾으면 고르지 않음
        self.assertEqual(r["parsed"]["ips"], g0["ips"])                 # 최상위 값 = 첫 묶음
        self.assertEqual(r["domains"], [])

    def test_plain_html_and_template(self):
        self.assertIn("Source IP | ", A._plain("<tr><td>Source IP</td><td>x</td></tr>"))
        self.assertEqual(A._plain("그냥 글"), "그냥 글")
        t = self.J(self.c.get("/api/jira/template"))
        self.assertIn("Source IP", t["html"])
        self.assertIn("Service Port", t["text"])
        g, _w, found = A.parse_request_table(t["html"])
        self.assertTrue(found)                                          # 도구가 만든 양식 머리글을 도구가 읽는다
        self.assertEqual(g, [])                                         # 예시·빈 행은 묶음을 만들지 않는다

    def test_transitions_and_finish(self):
        calls = []

        def fake(method, path, **kw):
            calls.append((method, path, kw.get("json")))
            if path.endswith("/transitions") and method == "GET":
                return {"transitions": [{"id": 71, "name": "완료 처리", "to": {"name": "완료"}}, {"id": 5, "name": "반려", "to": {"name": "반려"}}]}
            if method == "GET":
                return {"fields": {"summary": "s", "status": {"name": "진행 중"}}}
            return {}
        A.jira_call = fake
        r = self.J(self.c.get("/api/jira/transitions?key=isrir-1"))
        self.assertEqual((r["status"], [t["name"] for t in r["transitions"]], r["transitions"][0]["id"]), ("진행 중", ["완료 처리", "반려"], "71"))
        ok = self.J(self.c.post("/api/jira/finish", json={"key": "ISRIR-1", "comment": "적용 완료", "transition_id": "71"}))
        self.assertEqual((ok["commented"], ok["transitioned"]), (True, "완료 처리"))
        posts = [(m, p) for m, p, _j in calls if m == "POST"]
        self.assertEqual(posts, [("POST", "/issue/ISRIR-1/comment"), ("POST", "/issue/ISRIR-1/transitions")])   # 코멘트 → 전환 순서
        self.assertEqual([j for m, p, j in calls if p.endswith("/transitions") and m == "POST"][0], {"transition": {"id": "71"}})
        n = len(calls)
        self.assertEqual(self.c.post("/api/jira/finish", json={"key": "ISRIR-1", "comment": "x", "transition_id": "999"}).status_code, 400)
        self.assertFalse(any(m == "POST" for m, _p, _j in calls[n:]))     # 없는 전환이면 코멘트도 남기지 않는다
        self.assertEqual(self.c.post("/api/jira/finish", json={"key": "ISRIR-1"}).status_code, 400)
        self.assertEqual(self.c.post("/api/jira/finish", json={"key": "bad", "comment": "x"}).status_code, 400)

    def test_finish_reports_partial_when_transition_fails(self):
        def fake(method, path, **kw):
            if method == "GET":
                return {"transitions": [{"id": 71, "name": "완료 처리", "to": {"name": "완료"}}]}
            if path.endswith("/transitions"):
                raise A.ApiError("Jira 오류 400: 필수 필드", 502)
            return {}
        A.jira_call = fake
        r = self.c.post("/api/jira/finish", json={"key": "ISRIR-1", "comment": "c", "transition_id": "71"})
        self.assertEqual(r.status_code, 502)
        self.assertIn("코멘트는 남겼지만", self.J(r)["error"])


class PlanImpactAndAutoApplyTests(TempEnv):
    ADD = ("  # module.l-sg-bbz-x-sg.aws_security_group_rule.r1 will be created\n  + resource \"aws_security_group_rule\" \"r1\" {\n    }\n"
           "Plan: 1 to add, 0 to change, 0 to destroy.")

    def setUp(self):
        super().setUp()
        self.gl0 = A.gl
        A.gl = lambda env, method, path, **kw: {"sha": "s1", "state": "opened", "source_branch": "b"}

    def tearDown(self):
        A.gl = self.gl0
        super().tearDown()

    def status(self, rec, q="targets=l-sg-bbz-x-sg&expect=1"):
        A.plan_put(A.get_env("g"), "7", {"sha": "s1", "applied": False, **rec})
        return self.J(self.c.get("/api/env/g/atlantis/plan-status?iid=7&" + q))

    def test_impact_parsing_and_analyze(self):
        imp = A.plan_impact(self.ADD + "\n# aws_x.y must be replaced\n# aws_x.z will be destroyed\n# aws_x.w will be updated in-place")
        self.assertEqual((imp["created"], imp["replaced"], imp["destroyed"], imp["updated"]), (["module.l-sg-bbz-x-sg.aws_security_group_rule.r1"], ["aws_x.y"], ["aws_x.z"], ["aws_x.w"]))
        r = A.analyze_atlantis(self.ADD, "plan")
        self.assertEqual(r["state"], "ok")
        self.assertEqual(r["impact"]["created"], ["module.l-sg-bbz-x-sg.aws_security_group_rule.r1"])

    def test_auto_apply_allowed_only_when_clean_and_in_scope(self):
        rec = {"state": "ok", "plan": {"found": True, "add": 1, "change": 0, "destroy": 0, "replace": 0}, "impact": {"created": ["module.l-sg-bbz-x-sg.aws_security_group_rule.r1"]}}
        s = self.status(rec)
        self.assertTrue(s["auto_ok"], s)
        self.assertEqual([c["id"] for c in s["checks"]], ["plan", "destroy", "change", "scope", "expect"])
        out = self.status({**rec, "impact": {"created": ["module.l-sg-bbz-x-sg.aws_security_group_rule.r1", "module.other-sg.aws_security_group.s"]}})
        self.assertFalse(out["auto_ok"])
        self.assertIn("대상이 아닌 리소스", out["auto_reason"])
        out = self.status({**rec, "state": "warn", "plan": {"found": True, "add": 1, "change": 0, "destroy": 1, "replace": 0}})
        self.assertFalse(out["auto_ok"])                                # 삭제 포함이면 자동 apply 안 함
        out = self.status({**rec, "plan": {"found": True, "add": 0, "change": 0, "destroy": 0, "replace": 0}})
        self.assertFalse(out["auto_ok"])                                # 변경 없음
        out = self.status({**rec, "impact": {"created": ["unknown.addr"]}})
        self.assertTrue(out["auto_ok"])                                 # 이름으로 대상 확인이 안 되면 막지는 않고 알림만
        self.assertFalse([c for c in out["checks"] if c["id"] == "scope"][0]["block"])
        out = self.status({**rec, "applied": True})
        self.assertFalse(out["auto_ok"])                                # 이미 apply 함
        self.assertFalse(self.status({"state": "pending", "plan": None})["auto_ok"])

    def test_output_endpoint_stores_impact(self):
        A.gl = lambda env, method, path, **kw: [{"id": 201, "body": self.ADD}]
        r = self.J(self.c.get("/api/env/g/atlantis/output?iid=8&since=100&action=plan"))
        self.assertEqual(r["state"], "ok")
        self.assertEqual(A.plan_get(A.get_env("g"), "8")["impact"]["created"], ["module.l-sg-bbz-x-sg.aws_security_group_rule.r1"])


class OwnerAndAuditTests(TempEnv):
    def write_rules(self, ingress, egress=None):
        d = os.path.join(self.repo, "aws", "live", "sub", "sg", "sg_rule")
        put(os.path.join(d, "l-sg-bbz-x-sg-ingress-rules.json"), json.dumps(ingress, indent=2) + "\n")
        put(os.path.join(d, "l-sg-bbz-x-sg-egress-rules.json"), json.dumps(egress or [], indent=2) + "\n")
        A._SG_CACHE.clear()

    def r(self, cidr, f, t=None, desc="d", proto="TCP"):
        return {"from_port": f, "to_port": t if t is not None else f, "protocol": proto, "cidr_blocks": [cidr], "security_groups": "null",
                "prefix_list_ids": [], "description": desc}

    def setUp(self):
        super().setUp()
        self.meta0 = A.read_json(A.META_PATH, {})
        A.write_json(A.META_PATH, {"envs": {"g": {"sgs": {"l-sg-bbz-x-sg": {"alias": "a", "sg_id": "sg-0aaa111", "owner": "보안팀", "tags": [{"type": "", "value": "10.1.1.1"}]}}}}})

    def tearDown(self):
        A.write_json(A.META_PATH, self.meta0)
        super().tearDown()

    def test_meta_csv_roundtrip_keeps_owner(self):
        csv_text = self.c.get("/api/meta/csv").get_data(as_text=True)
        self.assertIn("owner", csv_text.splitlines()[0])
        self.assertIn("보안팀", csv_text)
        old = "env_id,sg_name,sg_id,alias,tag_type,tag_value\ng,l-sg-bbz-x-sg,sg-0aaa111,a,,10.1.1.1\n"      # owner 열이 없는 예전 CSV
        r = self.c.post("/api/meta/csv", data={"file": (io.BytesIO(old.encode("utf-8")), "m.csv")}, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(A.load_meta()["envs"]["g"]["sgs"]["l-sg-bbz-x-sg"]["owner"], "보안팀")                  # 지워지지 않음
        new = old.replace("tag_value\n", "tag_value,owner\n").replace("10.1.1.1\n", "10.1.1.1,플랫폼팀\n")
        self.c.post("/api/meta/csv", data={"file": (io.BytesIO(new.encode("utf-8")), "m.csv")}, content_type="multipart/form-data")
        self.assertEqual(A.load_meta()["envs"]["g"]["sgs"]["l-sg-bbz-x-sg"]["owner"], "플랫폼팀")

    def test_reports_carry_owner(self):
        self.write_rules([self.r("10.1.1.1/32", 80, desc="a 만료:2000-01-01")])
        e = self.J(self.c.get("/api/report/expiry?days=30"))
        self.assertTrue(e["rows"] and e["rows"][0]["owner"] == "보안팀")
        self.assertIn("담당자", self.c.get("/api/report/expiry?format=csv").get_data(as_text=True).splitlines()[0])
        o = self.J(self.c.get("/api/report/owners"))
        mine = [x for x in o["owners"] if x["owner"] == "보안팀"][0]
        self.assertTrue(mine["sgs"] >= 1 and mine["expired"] >= 1)
        self.assertTrue(any(x["owner"] == "(미지정)" for x in o["owners"]))                    # 담당자 없는 SG 가 있다 (platform 환경)

    def test_audit_xlsx(self):
        from openpyxl import load_workbook
        A.write_json(A.HISTORY_PATH, {"p": [{"id": "h1", "ts": int(datetime.now().timestamp() * 1000), "t": "x", "step": "규칙 추가 → SG 1개", "kind": "rule", "state": "ok", "headline": "✓ 1건 추가", "text": "l-sg: +1\nline2", "user": "heejim"},
                                           {"id": "h2", "ts": 1000, "t": "old", "step": "오래된", "kind": "rule", "state": "ok"}]})
        A.write_json(os.path.join(A.DATA, "risk_approvals.json"), [{"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "user": "heejim", "env_id": "g", "ticket": "ISRIR-1", "branch": "b", "sg": "s", "risks": ["광범위"], "reason": "승인함"}])
        r = self.c.get("/api/report/audit-xlsx")
        self.assertEqual(r.status_code, 200)
        self.assertIn("spreadsheetml", r.mimetype)
        wb = load_workbook(io.BytesIO(r.data))
        self.assertEqual(wb.sheetnames, ["요약", "변경 이력", "위험 규칙 승인", "만료 규칙", "정리 제안", "기준 점검", "담당자별"])
        hist = list(wb["변경 이력"].iter_rows(values_only=True))
        self.assertEqual(len(hist), 2)                                                         # 머리글 + 기간 안의 1건 (오래된 것 제외)
        self.assertEqual(hist[1][7], "l-sg: +1")                                               # 내용은 첫 줄만
        self.assertEqual(list(wb["위험 규칙 승인"].iter_rows(values_only=True))[1][7], "승인함")
        self.assertEqual(self.c.get("/api/report/audit-xlsx?from=2026-02-01&to=2026-01-01").status_code, 400)
        self.assertEqual(self.c.get("/api/report/audit-xlsx?from=bad").status_code, 400)


class InPlaceActionTests(TempEnv):
    def setUp(self):
        super().setUp()
        env = A.get_env("g")
        A.run_git(env, "checkout", "-f", "main")
        A.run_git(env, "clean", "-fd")
        A.invalidate_status()
        A._SG_CACHE.clear()

    def write_rules(self, ingress, egress=None):
        d = os.path.join(self.repo, "aws", "live", "sub", "sg", "sg_rule")
        put(os.path.join(d, "l-sg-bbz-x-sg-ingress-rules.json"), json.dumps(ingress, indent=2) + chr(10))
        put(os.path.join(d, "l-sg-bbz-x-sg-egress-rules.json"), json.dumps(egress or [], indent=2) + chr(10))
        A._SG_CACHE.clear()

    def r(self, cidr, f, desc="d"):
        return {"from_port": f, "to_port": f, "protocol": "TCP", "cidr_blocks": [cidr], "security_groups": "null", "prefix_list_ids": [], "description": desc}

    def panel(self):
        return self.J(self.c.get("/api/env/g/sg/l-sg-bbz-x-sg/rules"))

    def test_panel_lists_rules_with_position_and_branch_state(self):
        p = self.panel()
        self.assertFalse(p["work_branch"])                                       # 기본 브랜치면 작업 브랜치가 필요하다고 알린다
        self.assertEqual((p["sg"], [(x["direction"], x["idx"]) for x in p["rules"]]), ("l-sg-bbz-x-sg", [("ingress", 0)]))
        self.assertTrue(p["rules"][0]["sig"] and "meta" in p)
        self.assertEqual(self.c.get("/api/env/g/sg/no-such/rules").status_code, 404)
        self.work_branch("ISRIR-90")
        self.write_rules([self.r("10.1.1.1/32", 80, "tf_261020_ISRIR-1_a to x Connection 만료:2030-01-01"), self.r("10.1.1.2/32", 81)])
        p = self.panel()
        self.assertTrue(p["work_branch"])
        self.assertEqual((len(p["rules"]), p["rules"][0]["expires"], p["rules"][1]["expires"]), (2, "2030-01-01", ""))

    def test_extend_changes_only_the_date_and_checks_branch_and_signature(self):
        base = self.panel()["rules"][0]
        body = {"env_id": "g", "sg": "l-sg-bbz-x-sg", "direction": "ingress", "idx": 0, "sig": base["sig"], "date": "2031-02-03"}
        self.assertEqual(self.c.post("/api/rule/extend", json=body).status_code, 409)                  # 작업 브랜치가 아니면 막는다
        self.work_branch("ISRIR-91")
        self.write_rules([self.r("10.1.1.1/32", 80, "tf_261020_ISRIR-1_a to x Connection 만료:2030-01-01"), self.r("10.1.1.2/32", 81, "설명만 있음")])
        rows = self.panel()["rules"]
        body["sig"] = rows[0]["sig"]
        self.assertEqual(self.c.post("/api/rule/extend", json={**body, "date": "2001-01-01"}).status_code, 400)   # 과거 날짜
        self.assertEqual(self.c.post("/api/rule/extend", json={**body, "sig": "x"}).status_code, 409)           # 그 사이 바뀐 규칙
        r = self.J(self.c.post("/api/rule/extend", json={**body, "dry_run": True}))
        self.assertEqual(r["new"], "tf_261020_ISRIR-1_a to x Connection 만료:2031-02-03")
        self.assertEqual(self.panel()["rules"][0]["expires"], "2030-01-01")                            # dry_run 은 바꾸지 않는다
        self.J(self.c.post("/api/rule/extend", json=body))
        rules = self.panel()["rules"]
        self.assertEqual((rules[0]["expires"], rules[1]["description"]), ("2031-02-03", "설명만 있음"))
        r2 = self.J(self.c.post("/api/rule/extend", json={**body, "idx": 1, "sig": rules[1]["sig"], "date": "2031-05-06"}))   # 만료일이 없으면 덧붙인다
        self.assertEqual(r2["new"], "설명만 있음 만료:2031-05-06")

    def test_expiry_rows_can_be_deleted_in_place(self):
        self.work_branch("ISRIR-92")
        past = (datetime.now().date() - timedelta(days=3)).isoformat()
        self.write_rules([self.r("10.1.1.1/32", 80, "a 만료:" + past), self.r("10.1.1.2/32", 81)])
        row = self.J(self.c.get("/api/report/expiry?days=30"))["rows"][0]
        self.assertEqual((row["sg"], row["idx"]), ("l-sg-bbz-x-sg", 0))
        item = {"env_id": row["env_id"], "sg": row["sg"], "direction": row["direction"], "idx": row["idx"], "sig": row["sig"]}
        pv = self.J(self.c.post("/api/cleanup/apply", json={"items": [item], "dry_run": True}))
        self.assertEqual(pv["removed"], 1)
        self.J(self.c.post("/api/cleanup/apply", json={"items": [item]}))
        self.assertEqual(len(self.panel()["rules"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
