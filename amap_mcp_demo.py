"""地图助手演示：DeepSeek 决定调用哪个高德 MCP 工具，再由本程序执行调用。

运行前：
1. 复制 .env.example 为 .env。
2. 在 .env 中填写 AMAP_MAPS_API_KEY 和 DEEPSEEK_API_KEY。
3. 安装依赖：python -m pip install -r requirements.txt。
4. 运行：python amap_mcp_demo.py。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import traceback
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dotenv import load_dotenv
from mcp import Client
from openai import OpenAI

MAX_TOOL_ROUNDS = 6
SYSTEM_PROMPT = """你是一个地图助手。参考此前对话理解用户的追问，但此前回答不能代替当前地图事实。
遇到地点搜索、周边搜索、路线、天气或其他需要当前地图事实的问题时，必须调用提供的工具，不能根据记忆编造结果。
只能调用提供的工具；若用户信息不足，直接提出一个简短的澄清问题。收到工具结果后，只依据工具结果回答，并明确说明结果来自地图查询。"""


def redact_sensitive_text(text: str) -> str:
    """对异常追踪文本中的常见凭据形式脱敏，便于安全地分享报错。"""
    text = re.sub(
        r"([?&](?:key|api_key|api-key|token|access_token)=)[^&\s'\"]+",
        r"\1***",
        text,
        flags=re.IGNORECASE,
    )
    return re.sub(r"(Bearer\s+)[^\s'\"]+", r"\1***", text, flags=re.IGNORECASE)


def require_setting(name: str) -> str:
    """读取必填环境变量，缺失时给出不包含敏感值的错误。"""
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"缺少 {name}。请复制 .env.example 为 .env 后在其中填写。")
    return value


def build_amap_mcp_url(endpoint: str, api_key: str) -> str:
    """将 Key 只用于实际连接地址，避免在演示日志中打印它。"""
    parts = urlsplit(endpoint)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["key"] = api_key
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def to_jsonable(value: Any) -> Any:
    """把 SDK 返回的 Pydantic 对象安全转换为可传给模型的 JSON 数据。"""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return value


def mcp_result_for_model(result: Any) -> str:
    """将 MCP 工具结果包装为工具消息内容。"""
    payload = {
        "is_error": bool(getattr(result, "is_error", False)),
        "structured_content": to_jsonable(getattr(result, "structured_content", None)),
        "content": to_jsonable(getattr(result, "content", [])),
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


def tools_for_model(mcp_tools: list[Any]) -> list[dict[str, Any]]:
    """把 MCP 的工具描述转换为 DeepSeek Function Calling 所需的格式。"""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or f"调用地图工具 {tool.name}",
                "parameters": to_jsonable(tool.input_schema),
            },
        }
        for tool in mcp_tools
    ]


async def list_all_mcp_tools(mcp_client: Client) -> list[Any]:
    """读取所有 MCP 工具页，兼容没有 list_all_tools() 的 SDK 版本。"""
    tools: list[Any] = []
    cursor: str | None = None
    while True:
        page = await mcp_client.list_tools(cursor=cursor)
        tools.extend(page.tools)
        cursor = page.next_cursor
        if cursor is None:
            return tools


async def ask_agent(
    question: str,
    on_event: Callable[[dict[str, str]], None] | None = None,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """完成一次提问，可带入先前问答，返回回答与过程记录。"""
    if not question.strip():
        raise ValueError("问题不能为空。")

    events: list[dict[str, str]] = []

    def emit(stage: str, message: str) -> None:
        event = {"stage": stage, "message": redact_sensitive_text(message)}
        events.append(event)
        if on_event is not None:
            on_event(event)

    amap_url = build_amap_mcp_url(
        require_setting("AMAP_MCP_ENDPOINT"),
        require_setting("AMAP_MAPS_API_KEY"),
    )
    deepseek = OpenAI(
        api_key=require_setting("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip(),
    )
    model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()

    emit("连接 MCP", "正在连接高德地图 MCP Server。")
    async with Client(amap_url) as mcp_client:
        mcp_tools = await list_all_mcp_tools(mcp_client)
        if not mcp_tools:
            raise RuntimeError("高德 MCP 未返回任何工具，无法继续演示。")

        allowed_tools = {tool.name for tool in mcp_tools}
        model_tools = tools_for_model(mcp_tools)
        emit("发现工具", f"高德 MCP 提供 {len(mcp_tools)} 个工具：{', '.join(tool.name for tool in mcp_tools)}")

        messages: list[Any] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *(history or []),
            {"role": "user", "content": question},
        ]

        emit("模型决策", "已将 MCP 工具描述交给 DeepSeek，由模型选择是否调用工具。")
        response = deepseek.chat.completions.create(
            model=model_name,
            messages=messages,
            tools=model_tools,
            tool_choice="auto",
        )

        for round_number in range(1, MAX_TOOL_ROUNDS + 1):
            assistant_message = response.choices[0].message
            tool_calls = assistant_message.tool_calls or []

            if not tool_calls:
                answer = assistant_message.content or "模型未返回文本回答。"
                emit("最终回答", answer)
                return {"answer": answer, "events": events}

            emit("模型决策", f"第 {round_number} 轮：模型请求调用 {len(tool_calls)} 个工具。")
            messages.append(assistant_message)

            for tool_call in tool_calls:
                tool_name = tool_call.function.name
                raw_arguments = tool_call.function.arguments
                try:
                    arguments = json.loads(raw_arguments or "{}")
                except json.JSONDecodeError:
                    arguments = None

                emit("工具调用", f"工具：{tool_name}\n参数：{raw_arguments}")

                if tool_name not in allowed_tools:
                    tool_content = json.dumps(
                        {"is_error": True, "message": "模型请求了未声明的 MCP 工具。"},
                        ensure_ascii=False,
                    )
                elif not isinstance(arguments, dict):
                    tool_content = json.dumps(
                        {"is_error": True, "message": "模型生成的工具参数不是有效 JSON 对象。"},
                        ensure_ascii=False,
                    )
                else:
                    try:
                        result = await mcp_client.call_tool(tool_name, arguments)
                        tool_content = mcp_result_for_model(result)
                    except Exception as error:  # 演示中将服务失败交给模型解释。
                        tool_content = json.dumps(
                            {"is_error": True, "message": f"MCP 调用失败：{type(error).__name__}"},
                            ensure_ascii=False,
                        )

                emit("工具结果", tool_content[:800] + ("…" if len(tool_content) > 800 else ""))
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_content,
                    }
                )

            response = deepseek.chat.completions.create(
                model=model_name,
                messages=messages,
                tools=model_tools,
                tool_choice="auto",
            )

        final_message = response.choices[0].message
        if final_message.tool_calls:
            answer = "本次问题需要更多工具调用；演示已达到两轮上限，请缩小问题范围后重试。"
            emit("调用上限", answer)
        else:
            answer = final_message.content or "模型未返回文本回答。"
            emit("最终回答", answer)
        return {"answer": answer, "events": events}


async def run_demo(question: str) -> None:
    """保持原有命令行入口：将过程与回答打印到终端。"""
    def print_event(event: dict[str, str]) -> None:
        print(f"\n[{event['stage']}] {event['message']}")

    await ask_agent(question, on_event=print_event)


def main() -> None:
    load_dotenv()
    question = input("请输入一个地图问题（例如：北京大学东门附近有哪些咖啡店？）\n> ").strip()
    if not question:
        raise SystemExit("未输入问题，演示结束。")
    asyncio.run(run_demo(question))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n用户中断，演示结束。")
    except Exception as error:
        print("\n演示失败。以下是已脱敏的详细错误信息：")
        detailed_traceback = "".join(traceback.format_exception(error))
        print(redact_sensitive_text(detailed_traceback))
