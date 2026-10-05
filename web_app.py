"""本机网页后端：接收浏览器问题，并调用现有地图 Agent。"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import socket
import traceback
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from dotenv import load_dotenv

from amap_mcp_demo import ask_agent, redact_sensitive_text

HOST = "127.0.0.1"
PORT = 8000
MAX_REQUEST_BYTES = 8192
MAX_HISTORY_MESSAGES = 40
MAX_CONTEXT_MESSAGES = 12
MAX_SESSIONS = 100
SESSION_COOKIE = "amap_chat_session"
WEB_PAGE = Path(__file__).with_name("index.html")
sessions: dict[str, list[dict[str, str]]] = {}


class ExclusiveHTTPServer(HTTPServer):
    """避免 Windows 将同一端口上的请求分配给多个旧服务器进程。"""

    allow_reuse_address = False

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def safe_traceback(error: Exception) -> str:
    """将完整错误留在终端，同时隐藏配置中的真实密钥。"""
    details = "".join(traceback.format_exception(error))
    for setting in ("AMAP_MAPS_API_KEY", "DEEPSEEK_API_KEY"):
        secret = os.getenv(setting, "")
        if secret:
            details = details.replace(secret, "***")
    return redact_sensitive_text(details)


class AppHandler(BaseHTTPRequestHandler):
    def send_json(self, status: int, data: dict, session_id: str | None = None) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        if session_id is not None:
            self.send_header("Set-Cookie", f"{SESSION_COOKIE}={session_id}; HttpOnly; SameSite=Lax; Path=/")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def get_session(self) -> tuple[str, list[dict[str, str]]]:
        """用浏览器 Cookie 找到本机内存中的对话；没有则创建。"""
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            pass
        token = cookie.get(SESSION_COOKIE)
        session_id = token.value if token else ""
        if session_id in sessions:
            return session_id, sessions[session_id]
        if len(sessions) >= MAX_SESSIONS:
            sessions.pop(next(iter(sessions)))
        session_id = secrets.token_urlsafe(32)
        sessions[session_id] = []
        return session_id, sessions[session_id]

    def do_GET(self) -> None:
        if self.path == "/api/health":
            self.send_json(200, {"status": "ok"})
            return
        if self.path == "/api/history":
            session_id, history = self.get_session()
            self.send_json(200, {"messages": history}, session_id)
            return
        if self.path != "/":
            self.send_error(404, "Not Found")
            return
        body = WEB_PAGE.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path == "/api/reset":
            session_id, history = self.get_session()
            history.clear()
            self.send_json(200, {"messages": []}, session_id)
            return
        if self.path != "/api/chat":
            self.send_json(404, {"error": "接口不存在。"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json(400, {"error": "请求长度无效。"})
            return
        if length <= 0 or length > MAX_REQUEST_BYTES:
            self.send_json(413, {"error": "问题过长或请求内容为空。"})
            return

        try:
            data = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json(400, {"error": "请求必须是有效的 JSON。"})
            return
        question = data.get("question") if isinstance(data, dict) else None
        if not isinstance(question, str) or not question.strip():
            self.send_json(400, {"error": "请输入问题。"})
            return

        try:
            session_id, history = self.get_session()
            result = asyncio.run(ask_agent(question.strip(), history=history[-MAX_CONTEXT_MESSAGES:]))
        except Exception as error:
            # 终端显示脱敏详情；浏览器不接收可能含密钥的异常对象。
            print("处理请求失败，详细错误如下（密钥已脱敏）：", flush=True)
            print(safe_traceback(error), flush=True)
            self.send_json(502, {"error": "地图或模型服务暂时不可用，请检查终端与本地配置后重试。"})
            return
        history.extend([
            {"role": "user", "content": question.strip()},
            {"role": "assistant", "content": result["answer"]},
        ])
        del history[:-MAX_HISTORY_MESSAGES]
        self.send_json(200, result, session_id)


if __name__ == "__main__":
    load_dotenv()
    # 单用户演示用顺序服务器，让 MCP 调用与命令行 demo 一样在主线程运行。
    try:
        server = ExclusiveHTTPServer((HOST, PORT), AppHandler)
    except OSError as error:
        raise SystemExit(
            f"无法启动网页：{HOST}:{PORT} 已被占用。请先在旧服务器终端按 Ctrl+C，再重试。"
        ) from error
    print(f"网页已启动：http://{HOST}:{PORT}（进程 ID：{os.getpid()}）")
    print("按 Ctrl+C 停止。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n网页已停止。")
    finally:
        server.server_close()
