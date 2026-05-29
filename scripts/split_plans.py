"""
Split monolithic plan files into individual task files + create progress tracking docs.

Handles 4 heading formats:
  Phase 1: ## Task N: Title
  Phase 2: ### Task N: Title  (with non-task ### subsections inside tasks)
  Phase 3: ## Task N: Title
  Phase 4: ## TN: Title  (T1, T2, ... T34)
"""

import re
import os
from pathlib import Path

PLANS_DIR = Path("/data1/wangyafan/zhima_ai/claud_code/GraphRAG/docs/superpowers/plans")
TASKS_DIR = PLANS_DIR / "tasks"

plan_configs = [
    {
        "file": PLANS_DIR / "2026-05-29-phase1-document-parsing-qa-api-plan.md",
        "pattern": r"^## Task (\d+): (.+)",
        "phase": 1,
        "name": "文档解析 + 全文 QA + 指标 API",
    },
    {
        "file": PLANS_DIR / "2026-05-29-phase2-knowledge-graph-construction-plan.md",
        "pattern": r"^### Task (\d+): (.+)",
        "phase": 2,
        "name": "知识图谱构建",
        # Phase 2 has non-task h3 sections (供应链关系, 股权关系 etc.)
        # We need to ensure we only split on actual Task headings
        "task_only": True,
    },
    {
        "file": PLANS_DIR / "2026-05-29-phase3-multimodal-timeseries-plan.md",
        "pattern": r"^## Task (\d+): (.+)",
        "phase": 3,
        "name": "多模态理解 + 时序分析",
    },
    {
        "file": PLANS_DIR / "2026-05-29-phase4-incremental-production-plan.md",
        "pattern": r"^## T(\d+): (.+)",
        "phase": 4,
        "name": "增量摄入 + 生产化",
    },
]


def slugify(title: str, max_len: int = 50) -> str:
    """Convert title to kebab-case slug."""
    # Take first 50 chars of meaningful text
    s = title.lower()
    s = re.sub(r"[^a-z0-9一-鿿]+", "-", s)
    s = s.strip("-")
    # Keep only first max_len chars, but don't break in middle of a word
    if len(s) > max_len:
        s = s[:max_len].rstrip("-")
    return s


def split_plan(file_path: Path, pattern: str, phase: int, phase_name: str, task_only: bool = False):
    """Split a plan file into individual task files."""
    content = file_path.read_text(encoding="utf-8")

    # Split content using regex pattern
    task_starts = []
    for m in re.finditer(pattern, content, re.MULTILINE):
        task_starts.append((m.start(), int(m.group(1)), m.group(2).strip()))

    if not task_starts:
        print(f"  WARNING: No tasks found in {file_path.name}!")
        return []

    # Build task slices
    tasks = []
    for i, (start, num, title) in enumerate(task_starts):
        if i + 1 < len(task_starts):
            end = task_starts[i + 1][0]
        else:
            end = len(content)
        task_content = content[start:end].strip()
        tasks.append({"num": num, "title": title, "content": task_content})

    # Save individual task files
    phase_dir = TASKS_DIR / f"phase{phase}"
    phase_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    for t in tasks:
        slug = slugify(t["title"])
        fname = f"phase{phase}_task{t['num']:02d}_{slug}_plan.md"
        fpath = phase_dir / fname
        wrapped = f"# Task {t['num']}: {t['title']}\n\n{phase_name} 的第 {t['num']} 个任务。\n\n---\n\n{t['content']}\n"
        fpath.write_text(wrapped, encoding="utf-8")
        saved.append({"num": t["num"], "title": t["title"], "file": fname, "path": fpath})
        print(f"  ✓ Task {t['num']}: {fname}")

    return saved


def create_progress_doc(phase: int, phase_name: str, goal: str, tasks: list, plan_file: str):
    """Create a Chinese progress tracking document for a phase."""
    phase_dir = TASKS_DIR / f"phase{phase}"
    progress_path = phase_dir / "progress.md"

    # Build task table rows
    task_rows = []
    for t in tasks:
        file_link = f"[{t['file']}]({t['file']})"
        task_rows.append(f"| {t['num']} | {t['title']} | {file_link} | ⏳ 待开始 | - |")

    table = "\n".join(task_rows)

    content = f"""# Phase {phase}: {phase_name} — 进度跟踪

> **目标:** {goal}
>
> **计划文件:** [{plan_file}](../{plan_file})

## 执行状态总览

| 总任务数 | 已完成 | 进行中 | 待开始 |
|---------|-------|-------|-------|
| {len(tasks)} | 0 | 0 | {len(tasks)} |

## Task 列表

| # | 任务名称 | 计划文件 | 状态 | 备注 |
|---|---------|---------|------|------|
{table}

## 状态说明

- ⏳ **待开始** — 尚未执行
- 🔄 **进行中** — 正在执行
- ✅ **已完成** — 执行完毕
- ❌ **阻塞** — 存在依赖问题无法继续

## 笔记

<!-- 在此记录执行过程中的问题、决策、变更 -->

---
*最后更新: {os.popen('date +%Y-%m-%d').read().strip()}*
"""
    progress_path.write_text(content, encoding="utf-8")
    print(f"  ✓ Progress doc: {progress_path}")
    return progress_path


def main():
    TASKS_DIR.mkdir(parents=True, exist_ok=True)

    goals = {
        1: "构建核心文档解析管线、向量+全文索引、以及金融文档问答引擎",
        2: "构建 Neo4j 知识图谱，支持跨文档关联和图增强检索",
        3: "实现图表理解和时序金融分析能力",
        4: "系统生产化：增量摄入、性能优化、Web UI、监控告警",
    }

    for cfg in plan_configs:
        fpath = cfg["file"]
        if not fpath.exists():
            print(f"SKIP: {fpath.name} not found")
            continue

        print(f"\n=== Phase {cfg['phase']}: {cfg['name']} ===")
        tasks = split_plan(
            file_path=fpath,
            pattern=cfg["pattern"],
            phase=cfg["phase"],
            phase_name=cfg["name"],
            task_only=cfg.get("task_only", False),
        )

        if tasks:
            doc = create_progress_doc(
                phase=cfg["phase"],
                phase_name=cfg["name"],
                goal=goals[cfg["phase"]],
                tasks=tasks,
                plan_file=fpath.name,
            )

        print(f"  → {len(tasks)} tasks saved")

    print("\n=== Done! ===")


if __name__ == "__main__":
    main()