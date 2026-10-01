"""Fleet worker for Agent of Empires.

Speaks JSON-RPC 2.0 over newline-delimited JSON on stdio. The host sends its
requests/notifications on stdin; this worker sends host RPCs (config.get,
ui.state.set) on stdout and reads their responses back from stdin.
"""

from __future__ import annotations

import itertools
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

RPC_TIMEOUT = 10.0
HTTP_TIMEOUT = 5.0
MAX_ROWS_PER_HOST = 25
LOCAL_TOKEN = Path.home() / ".agent-of-empires" / "serve.token"

STATUS_TONE = {
    "Running": "info",
    "Waiting": "warn",
    "Error": "danger",
    "Idle": "neutral",
    "Stopped": "neutral",
}
STATUS_KO = {
    "Running": "실행 중",
    "Waiting": "입력 대기",
    "Error": "오류",
    "Idle": "유휴",
    "Stopped": "정지",
    "Starting": "시작 중",
}

_ids = itertools.count(1)
_pending: dict[int, dict[str, Any]] = {}
_pending_lock = threading.Lock()
_out_lock = threading.Lock()
_wake = threading.Event()


def log(msg: str) -> None:
    sys.stderr.write(f"[fleet] {msg}\n")
    sys.stderr.flush()


def send(obj: dict[str, Any]) -> None:
    with _out_lock:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def call(method: str, params: dict[str, Any]) -> Any:
    msg_id = next(_ids)
    slot: dict[str, Any] = {"event": threading.Event()}
    with _pending_lock:
        _pending[msg_id] = slot
    send({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params})
    if not slot["event"].wait(RPC_TIMEOUT):
        with _pending_lock:
            _pending.pop(msg_id, None)
        raise TimeoutError(f"{method} timed out")
    if "error" in slot:
        raise RuntimeError(f"{method}: {slot['error']}")
    return slot.get("result")


def reader() -> None:
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(msg, dict):
            continue
        if "method" not in msg:  # response to one of our host RPCs
            with _pending_lock:
                slot = _pending.pop(msg.get("id"), None)
            if slot is not None:
                if "error" in msg:
                    slot["error"] = msg["error"]
                else:
                    slot["result"] = msg.get("result")
                slot["event"].set()
            continue
        method = str(msg.get("method", ""))
        tail = method.rsplit(".", 1)[-1]
        if tail in {"refresh", "changed"}:  # command, pane action, settings change
            _wake.set()
        if msg.get("id") is not None:
            if tail in {"refresh", "status"}:
                send({"jsonrpc": "2.0", "id": msg["id"], "result": {"ok": True}})
            else:
                send({"jsonrpc": "2.0", "id": msg["id"],
                      "error": {"code": -32601, "message": f"unknown method {method}"}})
    os._exit(0)  # host closed stdin


def setting(key: str, default: Any) -> Any:
    try:
        value = (call("config.get", {"key": key}) or {}).get("value")
    except Exception as exc:  # noqa: BLE001
        log(f"config.get {key}: {exc}")
        return default
    return default if value is None else value


def http_json(url: str, token: str | None = None) -> Any:
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def is_loopback(url: str) -> bool:
    return (urlparse(url).hostname or "") in {"127.0.0.1", "localhost", "::1"}


def host_token(host: dict[str, Any]) -> str | None:
    path = (host.get("token_file") or "").strip()
    if path:
        return Path(path).expanduser().read_text().strip()
    if is_loopback(host["url"]) and LOCAL_TOKEN.exists():
        return LOCAL_TOKEN.read_text().strip()
    return None


def fetch_host(host: dict[str, Any]) -> dict[str, Any]:
    base = host["url"].rstrip("/")
    try:
        data = http_json(f"{base}/api/sessions?state=live", host_token(host))
        return {"host": host, "sessions": data.get("sessions", []), "error": None}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", None) or exc
        return {"host": host, "sessions": [], "error": str(reason)}


def host_section(result: dict[str, Any]) -> dict[str, Any]:
    host = result["host"]
    base = host["url"].rstrip("/")
    if result["error"]:
        return {"kind": "section", "title": host["name"], "boxed": True, "value": "연결 끊김",
                "value_tone": "danger",
                "children": [{"kind": "note", "tone": "danger", "text": result["error"]}]}
    sessions = result["sessions"]
    counts: dict[str, int] = {}
    for s in sessions:
        counts[s.get("status", "?")] = counts.get(s.get("status", "?"), 0) + 1
    order = {"Error": 0, "Waiting": 1, "Running": 2}
    sessions = sorted(sessions, key=lambda s: (order.get(s.get("status"), 3), s.get("title") or ""))
    children = []
    for s in sessions[:MAX_ROWS_PER_HOST]:
        status = s.get("status", "?")
        children.append({
            "kind": "row",
            "prefix": s.get("tool") or "?",
            "label": s.get("title") or s.get("id"),
            "sublabel": " · ".join(filter(None, [s.get("group_path"), s.get("branch")])),
            "value": STATUS_KO.get(status, status),
            "value_tone": STATUS_TONE.get(status, "neutral"),
            "href": f"{base}/session/{s['id']}" if not is_loopback(base) else f"/session/{s['id']}",
            "mono": False,
        })
    if len(sessions) > MAX_ROWS_PER_HOST:
        children.append({"kind": "note", "text": f"외 {len(sessions) - MAX_ROWS_PER_HOST}개"})
    if not sessions:
        children.append({"kind": "note", "text": "실행 중인 세션 없음"})
    badges = [{"text": f"{STATUS_KO.get(k, k)} {v}", "tone": STATUS_TONE.get(k, "neutral")}
              for k, v in sorted(counts.items(), key=lambda kv: order.get(kv[0], 3))]
    return {"kind": "section", "title": host["name"], "boxed": True, "badges": badges,
            "collapsible": True, "scroll": True, "children": children}


def refresh(pool: ThreadPoolExecutor) -> int:
    hosts = [h for h in setting("hosts", []) if isinstance(h, dict) and h.get("name") and h.get("url")]
    if not hosts:
        hosts = [{"name": "이 Mac", "url": "http://127.0.0.1:8080"}]
    results = list(pool.map(fetch_host, hosts))
    online = sum(1 for r in results if not r["error"])
    waiting = sum(1 for r in results for s in r["sessions"] if s.get("status") == "Waiting")
    errors = sum(1 for r in results for s in r["sessions"] if s.get("status") == "Error")

    blocks: list[dict[str, Any]] = []
    if waiting or errors or online < len(results):
        detail = f"입력 대기 {waiting}개 · 오류 {errors}개 · 연결된 장비 {online}/{len(results)}"
        blocks.append({"kind": "callout", "tone": "danger" if errors or online < len(results) else "warn",
                       "title": "확인이 필요한 세션이 있습니다", "detail": detail})
    blocks.extend(host_section(r) for r in results)
    blocks.append({"kind": "action", "label": "지금 새로고침", "method": "refresh", "icon": "refresh-cw"})

    now = datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S")
    call("ui.state.set", {"slot": "home-pane", "id": "fleet", "payload": {
        "title": "장비 · 세션", "icon": "server", "blocks": blocks,
        "footer": {"text": f"갱신 {now}", "value": f"장비 {online}/{len(results)}",
                   "tone": "success" if online == len(results) else "danger", "icon": "refresh-cw"},
    }})
    return max(5, int(setting("refresh_secs", 20)))


def main() -> None:
    threading.Thread(target=reader, daemon=True).start()
    with ThreadPoolExecutor(max_workers=8) as pool:
        while True:
            try:
                delay = refresh(pool)
            except Exception as exc:  # noqa: BLE001 - keep the worker alive
                log(f"refresh failed: {exc}")
                delay = 30
            _wake.wait(delay)
            _wake.clear()


if __name__ == "__main__":
    main()
