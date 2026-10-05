"""验证网页会话的追问、隔离与清空行为，不调用外部服务。"""

import http.client
import json
import threading
import unittest
from http.server import HTTPServer
from unittest.mock import AsyncMock, patch

from web_app import AppHandler, sessions


class WebConversationTests(unittest.TestCase):
    def setUp(self) -> None:
        sessions.clear()
        self.server = HTTPServer(("127.0.0.1", 0), AppHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.cookie = ""

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        sessions.clear()

    def request(self, method: str, path: str, data: dict | None = None, use_cookie: bool = True) -> tuple[int, dict]:
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        headers = {"Content-Type": "application/json"}
        if use_cookie and self.cookie:
            headers["Cookie"] = self.cookie
        body = json.dumps(data).encode("utf-8") if data is not None else None
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        cookie = response.getheader("Set-Cookie")
        if use_cookie and cookie:
            self.cookie = cookie.split(";", 1)[0]
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    def test_follow_up_isolated_and_reset(self) -> None:
        agent = AsyncMock(side_effect=[
            {"answer": "北京大学附近有几家咖啡店。", "events": []},
            {"answer": "其中第一家在东门附近。", "events": []},
            {"answer": "新的回答", "events": []},
        ])
        with patch("web_app.ask_agent", agent):
            self.assertEqual(self.request("GET", "/api/history"), (200, {"messages": []}))
            self.assertEqual(self.request("POST", "/api/chat", {"question": "北京大学附近有咖啡店吗？"})[0], 200)
            self.assertEqual(self.request("POST", "/api/chat", {"question": "第一家在哪里？"})[0], 200)
            self.assertEqual(agent.await_args_list[0].kwargs["history"], [])
            self.assertEqual(agent.await_args_list[1].kwargs["history"], [
                {"role": "user", "content": "北京大学附近有咖啡店吗？"},
                {"role": "assistant", "content": "北京大学附近有几家咖啡店。"},
            ])
            self.assertEqual(len(self.request("GET", "/api/history")[1]["messages"]), 4)
            self.assertEqual(self.request("GET", "/api/history", use_cookie=False), (200, {"messages": []}))
            self.assertEqual(self.request("POST", "/api/reset"), (200, {"messages": []}))
            self.assertEqual(self.request("POST", "/api/chat", {"question": "重新开始"})[0], 200)
            self.assertEqual(agent.await_args_list[2].kwargs["history"], [])

    def test_failed_request_is_not_saved(self) -> None:
        with patch("web_app.ask_agent", AsyncMock(side_effect=RuntimeError("服务故障"))):
            self.request("GET", "/api/history")
            status, _ = self.request("POST", "/api/chat", {"question": "天气怎么样？"})
            self.assertEqual(status, 502)
            self.assertEqual(self.request("GET", "/api/history"), (200, {"messages": []}))


if __name__ == "__main__":
    unittest.main()
