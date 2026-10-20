# github-tech-stack-stats

抓取 GitHub 账号下**全部仓库（含私有）**的语言字节分布，存成带**多轮历史**的本地 SQLite，并生成一张 Top Languages 统计卡片（SVG）。

单文件脚本，只依赖 Python 3.9+ 标准库，无第三方包、无需虚拟环境。

<p align="center">
  <img alt="Top Languages" src="https://raw.githubusercontent.com/Haoke98/Haoke98/main/lang-stats.svg" width="420"/>
</p>

> 上面这张卡片由本脚本生成，产物提交在个人主页仓库 `Haoke98/Haoke98`，这里只放工具本身。

## 特性

- **全量统计**：公开 + 私有仓库逐一取 `/languages`，按字节汇总，不受 GitHub 自带语言条（只算公开仓库）的限制。
- **多轮历史，只追加**：每跑一次写入一条 `runs` 快照（仓库数、总字节、语言数、⭐/🍴/📝 总数），外加每仓库明细与聚合 JSON。历史轮次永不覆盖。
- **老库自动升级**：改了表结构不会让旧库炸掉。启动时比对 `PRAGMA table_info`，缺列就 `ALTER TABLE ADD COLUMN`（纯追加），**升级前自动生成 `lang-stats.db.bak-migration-<时间戳>` 快照**。
- **断点续跑**：每仓库语言数据缓存 30 分钟（`--cache-ttl` 可调），中断后重跑不会从头再抓。抓结论为"这仓库没有代码"的空结果会单独负缓存 6 小时，所以那些空仓库不会每次都被重新请求。
- **只改展示不动历史**：`--top` / `--theme` / `--output` 只影响出图，永远不会触发抓取；如果本轮 0 次 API 调用且仓库列表没变化，**不会新增 run 记录**，直接复用上一轮。
- **`--reuse-missing`**：某仓库语言接口返回空（限流 / 瞬时 5xx / 仓库临时不可达）时，沿用上一轮该仓库的数据，避免总量被悄悄削掉。
- **5 套配色主题**，输出 github-readme-stats 风格卡片。卡片宽度自适应：语言名列按实际文字宽度测量（不再写死），超长名才会用省略号截断，长名如 `Jupyter Notebook` 不会被色条盖住。
- **底部水印标注数据采集时间**：`Data collected 2026-07-08 17:44 UTC+08`，小字、居中、低透明度；时区显式写出（不依赖查看者本地区域），鼠标悬停可看到完整 ISO 时间戳。`--no-timestamp` 可关闭。

## 安装

```bash
git clone https://github.com/Haoke98/github-tech-stack-stats.git
cd github-tech-stack-stats
```

需要一个 GitHub token（fine-grained 即可）：至少要 **Metadata: Read**（列仓库）+ **Contents: Read**（读私有仓库语言），勾选全部私有仓库。

```bash
export GITHUB_TOKEN=github_pat_xxx     # 别写进命令行，会留在 shell 历史里
```

## 用法

```bash
# 抓取并入库（只存数据，不出图）
python3 generate-lang-stats.py

# 抓取 + 出图，产物直接写进个人主页仓库
python3 generate-lang-stats.py --svg -o ../Haoke98/lang-stats.svg

# 用上一轮数据补齐本轮抓取失败的仓库
python3 generate-lang-stats.py --reuse-missing --svg -o ../Haoke98/lang-stats.svg

# 不联网，直接从库里最新一轮出图
python3 generate-lang-stats.py --svg-only -T tokyonight -n 15 -o out.svg

# 看历史轮次
python3 generate-lang-stats.py --history
```

| 参数 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `-t, --token` | 无（回退到 `GITHUB_TOKEN`） | GitHub token |
| `-u, --username` | `Haoke98` | 目标账号 |
| `--db PATH` | 脚本同目录 `lang-stats.db` | SQLite 数据库路径 |
| `--cache PATH` | 脚本同目录 `lang-cache.json` | 接口缓存路径 |
| `-o, --output` | 脚本同目录 `lang-stats.svg` | SVG 输出路径 |
| `-T, --theme` | `merko` | `dark` / `merko` / `tokyonight` / `onedark` / `nord` |
| `-n, --top` | `20` | 卡片显示前 N 种语言 |
| `--svg` | 关 | 抓取后立即出图 |
| `--svg-only` | 关 | 不抓取，用库里最新一轮出图 |
| `--history` | 关 | 打印最近 5 轮快照 |
| `--no-cache` | 关 | 忽略缓存，强制重抓 |
| `--cache-ttl MIN` | `30` | 缓存有效期（分钟）；`0` 等于 `--no-cache` |
| `--reuse-missing` | 关 | 抓不到的仓库沿用上一轮数据 |
| `--save-json PATH` | 关 | 额外导出最新聚合数据为 JSON |
| `--no-timestamp` | 关 | 不显示卡片底部的采集时间水印 |
| `-h, --help` | — | 打印帮助 |
| `--version` | — | 打印版本号并退出 |

## 数据文件

`lang-stats.db` 与 `lang-cache.json` 都在 `.gitignore` 里，**只留在本地**，不会进版本库。数据库可以放在任意位置（`--db`），工具与数据彻底解耦。

## 常见疑问

**只说"我改了个主题，怎么又全量重抓了？"**

`--theme` / `--top` / `--output` 在代码里只传给 SVG 生成函数，连抓取函数的参数列表都进不去，**不可能**影响缓存。每次运行开头都会打印当前缓存状态：

```
🗃️  Cache: 279 entries, 256 fresh (TTL 30 min, oldest 12 min, 24 known-empty)
```

- `fresh` 接近 `entries` → 这一轮几乎不联网；
- `oldest` 超过 `TTL` → 条目全部过期，整轮重抓。

所以"改了主题就重抓"通常是**两次运行刚好跨过 30 分钟**。要么 `--cache-ttl 720` 放宽，要么干脆只换皮：

```bash
python3 generate-lang-stats.py --svg-only -T tokyonight -n 15 -o ../Haoke98/lang-stats.svg
```

`--svg-only` 不联网、不写库，纯粹拿库里最新一轮重画，改多少次主题都不会产生新 run。

**为什么有些仓库显示 `cache hit (known empty, 0 langs)`？**

它们的 `/languages` 返回空（空仓库，或像 `TyporaCrack` 那样 451 被下架）。这类结论会被负缓存 6 小时，否则每轮都要为它们白跑一次请求——你原来那 24 个 `Skipped` 就属于这类。

**为什么这轮 `Run ID` 没变？**

0 次 API 调用 + 仓库列表没变化 = 数据没有任何新信息，脚本不写新 run，直接复用上一轮并在日志里说明。历史里只留真正测到东西的轮次。

**卡片底部时间为什么不是"刚刚"？**

那一行是**数据采集时间**，不是出图时间。这里有两种情况都算正常：

- 用 `--svg-only` 重画：时间当然还是原来那一轮的采集时间；
- 本轮 0 次 API 调用（缓存全命中，见上面的 `Cache` 横幅）：没有新数据入库，脚本复用上一轮，于是底部也沿用那一轮的时间。

想让它变成当下时间，得真的抓一轮新数据（`--cache-ttl 0` 或等缓存过期）。

## 数据库结构

| 表 | 内容 |
| :--- | :--- |
| `runs` | 每轮一行：账号、时间、仓库数（公开/私有）、总字节、语言数、⭐/🍴/📝 总数 |
| `repo_languages` | 每轮 × 每仓库 × 每语言：字节数 |
| `repo_metadata` | 每轮 × 每仓库：stars/forks/issues/watchers/size/是否 fork/是否私有/时间戳 |
| `language_stats` | 每轮的聚合结果（JSON，供 `--svg-only` 快速取用） |

## 表结构升级策略

改表结构时**不要**靠删库重跑——那样历史全丢。正确姿势：

1. 在 `SCHEMA_UPGRADES` 里登记新列（纯追加，带 `DEFAULT`，旧行自动填默认值）；
2. `init_db()` 启动时自动补齐缺列；
3. 有 `repo_metadata` 明细的历史轮次，`backfill_run_totals()` 会把 ⭐/🍴/📝 汇总回填。

如果某轮统计是在采集元数据之前跑的，它的 ⭐/🍴 会是 0——这是"当时没采"，不是数据丢失。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

覆盖：老库就地升级不丢行、升级幂等且只备份一次、元数据回填、空库建表、新轮次追加不动历史；缓存按 TTL 命中/过期、空结果负缓存、纯重绘不新增 run、仓库列表变化必须落库。
