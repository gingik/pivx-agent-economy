#!/usr/bin/env python3
"""mcp-bridge.py — stdio↔HTTP bridge for the kit's stdio-only MCP server.

Why: n8n runs in Docker and cannot spawn host stdio servers. This bridge exposes
the kit's `serve` MCP endpoint over HTTP so n8n (HTTP node) can call it.

RECOMMENDED ALTERNATIVE (simpler, no long-lived process): use n8n "Execute Command"
node calling `pivx-agent-kit <subcommand>` directly (JSON in/out). See
config/n8n-task-workflow.json. Use this bridge only if you need persistent tool
sessions.

Run:  PIVX_AGENT=hermes-main python3 mcp-bridge.py [port]   (default 127.0.0.1:8787)
"""
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

KIT = os.path.expanduser("~/.local/bin/pivx-agent-kit")


def call_kit(payload: dict) -> dict:
    """Spawn the kit in serve mode, send one JSON-RPC request, return the response."""
    env = dict(os.environ)
    env["PIVX_AGENT"] = os.environ.get("PIVX_AGENT", "hermes-main")
    proc = subprocess.Popen([KIT, "serve"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=env, text=True)
    out, err = proc.communicate(json.dumps(payload) + "\n", timeout=60)
    proc.wait(timeout=5)
    if proc.returncode != 0:
        return {"jsonrpc": "2.0", "error": {"code": -32000, "message": f"kit exited {proc.returncode}: {err[-500:]}"}}
    # Last line should be the JSON-RPC response
    for line in reversed(out.strip().splitlines()):
        try:
            return json.loads(line)
        except Exception:
            continue
    return {"jsonrpc": "2.0", "error": {"code": -32000, "message": "no JSON-RPC response"}}

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("content-length", "0"))
        try:
            req = json.loads(self.rfile.read(n)) if n else {}
        except Exception:
            req = {}
        resp = call_kit(req)
        body = json.dumps(resp).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a, **k):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    print(f"mcp-bridge on http://127.0.0.1:{port} (agent={os.environ.get('PIVX_AGENT','hermes-main')})")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
