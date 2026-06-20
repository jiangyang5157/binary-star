"""Shared helpers for OpenAI-compatible adapters (DeepSeek, Qwen)."""
import json
from typing import Any

JSON_HINT = (
    "IMPORTANT: You MUST respond ONLY with a valid JSON object. "
    "Do NOT include markdown blocks, preamble, or explanations."
)


def build_messages(
    system_instruction: str | None, contents: list[Any]
) -> list[dict]:
    system_content = (
        f"{system_instruction}\n\n{JSON_HINT}"
        if system_instruction else JSON_HINT
    )
    messages: list[dict] = [{"role": "system", "content": system_content}]
    for item in contents:
        if isinstance(item, str):
            messages.append({"role": "user", "content": item})
        elif isinstance(item, dict):
            role = item.get("role", "user")
            if "text" in item:
                messages.append({"role": role, "content": item["text"]})
            elif "tool_responses" in item:
                for tr in item["tool_responses"]:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tr["id"],
                        "content": json.dumps(tr.get("result", {})),
                    })
            elif "tool_calls" in item:
                tcs = [{
                    "id": tc["id"], "type": "function",
                    "function": {"name": tc["name"], "arguments": json.dumps(tc["args"])},
                } for tc in item["tool_calls"]]
                messages.append({"role": "assistant", "content": None, "tool_calls": tcs})
    return messages


def convert_tools(tools: list[Any]) -> list[dict]:
    result = []
    for tool in tools:
        if hasattr(tool, "function_declarations"):
            for fd in tool.function_declarations:
                props, required = {}, []
                if hasattr(fd, "parameters") and fd.parameters:
                    for pn, ps in getattr(fd.parameters, "properties", {}).items():
                        props[pn] = {
                            "type": getattr(ps, "type", "string").lower(),
                            "description": getattr(ps, "description", ""),
                        }
                    required = list(getattr(fd.parameters, "required", []) or [])
                result.append({
                    "type": "function",
                    "function": {
                        "name": fd.name, "description": fd.description or "",
                        "parameters": {"type": "object", "properties": props, "required": required},
                    },
                })
    return result


def clean_json_text(raw_text: str) -> str:
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text.split("```json", 1)[1].rsplit("```", 1)[0].strip()
    elif text.startswith("```"):
        text = text.split("```", 1)[1].rsplit("```", 1)[0].strip()
    return text
