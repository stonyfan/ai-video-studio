# tests/

阶段 1 待填：测试体系。

## 计划测试类型（参考 docs/项目商品化开发计划书.md 5.2）

```
tests/
  unit/              # 单元测试
    test_path_handling.py
    test_video_filter.py
    test_json_schema.py
    test_cut_compute.py
    test_duration.py
  integration/       # 集成测试
    test_scene_detect.py
    test_frame_extract.py
    test_storyboard.py
    test_render.py
  e2e/               # 端到端
    test_full_job.py
  regression/        # 回归测试
    fixtures/        # 固定素材（小，可入仓）
    expected/        # 预期输出指标
```

## 阶段 1 完成标准

- [ ] 每个核心函数有单元测试
- [ ] 每个 worker 阶段可单独运行测试
- [ ] 端到端测试可在 1 分钟内跑完
- [ ] 失败输出结构化错误码

最低要求：每次发布前跑通一个 1 分钟内的小素材端到端任务。
