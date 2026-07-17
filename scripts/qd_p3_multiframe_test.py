"""
qd_p3 多帧 image_url 对比测试
- 用真实 GLM API 跑 17 个场景
- 对比 3 帧三联图 vs 12 帧序列的评分分布
"""
from __future__ import annotations
import json
import logging
import os
import sys
from pathlib import Path

# 设置 GLM API key（用户提供的真实 key）
os.environ.setdefault("ZHIPU_API_KEY", "253e42f83cff402b8e2c2825dbee3310.qRIdGGx9MvzIG9IC")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from video_worker import job as job_mod
from video_worker.validators import JobConfig
from video_worker.paths import resolve_ffmpeg, bundled_config


def main():
    job_id = "qd_p3_mf"
    # 清掉旧 mf 任务目录（如果有）
    job_dir = Path("jobs") / job_id
    if job_dir.exists():
        import shutil
        shutil.rmtree(job_dir)

    cfg = JobConfig(
        job_id=job_id,
        input_path=r"C:\Users\86150\Downloads\青岛",
        platform="general",
        style="narrative",
        target_duration=30,
        provider="glm",
        work_root="jobs",
        ffmpeg_path=str(resolve_ffmpeg(Path("tools/ffmpeg.exe"))),
        config_path=bundled_config(Path("configs/default.yaml")),
    )

    logger = logging.getLogger("qd_p3_mf")
    logging.basicConfig(level=logging.INFO,
                        format="[%(levelname)s] %(message)s")

    print(f"[qd_p3_mf] 启动 job {job_id}")
    result = job_mod.process_job(cfg, logger=logger, resume=False, model="glm-4.6v")

    print("\n=== 结果 ===")
    print(f"job_id: {result.job_id}")
    print(f"status: {result.status}")
    print(f"final:  {result.final_video}")
    print(f"log:    {result.log}")
    print(f"cost:   vision_calls={result.cost.vision_calls} duration={result.cost.duration_sec:.1f}s")

    # 加载新 analyzed 结果做对比
    new_path = Path(f"jobs/{job_id}/work/analyzed.json")
    old_path = Path("jobs/qd_p3_test/work/analyzed.3frame.json")
    if new_path.exists() and old_path.exists():
        new_data = {a["id"]: a for a in json.loads(new_path.read_text(encoding="utf-8"))}
        old_data = {a["id"]: a for a in json.loads(old_path.read_text(encoding="utf-8"))}

        print("\n=== 对比：3 帧三联图 vs 12 帧序列 ===")
        print(f"{'scene_id':<55} | {'VQ 3f→12f':<13} | {'MO 3f→12f':<13} | {'HL 3f→12f':<13}")
        print("-" * 100)
        for sid in sorted(new_data.keys()):
            old = old_data.get(sid, {})
            new = new_data[sid]
            o_vq = old.get("visual_quality", "?")
            n_vq = new.get("visual_quality", "?")
            o_mo = old.get("motion_score", "?")
            n_mo = new.get("motion_score", "?")
            o_hl = old.get("highlight_score", "?")
            n_hl = new.get("highlight_score", "?")
            short_sid = sid[-50:]
            print(f"{short_sid:<55} | {str(o_vq):>2} → {str(n_vq):<2}        | {str(o_mo):>2} → {str(n_mo):<2}        | {str(o_hl):>2} → {str(n_hl):<2}")

        # 统计：3 帧版本 GLM 给所有场景都是 8（如对话所述）
        old_vq_dist = {}
        new_vq_dist = {}
        old_hl_dist = {}
        new_hl_dist = {}
        for sid, new in new_data.items():
            old = old_data.get(sid, {})
            ov = old.get("visual_quality", 0)
            nv = new.get("visual_quality", 0)
            oh = old.get("highlight_score", 0)
            nh = new.get("highlight_score", 0)
            old_vq_dist[ov] = old_vq_dist.get(ov, 0) + 1
            new_vq_dist[nv] = new_vq_dist.get(nv, 0) + 1
            old_hl_dist[oh] = old_hl_dist.get(oh, 0) + 1
            new_hl_dist[nh] = new_hl_dist.get(nh, 0) + 1

        print(f"\nVisual Quality 分布（3帧 vs 12帧）：")
        print(f"  3帧: {dict(sorted(old_vq_dist.items()))}")
        print(f"  12帧: {dict(sorted(new_vq_dist.items()))}")
        print(f"\nHighlight Score 分布（3帧 vs 12帧）：")
        print(f"  3帧: {dict(sorted(old_hl_dist.items()))}")
        print(f"  12帧: {dict(sorted(new_hl_dist.items()))}")


if __name__ == "__main__":
    main()
