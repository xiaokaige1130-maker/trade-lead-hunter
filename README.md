# 外贸获客台 · 多源客户数据

从公开渠道批量获取 B2B 客户线索：**社媒评论截流** + **地图商户** + **黄页目录** + **B2B 买家** + **域名深挖** + **邮箱模式生成**。

> 仅采集公开信息，用于合法商务拓展。请遵守平台条款与当地营销法规。

## 功能一览

| 模块 | 说明 |
|------|------|
| 视频评论截流 | TikTok / YouTube / Facebook / Instagram 评论 → 邮箱/WhatsApp |
| 关键词热门视频 | YouTube 搜索相关视频批量截流 |
| 粘贴评论提取 | 风控时手动粘贴评论提取联系方式 |
| **地图商户** | OpenStreetMap / Nominatim：店名、电话、邮箱、官网 |
| **黄页目录** | 目录站/黄页向搜索 + contact 页深挖 |
| **B2B 买家** | importer / wholesaler / distributor 专项 |
| **域名深挖** | 批量官网 contact/about 提取 |
| **邮箱生成** | sales@ / info@ 等模式 + MX 存活探测 |
| **文本提取** | 任意名录/HTML 海量抠邮箱电话 |
| **一键组合** | 地图 + 目录 + B2B 三管齐下 |
| 线索库 | 筛选、状态、导出 CSV |

## 快速开始

```bash
git clone https://github.com/xiaokaige1130-maker/trade-lead-hunter.git
cd trade-lead-hunter
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
./start.sh
# 默认 http://127.0.0.1:8866/
```

## 多源爬取 API 示例

```bash
# 地图商户
curl -X POST http://127.0.0.1:8866/api/scrape/maps \
  -H 'Content-Type: application/json' \
  -d '{"keyword":"furniture","country_code":"AE","city":"dubai","limit":15}'

# 一键组合
curl -X POST http://127.0.0.1:8866/api/scrape/combo \
  -H 'Content-Type: application/json' \
  -d '{"keyword":"LED light","country_code":"US","city":"miami","use_maps":true,"use_directory":true,"use_b2b":true}'

# 邮箱模式
curl -X POST http://127.0.0.1:8866/api/scrape/email-gen \
  -H 'Content-Type: application/json' \
  -d '{"companies":["acme-trading.com"],"verify_mx":true}'
```

## 目录

```
app/
  main.py                # FastAPI
  comment_intercept.py   # 社媒评论截流
  multi_scraper.py       # 多源客户爬取
  hunter.py              # 网页搜索获客
  extractor.py           # 联系方式提取
  db.py                  # SQLite 线索库
static/index.html        # Web UI
```

## 合规

- 只处理公开网页/公开评论/开放地图数据
- 勿骚扰、勿垃圾群发、勿倒卖数据
- `data/cookies.txt` 与本地数据库不会进入 Git

## License

MIT
