# 玉兰花马天尼项目（多平台输出）

> 当前最新 demo，验证单素材 → 多平台差异化输出

## 输入

- 19 段 4K 手机视频（用户私有）
- 总时长约 2:46，约 3.4 GB
- 来源：`D:\BaiduNetdiskDownload\玉兰花马天尼\`

## 输出（3 个平台）

| 平台 | 文件 | 时长 | 风格 |
|---|---|---|---|
| 抖音 | final_玉兰马天尼_抖音15s.mp4 | 15s | 极限快剪 + 强冷调 + 大字 |
| 小红书 | final_玉兰马天尼_小红书30s.mp4 | 30s | 暖调氛围 + 细字 |
| 视频号 | final_玉兰马天尼_视频号30s.mp4 | 30s | 自然色调 + 中速 |

## 流程命令

```bash
# 1. 标准化素材（4K → 720×1280）
python prep.py

# 2. 场景切分
python scene_split.py

# 3. 三联图（每场景 25%/50%/75% 帧）
python make_triplets.py

# 4. BGM 节拍检测
python detect_beats.py

# 5. AI 编排（手工编辑 storyboard_*.json）

# 6. 一次性构建 3 个平台
python multi_build.py --all
```

## 三平台差异化

| 维度 | 抖音 15s | 小红书 30s | 视频号 30s |
|---|---|---|---|
| BGM | Sudden Tour（atempo 1.5×）| slow down（atempo 0.85×）| Dubstepper（原速）|
| 节拍 BPM | 255 | 145 | 96 |
| 瞬时数 | 18 | 21 | 21 |
| 每瞬时 | 0.8s | 1.4s | 1.4s |
| 色调 | 强冷调 + 强锐化 | 暖调 + 复古褪色 | 自然 + 轻冷调 |
| 字幕 | 大字粗描边 36pt | 细字优雅 26pt | 标准 30pt |

## 关键设计决策

1. **拍摄时序 = 故事弧**：不强用 AI 重排，按文件名 1-1 → 14-3 顺序
2. **AI 仅用于**：找每段最佳瞬时 + 识别明显重复
3. **节拍对齐**：BGM 节拍吸附 ±0.3s
4. **atempo 加速 BGM**：不改音高，制造节奏差异

## 数据文件

- `scenes.json` - 21 场景原始数据
- `scenes_v6.json` - 三联图高光数据
- `storyboard.json` - 默认编排（按拍摄时序）
- `storyboard_douyin15.json` - 抖音版（18 瞬时）
- `storyboard_xhs30.json` - 小红书版（21 瞬时）
- `storyboard_videohao30.json` - 视频号版（21 瞬时）
