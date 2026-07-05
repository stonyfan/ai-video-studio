# AI 视频智能剪辑 - Prompt 模板库

> 4 个核心 prompt + 3 个垂类定制示例 + 1 个降本技巧
> 配套文档：《项目总结与服务化分析.md》

---

## 目录

1. [Prompt 1：主体位置识别](#prompt-1主体位置识别) — 用于智能裁剪
2. [Prompt 2：场景内容分析](#prompt-2场景内容分析) — 用于去重和编排
3. [Prompt 3：三联图高光瞬时检测](#prompt-3三联图高光瞬时检测) — **核心独创**
4. [Prompt 4：故事弧编排](#prompt-4故事弧编排) — 用于跨场景决策
5. [垂类定制：餐饮探店](#垂类定制餐饮探店)
6. [垂类定制：旅行 Vlog](#垂类定制旅行-vlog)
7. [垂类定制：美妆教程](#垂类定制美妆教程)
8. [降本技巧：JSON 强制 + 重试逻辑](#降本技巧)

---

## Prompt 1：主体位置识别

**用途**：判断画面主体横向位置，用于智能裁剪（让主体居中）。
**输入**：横屏源视频中间帧。
**输出**：0.0-1.0 浮点数。

### 模板

```
这是横屏视频的中间帧。请按以下格式回复：

POSITION: <一句话描述主体在画面里横向的什么位置>
X: <一个 0.0 到 1.0 之间的浮点数，0.0=最左，0.5=居中，1.0=最右>

主体指：{主体定义，如"食物/手/人/物品/有动作的物体"}。根据画面实际内容判断，不要给固定值。
```

### 关键规则

- ❌ **不能给数字示例**（如 `X: 0.45`），模型会抄
- ✅ **要求"先描述再给值"**，让模型思考后输出
- ✅ **明确主体定义**（不同垂类主体不同）

### 调用参数

```python
# Qwen-VL-Plus 示例
response = client.chat.completions.create(
    model="qwen-vl-plus",
    messages=[{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": image_url_or_base64}},
            {"type": "text", "text": PROMPT}
        ]
    }]
)
```

---

## Prompt 2：场景内容分析

**用途**：理解每个场景的内容，用于去重和编排。
**输入**：场景代表帧（中间时刻）。
**输出**：结构化 JSON。

### 模板

```
视频帧。只返回 JSON，无其他文字：
{"action": "<2-4字动作>", "objects": ["<主要物体1>", "<物体2>"], "shot_type": "<特写|近景|中景|全景>", "visual_quality": <1-10整数>, "emotional_impact": <1-10整数>, "best_moment": "<5-10字瞬间描述>"}

判断：visual_quality 高=清晰/稳定/构图好；emotional_impact 高=吸引眼球/有冲击力。
```

### 字段说明

| 字段 | 取值 | 用途 |
|---|---|---|
| `action` | 2-4 字动作（"切柠檬"/"倒酒"）| 跨场景去重 |
| `objects` | 主要物体列表 | 编排参考 |
| `shot_type` | 特写/近景/中景/全景 | 节奏控制 |
| `visual_quality` | 1-10 | 画质筛选 |
| `emotional_impact` | 1-10 | 视觉冲击排序 |
| `best_moment` | 5-10 字 | 编排 reason |

### 关键规则

- ✅ **严格 JSON**（用 `response_format={"type": "json_object"}` 强制）
- ✅ **数值字段用整数**（避免浮点解析问题）
- ✅ **action 限 2-4 字**（便于跨场景聚类）

---

## Prompt 3：三联图高光瞬时检测 ⭐ 核心独创

**用途**：在场景内找最佳瞬间（不是场景边界）。
**输入**：场景的 25%/50%/75% 三帧拼成的横排三联图。
**输出**：哪帧最佳 + 切片长度 + 描述。

### 三联图生成（Python + PIL）

```python
from PIL import Image

def make_triplet(frame_25, frame_50, frame_75, output_path, frame_w=360, frame_h=640):
    """3 帧横排拼接"""
    canvas = Image.new("RGB", (frame_w * 3 + 20, frame_h), (20, 20, 20))
    canvas.paste(Image.open(frame_25).resize((frame_w, frame_h)), (0, 0))
    canvas.paste(Image.open(frame_50).resize((frame_w, frame_h)), (frame_w + 10, 0))
    canvas.paste(Image.open(frame_75).resize((frame_w, frame_h)), (frame_w * 2 + 20, 0))
    canvas.save(output_path, quality=85)
```

### Prompt 模板

```
这是同一视频场景的 3 个连续时刻横排（左=早 25%，中=中 50%，右=晚 75%）。
判断哪一帧是这个场景的最佳瞬间（动作高潮/视觉冲击最强）。

只返回 JSON，无其他文字：
{"best_frame": "left|mid|right", "cut_duration": <1.0-2.5 浮点数>, "best_moment": "<5-10 字描述>"}

判断：
- 动作高潮（{高潮示例，如"液体接触杯口/刀切瞬间/手挤压"}）> 静态准备
- cut_duration：紧凑动作 1.0-1.5；长过程 2.0-2.5
```

### 切片位置计算

```python
def compute_cut(scene_start, scene_end, best_frame, cut_duration):
    """根据 best_frame 算切片位置"""
    D = scene_end - scene_start
    cut = min(cut_duration, D)

    if best_frame == "left":
        return scene_start, scene_start + cut
    elif best_frame == "right":
        return scene_end - cut, scene_end
    else:  # mid
        mid = (scene_start + scene_end) / 2
        return max(scene_start, mid - cut/2), min(scene_end, mid + cut/2)
```

### 关键规则

- ⭐ **三联图比单帧判断更准**（AI 能感知早→中→晚的动作节奏）
- ✅ **cut_duration 给范围**（1.0-2.5），AI 按动作紧凑度自决
- ✅ **best_frame 限定三选一**（left/mid/right），避免歧义

---

## Prompt 4：故事弧编排

**用途**：把多个场景按时序/逻辑排序。
**输入**：所有场景的 JSON 数据（含 action/objects/VQ/EI）。
**输出**：精选场景 ID 的有序列表 + 总时长。

### 模板

```
下面是 N 个候选场景，每个含动作/物体/景别/质量/情绪强度/时长。
请精选 8-12 个，总时长控制在 28-32 秒，编排成一个 30 秒短视频。
你自己判断最佳顺序（不限定故事弧）。只输出 JSON：

{
  "selected": [
    {"id": "05_1", "reason": "..."},
    {"id": "12_3", "reason": "..."}
  ],
  "total_duration": 30.5,
  "narrative": "一句话描述这个视频讲什么"
}

去重规则：
1. AI 描述相同的场景只留 1 个（如多个"柠檬入水"只留最强那个）
2. 同 action 不同对象可保留（如"倒酒入量杯"+"倒酒入调酒壶"）
3. 优先用独特内容（非重复动作）

故事弧原则：
- 开场：视觉冲击力强
- 中段：按内容逻辑递进
- 结尾：成品/收尾

[场景数据 JSON...]
```

### 关键规则

- ✅ **明确去重规则**（AI 默认会塞同动作镜头）
- ✅ **限定总时长**（28-32s 给容错空间）
- ✅ **要求 narrative**（一句话总结，便于调试）

---

## 垂类定制：餐饮探店

### 主体定义调整

通用版："食物/手/人/物品/有动作的物体"

餐饮版："**菜品/食材/烹饪动作/厨师手部/餐具/烟火气**"

### 故事弧模板

```
故事弧（餐饮探店专用）：
1. 开场（1-2 个）：店面招牌/烟火特写
2. 食材展示（2-3 个）：新鲜食材/特色原料
3. 烹饪过程（4-5 个）：切配-下锅-翻炒-出锅
4. 装盘出品（2-3 个）：摆盘-上桌
5. 品尝反馈（1-2 个）：顾客表情/特写
```

### 动作识别增强

```
动作分类（餐饮专用）：
- 准备类：洗/切/腌/拌
- 烹饪类：炒/煮/炸/蒸/烤
- 出品类：装盘/上桌/特写
- 互动类：顾客品尝/老板介绍
```

### 高潮示例

```
判断高潮（餐饮专用）：
- 食材下锅瞬间油花四溅
- 翻炒颠勺动作
- 装盘时酱汁浇下
- 顾客咬下第一口表情
```

---

## 垂类定制：旅行 Vlog

### 主体定义调整

```
主体指：地标建筑/风景全景/人物背影/特色美食/路牌交通/文化元素
```

### 故事弧模板

```
故事弧（旅行 Vlog 专用）：
1. 出发（1-2 个）：行李/机场/车站
2. 抵达（2-3 个）：地标初见/街景
3. 体验（4-5 个）：景点/活动/美食
4. 人物（2-3 个）：合影/特写
5. 收尾（1-2 个）：夕阳/夜景/告别
```

### 动作识别增强

```
动作分类（旅行专用）：
- 移动类：走路/乘车/飞行
- 观光类：拍照/驻足/远眺
- 体验类：尝试/品尝/参与
- 互动类：合影/对话/交流
```

### 高潮示例

```
判断高潮（旅行专用）：
- 地标首次入镜
- 风景从局部到全景的展开
- 人物惊喜表情
- 美食上桌瞬间
```

---

## 垂类定制：美妆教程

### 主体定义调整

```
主体指：脸部特写/化妆工具/产品瓶身/手部动作/镜子反射
```

### 故事弧模板

```
故事弧（美妆专用）：
1. 素颜开场（1-2 个）：原始状态
2. 护肤打底（2-3 个）：基础护理
3. 底妆（3-4 个）：粉底/遮瑕/定妆
4. 眼妆（3-4 个）：眼影/眼线/睫毛
5. 唇妆（2-3 个）：口红/唇彩
6. 完妆展示（1-2 个）：对比/成品
```

### 动作识别增强

```
动作分类（美妆专用）：
- 打底类：洁面/水乳/防晒
- 底妆类：粉底/遮瑕/定妆
- 色彩类：眼影/腮红/口红
- 工具类：刷具/美妆蛋/睫毛夹
```

### 高潮示例

```
判断高潮（美妆专用）：
- 产品挤出到涂抹的瞬间
- 眼影颜色显色瞬间
- 睫毛夹翘动作
- 完妆前后对比
```

---

## 降本技巧

### 1. JSON 强制（避免解析失败重试）

```python
# Qwen-VL-Plus 支持 response_format
response = client.chat.completions.create(
    model="qwen-vl-plus",
    response_format={"type": "json_object"},  # 强制 JSON
    messages=[...]
)
```

### 2. 重试容错（处理偶发非 JSON 输出）

```python
import json
import re

def safe_parse(response_text):
    """从容错文本中提取 JSON"""
    try:
        return json.loads(response_text)
    except:
        # 尝试从 markdown 代码块提取
        m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
        if m:
            return json.loads(m.group(1))
        # 尝试提取第一个 {...}
        m = re.search(r'\{[^{}]*\}', response_text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
    return None
```

### 3. 并发调用（Python）

```python
import concurrent.futures

def batch_analyze(image_paths, prompt, max_workers=10):
    """并发调用视觉 API"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(analyze_one, p, prompt): p for p in image_paths}
        results = {}
        for future in concurrent.futures.as_completed(futures):
            path = futures[future]
            try:
                results[path] = future.result()
            except Exception as e:
                results[path] = {"error": str(e)}
        return results
```

### 4. 缓存（同图不同 prompt 不重复调用）

```python
import hashlib
from pathlib import Path

def cached_analyze(image_path, prompt_key, analyzer):
    """按图片 hash + prompt 类型缓存"""
    img_hash = hashlib.md5(Path(image_path).read_bytes()[:1024]).hexdigest()
    cache_key = f"{img_hash}_{prompt_key}"
    if cache_exists(cache_key):
        return load_cache(cache_key)
    result = analyzer(image_path)
    save_cache(cache_key, result)
    return result
```

### 5. 模型分级（按任务难度选模型）

| 任务 | 推荐模型 | 成本 |
|---|---|---|
| 主体位置识别（简单） | Doubao-vision-lite | ¥0.001/千 |
| 场景内容分析（中等） | Qwen-VL-Plus | ¥0.008/千 |
| 三联图判断（复杂） | Qwen-VL-Max | ¥0.02/千 |
| 故事弧编排（文本） | DeepSeek-V3 | ¥0.001/千 |

---

## 验证清单（生产环境部署）

部署 prompt 到生产前，建议跑一遍：

- [ ] **测试 10 张图**：JSON 输出全部可解析（无文字干扰）
- [ ] **并发测试**：20 个并发调用稳定返回（无 rate limit）
- [ ] **缓存命中率**：>30%（同素材多次处理场景）
- [ ] **降级方案**：API 失败时有 fallback（如固定 cut_duration=1.5）
- [ ] **成本监控**：单视频处理成本 < 5 元（用 Doubao-vision-pro + 上述降本）

---

## 完整 Pipeline 串接示例

```python
# 主流程
def process_video(source_clips, vertical="dining"):
    """从原始素材到 30s 精华"""
    # 1. 视频标准化（FFmpeg）
    normalized = normalize_clips(source_clips)  # 统一方向/分辨率

    # 2. 场景切分（PySceneDetect）
    scenes = detect_scenes(normalized)  # ~100-150 个

    # 3. 抽代表帧（FFmpeg）
    probes = extract_middle_frames(scenes)

    # 4. 场景内容分析（AI 视觉）
    scene_data = batch_analyze(probes, PROMPT_SCENE_ANALYSIS.format(vertical=vertical))

    # 5. 三联图生成（PIL）
    triplets = make_triplets_for_scenes(scenes)

    # 6. 高光瞬时检测（AI 视觉）
    highlight_data = batch_analyze(triplets, PROMPT_HIGHLIGHT_DETECTION.format(vertical=vertical))

    # 7. 计算切片位置
    cut_plan = compute_cuts(scenes, highlight_data)

    # 8. 故事弧编排（AI 文本）
    storyboard = orchestrate(scene_data, cut_plan, vertical=vertical)

    # 9. 切割+拼接+BGM（FFmpeg）
    final = render(storyboard, bgm="bgm.mp3")
    return final
```

---

*配套文档：《项目总结与服务化分析.md》*
*生成时间：2026-07-02*
