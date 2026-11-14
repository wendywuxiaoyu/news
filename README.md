# AI 技能学习工作区

> 一个地方放齐：学习计划、进度、周报、生成脚本、云端配置。
> 对应仓库：https://github.com/wendywuxiaoyu/news
> 建立日期：2026-11-14

---

## 一、目录结构

```
E:\技能学习\                      ← 这个文件夹 = 本地工作区 + GitHub 仓库
├─ 学习计划\      AI 学习路线图（14 周，原理 + 使用）
├─ 学习进度\      学习进度追踪（每周复盘后更新）
├─ 周报\          AI 周报，一期一个 md + html
├─ 配置\
│   └─ plan-context.md     当前周次，周报生成时读取
├─ prompts\
│   └─ digest_prompt.md    周报的写作指令，想改风格改这里
├─ scripts\
│   ├─ weekly_digest.py    云端主程序：抓取 → 模型 → 渲染 → 发信 → Notion
│   ├─ send_email.py       本地发信
│   └─ md2html.py          Markdown 转邮件 HTML
├─ .github\workflows\
│   └─ weekly.yml          GitHub Actions 定时任务
└─ README.md

E:\技能学习-私密配置\             ← 故意放在仓库外面，不会被上传
└─ email-config.json            邮箱授权码
```

**重要**：`E:\技能学习` 里现在**不含任何密钥**，可以整个拖到 GitHub 上，不会泄露。

---

## 二、每周发生什么

每周一北京时间 09:00，GitHub 自动：

1. 抓取 7 个 RSS 源过去 8 天的条目
2. 交给模型，按 `prompts/digest_prompt.md` 的要求写解读
3. 生成 `周报/2026-WXX.md` 和 `.html`
4. 发到你的邮箱
5. 把这一期提交回仓库（留档）
6. 如果配了 Notion，同时写成一个 Notion 子页面

---

## 三、云端部署：三步

### 第 1 步：上传文件

打开 https://github.com/wendywuxiaoyu/news → **Add file → Upload files** → 把 `E:\技能学习` 里的**所有内容**拖进去 → Commit。

> 整个文件夹都可以拖，里面没有密钥。
> 如果 `.github` 没被传上去（某些浏览器会跳过隐藏文件夹）：
> 点 **Add file → Create new file**，文件名直接输入 `.github/workflows/weekly.yml`，
> 内容从本地的 `E:\技能学习\.github\workflows\weekly.yml` 复制粘贴。

### 第 2 步：配 Secrets

仓库 → **Settings → Secrets and variables → Actions**

**Secrets（加密，创建后不可见）**

| 名称 | 值 |
|---|---|
| `MAIL_USER` | `2845824687@qq.com` |
| `MAIL_PASS` | QQ 邮箱授权码（和 `E:\技能学习-私密配置\email-config.json` 里的一致） |
| `MAIL_TO` | `2845824687@qq.com` |
| `LLM_API_KEY` | 模型平台的 API Key |
| `NOTION_TOKEN` | 可选 |

**Variables（明文）**

| 名称 | 值 |
|---|---|
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` |
| `LLM_MODEL` | `deepseek-chat` |
| `NOTION_PAGE_ID` | 可选 |

### 第 3 步：手动跑一次

仓库 → **Actions** → 左侧 **Weekly AI Digest** → 右侧 **Run workflow**。

看日志：抓取了多少条、模型有没有报错、邮件发没发出去。成功一次之后，每周一自动运行。

---

## 四、本地手动跑

```powershell
cd E:\技能学习

# 只抓取，检查源通不通（不需要 Key）
python scripts\weekly_digest.py --dry-run

# 生成但不发邮件
$env:LLM_API_KEY="你的key"
python scripts\weekly_digest.py --no-email

# 本地单独发信（会自动找到 私密配置 里的授权码）
python scripts\send_email.py --html 周报\2026-W46.html --subject "AI 周报 · 2026 年第 46 周"
```

---

## 五、Notion 怎么配

1. 打开 https://www.notion.so/my-integrations → **New integration** → 名称随意 → 复制 `secret_...`
2. Notion 里新建一个页面，命名「AI 学习」
3. 页面右上角 `⋯` → **连接** → 选中刚建的 integration
4. 复制页面链接，最后那串 32 位就是 `NOTION_PAGE_ID`
5. 把 token 和 ID 填到 GitHub 的 Secrets / Variables 里

配好后，每期周报会变成「AI 学习」下的一个子页面。

**注意**：Notion 里看到的是周报**内容**，不是邮件本身。表格会被跳过（Notion API 只支持文本块）。

---

## 六、改东西改哪里

| 想改什么 | 改哪个文件 |
|---|---|
| 周报风格、条目数、筛选标准 | `prompts/digest_prompt.md` |
| 抓哪些源 | `scripts/weekly_digest.py` 里的 `FEEDS` |
| 抓几天 | `.github/workflows/weekly.yml` 里的 `DIGEST_DAYS` |
| 每周几点跑 | 同上，`cron`（UTC 时间，北京时间减 8 小时） |
| 当前学到第几周 | `配置/plan-context.md` |
| 发件邮箱 | 仓库 Secrets |

---

## 七、安全

1. **仓库当前是 Public**，学习计划和进度任何人都能看到。介意的话：
   Settings → General → 最下方 Danger Zone → Change visibility → 改成 Private。
2. 邮箱授权码只存在两处：本地 `E:\技能学习-私密配置\`、GitHub Secrets。两处都不会出现在仓库文件里。
3. 授权码可随时在 QQ 邮箱重新生成，旧码立即失效。
4. `.gitignore` 已把 `email-config.json` 排除，将来装了 Git 也不会误提交。

---

## 八、成本

- GitHub Actions：这个任务一周不到 1 分钟，免费额度绰绰有余。
- 模型：每周约 3 万 token，DeepSeek 大约几分钱到一毛。
- 邮箱：免费。
