#!/usr/bin/env python3
"""AI 周报生成器（云端版，仅依赖标准库）。

流程：抓取 RSS → 调 LLM 生成解读 → 渲染 Markdown/HTML → 发邮件 → 可选同步 Notion。

环境变量：
  MAIL_USER / MAIL_PASS / MAIL_TO   SMTP 账号（QQ 邮箱授权码），必填
  SMTP_SERVER                       默认 smtp.qq.com
  SMTP_PORT                         默认 465
  LLM_API_KEY                       OpenAI 兼容接口的密钥，必填
  LLM_BASE_URL                      默认 https://api.deepseek.com/v1
  LLM_MODEL                         默认 deepseek-chat
  NOTION_TOKEN / NOTION_PAGE_ID     可选，都填才会同步
  DIGEST_DAYS                       默认 8，抓取最近多少天

用法：
  python scripts/weekly_digest.py --dry-run     # 只抓取，不调用模型、不发送
  python scripts/weekly_digest.py --no-email    # 生成文件但不发邮件
"""

from __future__ import annotations

import argparse
import json
import os
import re
import smtplib
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, formatdate
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
DIGEST_DIR = ROOT / "周报"
CONFIG_DIR = ROOT / "配置"
PROMPT_FILE = ROOT / "prompts" / "digest_prompt.md"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from md2html import convert as md_to_html  # noqa: E402

UA = "Mozilla/5.0 (compatible; dsh-weekly-digest/1.0)"

FEEDS = [
    ("Simon Willison", "https://simonwillison.net/atom/everything/"),
    ("OpenAI", "https://openai.com/news/rss.xml"),
    ("Google AI", "https://blog.google/technology/ai/rss/"),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml"),
    ("量子位", "https://www.qbitai.com/feed"),
    ("机器之心", "https://www.jiqizhixin.com/rss"),
    ("Latent Space", "https://www.latent.space/feed"),
]

BUILTIN_PROMPT = """你是我的 AI 行业情报分析员。下面是我订阅源在过去一周的原始条目。
请写一份中文周报，只保留真正影响"我会怎么用 AI"的信息。

写作要求：
1. 开头「本周三件事」，3 条，每条一句话说清是什么 + 一句"所以呢"。
2. 主体「逐条解读」，每条固定三段：**发生了什么**（事实，2-3 句）、**意味着什么**（判断，2 句）、**对你的影响**（具体到动作或"与你无关"）。
3. 只保留三类信息：能力边界变化、价格或速度变化、新形态。其余全部丢弃，宁少勿多。
4. 不确定的地方写明"未核实"，不要编造数字。
5. 结尾给「本周该记住的一个判断」和「下周关注」。
6. 直接输出 Markdown，不要用代码块包裹全文。

日期范围：{date_range}

{plan_context}

原始条目：

{items}
"""


def log(msg: str) -> None:
    print(msg, flush=True)


def fetch(url: str, timeout: int = 25) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def strip_html(text: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (text.replace("&amp;", "&").replace("&lt;", "<")
                .replace("&gt;", ">").replace("&quot;", '"')
                .replace("&#39;", "'").replace("&nbsp;", " "))
    return re.sub(r"\s+", " ", text).strip()


def parse_feed(raw: bytes, source: str):
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []

    entries = []
    for node in root.iter():
        if localname(node.tag) not in ("item", "entry"):
            continue

        title, link, summary, published = "", "", "", ""
        for child in node:
            name = localname(child.tag)
            if name == "title":
                title = (child.text or "").strip()
            elif name == "link":
                link = child.get("href") or (child.text or "").strip()
            elif name in ("summary", "description", "content", "encoded"):
                summary = summary or (child.text or "").strip()
            elif name in ("published", "updated", "pubdate", "date"):
                published = published or (child.text or "").strip()

        if not title:
            continue
        entries.append(
            {
                "source": source,
                "title": strip_html(title),
                "link": link,
                "summary": strip_html(summary)[:900],
                "date": parse_date(published),
            }
        )
    return entries


def parse_date(text: str):
    if not text:
        return None
    text = text.strip()
    formats = (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d",
    )
    for fmt in formats:
        try:
            dt = datetime.strptime(text, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def collect(days: int):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    items, failures = [], []

    for source, url in FEEDS:
        try:
            entries = parse_feed(fetch(url), source)
            fresh = [e for e in entries if e["date"] is None or e["date"] >= cutoff]
            items.extend(fresh)
            log(f"  [ok]   {source}: {len(fresh)} 条")
        except Exception as exc:  # 单个源失败不影响整体
            failures.append((source, str(exc)[:120]))
            log(f"  [skip] {source}: {exc}")

    items.sort(key=lambda e: e["date"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return items[:45], failures


def build_prompt(items, days, plan_context: str) -> str:
    template = PROMPT_FILE.read_text(encoding="utf-8") if PROMPT_FILE.is_file() else BUILTIN_PROMPT
    today = datetime.now()
    date_range = f"{(today - timedelta(days=days)).strftime('%Y-%m-%d')} 至 {today.strftime('%Y-%m-%d')}"

    blocks = []
    for it in items:
        when = it["date"].strftime("%Y-%m-%d") if it["date"] else "日期未知"
        blocks.append(
            f"### [{it['source']}] {it['title']}\n"
            f"- 时间：{when}\n- 链接：{it['link']}\n- 摘要：{it['summary']}\n"
        )

    return template.format(
        date_range=date_range, plan_context=plan_context, items="\n".join(blocks)
    )


def call_llm(prompt: str) -> str:
    api_key = os.environ.get("LLM_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少 LLM_API_KEY")

    base = (os.environ.get("LLM_BASE_URL") or "https://api.deepseek.com/v1").rstrip("/")
    model = os.environ.get("LLM_MODEL") or "deepseek-chat"

    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": "你是一位冷静、克制的 AI 行业分析员，只输出 Markdown。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def send_mail(subject: str, html: str) -> None:
    user = os.environ.get("MAIL_USER", "").strip()
    password = os.environ.get("MAIL_PASS", "").strip()
    to = os.environ.get("MAIL_TO", "").strip() or user
    if not (user and password and to):
        raise RuntimeError("缺少 MAIL_USER / MAIL_PASS / MAIL_TO")

    server = os.environ.get("SMTP_SERVER", "smtp.qq.com")
    ports = [int(os.environ.get("SMTP_PORT") or "465"), 465, 587]

    msg = EmailMessage()
    msg["From"] = formataddr(("AI 周报", user))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg.set_content("本邮件为 HTML 格式，请用支持 HTML 的客户端查看。")
    msg.add_alternative(html, subtype="html")

    ctx = ssl.create_default_context()
    seen, ordered = set(), []
    for p in ports:
        if p not in seen:
            seen.add(p)
            ordered.append(p)

    last = None
    for port in ordered:
        conn = None
        try:
            if port == 465:
                conn = smtplib.SMTP_SSL(server, port, timeout=30, context=ctx)
            else:
                conn = smtplib.SMTP(server, port, timeout=30)
                conn.ehlo()
                conn.starttls(context=ctx)
                conn.ehlo()
            conn.login(user, password)
            conn.send_message(msg)
            conn.quit()
            log(f"  [ok]   邮件已发送（端口 {port}）-> {to}")
            return
        except smtplib.SMTPAuthenticationError as exc:
            raise RuntimeError(f"邮件认证失败，授权码可能失效：{exc}") from exc
        except Exception as exc:
            last = exc
            log(f"  [retry] 端口 {port} 失败：{exc}")
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    raise RuntimeError(f"邮件发送失败：{last}")


def notion_blocks(markdown: str):
    blocks = []
    for raw in markdown.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.strip() in ("---", "***"):
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            continue
        if line.strip().startswith("|"):
            continue  # 表格在 Notion 里会失真，跳过
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            key = f"heading_{level}"
            blocks.append(
                {"object": "block", "type": key, key: {"rich_text": rich(m.group(2))}}
            )
            continue
        if re.match(r"^[-*]\s+", line.strip()):
            blocks.append(
                {"object": "block", "type": "bulleted_list_item",
                 "bulleted_list_item": {"rich_text": rich(re.sub(r"^[-*]\s+", "", line.strip()))}}
            )
            continue
        if re.match(r"^\d+\.\s+", line.strip()):
            blocks.append(
                {"object": "block", "type": "numbered_list_item",
                 "numbered_list_item": {"rich_text": rich(re.sub(r"^\d+\.\s+", "", line.strip()))}}
            )
            continue
        if line.strip().startswith(">"):
            blocks.append(
                {"object": "block", "type": "quote",
                 "quote": {"rich_text": rich(line.strip().lstrip(">").strip())}}
            )
            continue
        blocks.append(
            {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich(line)}}
        )
    return blocks[:400]


def rich(text: str):
    cleaned = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    cleaned = re.sub(r"`(.+?)`", r"\1", cleaned)
    cleaned = re.sub(r"\[(.+?)\]\((.+?)\)", r"\1 (\2)", cleaned)
    return [{"type": "text", "text": {"content": cleaned[:1800]}}]


def sync_notion(title: str, markdown: str) -> None:
    token = os.environ.get("NOTION_TOKEN", "").strip()
    page_id = os.environ.get("NOTION_PAGE_ID", "").strip()
    if not (token and page_id):
        log(
            "  [skip] Notion 未配置，跳过同步 "
            f"(token={'有' if token else '缺'}, page_id={'有' if page_id else '缺'})"
        )
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    blocks = notion_blocks(markdown)

    def call(url, method="GET", body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=60) as resp:
            text = resp.read().decode("utf-8")
            return json.loads(text) if text else {}

    # 先清掉同名旧页面，避免手动重跑时越积越多
    try:
        children = call(f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100")
        for child in children.get("results", []):
            if (
                child.get("type") == "child_page"
                and child["child_page"]["title"].strip() == title
            ):
                call(f"https://api.notion.com/v1/blocks/{child['id']}", "DELETE")
                log(f"  [ok]   清理同名旧页面：{title}")
    except Exception as exc:
        log(f"  [warn] 清理旧页面失败（继续新建）：{exc}")

    created = call(
        "https://api.notion.com/v1/pages",
        "POST",
        {
            "parent": {"page_id": page_id},
            "properties": {"title": {"title": [{"text": {"content": title}}]}},
            "children": blocks[:100],
        },
    )
    block_id = created["id"]
    rest = blocks[100:]
    while rest:
        call(
            f"https://api.notion.com/v1/blocks/{block_id}/children",
            "PATCH",
            {"children": rest[:100]},
        )
        rest = rest[100:]
    log(f"  [ok]   Notion 已同步：{title}")


def load_plan_context() -> str:
    path = CONFIG_DIR / "plan-context.md"
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8").strip()
    return f"我的学习计划上下文（用于写「与你学习计划的关联」一栏）：\n\n{text}"


def load_week_task():
    """按日期计算当前是第几周，返回 (周次, 任务字典)。"""
    path = CONFIG_DIR / "week-tasks.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    weeks = data.get("weeks") or []
    if not weeks:
        return None
    start = datetime.strptime(data["start"], "%Y-%m-%d").date()
    offset = (datetime.now().date() - start).days // 7
    index = max(0, min(offset, len(weeks) - 1))
    return weeks[index]["week"], weeks[index]


def task_section(week_no: int, task: dict) -> str:
    return (
        f"## 📌 本周任务 · W{week_no}　{task['title']}\n\n"
        f"- **本周目标**：{task['goal']}\n"
        f"- **动手**：{task['do']}\n"
        f"- **交付**：{task['deliver']}\n"
        f"- **过关标准**：{task['check']}\n"
    )


NOTES_PAGE_TITLE = "笔记"  # 容器页标题里带「笔记」两个字即可


def _notion_call(url: str, token: str, method: str = "GET", body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


def blocks_to_text(blocks) -> str:
    lines = []
    for block in blocks:
        kind = block.get("type")
        payload = block.get(kind) or {}
        text = "".join(x.get("plain_text", "") for x in payload.get("rich_text", []))
        if text.strip():
            prefix = "- " if kind in ("bulleted_list_item", "numbered_list_item") else ""
            lines.append(prefix + text.strip())
    return "\n".join(lines)


def fetch_notes(days: int = 8):
    """读取「学习笔记」页面下最近几篇子页面的文本。"""
    token = os.environ.get("NOTION_TOKEN", "").strip()
    page_id = os.environ.get("NOTION_PAGE_ID", "").strip()
    if not (token and page_id):
        return []

    try:
        root = _notion_call(
            f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100", token
        )
    except Exception as exc:
        log(f"  [warn] 读取笔记目录失败：{exc}")
        return []

    notes_page = next(
        (
            c["id"]
            for c in root.get("results", [])
            if c.get("type") == "child_page"
            and NOTES_PAGE_TITLE in c["child_page"]["title"]
        ),
        None,
    )
    if not notes_page:
        return []

    try:
        sub = _notion_call(
            f"https://api.notion.com/v1/blocks/{notes_page}/children?page_size=50", token
        )
    except Exception as exc:
        log(f"  [warn] 读取笔记列表失败：{exc}")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    pages = [c for c in sub.get("results", []) if c.get("type") == "child_page"]
    pages.sort(key=lambda c: c.get("created_time", ""), reverse=True)

    notes = []
    for page in pages[:10]:
        try:
            stamp = datetime.strptime(
                page.get("created_time", "")[:19], "%Y-%m-%dT%H:%M:%S"
            ).replace(tzinfo=timezone.utc)
            if stamp < cutoff:
                continue
        except Exception:
            pass
        try:
            body = _notion_call(
                f"https://api.notion.com/v1/blocks/{page['id']}/children?page_size=100", token
            )
        except Exception:
            continue
        text = blocks_to_text(body.get("results", []))
        # 只有标题、没写内容的页面不算笔记
        if len(text.strip()) >= 40:
            notes.append((page["child_page"]["title"], text[:2500]))
    return notes


DIAGNOSIS_PROMPT = """你在检查一位上班族的每周学习进展。

计划本周目标：{goal}
计划交付物：{deliver}
验收标准：{check}

他这一周的笔记（可能有多篇）：

{notes}

只输出 Markdown，三小节，总长不超过 220 字：

### 进度判定
从「达标 / 部分完成 / 滞后」中选一个，一句理由，必须引用笔记里的具体内容。

### 缺口
最关键的 1–2 个缺口，说清楚缺的是什么。

### 本周建议
给一个具体动作，他能在 30 分钟内开始做。

规则：
- 笔记与目标无关，就直接写「笔记未覆盖本周目标」，不要硬凑。
- 不要编造他没写过的内容。
- 不说客套话。"""


def build_diagnosis_prompt(task: dict, notes) -> str:
    joined = "\n\n".join(f"【{title}】\n{text}" for title, text in notes)
    return DIAGNOSIS_PROMPT.format(
        goal=task["goal"], deliver=task["deliver"], check=task["check"], notes=joined
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只抓取，不调模型不发邮件")
    parser.add_argument("--no-email", action="store_true", help="生成文件但不发邮件")
    parser.add_argument("--days", type=int, default=int(os.environ.get("DIGEST_DAYS") or "8"))
    args = parser.parse_args()

    now = datetime.now()
    iso = now.isocalendar()
    week_tag = f"{iso.year}-W{iso.week:02d}"

    log(f"== 生成周报 {week_tag} ==")
    items, failures = collect(args.days)
    log(f"共 {len(items)} 条候选，{len(failures)} 个源失败")

    if args.dry_run:
        for it in items[:10]:
            log(f"  - [{it['source']}] {it['title'][:60]}")
        return 0

    if not items:
        log("[失败] 没有抓到任何条目，终止")
        return 1

    week = load_week_task()
    plan_context = load_plan_context()
    week_no = task = None
    if week:
        week_no, task = week
        plan_context = (
            f"当前是我学习的第 {week_no} 周，本周主题：{task['title']}。\n\n{plan_context}"
        )

    markdown = call_llm(build_prompt(items, args.days, plan_context))
    if week_no:
        markdown = task_section(week_no, task) + "\n---\n\n" + markdown

        notes = fetch_notes(args.days)
        if notes:
            try:
                diagnosis = call_llm(build_diagnosis_prompt(task, notes))
                markdown = (
                    markdown.rstrip()
                    + "\n\n---\n\n## 📊 上周进度诊断（根据你的 Notion 笔记）\n\n"
                    + diagnosis
                    + "\n"
                )
                log(f"  [ok]   进度诊断已生成（读 {len(notes)} 篇笔记）")
            except Exception as exc:
                log(f"  [warn] 进度诊断失败：{exc}")
        else:
            log("  [skip] 未找到「学习笔记」页面或最近无笔记，跳过进度诊断")
    DIGEST_DIR.mkdir(parents=True, exist_ok=True)
    md_path = DIGEST_DIR / f"{week_tag}.md"
    md_path.write_text(markdown, encoding="utf-8")
    html_path = DIGEST_DIR / f"{week_tag}.html"
    html_path.write_text(md_to_html(markdown), encoding="utf-8")
    log(f"  [ok]   已写入 {md_path.name} / {html_path.name}")

    if not args.no_email:
        send_mail(f"AI 周报 · {iso.year} 年第 {iso.week} 周", html_path.read_text(encoding="utf-8"))

    try:
        sync_notion(f"AI 周报 · {week_tag}", markdown)
    except Exception as exc:
        log(f"  [warn] Notion 同步失败（不影响邮件）：{exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
