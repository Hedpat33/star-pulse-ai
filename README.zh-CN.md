# star-pulse-ai

[English](README.md) | 简体中文

生成 GitHub AI 项目 Star 增长排行榜（Markdown 文件），可定时无人值守运行。

## 简介

每次运行时抓取 GitHub 上一批 AI 主题标签下的热门项目，与上一次运行对比，按 **Star 增量**排出增长最快的 TOP 榜单，并生成一份 Markdown 报告。

- 首次运行只记录基线（不出榜单），第二次运行开始产出排行榜
- 仅与上一次运行对比，不做长期趋势分析
- 支持可选的 `GITHUB_TOKEN`（提升 API 限流额度）
- **轻量**：第三方依赖仅 `requests`，无数据库、无后台服务，跑完即退出，状态文件不到 1 MB——非常适合 NAS、树莓派等低配设备长期定时运行

## 输出效果

每次运行生成一个按日期命名的文件，如 `output/20261002.md`（同日重复运行会覆盖），内容包括：

1. **排名表格**：排名、项目、Star 增量、Star 总量、名次变化（↑/↓/—/🆕）
2. **项目详情**：与排名同序的完整项目描述列表
3. **离榜附录**：上次在榜、本次跌出的项目（折叠展示）

## 快速开始

**1. 安装依赖**

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

**2. 运行**

```bash
.venv/bin/python -m starpulse
```

**3. 查看结果**

- 排行榜：`output/YYYYMMDD.md`
- 运行状态：`state/` 目录（自动维护，无需手动处理）

标签、榜单条数、Star 门槛等常用配置见 [config.json](config.json)。

**（可选）环境变量**

```bash
export GITHUB_TOKEN=ghp_xxx                               # 提升 API 限流额度，不设也能运行
export FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx   # 每次生成榜单后向飞书群发一张 TOP 10 卡片
export FEISHU_SECRET=xxx                                  # 机器人开启「签名校验」时才需要
```

未设置 `FEISHU_WEBHOOK_URL` 即跳过通知，发送失败也不影响榜单生成。

## License

See [LICENSE](LICENSE).
