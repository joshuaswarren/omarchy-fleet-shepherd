"""stderr must never be parsed as the payload: remote hosts control that stream.

Split out from test_snapshot.py because these cases need literal shell snippets
whose quoting does not survive being embedded in another generator.
"""

import importlib.machinery
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "fleet-snapshot"


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

DECOY_FIRST = 'echo \'{"decoy":1} warning\' >&2; sleep 0.1; echo \'{"real":2}\''
SPLIT_BODY = 'printf \'{"a\'; echo chatter >&2; sleep 0.05; printf \'":1}\''
STDERR_FLOOD = (
    "i=0; while [ $i -lt 400 ]; do "
    "echo xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx >&2; "
    "i=$((i+1)); done; echo '{\"ok\":1}'"
)
RPC_ERROR_ON_STDERR = 'echo \'{"error":{"code":"server_not_running"}}\' >&2; exit 1'
STDOUT_FLOOD = "i=0; while [ $i -lt 5000 ]; do printf '%0100d' 1; i=$((i+1)); done"


class StreamIsolationTests(unittest.TestCase):
    def test_stderr_cannot_preempt_the_stdout_document(self):
        # a stderr line containing '{' arriving first must not become the parse
        # candidate ahead of the real stdout payload
        out = FS.run_argv(["sh", "-c", DECOY_FIRST], 5.0)
        self.assertEqual(FS.parse_json_prefixed(out), {"real": 2})
        self.assertNotIn("decoy", out)

    def test_stderr_cannot_split_the_stdout_document(self):
        # interleaved stderr chatter must not land inside the JSON body
        out = FS.run_argv(["sh", "-c", SPLIT_BODY], 5.0)
        self.assertEqual(FS.parse_json_prefixed(out), {"a": 1})
        self.assertNotIn("chatter", out)

    def test_stderr_flood_is_truncated_not_fatal(self):
        # stderr is diagnostic only: a flood must not fail a healthy probe
        out = FS.run_argv(["sh", "-c", STDERR_FLOOD], 10.0)
        self.assertEqual(FS.parse_json_prefixed(out), {"ok": 1})

    def test_nonzero_exit_still_sees_stderr_error_body(self):
        # herdr reports its JSON-RPC error body on stderr with a failing exit
        # code; the classifier must still receive it
        with self.assertRaises(FS._NonZeroExit) as ctx:
            FS.run_argv(["sh", "-c", RPC_ERROR_ON_STDERR], 5.0)
        self.assertIn("server_not_running", str(ctx.exception))

    def test_stdout_overflow_still_fails_closed(self):
        with self.assertRaises(FS.ProbeError):
            FS.run_argv(["sh", "-c", STDOUT_FLOOD], 10.0, max_bytes=4096)

    def test_stderr_has_its_own_smaller_cap(self):
        self.assertLessEqual(FS.STDERR_MAX_BYTES, FS.OUTPUT_MAX_BYTES)


if __name__ == "__main__":
    unittest.main()


class DocClaimTests(unittest.TestCase):
    """Docs-vs-code drift is a marketplace defect class; pin the claims."""

    @staticmethod
    def _docs():
        return (
            (ROOT / "docs" / "REQUIREMENTS.md").read_text()
            + (ROOT / "docs" / "DESIGN.md").read_text()
        )

    def test_documented_per_connector_bounds_match_code(self):
        docs = self._docs()
        self.assertIn(f"{FS.MAX_AGENTS} agents", docs)
        self.assertIn(f"{FS.MAX_WORKSPACES} workspaces", docs)

    def test_documented_cache_ttl_matches_shipped_qml(self):
        panel = (ROOT / "Panel.qml").read_text()
        bar = (ROOT / "BarWidget.qml").read_text()
        self.assertIn('"--cache-ttl", "120"', panel)
        self.assertIn('"--cache-ttl", "120"', bar)
        self.assertIn("120-second runtime cache", self._docs())

    def test_no_persistence_claim_is_honest(self):
        # the omp spool must live in an atomically created private 0700
        # per-invocation directory — no predictable shared path — and be
        # removed on every exit path
        self.assertIn("mktemp -d", FS.OMP_SPOOL_SNIPPET)
        self.assertNotIn("fleet-shepherd", FS.OMP_SPOOL_SNIPPET)
        self.assertIn("trap", FS.OMP_SPOOL_SNIPPET)
