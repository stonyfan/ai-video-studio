# 檀道2 项目（v1-v6 演进）

> 历史 demo 项目，验证 AI 视频智能剪辑全流程

## 输入

- 37 段 4K 手机视频（用户私有，不放仓库）
- 总时长 3:41，约 5 GB

## 输出

| 版本 | 文件 | 时长 | 说明 |
|---|---|---|---|
| v4 | final_dao2_v4.mp4 | 3:41 | 完整版（机械排序 + 稳定 + BGM）|
| v5 | final_dao2_v5.mp4 | 0:32 | 30s 精选（7 个完整场景）|
| v6 | final_dao2_v6.mp4 | 0:24 | 24s 高光（20 个瞬时，用户编排顺序）|

## 演进路径

```
v1  排序 + 重编码 + 加 BGM           ❌ 把竖屏误判为横屏裁
v2  + vidstab 稳定                   ❌ 同上
v3  + AI 智能裁剪（主体居中）         ❌ 基于错误方向
v4  修正方向（源就是 9:16 竖屏）       ✅ 画面完整 3:41
v5  PySceneDetect 切场景 + AI 编排   ✅ 30s 但节奏松散
v6  三联图找最佳瞬时 + 高光编排       ✅ 24s 紧凑精华
```

## 流程命令

```bash
# 1. 重编码到 720×1280（4K → 720p 减少计算量）
python merge_dao2_v4.py        # v4 完整版

# 2. 切场景 + 抽代表帧
python scene_split.py

# 3. 三联图（25%/50%/75% 帧）+ AI 高光检测
python make_triplets.py

# 4. AI 编排（手工编辑 dao2_storyboard_v6.json）

# 5. 切割 + 拼接 + BGM
python build_v6.py
```

## 关键经验教训

1. **方向判断坑**：ffprobe 报尺寸 ≠ 实际像素（手机视频 rotation 元数据）
2. **AI 描述 ≠ 视觉相似**：18_0/20_0 AI 标"真空/水浴"，视觉上都是"袋子+柠檬"
3. **机械排序 ≠ 故事逻辑**：按文件名数字排会跳戏；按拍摄时序才连贯
4. **30s 短视频 = 高光瞬时密度**：1.2s/瞬时 × 25 个 > 整段 5-7s × 7 个

详见 [docs/项目总结与服务化分析.md](../../docs/项目总结与服务化分析.md)

## 数据文件（参考）

- `dao2_scenes.json` - 41 场景 + AI 标签（action/objects/VQ/EI）
- `dao2_scenes_v6.json` - 41 场景 + 三联图高光数据（best_frame/cut_duration）
- `dao2_storyboard_v6.json` - 最终编排（25 个瞬时）

阶段 1 重构时用作回归测试基线。
