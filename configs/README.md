# configs/

阶段 2 待填：模型 / prompt / 平台模板配置。

## 计划结构（参考 docs/项目商品化开发计划书.md 5.3）

```
configs/
  models.yaml         # AI 视觉模型 provider 配置（key 由后端代理）
  platforms/          # 平台规则（抖音/小红书/视频号）
    douyin.yaml
    xhs.yaml
    videohao.yaml
  prompts/            # prompt 模板（按垂类 + 任务）
    scene_analyze.md
    triplet_detect.md
    storyboard_plan.md
  styles/             # 风格预设
    fast_cut.yaml
    ambiance.yaml
    narrative.yaml
```

## 设计原则

- 所有路径来自配置或任务参数
- 所有模型参数来自配置中心
- 所有平台模板版本化
- 所有 prompt 必须带版本号
- 每个任务记录使用的配置版本
