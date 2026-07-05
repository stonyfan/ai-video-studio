# video_worker/

阶段 1 待填：标准化 Python 视频 worker 模块。

## 计划模块结构（参考 docs/项目商品化开发计划书.md 4.1）

```
video_worker/
  config.py          # 配置加载（环境变量 + YAML）
  job.py             # process_job 统一入口
  media_scan.py      # 素材扫描 + 过滤非视频
  preprocess.py      # 重编码 + 标准化方向
  scene_detect.py    # PySceneDetect 切场景
  frame_extract.py   # 抽帧 + 三联图生成
  vision_analyze.py  # AI 视觉分析（适配层调用）
  storyboard.py      # 编排策略
  render.py          # FFmpeg 渲染
  validators.py      # JSON schema 校验
  progress.py        # 进度上报
  storage.py         # 任务工作目录管理
```

## 阶段 1 完成标准

- [ ] process_job(config) 统一入口
- [ ] 不依赖硬编码本机路径
- [ ] JSON schema 校验（pydantic）
- [ ] 任务目录隔离（job_id）
- [ ] 失败时输出结构化错误码
- [ ] 同一任务可重复执行

详见计划书阶段 1 章节。
