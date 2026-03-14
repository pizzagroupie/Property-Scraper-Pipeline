# 🏠 Property Scraper Pipeline

自动爬取海外设计感房产网站，推送新房源到 Telegram。

## 支持的网站（第一梯队）

| 网站 | 国家 | 特点 | 货币 |
|------|------|------|------|
| [Aucoot](https://www.aucoot.com) | 英国 | 设计感房产 | GBP |
| [Historiska Hem](https://historiskahem.se) | 瑞典 | 北欧老公寓 | SEK |
| [Inigo](https://www.inigo.com) | 英国 | 历史建筑 | GBP |

## 快速开始

### 1. 克隆/复制到你的 GitHub 仓库

把这些文件放到一个新的 GitHub 仓库（或你现有的仓库）里。

### 2. 设置 GitHub Secrets

在仓库 Settings → Secrets and variables → Actions 中添加：

- `TELEGRAM_BOT_TOKEN` — 你的 Telegram Bot token
- `TELEGRAM_CHAT_ID` — 默认 `1031987552`（已在 config.py 中设置）

### 3. 本地测试

```bash
pip install -r requirements.txt

# 设置环境变量
export TELEGRAM_BOT_TOKEN="你的bot token"
export TELEGRAM_CHAT_ID="1031987552"

# 运行
python main.py
```

### 4. GitHub Actions 自动运行

推送到 GitHub 后，Actions 会每天 UTC 8:00（北京时间下午4点）自动运行。
也可以在 Actions 页面手动触发 (workflow_dispatch)。

## 文件说明

```
├── main.py                 # 主入口：串联爬取→去重→推送
├── config.py               # 配置：汇率、Telegram、爬虫参数
├── models.py               # 统一数据模型 PropertyListing
├── scraper_aucoot.py       # Aucoot 爬虫
├── scraper_historiska.py   # Historiska Hem 爬虫
├── scraper_inigo.py        # Inigo 爬虫
├── telegram_sender.py      # Telegram 消息发送
├── seen_listings.json      # 已推送房源记录（自动更新）
├── requirements.txt        # Python 依赖
├── .github/workflows/
│   └── scrape.yml          # GitHub Actions 定时任务
└── .gitignore
```

## 更新汇率

编辑 `config.py` 中的 `EXCHANGE_RATES`：

```python
EXCHANGE_RATES = {
    "GBP": 9.2,    # 1 GBP ≈ 9.2 CNY
    "SEK": 0.68,   # 1 SEK ≈ 0.68 CNY
}
```

## Telegram 消息格式

每个新房源会收到一条格式化消息，包含：
- 🏠 地址 + 城市
- 💰 价格（原币 + 人民币）
- 📐 面积
- 🛏🚿 卧室/卫生间
- 🏛 建筑年代 / 建筑师
- 📝 描述摘要
- 📋 户型图链接
- 📸 图片链接（前5张）
- 🔗 原文链接

每次运行结束还会发一条日报汇总。

## 后续扩展

第二梯队网站（待添加）：
- Fantastic Frank（robots.txt 限制）
- Uchi Japan（Algolia API）

第三梯队：
- The Modern House（反爬需 playwright）
- Clarke & Partners（内容适配度待定）
