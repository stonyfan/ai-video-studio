"""
CLI:
  登录：python -m video_worker login
  配置 API key：python -m video_worker set-key qwen-vl
  跑任务：python -m video_worker run -i <dir> --platform douyin

  Electron 集成：python -m video_worker run --skip-auth
    API key/model 通过环境变量 WORKER_API_KEY/WORKER_MODEL 注入（不读 config.json）
"""
from __future__ import annotations
import argparse
import getpass
import os
import sys
import uuid
from pathlib import Path

from .validators import JobConfig, Platform, Style, Provider
from .job import process_job
from .config_store import ConfigStore
from .auth_client import AuthClient
from .paths import resolve_ffmpeg, bundled_config


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
    print(f"  glm:     智谱 bigmodel ZHIPU_API_KEY (https://open.bigmodel.cn)")
    key = getpass.getpass("API key（输入不回显）: ").strip()
    model = input(f"模型名（回车用默认）: ").strip() or None
    store.set_provider_key(args.provider, key, model)
    print(f"\n✅ 已保存到 {store.path}")
    print(f"   后续 process_job 会自动用这个 key")


def cmd_run(args):
    # Electron 集成模式：--skip-auth 跳过登录态检查
    # API key/model 优先从环境变量读（Electron 注入），否则回退 config_store
    if not args.skip_auth:
        store = ConfigStore()
        auth = AuthClient(store=store)
        try:
            auth.ensure_session_valid()
        except Exception as e:
            print(f"❌ {e}", file=sys.stderr)
            print(f"   先运行: python -m video_worker login", file=sys.stderr)
            sys.exit(1)
    else:
        store = None

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
        ffmpeg_path=resolve_ffmpeg(args.ffmpeg),
        config_path=bundled_config(args.config),
        orchestration_mode=args.orchestration_mode,
        skill=args.skill,
        variants=args.variants,
    )

    # API key/model 注入：env 优先（Electron 模式），其次 config_store（CLI 模式）
    env_key = os.environ.get("WORKER_API_KEY")
    env_model = os.environ.get("WORKER_MODEL")
    # C 模式（云端代理）：WORKER_MODE=proxy 时走后端 model_proxy
    env_mode = os.environ.get("WORKER_MODE", "direct").lower()
    env_auth_token = os.environ.get("WORKER_AUTH_TOKEN")
    env_proxy_base_url = os.environ.get("WORKER_PROXY_BASE_URL")

    if env_mode == "proxy":
        # C 模式：不需要本地 API key，用 JWT 调后端
        if not env_auth_token:
            print("❌ proxy 模式需要 WORKER_AUTH_TOKEN（JWT）", file=sys.stderr)
            sys.exit(1)
        api_key = None
        model = env_model or None
        mode = "proxy"
        auth_token = env_auth_token
        proxy_base_url = env_proxy_base_url
    elif env_key:
        # A 模式（Electron 注入 env）
        api_key = env_key
        model = env_model
        mode = "direct"
        auth_token = None
        proxy_base_url = None
    elif store is not None:
        # A 模式（CLI 从 config_store 读）
        api_key = store.get_provider_key(args.provider)
        model = store.get_provider_model(args.provider)
        mode = "direct"
        auth_token = None
        proxy_base_url = None
    else:
        api_key = None
        model = None
        mode = "direct"
        auth_token = None
        proxy_base_url = None

    result = process_job(
        cfg,
        api_key=api_key,
        model=model,
        mode=mode,
        auth_token=auth_token,
        proxy_base_url=proxy_base_url,
        skip_vision=args.skip_vision,
        skip_render=args.skip_render,
        skip_auth=args.skip_auth,
        resume=args.resume,
        prompts_path=args.prompts_path,
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
    p_key.add_argument("provider", choices=["qwen-vl", "doubao", "glm"])

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
    p_run.add_argument("--skip-auth", action="store_true",
                       help="跳过登录态检查（Electron 集成用）")
    p_run.add_argument("--resume", action="store_true",
                       help="保留现有 job_dir，已完成的中间步骤会跳过")
    p_run.add_argument("--prompts-path", type=Path, default=None,
                       help="自定义 prompts.yaml 路径（Phase 10 后端动态下发；"
                            "不传用 bundled configs/prompts.yaml）")
    p_run.add_argument("--orchestration-mode", choices=["timeline", "llm", "default"],
                       default="timeline",
                       help="编排模式：timeline=creation_time 序+算法截断，"
                            "llm=creation_time 序+LLM 故事阶段聚类，"
                            "default=LLM 挑选+去重+时间序（混合）")
    p_run.add_argument("--skill", default="auto",
                       help="剪辑 skill 名称（auto=自动匹配，none=不使用，"
                            "其他为 configs/skills/<name>/ 下的目录名）")
    p_run.add_argument("--variants", type=int, default=1,
                       choices=range(1, 11),
                       help="一次任务生成 N 个变体（vision 复用，循环 LLM+render）")

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
