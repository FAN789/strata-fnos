"""Additional model settings for the fnOS console."""
from pathlib import Path
import json
import re


INTEGERS = {
    "ram_keep": ("系统预留内存（GiB）", 0, 90, "--ram-keep-gib", "0"),
    "thinking_budget": ("思考 token 上限", 0, 262144, None, "0 表示不单独限制"),
    "output_limit": ("默认输出 token 上限", 0, 262144, None, "0 表示沿用客户端"),
    "tool_rounds": ("工具调用轮数", 1, 32, None, "8"),
    "tool_timeout": ("单次工具超时（秒）", 5, 300, None, "60"),
    "tool_output": ("工具结果最大字符数", 1000, 64000, None, "20000"),
    "shell_timeout": ("Shell 最长执行时间（秒）", 1, 90, None, "45"),
}
CHOICES = {
    "thinking_level": ("默认思考强度", ["auto", "none", "low", "medium", "high"], ["自动（引擎默认）", "关闭", "低", "中", "高"]),
    "kv_grow": ("KV 按需增长", ["off", "on"], ["关闭", "开启"]),
}
PRESETS = {
    "balanced": {"label": "日常聊天", "values": {"thinking_level": "medium", "thinking_budget": "2048", "output_limit": "4096"}},
    "document": {"label": "长文档分析", "values": {"thinking_level": "high", "thinking_budget": "8192", "output_limit": "8192"}},
    "coding": {"label": "代码与工具", "values": {"thinking_level": "high", "thinking_budget": "4096", "output_limit": "8192",
                                             "tool_rounds": "12", "tool_timeout": "90"}},
}
HELP = {
    "ram_keep": "为系统保留的内存，数值越大，专家可用内存越少；不是固定专家常驻预算。0 沿用引擎自动策略。",
    "thinking_budget": "限制思考部分的 token；0 不单独限制。客户端明确设置时优先。",
    "output_limit": "客户端未指定时使用的输出上限，包含思考与正文。0 沿用客户端或引擎默认值。",
    "kv_grow": "仅适合当前引擎支持的单 GPU 专家模型。按需分配 KV 显存，保存失败会自动回退。",
    "thinking_level": "控制默认思考强度。模型能力不会因设置提高，复杂任务可选择高。",
    "tool_output": "过小可能截断搜索或命令结果；超出部分由工具层截断。",
}


def validate(fields):
    result = {}
    for name, (_, low, high, _, _) in INTEGERS.items():
        value = fields.get(name, "").strip()
        if value:
            if not re.fullmatch(r"\d{1,6}", value, re.ASCII) or not low <= int(value) <= high:
                raise ValueError(f"{INTEGERS[name][0]}须在 {low}–{high} 之间。")
            result[name] = str(int(value))
    for name, (_, choices, _) in CHOICES.items():
        value = fields.get(name, "").strip()
        if value:
            if value not in choices:
                raise ValueError("设置选项无效。")
            result[name] = value
    if fields.get("gpu", "").strip():
        value = fields["gpu"].strip()
        if value != "auto" and not re.fullmatch(r"\d{1,2}(?:,\d{1,2}){0,3}", value, re.ASCII):
            raise ValueError("GPU 须为 auto 或显卡编号列表，例如 0 或 0,1。")
        if value != "auto" and len(set(map(int, value.split(",")))) != len(value.split(",")):
            raise ValueError("GPU 编号不能重复。")
        result["gpu"] = value if value == "auto" else ",".join(str(int(n)) for n in value.split(","))
    if "shell_cwd" in fields:
        value = fields["shell_cwd"].strip()
        if value != "workspace":
            path = Path(value)
            if not re.match(r"^/vol\d+/", value) or path.resolve(strict=True) != path or not path.is_dir():
                raise ValueError("请选择飞牛授权的实际目录。")
        result["shell_cwd"] = value
    if "shell_dirs" in fields:
        raw = fields["shell_dirs"]
        if len(raw) > 6000:
            raise ValueError("Shell 目录列表过长。")
        try:
            paths = json.loads(raw)
        except ValueError:
            raise ValueError("Shell 目录列表格式无效。") from None
        if not isinstance(paths, list) or len(paths) > 16 or any(
                not isinstance(value, str) or len(value) > 512 or not re.match(r"^/vol\d+/", value)
                or re.search(r"[\x00-\x1f\x7f]", value) for value in paths):
            raise ValueError("最多可添加 16 个飞牛授权目录。")
        if len(set(paths)) != len(paths):
            raise ValueError("Shell 工作目录不能重复。")
        for value in paths:
            path = Path(value)
            if path.resolve(strict=True) != path or not path.is_dir():
                raise ValueError("请选择存在的实际目录。")
        result["shell_dirs"] = json.dumps(paths, ensure_ascii=False)
    return result


def apply(profile, values, set_arg):
    for name, (_, _, _, flag, _) in INTEGERS.items():
        if name in values and flag:
            for key in ("args", "args_written", "args_derived"):
                if key in profile:
                    set_arg(profile[key], flag, values[name])
    if "kv_grow" in values:
        for key in ("args", "args_written", "args_derived"):
            if key in profile:
                set_arg(profile[key], "--kv-grow", values["kv_grow"] == "on", switch=True)
        # Override an inherited runtime environment setting as well.
        profile.setdefault("env", {})["STRATA_KV_GROW"] = "1" if values["kv_grow"] == "on" else "0"
    for field, target in (("thinking_level", "reasoning_effort"), ("thinking_budget", "reasoning_budget_tokens")):
        if field in values:
            if values[field] == "auto":
                profile.pop(target, None)
            else:
                profile[target] = int(values[field]) if field == "thinking_budget" else values[field]
    if "output_limit" in values:
        profile["_fnos_output_limit"] = int(values["output_limit"])
        profile.setdefault("env", {})["STRATA_FNOS_MAX_OUTPUT"] = values["output_limit"]
    for name, key in (("tool_rounds", "max_rounds"), ("tool_timeout", "timeout_s"), ("tool_output", "max_result_chars")):
        if name in values:
            profile.setdefault("mcp", {})[key] = int(values[name])
    for name in ("shell_timeout", "shell_cwd"):
        if name in values:
            profile["_fnos_" + name] = int(values[name]) if name == "shell_timeout" else values[name]
    if "shell_dirs" in values:
        paths = json.loads(values["shell_dirs"])
        profile["_fnos_shell_dirs"] = paths
        if profile.get("_fnos_shell_cwd", "workspace") not in ["workspace", *paths]:
            if "shell_cwd" in values:
                raise ValueError("默认工作目录须在候选目录列表中。")
            profile["_fnos_shell_cwd"] = "workspace"
    if "gpu" in values:
        if values["gpu"] == "auto":
            profile.pop("gpu", None)
            profile["gpus_asked"] = False
        else:
            ids = [int(v) for v in values["gpu"].split(",")]
            profile["gpu"] = ids[0] if len(ids) == 1 else ids
            profile["gpus_asked"] = True
    if (values.get("kv_grow") == "on" or profile.get("env", {}).get("STRATA_KV_GROW") == "1") and isinstance(profile.get("gpu"), list) and len(profile["gpu"]) > 1:
        raise ValueError("KV 按需增长仅支持单 GPU，请先关闭此选项。")


def fields(profile, arg_value):
    args = profile.get("args", [])
    stored = {
        "thinking_budget": profile.get("reasoning_budget_tokens"),
        "output_limit": profile.get("_fnos_output_limit"),
        "tool_rounds": profile.get("mcp", {}).get("max_rounds"),
        "tool_timeout": profile.get("mcp", {}).get("timeout_s"),
        "tool_output": profile.get("mcp", {}).get("max_result_chars"),
        "shell_timeout": profile.get("_fnos_shell_timeout"),
    }
    items = []
    defaults = {"ram_keep": "0", "thinking_budget": "0", "output_limit": "0", "tool_rounds": "8",
                "tool_timeout": "60", "tool_output": "20000", "shell_timeout": "45"}
    for name, (label, low, high, flag, placeholder) in INTEGERS.items():
        value = arg_value(args, flag) if flag else stored.get(name)
        items.append({"id": name, "label": label, "min": low, "max": high,
                      "value": str(value) if value is not None else defaults[name], "placeholder": placeholder,
                      "defaulted": value is None})
    for name, (label, options, labels) in CHOICES.items():
        value = profile.get("reasoning_effort", "auto") if name == "thinking_level" else (
            "on" if "--kv-grow" in args or profile.get("env", {}).get("STRATA_KV_GROW") == "1" else "off")
        items.append({"id": name, "label": label, "value": value,
                      "options": [{"value": key, "label": text} for key, text in zip(options, labels)]})
    gpu = profile.get("gpu", "auto")
    gpu = ",".join(map(str, gpu)) if isinstance(gpu, list) else str(gpu)
    items.append({"id": "gpu", "label": "推理 GPU 编号", "value": gpu,
                  "type": "text", "placeholder": "auto",
                  "help": "按 nvidia-smi 编号选择。多 GPU 需按显存和实际性能另行验收。"})
    for item in items:
        if item["id"] in HELP:
            item["help"] = HELP[item["id"]]
        if item.get("defaulted"):
            item["help"] = "未单独设置，显示默认值。" + item.get("help", "")
    return items
