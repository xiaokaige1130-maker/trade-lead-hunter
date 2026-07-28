# TradeLead Hunter · 外贸获客台

**产品级 B2B 多源获客工作台** — 同一套代码支持：

| 形态 | 方式 |
|------|------|
| 本地工具 | `./start.sh` 或 `python -m app` |
| 云服务器 | `docker compose up -d` / systemd + uvicorn |
| 桌面安装包 | 规划中（PyInstaller / Electron，见 `scripts/build_desktop_notes.md`） |

> 默认**只入库能联系的线索**（邮箱 / 电话 / WhatsApp），并标注**业态（做什么）**与**联系人/职位画像**。

![license](https://img.shields.io/badge/license-MIT-blue) ![python](https://img.shields.io/badge/python-3.10%2B-green) ![version](https://img.shields.io/badge/version-2.0.0-purple)

---

## 功能

| 模块 | 说明 |
|------|------|
| 多源爬取 | 地图商户 · 黄页目录 · B2B 买家 · 域名深挖 · 邮箱模式 · 文本提取 · 一键组合 |
| 官网搜索 | DuckDuckGo 公开搜索 + contact 页提取 |
| 视频评论 | YouTube / TikTok / Instagram / Facebook（建议测试号） |
| 线索库 | 可联系筛选 · 业态 · 联系人 · 状态跟进 · CSV 导出 · 详情抽屉 |
| 产品化 | `config.yaml` · 环境变量 · API Token · Docker · OpenAPI |

对标说明与路线图：[`docs/PRODUCT_ROADMAP.md`](docs/PRODUCT_ROADMAP.md)

---

## 快速开始（本地）

```bash
git clone https://github.com/xiaokaige1130-maker/trade-lead-hunter.git
cd trade-lead-hunter

python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

./start.sh
# 或
python -m app
```

浏览器打开：http://127.0.0.1:8866/

- API 文档：http://127.0.0.1:8866/api/docs  
- 健康检查：http://127.0.0.1:8866/api/health  

---

## Docker 云部署

```bash
docker compose up -d --build
# 访问 http://服务器IP:8866/
```

建议生产环境：

```bash
export LEADHUNTER_API_TOKEN="请换成长随机串"
# 请求头带: X-API-Token: 请换成长随机串
```

数据持久化：Docker volume `lead_data` 或挂载 `./data`。

---

## 配置

主配置：[`config.yaml`](config.yaml)

| 环境变量 | 含义 |
|----------|------|
| `LEADHUNTER_HOST` | 监听地址，默认 `0.0.0.0` |
| `LEADHUNTER_PORT` | 端口，默认 `8866` |
| `LEADHUNTER_DATA` | 数据目录 |
| `LEADHUNTER_API_TOKEN` | API 鉴权 Token |
| `LEADHUNTER_CORS` | CORS 来源，逗号分隔 |

---

## 目录结构

```
app/
  main.py              # FastAPI 入口
  config.py            # 配置加载
  db.py                # SQLite 线索库
  profile.py           # 业态 / 联系人画像
  multi_scraper.py     # 多源爬取
  hunter.py            # 网页搜索
  comment_intercept.py # 社媒评论
  extractor.py         # 邮箱电话提取
static/index.html      # 专业工具型前端工作台
config.yaml            # 产品配置
Dockerfile             # 容器镜像
docker-compose.yml     # 一键编排
docs/PRODUCT_ROADMAP.md
scripts/build_desktop_notes.md
```

---

## 产品原则

1. **能联上才入库** — 不堆只有店名的垃圾行  
2. **每条可解释** — 业态、来源、联系方式  
3. **配置即部署** — 本地 / 云 / 未来安装包同一内核  
4. **工具感 UI** — 侧栏导航 + 工作台 + 高密度表格（不是营销官网）  
5. **合规默认** — 公开数据、礼貌延迟；社媒请用测试号  

---

## License

MIT
