#!/usr/bin/env python3
"""发送 AI 周报邮件（QQ 邮箱 SMTP）。

用法:
    python scripts/send_email.py --html 周报/2026-W46.html --subject "AI 周报 · 2026 年第 46 周"
    python scripts/send_email.py --html ... --subject ... --dry-run

凭证从 配置/email-config.json 读取，不写在代码里。
465 端口走隐式 TLS，587 走 STARTTLS，任一失败自动回落。
"""

import argparse
import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from email.utils import formataddr, formatdate
from pathlib import Path


def resolve_config(explicit=None):
    """按优先级找配置文件：显式参数 > 环境变量 > 配置/ > 上级私密目录 > 根目录。"""
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    env_path = os.environ.get("MAIL_CONFIG")
    if env_path:
        candidates.append(Path(env_path))
    base = Path(__file__).resolve().parent.parent
    candidates += [
        base / "配置" / "email-config.json",
        base.parent / "技能学习-私密配置" / "email-config.json",
        base / "email-config.json",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return candidates[0]


def fail(msg: str) -> None:
    print(f"[失败] {msg}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="发送 AI 周报邮件")
    parser.add_argument("--html", required=True, help="邮件正文 HTML 路径")
    parser.add_argument("--subject", required=True, help="邮件主题")
    parser.add_argument("--config", default=None, help="配置文件路径（默认自动查找）")
    parser.add_argument("--dry-run", action="store_true", help="只校验不发送")
    args = parser.parse_args()

    html_path = Path(args.html)
    if not html_path.is_file():
        fail(f"找不到 HTML 文件：{html_path}")
    html = html_path.read_text(encoding="utf-8")
    if not html.strip():
        fail(f"HTML 文件为空：{html_path}")

    config_path = resolve_config(args.config)
    if not config_path.is_file():
        fail(f"找不到配置文件：{config_path}")
    # 用 utf-8-sig 兼容被记事本或 PowerShell 写入 BOM 的配置文件
    cfg = json.loads(config_path.read_text(encoding="utf-8-sig"))

    for key in ("smtpServer", "from", "to", "password"):
        if not str(cfg.get(key, "")).strip():
            fail(f"email-config.json 缺少字段或为空：{key}")

    msg = EmailMessage()
    msg["From"] = formataddr((cfg.get("displayName", "AI 周报"), cfg["from"]))
    msg["To"] = cfg["to"]
    msg["Subject"] = args.subject
    msg["Date"] = formatdate(localtime=True)
    msg.set_content("本邮件为 HTML 格式，请用支持 HTML 的邮件客户端查看。")
    msg.add_alternative(html, subtype="html")

    server = cfg["smtpServer"]
    ports = [int(cfg.get("smtpPort", 465)), 465, 587]
    seen, order = set(), []
    for p in ports:
        if p not in seen:
            seen.add(p)
            order.append(p)

    if args.dry_run:
        print(f"[DryRun] 配置可读；收件人 {cfg['to']}；正文 {len(html)/1024:.1f} KB；"
              f"候选端口 {order}；主题「{args.subject}」")
        return 0

    ctx = ssl.create_default_context()
    last_error = None

    for port in order:
        conn = None
        try:
            if port == 465:
                conn = smtplib.SMTP_SSL(server, port, timeout=30, context=ctx)
            else:
                conn = smtplib.SMTP(server, port, timeout=30)
                conn.ehlo()
                conn.starttls(context=ctx)
                conn.ehlo()

            conn.login(cfg["from"], cfg["password"])
            conn.send_message(msg)
            conn.quit()
            print(f"[成功] 已发送「{args.subject}」-> {cfg['to']}（端口 {port}）")
            return 0
        except smtplib.SMTPAuthenticationError as exc:
            print(
                "[失败] 认证被拒绝：授权码可能不正确或已失效。\n"
                "       请到 QQ 邮箱 → 设置 → 账号 → POP3/SMTP 服务，重新生成授权码，\n"
                f"       填入 email-config.json 的 password 字段后重试。\n       原始信息：{exc}",
                file=sys.stderr,
            )
            return 1
        except Exception as exc:  # 端口不通、TLS 失败等，换下一个端口
            last_error = exc
            print(f"[提示] 端口 {port} 失败：{exc}", file=sys.stderr)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    fail(f"所有候选端口均失败。最后一个错误：{last_error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
