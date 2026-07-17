---
name: cocktail-mixology
description: 调酒视频剪辑 skill。适用于吧台、酒瓶、调酒器、鸡尾酒成品、冰块、倒酒动作等素材。叙事骨架 HOOK → SETUP → BUILD → GARNISH → SERVE，强调动作视觉冲击与节奏律动。
applies_to:
  main_objects: [cocktail, drink, glass, shaker, bottle, ice, liquid, liquor, wine, garnish, fruit, citrus, lemon, mint]
  action_types: [pour, shake, stir, layer, drop, garnish, close-up]
target_duration_default: 30
recommended_pace: fast
---

# Cocktail Mixology

## Principle

1. **动作驱动叙事**。调酒视频的灵魂是"调制动作的视觉冲击"——液体的倾倒、冰块的碰撞、分层的渐变、shake 的能量。优先选择 action_type 明确的段；静态空镜只用于节奏过渡。
2. **成品与过程交替**。观众要看到"我要这杯"和"怎么做出这杯"两件事。HOOK 给成品（如果有），BUILD 给过程，SERVE 收回成品形成闭环。
3. **快节奏短镜头**。短视频平台（抖音/小红书）的调酒内容默认快剪——单段 0.6–2.0s，BUILD 阶段可密集到 4–6 个 sub-shot。
4. **保留视觉峰值**。液体落下的瞬间、分层形成的瞬间、装饰物放置的瞬间——这些是"hook 时刻"，时长不能压缩。

## Archetype — 五阶段叙事骨架

```
HOOK (1-2s) → SETUP (1-2s) → BUILD (4-8s) → GARNISH (1-2s) → SERVE (1-2s)
```

| Stage | 角色 | 偏好 main_objects | 偏好 action_type |
|---|---|---|---|
| **HOOK** | 开场吸引：成品特写 / 第一杯倾倒入镜 | cocktail, glass, drink | close-up, pour |
| **SETUP** | 准备阶段：冰块入杯、工具就位、酒瓶入画 | ice, shaker, bottle, glass | drop, pour |
| **BUILD** | 核心调制：多角度多动作的密集剪辑（占视频 40-60% 时长） | shaker, bottle, liquid, glass | pour, shake, stir, layer |
| **GARNISH** | 装饰：柑橘皮、果片、装饰物落下 | garnish, fruit, citrus, lemon, mint | drop, garnish |
| **SERVE** | 成品呈现：最终特写 / 品鉴 / 可能的品牌 | cocktail, glass, drink | close-up |

**重要**：archetype 是**指导不是硬约束**。如果素材缺某个 stage（例如没有 GARNISH 段），跳过它，BUILD 的时长可以拉长补偿。

## Action Priorities（同一 stage 内挑段优先级）

```
T1（必选）：pour, layer              ← 视觉冲击最强
T2（高优先）：shake, drop, close-up   ← 节奏 + 焦点
T3（中优先）：stir, garnish           ← 过渡 + 收尾
T4（低优先）：static, broll           ← 仅当高优先段不够时填充
```

如果同 stage 内有多个 T1 段，按以下规则取舍：
- 优先 creation_time 不同的（避免同源重复视角）
- 优先 main_objects 多样的（一杯 vs 多瓶）
- 优先 highlight_score 高的

## Pacing（节奏指导）

- **HOOK**：1 段，1.0–2.0s（让成品看清）
- **SETUP**：1–2 段，0.6–1.5s（节奏起步）
- **BUILD**：3–6 段，每段 0.6–2.0s（密集剪辑，可以错落有致）
- **GARNISH**：1 段，0.8–1.5s（装饰动作要看清）
- **SERVE**：1 段，1.0–2.0s（收尾要稳，不要急切）

**节奏陷阱**（避免）：
- 不要把所有 pour 段都堆在 BUILD——分散到 SETUP（起步 pour）和 BUILD（核心 pour）更有节奏感
- 不要让 GARNISH 太长——装饰是"点睛"，不是"重头"
- 不要在 HOOK 用 shake/快动作——开场观众还没适应节奏，快动作会被忽略

## Prompt Snippet（注入到 LLM）

```
【当前 skill: cocktail-mixology 调酒视频剪辑】

请按 **HOOK → SETUP → BUILD → GARNISH → SERVE** 的五阶段叙事挑段与排序：

- HOOK：1 段成品特写或第一杯倾倒入镜（close-up / pour，1.0-2.0s）
- SETUP：1-2 段冰块/工具/酒瓶入画（drop / pour，0.6-1.5s）
- BUILD：3-6 段核心调制多镜头（pour / shake / stir / layer，每段 0.6-2.0s；占视频 40-60% 时长）
- GARNISH：1 段装饰物落下或放置（drop / garnish，0.8-1.5s）
- SERVE：1 段最终成品特写或品鉴（close-up，1.0-2.0s）

动作优先级（同 stage 内）：T1 pour/layer > T2 shake/drop/close-up > T3 stir/garnish > T4 static/broll。
若某 stage 在素材中找不到合适段，直接跳过；BUILD 的时长可拉长补偿。
narrative 用一句话点出"这是什么调酒、视觉亮点在哪"，例如"分层威士忌酸：冰镇杯口开场，柠檬皮油喷洒收尾"。
```

## Anti-patterns

- ❌ 把所有 pour 段堆在一起 → ✅ 分散到 SETUP + BUILD 两阶段
- ❌ GARNISH 段时长超过 2s → ✅ 控制在 0.8-1.5s
- ❌ SERVE 用快动作（shake/stir） → ✅ 用 close-up 稳定收尾
- ❌ BUILD 阶段所有段同源（同 creation_time） → ✅ 优先不同 creation_time 制造视角差异
- ❌ HOOK 用静态 broll → ✅ HOOK 必须有动态（pour 入画或成品微动）
