"""
CLI:
  登录：python -m video_worker --login
  配置 API key：python -m video_worker --set-key qwen-vl
  跑任务：python -m video_worker -i <dir> --platform douyin
"""
from __future__ import annotations
import argparse
import getpass
import sys
import uuid
from pathlib import Path

from .validators import JobConfig, Platform, Style, Provider
from .job import process_job
from .config_store import ConfigStore
from .auth_client import AuthClient


def cmd_login(args):
    store = ConfigStore()
    if args.backend_url:
        store.set_backend_url(args.backend_url)
    username = input("用户名: ").strip()
    password = getpass.getpass("密码: ")
    auth = AuthClient(store=store)
    try:
        data = auth.login(username, password)
        print(f"\n✅ 登录成功")
        print(f"   用户: {data['user'].get('username')}")
        print(f"   角色: {data['user'].get('role')}")
        print(f"   授权到期: {data['user'].get('license_expires_at') or '永久'}")
        print(f"   token 已保存到 {store.path}")
    except Exception as e:
        print(f"\n❌ 登录失败: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_set_key(args):
    store = ConfigStore()
    print(f"配置 {args.provider} 的 API key")
    print(f"  qwen-vl: 阿里百炼 DASHSCOPE_API_KEY (https://dashscope.console.aliyun.com)")
    print(f"  doubao:  火山方舟 ARK_API_KEY (https://console.volcengine.com/ark)")
    key = getpass.getpass("API key（输入不回显）: ").strip()
    model = input(f"模型名（回车用默认）: ").strip() or None
    store.set_provider_key(args.provider, key, model)
    print(f"\n✅ 已保存到 {store.path}")
    print(f"   后续 process_job 会自动用这个 key")


def cmd_run(args):
    store = ConfigStore()
    auth = AuthClient(store=store)
    try:
        auth.ensure_session_valid()
    except Exception as e:
        print(f"❌ {e}", file=sys.stderr)
        print(f"   先运行: python -m video_worker --login", file=sys.stderr)
        sys.exit(1)

    job_id = args.job_id or f"job_{uuid.uuid4().hex[:8]}"
    cfg = JobConfig(
        job_id=job_id,
        input_path=args.input,
        output_path=args.output,
        platform=Platform(args.platform),
        style=Style(args.style),
        target_duration=args.duration,
        bgm_path=args.bgm,
        provider=Provider(args.provider),
        work_root=args.work_root,
        ffmpeg_path=args.ffmpeg,
        config_path=args.config,
    )

    # 从 config_store 注入 API key（A 模式）
    api_key = store.get_provider_key(args.provider)
    model = store.get_provider_model(args.provider)

    result = process_job(
        cfg,
        api_key=api_key,
        model=model,
        skip_vision=args.skip_vision,
        skip_render=args.skip_render,
    )
    print(f"\n=== 结果 ===")
    print(f"job_id: {result.job_id}")
    print(f"status: {result.status.value}")
    print(f"final:  {result.final_video}")
    print(f"log:    {result.log}")
    sys.exit(0 if result.status.value == "completed" else 1)


def main():
    parser = argparse.ArgumentParser(prog="video_worker")
    sub = parser.add_subparsers(dest="cmd")

    # 登录
    p_login = sub.add_parser("login", help="登录后端服务")
    p_login.add_argument("--backend-url", help="覆盖默认后端地址")

    # 配置 API key
    p_key = sub.add_parser("set-key", help="配置 provider 的 API key")
    p_key.add_argument("provider", choices=["qwen-vl", "doubao"])

    # 跑任务
    p_run = sub.add_parser("run", help="跑视频剪辑任务")
    p_run.add_argument("--input", "-i", required=True, type=Path)
    p_run.add_argument("--output", "-o", type=Path, default=None)
    p_run.add_argument("--platform", "-p", choices=[p.value for p in Platform], default="general")
    p_run.add_argument("--style", "-s", choices=[s.value for s in Style], default="fast_cut")
    p_run.add_argument("--duration", "-d", type=int, default=30)
    p_run.add_argument("--bgm", type=Path, default=None)
    p_run.add_argument("--provider", choices=[p.value for p in Provider], default="qwen-vl")
    p_run.add_argument("--job-id", default=None)
    p_run.add_argument("--work-root", type=Path, default=Path("jobs"))
    p_run.add_argument("--ffmpeg", type=Path, default=Path("tools/ffmpeg.exe"))
    p_run.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    p_run.add_argument("--skip-vision", action="store_true")
    p_run.add_argument("--skip-render", action="store_true")

    # 兼容旧调用：无子命令时默认 run
    parser.add_argument("--input", "-i", type=Path, default=None, help="（兼容旧调用）")
    parser.add_argument("--platform", "-p", default=None)
    parser.add_argument("--duration", "-d", type=int, default=30)
    parser.add_argument("--ffmpeg", type=Path, default=Path("tools/ffmpeg.exe"))
    parser.add_argument("--skip-vision", action="store_true")
    parser.add_argument("--skip-render", action="store_true")
    parser.add_argument("--job-id", default=None)
    parser.add_argument("--work-root", type=Path, default=Path("jobs"))
    parser.add_argument("--config", type=Path, default=Path("configs/default.yaml"))

    args = parser.parse_args()

    if args.cmd == "login":
        cmd_login(args)
    elif args.cmd == "set-key":
        cmd_set_key(args)
    elif args.cmd == "run":
        cmd_run(args)
    elif args.input:
        # 兼容旧调用（直接 python -m video_worker -i xxx）
        # 不要求登录（旧脚本可能没人会话）
        job_id = args.job_id or f"job_{uuid.uuid4().hex[:8]}"
        from .validators import Platform as P, Style as S, Provider as Pr
        cfg = JobConfig(
            job_id=job_id,
            input_path=args.input,
            platform=P(args.platform) if args.platform else Platform.GENERAL,
            target_duration=args.duration,
            ffmpeg_path=args.ffmpeg,
            work_root=args.work_root,
            config_path=args.config,
        )
        result = process_job(cfg, skip_vision=args.skip_vision, skip_render=args.skip_render)
        print(f"status: {result.status.value}\nfinal: {result.final_video}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
