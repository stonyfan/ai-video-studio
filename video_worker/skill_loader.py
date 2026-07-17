"""读取 configs/skills/<name>/SKILL.md，解析 frontmatter + body。

SKILL.md 格式（Anthropic 标准）：
    ---
    name: cocktail-mixology
    description: ...
    applies_to:
      main_objects: [...]
      action_types: [...]
    target_duration_default: 30
    ---
    # Body...
    ## Prompt Snippet
    ```
    <注入到 LLM prompt 末尾的文本>
    ```
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = _PROJECT_ROOT / "configs" / "skills"


@dataclass
class Skill:
    name: str
    description: str = ""
    applies_to: dict = field(default_factory=dict)
    target_duration_default: Optional[int] = None
    recommended_pace: str = ""
    body: str = ""            # 完整 markdown body
    prompt_snippet: str = ""  # 从 body 里抽出的 Prompt Snippet 代码块
    principle: str = ""       ## Principle 段
    archetype: str = ""       ## Archetype 段（含五阶段骨架表）
    action_priorities: str = ""  ## Action Priorities 段（T1-T4）
    pacing: str = ""          ## Pacing 段（每阶段时长/段数指导）

    def full_prompt_block(self) -> str:
        """组合各段为完整 prompt 注入块（给 LLM 看）。

        顺序：Archetype → Action Priorities → Pacing → Prompt Snippet
        （Prompt Snippet 放最后，因为是"硬指令"；其他是"参考信息"）
        """
        parts = []
        if self.archetype:
            parts.append(f"**骨架参考**：\n{self.archetype}")
        if self.action_priorities:
            parts.append(f"**动作优先级参考**：\n{self.action_priorities}")
        if self.pacing:
            parts.append(f"**节奏参考**：\n{self.pacing}")
        if self.prompt_snippet:
            parts.append(f"**核心指令**：\n{self.prompt_snippet}")
        return "\n\n".join(parts)


_FMRX = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def _parse_frontmatter(raw: str) -> tuple[dict, str]:
    """用 pyyaml 解析 frontmatter（项目已有依赖）。"""
    m = _FMRX.match(raw)
    if not m:
        return {}, raw
    fm_text, body = m.group(1), m.group(2)
    try:
        import yaml
        fm = yaml.safe_load(fm_text) or {}
    except Exception:
        return {}, body
    return fm if isinstance(fm, dict) else {}, body


def _extract_prompt_snippet(body: str) -> str:
    """从 body 里找 '## Prompt Snippet' 下的代码块。"""
    m = re.search(
        r"##\s*Prompt Snippet.*?```(?:[a-zA-Z]*)?\n(.*?)```",
        body, re.DOTALL,
    )
    return m.group(1).strip() if m else ""


def _extract_section(body: str, title: str) -> str:
    """从 markdown body 抓 '## <title>' 段落到下一个 '## ' 之间。

    返回该段正文（含表格、代码块等），去掉 section 标题行本身。
    找不到返回空字符串。
    """
    # 匹配 '## Title' 或 '## Title — ...' 或 '## Title（...）'
    pattern = rf"##\s+{re.escape(title)}[^\n]*\n(.*?)(?=\n##\s+|\Z)"
    m = re.search(pattern, body, re.DOTALL)
    return m.group(1).strip() if m else ""


def load_skill(name: str) -> Optional[Skill]:
    """根据 name 加载 SKILL.md。不存在返回 None。"""
    skill_path = SKILLS_DIR / name / "SKILL.md"
    if not skill_path.exists():
        return None
    raw = skill_path.read_text(encoding="utf-8")
    fm, body = _parse_frontmatter(raw)
    snippet = _extract_prompt_snippet(body)
    applies_raw = fm.get("applies_to") or {}
    if not isinstance(applies_raw, dict):
        applies_raw = {}
    return Skill(
        name=fm.get("name", name),
        description=str(fm.get("description", "")),
        applies_to={
            "main_objects": applies_raw.get("main_objects", []) if isinstance(applies_raw.get("main_objects"), list) else [],
            "action_types": applies_raw.get("action_types", []) if isinstance(applies_raw.get("action_types"), list) else [],
        },
        target_duration_default=int(fm["target_duration_default"]) if fm.get("target_duration_default") else None,
        recommended_pace=str(fm.get("recommended_pace", "")),
        body=body.strip(),
        prompt_snippet=snippet,
        principle=_extract_section(body, "Principle"),
        archetype=_extract_section(body, "Archetype"),
        action_priorities=_extract_section(body, "Action Priorities"),
        pacing=_extract_section(body, "Pacing"),
    )


def list_skills() -> list[Skill]:
    """列出所有可用 skill。"""
    if not SKILLS_DIR.exists():
        return []
    skills = []
    for d in sorted(SKILLS_DIR.iterdir()):
        if d.is_dir() and (d / "SKILL.md").exists():
            s = load_skill(d.name)
            if s:
                skills.append(s)
    return skills


def match_skill_for_scenes(scenes: list[dict]) -> Optional[Skill]:
    """根据 scenes 的 main_objects / action_types 命中率自动匹配 skill。
    scenes: list of dict，至少含 main_objects + action_type 字段。
    """
    if not scenes:
        return None
    skills = list_skills()
    if not skills:
        return None

    # 统计素材里出现过的 main_objects 和 action_types
    objects_counter: dict[str, int] = {}
    actions_counter: dict[str, int] = {}
    for s in scenes:
        for obj in (s.get("main_objects") or []):
            obj_lower = obj.lower()
            objects_counter[obj_lower] = objects_counter.get(obj_lower, 0) + 1
        act = (s.get("action_type") or "").lower()
        if act:
            actions_counter[act] = actions_counter.get(act, 0) + 1

    best_skill: Optional[Skill] = None
    best_score = 0.0
    for sk in skills:
        if not sk.applies_to:
            continue
        target_objects = [o.lower() for o in sk.applies_to.get("main_objects", [])]
        target_actions = [a.lower() for a in sk.applies_to.get("action_types", [])]
        obj_hits = sum(1 for o in target_objects if any(o in k or k in o for k in objects_counter))
        act_hits = sum(1 for a in target_actions if any(a in k or k in a for k in actions_counter))
        denom = max(len(target_objects) + len(target_actions), 1)
        score = (obj_hits + act_hits) / denom
        if score > best_score and score >= 0.2:
            best_score = score
            best_skill = sk
    return best_skill
