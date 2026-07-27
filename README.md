# 外贸获客台 · 社媒评论截流

从 **TikTok / YouTube / Facebook / Instagram** 热门视频评论中截流公开联系方式（邮箱、WhatsApp、Telegram、电话），并支持官网网页获客与线索库导出。

> 仅采集用户主动公开的信息，用于合法 B2B 商务拓展。请遵守平台条款与当地反垃圾营销法规。

## 功能

| 模块 | 说明 |
|------|------|
| 视频评论截流 | 粘贴视频链接，抓评论并提取联系方式 |
| 关键词找热门 | YouTube 搜索相关视频批量截流 |
| 粘贴评论提取 | TK/INS/FB 风控时手动粘贴评论提取（最稳） |
| 官网网页获客 | 按国家+行业搜索公开邮箱/WhatsApp |
| 线索库 | 筛选、状态跟进、导出 CSV |
| Cookies | 提升 TikTok / Instagram / Facebook 成功率 |

## 平台支持

| 平台 | 自动抓评论 | 建议 |
|------|-----------|------|
| YouTube | 高 | 直接链接 / 关键词 |
| TikTok | 中 | 配置 cookies 或粘贴评论 |
| Instagram | 中低 | cookies 或粘贴评论 |
| Facebook | 中低 | 公开视频 / cookies / 粘贴 |

## 快速开始

```bash
# 克隆
git clone https://github.com/xiaokaige1130-maker/trade-lead-hunter.git
cd trade-lead-hunter

# 虚拟环境
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 启动
./start.sh
# 或
python -m uvicorn app.main:app --host 127.0.0.1 --port 8866
```

浏览器打开：http://127.0.0.1:8866/

## 目录结构

```
app/
  main.py               # FastAPI 入口
  comment_intercept.py  # 社媒评论截流
  hunter.py             # 网页获客
  extractor.py          # 邮箱/WhatsApp 提取
  db.py                 # SQLite 线索库
static/index.html       # 前端界面
data/                   # 本地数据库与 cookies（不入库）
```

## 合规提示

- 只处理公开评论与公开网页上的联系方式
- 勿骚扰、勿批量垃圾营销、勿倒卖数据
- Cookies 仅保存在本机 `data/cookies.txt`，切勿提交到 Git

## License

MIT
