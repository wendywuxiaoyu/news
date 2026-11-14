#!/usr/bin/env python3
"""周三 / 周日学习复盘：读 Notion 笔记 → 判断进度 → 发邮件；没写就发提醒。

环境变量与 weekly_digest.py 相同。
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import weekly_digest as wd  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = ROOT / "学习进度" / "自动复盘.md"

REMIND = """# 该更新学习笔记了

## 📌 本周任务 · W{week}　{title}

- **本周目标**：{goal}
- **动手**：{do}
- **交付**：{deliver}
- **过关标准**：{check}

---

过去 4 天，你的笔记里没有新内容。

不用写长，回答三句话就行：

1. 这周我做了什么？
2. 哪里卡住了？
3. 我怎么理解的？

写完这一页，下一次复盘就会带上你的进度判定。
"""

REVIEW = """你在给一位上班族做本周中段复盘。

计划本周目标：{goal}
计划交付物：{deliver}
验收标准：{check}

他写下的笔记：

{notes}

输出 Markdown，三小节，总长不超过 220 字：

### 进度判定
从「达标 / 部分完成 / 滞后」选一个，一句理由，必须引用笔记里的原话。

### 缺口
最关键的 1–2 个缺口。

### 下一步
一个 30 分钟内能开始的具体动作。

规则：不客套，不编造他没写过的东西。"""


def main() -> int:
    week = wd.load_week_task()
    if not week:
        print("没有找到 week-tasks.json，退出")
        return 1
    week_no, task = week

    notes = wd.fetch_notes(days=4)
    print(f"第 {week_no} 周，读到 {len(notes)} 篇笔记")

    if notes:
        joined = "\n\n".join(f"【{title}】\n{text}" for title, text in notes)
        body = wd.call_llm(
            REVIEW.format(
                goal=task["goal"],
                deliver=task["deliver"],
                check=task["check"],
                notes=joined,
            )
        )
        body = f"# 学习复盘 · W{week_no} {task['title']}\n\n{body}"
        subject = f"学习复盘 · W{week_no}"
    else:
        body = REMIND.format(
            week=week_no,
            title=task["title"],
            goal=task["goal"],
            do=task["do"],
            deliver=task["deliver"],
            check=task["check"],
        )
        subject = f"该更新学习笔记了 · W{week_no}"

    wd.send_mail(subject, wd.md_to_html(body))
    print("邮件已发送")

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    header = "" if LOG_FILE.is_file() else "# 自动复盘记录\n\n"
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(f"{header}## {stamp} · W{week_no}（{len(notes)} 篇笔记）\n\n{body}\n\n---\n\n")
    print("已写入", LOG_FILE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
