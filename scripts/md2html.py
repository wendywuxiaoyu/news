#!/usr/bin/env python3
"""极简 Markdown -> 邮件友好 HTML 转换器（无第三方依赖）。

用法:
    python tools/md2html.py 输入.md 输出.html

只支持周报用到的语法：标题、段落、粗体、行内代码、链接、列表、引用、表格、分隔线。
所有样式内联，避免邮件客户端剥离 <style>。
"""

import html
import re
import sys

FONT = "-apple-system,'Segoe UI','Microsoft YaHei',Helvetica,Arial,sans-serif"


def esc(text: str) -> str:
    return html.escape(text, quote=False)


def inline(text: str) -> str:
    """处理行内标记。先转义 HTML，再替换 markdown 标记。"""
    out = []
    codes = []

    def stash(m):
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", stash, text)
    text = esc(text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(
        r"\[([^\]]+)\]\(([^)\s]+)\)",
        r'<a href="\2" style="color:#2563eb;text-decoration:none">\1</a>',
        text,
    )

    def unstash(m):
        code = esc(codes[int(m.group(1))])
        return (
            '<code style="background:#f3f4f6;padding:1px 5px;border-radius:3px;'
            'font-family:Consolas,Menlo,monospace;font-size:13px">' + code + "</code>"
        )

    return re.sub(r"\x00(\d+)\x00", unstash, text)


def heading(level: int, text: str) -> str:
    if level == 1:
        return (
            '<h1 style="font-size:23px;line-height:1.4;margin:0 0 18px;color:#111827;'
            f'font-weight:700">{inline(text)}</h1>'
        )
    if level == 2:
        return (
            '<h2 style="font-size:18px;line-height:1.5;margin:34px 0 14px;color:#111827;'
            'font-weight:700;border-left:4px solid #2563eb;padding-left:10px">'
            f"{inline(text)}</h2>"
        )
    return (
        '<h3 style="font-size:15px;line-height:1.6;margin:26px 0 10px;color:#1f2937;'
        f'font-weight:700">{inline(text)}</h3>'
    )


def paragraph(lines) -> str:
    body = inline(" ".join(lines))
    return (
        '<p style="font-size:15px;line-height:1.8;margin:0 0 14px;color:#374151">'
        f"{body}</p>"
    )


def bullet_list(items) -> str:
    rows = "".join(
        '<li style="margin:0 0 8px;line-height:1.75">' + inline(it) + "</li>" for it in items
    )
    return (
        '<ul style="font-size:15px;color:#374151;margin:0 0 16px;padding-left:22px">'
        + rows
        + "</ul>"
    )


def ordered_list(items) -> str:
    rows = "".join(
        '<li style="margin:0 0 8px;line-height:1.75">' + inline(it) + "</li>" for it in items
    )
    return (
        '<ol style="font-size:15px;color:#374151;margin:0 0 16px;padding-left:22px">'
        + rows
        + "</ol>"
    )


def blockquote(lines) -> str:
    body = "<br>".join(inline(x) for x in lines if x)
    return (
        '<blockquote style="margin:0 0 18px;padding:12px 16px;background:#f9fafb;'
        "border-left:3px solid #d1d5db;color:#4b5563;font-size:14px;line-height:1.8\">"
        + body
        + "</blockquote>"
    )


def table(rows) -> str:
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    if len(cells) < 2:
        return ""
    header, body = cells[0], cells[2:] if re.match(r"^:?-{2,}:?$", cells[1][0] or "") else cells[1:]

    head = "".join(
        '<th style="border:1px solid #e5e7eb;background:#f3f4f6;padding:8px 10px;'
        'text-align:left;font-size:13px;color:#111827">' + inline(c) + "</th>"
        for c in header
    )
    body_html = ""
    for row in body:
        tds = "".join(
            '<td style="border:1px solid #e5e7eb;padding:8px 10px;font-size:13px;'
            'line-height:1.7;color:#374151">' + inline(c) + "</td>"
            for c in row
        )
        body_html += "<tr>" + tds + "</tr>"

    return (
        '<table style="border-collapse:collapse;width:100%;margin:16px 0 20px;'
        f'font-family:{FONT}">'
        "<thead><tr>" + head + "</tr></thead><tbody>" + body_html + "</tbody></table>"
    )


def convert(md: str) -> str:
    lines = md.splitlines()
    blocks = []
    i, n = 0, len(lines)

    while i < n:
        raw = lines[i]
        s = raw.strip()

        if not s:
            i += 1
            continue

        if re.match(r"^-{3,}$", s):
            blocks.append(
                '<hr style="border:none;border-top:1px solid #e5e7eb;margin:30px 0">'
            )
            i += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            blocks.append(heading(len(m.group(1)), m.group(2)))
            i += 1
            continue

        if s.startswith("|"):
            group = []
            while i < n and lines[i].strip().startswith("|"):
                group.append(lines[i].strip())
                i += 1
            blocks.append(table(group))
            continue

        if s.startswith(">"):
            group = []
            while i < n and lines[i].strip().startswith(">"):
                group.append(lines[i].strip().lstrip(">").strip())
                i += 1
            blocks.append(blockquote(group))
            continue

        if re.match(r"^[-*]\s+", s):
            group = []
            while i < n and re.match(r"^[-*]\s+", lines[i].strip()):
                group.append(re.sub(r"^[-*]\s+", "", lines[i].strip()))
                i += 1
            blocks.append(bullet_list(group))
            continue

        if re.match(r"^\d+\.\s+", s):
            group = []
            while i < n and re.match(r"^\d+\.\s+", lines[i].strip()):
                group.append(re.sub(r"^\d+\.\s+", "", lines[i].strip()))
                i += 1
            blocks.append(ordered_list(group))
            continue

        group = []
        while i < n:
            st = lines[i].strip()
            if (
                not st
                or st.startswith("|")
                or st.startswith(">")
                or re.match(r"^#{1,6}\s", st)
                or re.match(r"^[-*]\s+", st)
                or re.match(r"^\d+\.\s+", st)
                or re.match(r"^-{3,}$", st)
            ):
                break
            group.append(st)
            i += 1
        if group:
            blocks.append(paragraph(group))

    return wrap("\n".join(blocks))


def wrap(body: str) -> str:
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"></head>'
        f'<body style="margin:0;padding:0;background:#eef0f3;font-family:{FONT}">'
        '<div style="max-width:680px;margin:0 auto;padding:0 12px">'
        '<div style="background:#ffffff;padding:32px 28px 40px;margin:24px 0 40px;'
        'border-radius:8px">'
        + body
        + "</div></div></body></html>"
    )


def main() -> int:
    if len(sys.argv) != 3:
        print("用法: python tools/md2html.py 输入.md 输出.html", file=sys.stderr)
        return 2
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, encoding="utf-8") as fh:
        md = fh.read()
    with open(dst, "w", encoding="utf-8") as fh:
        fh.write(convert(md))
    print(f"已生成 {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
