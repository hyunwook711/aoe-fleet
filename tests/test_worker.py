"""Offline tests for the Fleet worker (stdlib unittest, no network)."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import worker  # noqa: E402

SESSIONS = [
    {"id": "a1", "tool": "claude", "title": "build", "status": "Running", "group_path": "proj", "branch": "main"},
    {"id": "b2", "tool": "codex", "title": "review", "status": "Waiting"},
    {"id": "c3", "tool": "claude", "title": "broken", "status": "Error"},
]


class HostSection(unittest.TestCase):
    def test_orders_error_waiting_running_and_counts(self) -> None:
        section = worker.host_section({"host": {"name": "m4-01", "url": "https://m4-01.example.ts.net"},
                                       "sessions": SESSIONS, "error": None})
        self.assertEqual([c["label"] for c in section["children"]], ["broken", "review", "build"])
        self.assertEqual(section["children"][0]["href"], "https://m4-01.example.ts.net/session/c3")
        self.assertEqual([b["text"] for b in section["badges"]], ["오류 1", "입력 대기 1", "실행 중 1"])

    def test_loopback_links_stay_on_dashboard(self) -> None:
        section = worker.host_section({"host": {"name": "local", "url": "http://127.0.0.1:8080"},
                                       "sessions": SESSIONS[:1], "error": None})
        self.assertEqual(section["children"][0]["href"], "/session/a1")

    def test_tunneled_host_links_to_its_public_dashboard(self) -> None:
        host = {"name": "m4", "url": "http://127.0.0.1:8789", "link_url": "https://aoe-m4.example.com/"}
        section = worker.host_section({"host": host, "sessions": SESSIONS[:1], "error": None})
        self.assertEqual(section["children"][0]["href"], "https://aoe-m4.example.com/session/a1")

    def test_unreachable_host(self) -> None:
        section = worker.host_section({"host": {"name": "win", "url": "http://10.0.0.9:8080"},
                                       "sessions": [], "error": "Connection refused"})
        self.assertEqual(section["value"], "연결 끊김")
        self.assertEqual(section["value_tone"], "danger")

    def test_row_cap(self) -> None:
        many = [{"id": str(i), "tool": "claude", "title": f"s{i}", "status": "Idle"} for i in range(40)]
        section = worker.host_section({"host": {"name": "big", "url": "http://127.0.0.1:8080"},
                                       "sessions": many, "error": None})
        self.assertEqual(len(section["children"]), worker.MAX_ROWS_PER_HOST + 1)


class Contract(unittest.TestCase):
    def test_unknown_method_returns_error(self) -> None:
        proc = subprocess.run(  # noqa: S603
            [sys.executable, str(ROOT / "worker.py")],
            input=json.dumps({"jsonrpc": "2.0", "id": 7, "method": "plugin.x.nope", "params": {}}) + "\n",
            capture_output=True, text=True, timeout=20, check=False,
        )
        replies = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
        self.assertTrue(any(r.get("id") == 7 and r.get("error", {}).get("code") == -32601 for r in replies))


if __name__ == "__main__":
    unittest.main()
