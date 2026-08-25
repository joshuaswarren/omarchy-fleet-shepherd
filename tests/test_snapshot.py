#!/usr/bin/env python3
"""Targeted tests for bin/fleet-snapshot."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
import os
import stat
import tempfile
import time
import unittest
import threading
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "fleet-snapshot"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_mod():
    spec = importlib.util.spec_from_loader(
        "fleet_snapshot",
        importlib.machinery.SourceFileLoader("fleet_snapshot", str(SCRIPT)),
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FS = load_mod()


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def herdr_payload(n_agents: int, title: str = "t", cwd: str = "/tmp/demo") -> str:
    agents = []
    for i in range(n_agents):
        agents.append({
            "pane_id": f"w1:p{i}",
            "workspace_id": "w1",
            "agent": "omp",
            "agent_status": "idle",
            "cwd": cwd,
            "terminal_title_stripped": title,
            "agent_session": {"value": "SECRET_SESSION_PATH"},
        })
    body = {
        "id": 1,
        "result": {
            "snapshot": {
                "workspaces": [{"workspace_id": "w1", "label": "ws", "agent_status": "idle"}],
                "agents": agents,
                "panes": agents,
            }
        },
    }
    return json.dumps(body)


class Recorder:
    def __init__(self, mapping: dict[tuple[str, ...], str], hang: set[tuple[str, ...]] | None = None, huge: set[tuple[str, ...]] | None = None):
        self.mapping = mapping
        self.hang = hang or set()
        self.huge = huge or set()
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], timeout: float, max_bytes: int) -> str:
        self.calls.append(list(argv))
        key = tuple(argv)
        if key in self.hang:
            time.sleep(timeout + 0.2)
            raise FS.ProbeError("timeout")
        if key in self.huge:
            raise FS.ProbeError("output too large")
        if key not in self.mapping:
            raise FS.ProbeError("command failed")
        return self.mapping[key]


def write_exec(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


class ArgvTests(unittest.TestCase):
    def test_local_herdr_argv(self):
        self.assertEqual(FS.local_herdr_argv(), ["herdr", "api", "snapshot"])

    def test_local_omp_argv(self):
        self.assertEqual(FS.local_omp_argv(), ["sh", "-c", 't=$(mktemp) && omp stats --json > "$t" && cat "$t" && rm -f "$t"'])

    def test_ssh_herdr_argv(self):
        self.assertEqual(
            FS.ssh_herdr_argv("jw14m2"),
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=8",
                "-o",
                "StrictHostKeyChecking=yes",
                "--",
                "jw14m2",
                "herdr",
                "api",
                "snapshot",
            ],
        )

    def test_ssh_omp_argv(self):
        self.assertEqual(
            FS.ssh_omp_argv("jw14m2"),
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=8",
                "-o",
                "StrictHostKeyChecking=yes",
                "--",
                "jw14m2",
                't=$(mktemp) && omp stats --json > "$t" && cat "$t" && rm -f "$t"',
            ],
        )


class HostileTargetTests(unittest.TestCase):
    def test_reject_semicolon(self):
        with self.assertRaises(FS.ConfigError):
            FS.ssh_herdr_argv("host;rm")

    def test_reject_spaces(self):
        with self.assertRaises(FS.ConfigError):
            FS.validate_id("bad host", "ssh target")

    def test_reject_dollar_paren(self):
        with self.assertRaises(FS.ConfigError):
            FS.validate_id("host$(id)", "ssh target")

    def test_reject_backticks(self):
        with self.assertRaises(FS.ConfigError):
            FS.validate_id("host`id`", "ssh target")

    def test_reject_newline(self):
        with self.assertRaises(FS.ConfigError):
            FS.validate_id("host\n-oProxyCommand=x", "ssh target")

    def test_reject_leading_dash(self):
        with self.assertRaises(FS.ConfigError):
            FS.validate_id("-oProxyCommand=x", "ssh target")


class ConfigSafetyTests(unittest.TestCase):
    def test_missing_config_defaults_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "missing.json")
            self.assertEqual(FS.load_connectors(path), [FS.default_local()])

    def test_ok_config(self):
        got = FS.parse_connectors(fixture("connectors_ok.json").encode())
        self.assertEqual([c["id"] for c in got], ["local", "jw14"])
        self.assertEqual(got[1]["target"], "jw14m2")

    def test_unknown_field(self):
        raw = json.dumps({"connectors": [{"id": "a", "label": "a", "mode": "local", "extra": 1}]})
        with self.assertRaises(FS.ConfigError):
            FS.parse_connectors(raw.encode())

    def test_identity_file_rejected(self):
        raw = json.dumps({
            "connectors": [{
                "id": "a",
                "label": "a",
                "mode": "ssh",
                "target": "box",
                "identityFile": "/tmp/id_rsa",
            }]
        })
        with self.assertRaises(FS.ConfigError):
            FS.parse_connectors(raw.encode())

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "real.json"
            link = Path(tmp) / "link.json"
            real.write_text(fixture("connectors_ok.json"), encoding="utf-8")
            link.symlink_to(real)
            with self.assertRaises(FS.ConfigError) as ctx:
                FS.read_config_bytes(str(link))
            self.assertIn("symlink", str(ctx.exception))

    def test_fifo_rejected_fast(self):
        with tempfile.TemporaryDirectory() as tmp:
            fifo = Path(tmp) / "cfg.fifo"
            os.mkfifo(fifo)
            start = time.monotonic()
            with self.assertRaises(FS.ConfigError):
                FS.read_config_bytes(str(fifo))
            self.assertLess(time.monotonic() - start, 1.0)

    def test_oversize_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "big.json"
            path.write_bytes(b"{" + (b"x" * (FS.CONFIG_MAX_BYTES + 1)) + b"}")
            with self.assertRaises(FS.ConfigError) as ctx:
                FS.read_config_bytes(str(path))
            self.assertIn("large", str(ctx.exception))

    def test_prepends_local(self):
        raw = json.dumps({"connectors": [{"id": "box", "label": "box", "mode": "ssh", "target": "box"}]})
        got = FS.parse_connectors(raw.encode())
        self.assertEqual(got[0]["mode"], "local")
        self.assertEqual(got[1]["id"], "box")


class NormalizeTests(unittest.TestCase):
    def test_prefixed_omp(self):
        text = "Synced 37 new entries from 5 files\n\n" + fixture("omp_ok.json")
        parsed = FS.parse_json_prefixed(text)
        norm = FS.normalize_omp(parsed)
        self.assertEqual(norm["overall"]["totalRequests"], 10)
        self.assertEqual(len(norm["byModel"]), 2)

    def test_malformed_herdr(self):
        with self.assertRaises(FS.ProbeError):
            FS.normalize_herdr({"nope": True})

    def test_malformed_omp(self):
        with self.assertRaises(FS.ProbeError):
            FS.normalize_omp({"overall": []})

    def test_cwd_basename_and_title_cap(self):
        title = "T" * 400
        raw = json.loads(herdr_payload(1, title=title, cwd="/home/user/src/infra"))
        norm = FS.normalize_herdr(raw)
        agent = norm["agents"][0]
        self.assertEqual(agent["cwd"], "infra")
        self.assertEqual(len(agent["title"]), FS.MAX_TITLE)
        self.assertNotIn("paneId", agent)
        self.assertNotIn("pane_id", agent)

    def test_item_cap_64(self):
        raw = json.loads(herdr_payload(80))
        norm = FS.normalize_herdr(raw)
        self.assertEqual(len(norm["agents"]), 64)
        self.assertTrue(norm["truncated"])

    def test_status_enum(self):
        self.assertEqual(FS.normalize_status("WORKING"), "working")
        self.assertEqual(FS.normalize_status("blocked"), "blocked")


class SnapshotTests(unittest.TestCase):
    def _runner(self, **kwargs) -> Recorder:
        local = FS.default_local()
        mapping = {
            tuple(FS.local_herdr_argv()): fixture("herdr_ok.json"),
            tuple(FS.local_omp_argv()): "Synced 1 file\n\n" + fixture("omp_ok.json"),
            tuple(FS.ssh_herdr_argv("jw14m2")): fixture("herdr_ok.json"),
            tuple(FS.ssh_omp_argv("jw14m2")): fixture("omp_remote.json"),
        }
        mapping.update(kwargs.pop("mapping", {}))
        return Recorder(mapping, **kwargs)

    def test_local_success(self):
        snap = FS.collect_snapshot(
            [FS.default_local()],
            runner=self._runner(),
            now=lambda: "2026-08-23T00:00:00Z",
        )
        conn = snap["connectors"][0]
        self.assertEqual(snap["schemaVersion"], 1)
        self.assertEqual(conn["health"], "online")
        self.assertIsNone(conn["error"])
        self.assertEqual(len(conn["herdr"]["agents"]), 2)
        self.assertEqual(conn["omp"]["overall"]["totalRequests"], 10)
        self.assertEqual(conn["freshness"], "2026-08-23T00:00:00Z")
        self.assertIsInstance(conn["latencyMs"], int)

    def test_mixed_failure(self):
        runner = self._runner()
        runner.mapping.pop(tuple(FS.ssh_herdr_argv("jw14m2")))
        runner.mapping.pop(tuple(FS.ssh_omp_argv("jw14m2")))
        connectors = FS.parse_connectors(fixture("connectors_ok.json").encode())
        snap = FS.collect_snapshot(connectors, runner=runner, now=lambda: "t")
        by_id = {c["id"]: c for c in snap["connectors"]}
        self.assertEqual(by_id["local"]["health"], "online")
        self.assertEqual(by_id["jw14"]["health"], "offline")
        self.assertIsNone(by_id["jw14"]["herdr"])
        self.assertIsNone(by_id["jw14"]["omp"])
        self.assertTrue(by_id["jw14"]["error"])
        self.assertEqual(snap["totals"]["ok"], 1)
        self.assertEqual(snap["totals"]["totalRequests"], 10)

    def test_deterministic_aggregate_totals(self):
        connectors = FS.parse_connectors(fixture("connectors_ok.json").encode())
        snap = FS.collect_snapshot(connectors, runner=self._runner(), now=lambda: "t")
        self.assertEqual([c["id"] for c in snap["connectors"]], ["jw14", "local"])
        self.assertEqual(snap["totals"]["totalRequests"], 13)
        self.assertEqual(snap["totals"]["totalCost"], 1.75)
        self.assertEqual(snap["totals"]["agents"], 4)
        again = FS.collect_snapshot(list(reversed(connectors)), runner=self._runner(), now=lambda: "t")
        self.assertEqual(again["totals"], snap["totals"])
        self.assertEqual([c["id"] for c in again["connectors"]], ["jw14", "local"])

    def test_no_secrets(self):
        snap = FS.collect_snapshot([FS.default_local()], runner=self._runner(), now=lambda: "t")
        blob = json.dumps(snap)
        self.assertNotIn("SECRET_SESSION_PATH", blob)
        self.assertNotIn("pane_id", blob)
        self.assertNotIn("w1:p1", blob)
        self.assertNotIn("/home/user", blob)

    def test_one_host_timeout_keeps_others(self):
        runner = self._runner(hang={tuple(FS.ssh_herdr_argv("jw14m2")), tuple(FS.ssh_omp_argv("jw14m2"))})
        connectors = FS.parse_connectors(fixture("connectors_ok.json").encode())
        snap = FS.collect_snapshot(connectors, runner=runner, cmd_timeout=0.05, now=lambda: "t")
        by_id = {c["id"]: c for c in snap["connectors"]}
        self.assertEqual(by_id["local"]["health"], "online")
        self.assertIn(by_id["jw14"]["health"], {"offline", "degraded"})
        self.assertIn("timeout", by_id["jw14"]["error"] or "")

    def test_failed_probe_is_null_not_zero(self):
        runner = self._runner()
        runner.mapping.pop(tuple(FS.local_omp_argv()))
        snap = FS.collect_snapshot([FS.default_local()], runner=runner, now=lambda: "t")
        conn = snap["connectors"][0]
        self.assertEqual(conn["health"], "degraded")
        self.assertIsNone(conn["omp"])
        self.assertIsNotNone(conn["herdr"])
        self.assertEqual(len(conn["herdr"]["agents"]), 2)


class RunArgvTests(unittest.TestCase):
    def test_hung_child_killed(self):
        start = time.monotonic()
        with self.assertRaises(FS.ProbeError) as ctx:
            FS.run_argv(["sleep", "30"], timeout=0.2, max_bytes=1024)
        self.assertEqual(str(ctx.exception), "timeout")
        self.assertLess(time.monotonic() - start, 2.0)

    def test_oversized_output(self):
        code = "import sys; sys.stdout.write('x' * 400000)"
        with self.assertRaises(FS.ProbeError) as ctx:
            FS.run_argv([os.sys.executable, "-c", code], timeout=2, max_bytes=4096)
        self.assertEqual(str(ctx.exception), "output too large")

    def test_ten_k_agent_payload_rejected(self):
        huge = herdr_payload(10000)
        self.assertGreater(len(huge), FS.OUTPUT_MAX_BYTES)

        def runner(argv, timeout, max_bytes):
            if argv == FS.local_herdr_argv():
                if len(huge) > max_bytes:
                    raise FS.ProbeError("output too large")
                return huge
            return fixture("omp_ok.json")

        snap = FS.collect_snapshot([FS.default_local()], runner=runner, now=lambda: "t")
        conn = snap["connectors"][0]
        self.assertIsNone(conn["herdr"])
        self.assertIn("output too large", conn["error"])


class FakeSshTests(unittest.TestCase):
    def test_fake_ssh_records_safe_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            log = tmp_path / "ssh.jsonl"
            herdr_fix = tmp_path / "herdr.json"
            omp_fix = tmp_path / "omp.json"
            herdr_fix.write_text(fixture("herdr_ok.json"), encoding="utf-8")
            omp_fix.write_text(fixture("omp_ok.json"), encoding="utf-8")
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            write_exec(
                bin_dir / "herdr",
                "#!/usr/bin/env python3\nimport os,sys\nsys.stdout.write(open(os.environ['HERDR_FIXTURE']).read())\n",
            )
            write_exec(
                bin_dir / "omp",
                "#!/usr/bin/env python3\nimport os,sys\nsys.stdout.write(open(os.environ['OMP_FIXTURE']).read())\n",
            )
            write_exec(
                bin_dir / "ssh",
                "#!/usr/bin/env python3\n"
                "import json,os,sys\n"
                "open(os.environ['SSH_ARGV_LOG'],'a').write(json.dumps(sys.argv)+'\\n')\n"
                "args=sys.argv[1:]\n"
                "idx=args.index('--')\n"
                "remote=args[idx+2:]\n"
                "os.execvp(remote[0], remote)\n",
            )
            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:/usr/bin:/bin:{os.path.dirname(os.sys.executable)}"
            env["HERDR_FIXTURE"] = str(herdr_fix)
            env["OMP_FIXTURE"] = str(omp_fix)
            env["SSH_ARGV_LOG"] = str(log)
            old = os.environ.copy()
            os.environ.clear()
            os.environ.update(env)
            try:
                argv = FS.ssh_herdr_argv("jw14m2")
                out = FS.run_argv(argv, timeout=2, max_bytes=FS.OUTPUT_MAX_BYTES)
                self.assertIn("snapshot", out)
            finally:
                os.environ.clear()
                os.environ.update(old)
            recorded = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertTrue(recorded)
            joined = " ".join(recorded[0])
            self.assertIn("BatchMode=yes", joined)
            self.assertIn("ConnectTimeout=8", joined)
            self.assertIn("StrictHostKeyChecking=yes", joined)
            self.assertNotIn("accept-new", joined)
            self.assertNotIn("UserKnownHostsFile", joined)
            self.assertNotIn("/dev/null", joined)
            self.assertNotIn("ProxyCommand", joined)
            self.assertNotIn("IdentityFile", joined)
            self.assertNotIn("StrictHostKeyChecking=no", joined)


class SourceGuardTests(unittest.TestCase):
    def test_source_has_no_mutation_or_shell(self):
        src = SCRIPT.read_text(encoding="utf-8")
        lowered = src.lower()
        self.assertNotIn("shell=true", lowered)
        self.assertNotIn("shell = true", lowered)
        self.assertNotIn("communicate(", src)
        self.assertNotIn("sudo", lowered)
        self.assertNotIn("agent focus", lowered)
        self.assertNotIn("herdr agent", lowered)
        self.assertNotIn("hyprctl", lowered)
        self.assertIn("O_NOFOLLOW", src)
        self.assertIn("O_NONBLOCK", src)
        self.assertIn("BatchMode=yes", src)
        self.assertIn("StrictHostKeyChecking=yes", src)

    def test_cli_config_error_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text('{"connectors":[{"id":"x;y","label":"x","mode":"ssh","target":"x;y"}]}', encoding="utf-8")
            buf = io.StringIO()
            err = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(err):
                code = FS.main(["--connectors", str(path)])
            self.assertEqual(code, 2)
            self.assertEqual(buf.getvalue(), "")
            self.assertTrue(err.getvalue())


if __name__ == "__main__":
    unittest.main()

class ShippedExampleTests(unittest.TestCase):
    def test_shipped_connector_example_loads(self):
        example = Path(__file__).resolve().parents[1] / "connectors.example.json"
        got = FS.load_connectors(str(example))
        self.assertEqual([c["id"] for c in got], ["local", "connector-a"])

    def test_unsupported_schema_rejected(self):
        raw = json.dumps({"schemaVersion": 2, "connectors": []}).encode()
        with self.assertRaises(FS.ConfigError):
            FS.parse_connectors(raw)


class CacheTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_xdg = os.environ.get("XDG_RUNTIME_DIR")
        os.environ["XDG_RUNTIME_DIR"] = self._tmp.name

    def tearDown(self):
        if self._old_xdg is None:
            os.environ.pop("XDG_RUNTIME_DIR", None)
        else:
            os.environ["XDG_RUNTIME_DIR"] = self._old_xdg
        self._tmp.cleanup()

    def _runner(self) -> Recorder:
        return Recorder({
            tuple(FS.local_herdr_argv()): fixture("herdr_ok.json"),
            tuple(FS.local_omp_argv()): fixture("omp_ok.json"),
        })

    def _collect(self, runner: Recorder, now: str = "t"):
        return lambda: FS.collect_snapshot([FS.default_local()], runner=runner, now=lambda: now)

    def _cache_path(self) -> Path:
        return Path(os.environ["XDG_RUNTIME_DIR"]) / FS.CACHE_DIRNAME / FS.CACHE_FILENAME

    def _cache_dir(self) -> Path:
        return Path(os.environ["XDG_RUNTIME_DIR"]) / FS.CACHE_DIRNAME

    def test_cache_hit_avoids_runner(self):
        rec = self._runner()
        first = FS.cached_snapshot(self._collect(rec), 15)
        n = len(rec.calls)
        self.assertGreater(n, 0)
        second = FS.cached_snapshot(self._collect(rec), 15)
        self.assertEqual(len(rec.calls), n)
        self.assertEqual(second["schemaVersion"], 1)
        self.assertEqual(second["connectors"][0]["id"], first["connectors"][0]["id"])
        blob = json.dumps(second)
        self.assertNotIn("SECRET_SESSION_PATH", blob)

    def test_stale_cache_collects(self):
        rec = self._runner()
        FS.cached_snapshot(self._collect(rec), 15)
        n = len(rec.calls)
        cache = self._cache_path()
        past = time.time() - 20
        os.utime(cache, (past, past))
        FS.cached_snapshot(self._collect(rec), 15)
        self.assertGreater(len(rec.calls), n)

    def test_simultaneous_dedup(self):
        rec = self._runner()
        counts = {"n": 0}
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def collect():
            counts["n"] += 1
            time.sleep(0.2)
            return FS.collect_snapshot([FS.default_local()], runner=rec, now=lambda: "t")

        def worker():
            try:
                barrier.wait()
                FS.cached_snapshot(collect, 15)
            except BaseException as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(counts["n"], 1)

    def test_corrupt_cache_replaced(self):
        rec = self._runner()
        FS.cached_snapshot(self._collect(rec), 15)
        n = len(rec.calls)
        self._cache_path().write_text("{not-json", encoding="utf-8")
        snap = FS.cached_snapshot(self._collect(rec), 15)
        self.assertGreater(len(rec.calls), n)
        self.assertEqual(snap["schemaVersion"], 1)
        self.assertIsInstance(snap["connectors"], list)

    def test_symlink_file_rejected(self):
        rec = self._runner()
        FS.cached_snapshot(self._collect(rec), 15)
        cache = self._cache_path()
        target = Path(self._tmp.name) / "secret.json"
        target.write_text(json.dumps({"schemaVersion": 1, "connectors": []}), encoding="utf-8")
        cache.unlink()
        cache.symlink_to(target)
        n = len(rec.calls)
        snap = FS.cached_snapshot(self._collect(rec), 15)
        self.assertGreater(len(rec.calls), n)
        self.assertTrue(cache.is_file())
        self.assertFalse(cache.is_symlink())
        self.assertTrue(snap["connectors"])

    def test_symlink_dir_rejected(self):
        elsewhere = Path(self._tmp.name) / "elsewhere"
        elsewhere.mkdir()
        link = Path(self._tmp.name) / FS.CACHE_DIRNAME
        link.symlink_to(elsewhere)
        rec = self._runner()
        snap = FS.cached_snapshot(self._collect(rec), 15)
        self.assertEqual(snap["schemaVersion"], 1)
        self.assertEqual(list(elsewhere.iterdir()), [])
        self.assertTrue(link.is_symlink())

    def test_fifo_rejected(self):
        rec = self._runner()
        FS.cached_snapshot(self._collect(rec), 15)
        cache = self._cache_path()
        cache.unlink()
        os.mkfifo(cache)
        n = len(rec.calls)
        start = time.monotonic()
        snap = FS.cached_snapshot(self._collect(rec), 15)
        self.assertLess(time.monotonic() - start, 1.0)
        self.assertGreater(len(rec.calls), n)
        self.assertTrue(cache.is_file())
        self.assertFalse(stat.S_ISFIFO(cache.stat().st_mode))
        self.assertEqual(snap["schemaVersion"], 1)

    def test_oversize_rejected(self):
        rec = self._runner()
        FS.cached_snapshot(self._collect(rec), 15)
        n = len(rec.calls)
        self._cache_path().write_bytes(b"{" + (b"x" * (FS.FINAL_MAX_BYTES + 1)) + b"}")
        snap = FS.cached_snapshot(self._collect(rec), 15)
        self.assertGreater(len(rec.calls), n)
        self.assertEqual(snap["schemaVersion"], 1)
        self.assertLessEqual(self._cache_path().stat().st_size, FS.FINAL_MAX_BYTES)

    def test_permissions(self):
        rec = self._runner()
        FS.cached_snapshot(self._collect(rec), 15)
        cache_dir = self._cache_dir()
        cache = self._cache_path()
        lock = cache_dir / FS.CACHE_LOCKNAME
        self.assertEqual(cache_dir.stat().st_mode & 0o777, 0o700)
        self.assertEqual(cache.stat().st_mode & 0o777, 0o600)
        self.assertEqual(lock.stat().st_mode & 0o777, 0o600)

    def test_atomic_update(self):
        rec = self._runner()
        first = FS.cached_snapshot(self._collect(rec, now="one"), 15)
        self.assertEqual(first["generatedAt"], "one")
        second = FS.cached_snapshot(self._collect(rec, now="two"), 15, refresh=True)
        self.assertEqual(second["generatedAt"], "two")
        raw = json.loads(self._cache_path().read_text(encoding="utf-8"))
        self.assertEqual(raw["generatedAt"], "two")
        self.assertEqual(raw["schemaVersion"], 1)
        self.assertIsInstance(raw["connectors"], list)
        leftovers = list(self._cache_dir().glob(".snapshot.json.tmp*"))
        self.assertEqual(leftovers, [])

    def test_refresh_bypasses_freshness(self):
        rec = self._runner()
        FS.cached_snapshot(self._collect(rec), 15)
        n = len(rec.calls)
        FS.cached_snapshot(self._collect(rec), 15, refresh=True)
        self.assertGreater(len(rec.calls), n)
        after = len(rec.calls)
        FS.cached_snapshot(self._collect(rec), 15)
        self.assertEqual(len(rec.calls), after)

    def test_missing_xdg_disables_cache(self):
        rec = self._runner()
        os.environ.pop("XDG_RUNTIME_DIR", None)
        with tempfile.TemporaryDirectory() as home:
            old_home = os.environ.get("HOME")
            os.environ["HOME"] = home
            try:
                snap = FS.cached_snapshot(self._collect(rec), 15)
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home
        self.assertEqual(snap["schemaVersion"], 1)
        self.assertFalse((Path(home) / FS.CACHE_DIRNAME).exists())
        self.assertFalse((Path(home) / ".cache" / FS.CACHE_DIRNAME).exists())
        self.assertFalse((ROOT / FS.CACHE_DIRNAME).exists())
        self.assertGreater(len(rec.calls), 0)

    def test_parser_cache_flags(self):
        args = FS.build_parser().parse_args(["--cache-ttl", "15", "--refresh"])
        self.assertEqual(args.cache_ttl, 15)
        self.assertTrue(args.refresh)

    def test_cache_key_mismatch_forces_new_collection(self):
        first_calls = []
        second_calls = []

        def one():
            first_calls.append(1)
            return {"schemaVersion": 1, "generatedAt": "one", "connectors": [{"id": "a"}]}

        def two():
            second_calls.append(1)
            return {"schemaVersion": 1, "generatedAt": "two", "connectors": [{"id": "b"}]}

        a = FS.cached_snapshot(one, 15, cache_key="inventory-a")
        b = FS.cached_snapshot(two, 15, cache_key="inventory-b")
        self.assertEqual(a["connectors"][0]["id"], "a")
        self.assertEqual(b["connectors"][0]["id"], "b")
        self.assertEqual(len(first_calls), 1)
        self.assertEqual(len(second_calls), 1)

    def test_herdr_server_not_running_is_idle_not_error(self):
        import json as _json
        payload = _json.dumps({"id": "cli:api:snapshot", "error": {"code": "server_not_running", "message": "no herdr server"}}).encode()
        omp_ok = _json.dumps({"overall": {"totalRequests": 1, "totalCost": 0.1}, "byModel": []})
        def runner(argv, timeout, cap):
            return payload.decode() if argv[-3:] == ["herdr", "api", "snapshot"] else omp_ok
        cfg = FS.parse_connectors(b'{"connectors":[{"id":"h","label":"h","mode":"ssh","target":"h"}]}')
        got = FS.collect_snapshot(cfg, runner=lambda argv, timeout, cap: runner(argv, timeout, cap), now=lambda: "t")
        conn = got["connectors"][0]
        self.assertEqual(conn["health"], "online")
        self.assertIsNone(conn["error"])
        self.assertEqual(conn["herdr"]["idle"], True)
        self.assertEqual(conn["herdr"]["agents"], [])

    def test_nonzero_exit_with_rpc_error_body_classified(self):
        import json as _json
        body = _json.dumps({"error": {"code": "server_not_running", "message": "no server"}})
        exc = FS.classify_probe_failure("herdr", body)
        self.assertIsInstance(exc, FS.HerdrIdle)
        exc2 = FS.classify_probe_failure("herdr", "some random failure text")
        self.assertIsInstance(exc2, FS.ProbeError)

    def test_run_argv_raises_nonzero_with_output(self):
        import io, os as _os
        r, w = _os.pipe()
        _os.close(w)
        def fake_popen(argv, **kw):
            class P:
                pid = 123
                stdout = io.FileIO(r, closefd=False)
                stderr = io.FileIO(r, closefd=False)
                def poll(self):
                    return 3
                def wait(self, timeout=None):
                    return 3
                def kill(self):
                    pass
            return P()
        import types
        real_popen = FS.subprocess.Popen
        FS.subprocess.Popen = fake_popen
        try:
            try:
                FS.run_argv(["false"], 1.0)
                self.fail("expected _NonZeroExit")
            except FS._NonZeroExit as exc:
                self.assertEqual(str(exc), "")
        finally:
            FS.subprocess.Popen = real_popen


class FocusMatcherTests(unittest.TestCase):
    """Exercises bin/fleet-focus matches() directly, not a copy of its logic."""

    @staticmethod
    def _matches():
        script = ROOT / "bin" / "fleet-focus"
        spec = importlib.util.spec_from_loader(
            "fleet_focus",
            importlib.machinery.SourceFileLoader("fleet_focus", str(script)),
        )
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.matches

    def test_herdr_client_subprocess_is_not_the_local_connector(self):
        # a remote session spawns `herdr client`, which carries no --remote flag;
        # treating it as local sent every local click to the wrong terminal
        m = self._matches()
        self.assertFalse(m("/home/j/.local/bin/herdr client", "local"))
        self.assertFalse(m("/home/j/.local/bin/herdr server", "local"))

    def test_bare_herdr_is_the_local_connector(self):
        self.assertTrue(self._matches()("herdr", "local"))

    def test_remote_target_matches_exactly(self):
        m = self._matches()
        self.assertTrue(m("herdr --remote builds-main", "builds-main"))
        self.assertTrue(m("herdr --remote=media-main", "media-main"))
        self.assertFalse(m("herdr --remote home-main", "home-ma"))
        self.assertFalse(m("herdr --remote builds-main", "local"))
