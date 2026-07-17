"""curate_cli — desktop subprocess 入口

协议：stdout 每行一个 JSON（UTF-8）。desktop spawn 后逐行解析。

通用消息：
    {"type":"log","level":"info|warn|error","msg":"..."}
    {"type":"error","message":"...","traceback":"...?"}   # 致命错误，进程随后 exit 1

子命令对应消息：
    load-data     → 最终 {"type":"data","data":{CurateData}}
    build-previews→ 进度 {"type":"progress","done":N,"todo":N,"stage":"previews","msg":"..."}
                  → 最终 {"type":"done"}
    submit        → 进度 {"type":"progress","done":N,"todo":N,"stage":"llm|storyboard|render","msg":"..."}
                  → 最终 {"type":"result","result":{CurateResult}}

用法：
    python scripts/curate_cli.py load-data --job <id> [--input-dir <dir>]
    python scripts/curate_cli.py build-previews --job <id>
    python scripts/curate_cli.py submit --job <id> --payload <json-path> [--input-dir <dir>]
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

# === 路径设置 ===================================================
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# === stdout JSON 协议 ==========================================

def emit(msg: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def emit_log(level: str, msg: str) -> None:
    emit({"type": "log", "level": level, "msg": msg})


def emit_progress(done: int, todo: int, stage: str, msg: str) -> None:
    emit({"type": "progress", "done": done, "todo": todo, "stage": stage, "msg": msg})


def emit_error(message: str, tb: str = "") -> None:
    emit({"type": "error", "message": message, "traceback": tb})


# === 子命令 ====================================================

def cmd_load_data(args: argparse.Namespace) -> int:
    from curate_service.service import load_curate_data
    data = load_curate_data(
        args.job, input_dir=args.input_dir, on_log=emit_log,
    )
    emit({"type": "data", "data": data.model_dump(mode="json")})
    return 0


def cmd_build_previews(args: argparse.Namespace) -> int:
    from curate_service.service import build_previews
    build_previews(args.job, on_log=emit_log, on_progress=emit_progress)
    emit({"type": "done"})
    return 0


def cmd_submit(args: argparse.Namespace) -> int:
    from curate_service.schemas import CurateSubmitPayload
    from curate_service.service import run_curation

    payload_raw = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    payload = CurateSubmitPayload(**payload_raw)

    result = run_curation(
        args.job, args.input_dir, payload,
        on_log=emit_log, on_progress=emit_progress,
    )
    emit({"type": "result", "result": result.model_dump(mode="json")})
    return 0


def cmd_regenerate(args: argparse.Namespace) -> int:
    from curate_service.schemas import RegeneratePayload
    from curate_service.service import regenerate_with_instruction

    payload_raw = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    payload = RegeneratePayload(**payload_raw)

    result = regenerate_with_instruction(
        args.job, args.input_dir, payload,
        on_log=emit_log, on_progress=emit_progress,
    )
    emit({"type": "result", "result": result.model_dump(mode="json")})
    return 0


# === main ======================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="curate subprocess entry")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_load = sub.add_parser("load-data", help="加载 stages + scenes")
    p_load.add_argument("--job", required=True)
    p_load.add_argument("--input-dir", default=None)
    p_load.set_defaults(func=cmd_load_data)

    p_prev = sub.add_parser("build-previews", help="切预览 MP4")
    p_prev.add_argument("--job", required=True)
    p_prev.set_defaults(func=cmd_build_previews)

    p_sub = sub.add_parser("submit", help="提交勾选，跑 LLM 决策 + 渲染")
    p_sub.add_argument("--job", required=True)
    p_sub.add_argument("--payload", required=True,
                        help="JSON 文件路径，内容为 CurateSubmitPayload")
    p_sub.add_argument("--input-dir", default=None)
    p_sub.set_defaults(func=cmd_submit)

    p_regen = sub.add_parser("regenerate", help="自然语言再编辑：基于当前 storyboard + 指令重剪")
    p_regen.add_argument("--job", required=True)
    p_regen.add_argument("--payload", required=True,
                         help="JSON 文件路径，内容为 RegeneratePayload")
    p_regen.add_argument("--input-dir", default=None)
    p_regen.set_defaults(func=cmd_regenerate)

    args = parser.parse_args()

    try:
        return args.func(args)
    except Exception as e:
        tb = traceback.format_exc()
        emit_log("error", f"{type(e).__name__}: {e}")
        emit_error(f"{type(e).__name__}: {e}", tb)
        return 1


if __name__ == "__main__":
    sys.exit(main())
