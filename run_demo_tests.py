"""批量运行 5 条固定问题，观察单轮地图 Agent 的真实 MCP 调用过程。"""

from __future__ import annotations

import asyncio
import traceback

from dotenv import load_dotenv

from amap_mcp_demo import redact_sensitive_text, run_demo

TEST_QUESTIONS = [
    "北京大学东门附近有哪些咖啡店？",
    "从晋中学院到太原南站，推荐公共交通路线。",
    "杭州今天的天气怎么样？",
    "带我去机场。",
    "帮我查询今天比特币的价格。",
]


async def main() -> None:
    load_dotenv()
    for number, question in enumerate(TEST_QUESTIONS, start=1):
        print("\n" + "=" * 72)
        print(f"测试 {number}/5：{question}")
        print("=" * 72)
        try:
            await run_demo(question)
        except Exception as error:
            print(f"测试 {number} 失败。以下是已脱敏的详细错误信息：")
            detailed_traceback = "".join(traceback.format_exception(error))
            print(redact_sensitive_text(detailed_traceback))


if __name__ == "__main__":
    asyncio.run(main())
