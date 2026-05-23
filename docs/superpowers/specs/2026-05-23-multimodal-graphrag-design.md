# 多模态金融 GraphRAG 系统设计

## 项目概况

- **场景**：金融文档分析（A 股公告、研报、个股新闻、港股美股公告/新闻）
- **规模**：百万级 PDF/文本，持续增量摄入
- **用户**：小团队内部使用
- **查询能力**：全文 QA + 跨文档关联 + 实体/事件图谱 + 结构化提取 + 时序对比
- **技术路线**：方案 B — 可控 Graph（Docling + Neo4j + Milvus 混合检索）

## 一、顶层架构

```
查询层 → 查询路由 → 混合检索 → 结果合成 → LLM 回答
图谱层 → LangExtract + LLM 抽取 → Neo4j 知识图谱 → Cypher 查询
向量层 → HTML 分块 → BGE-M3 Embedding → Milvus 语义检索
解析层 → Docling/Marker/GLM-OCR/Qwen-VL → HTML + 元数据 JSON
```

**核心数据流**：原始文档 → HTML 解析 → 分块+Embedding(→Milvus) + 实体关系抽取(→Neo4j) → 混合检索 → LLM 生成

## 二、多模态文档解析层

### 工具链

| 工具 | 用途 |
|------|------|
| **Docling** (主力) | PDF/PPT/图片 → HTML，保留 rowspan/colspan |
| **Marker** (辅助) | Docling 解析失败时的 PDF 兜底 |
| **Qwen-VL** | 图表/截图理解，生成结构化描述 |
| **GLM-OCR** | 扫描件 OCR |
| **Pandas** | Excel/CSV 直接解析 |

### 输出格式

统一输出 HTML + 元数据 JSON：

```json
{
    "doc_id": "ann_20240523_600000",
    "metadata": {
        "title": "XX公司2024年第一季度报告",
        "company": "...", "stock_code": "600000",
        "publish_date": "2024-05-23",
        "doc_type": "quarterly_report",
        "industry": "银行", "source_url": "...",
        "file_type": "pdf", "page_count": 45
    },
    "html_content": "<h1>...</h1><table>...</table>...",
    "images": [{"id": "img_001", "description": "营收趋势柱状图...", "bbox": [...]}],
    "tables": [{"id": "tab_001", "caption": "合并资产负债表", "html": "<table>...</table>"}],
    "parse_confidence": 0.95
}
```

### 设计决策：HTML 而非 Markdown

财务报表存在大量合并单元格（rowspan/colspan），Markdown 不支持。HTML 完整保留表格语义，下游分块和 Embedding 时 strip 标签取纯文本即可，LLM 对 HTML 理解良好。

### MinerU 兜底

Docling 解析置信度 < 0.7 的文档自动路由到 MinerU 处理（预计 < 5%），保留高精度但避免全量使用的资源成本。

## 三、文本分块 + 向量存储

### 多粒度分块策略

```
完整 HTML 文档
  ├── 按 <h1>-<h6> 切分 → Section Chunk (500-2000 token，table 不拆散)
  ├── 独立提取 <table> → Table Chunk (完整 HTML table + 章节上下文)
  └── 固定窗口滑动切分 → Small Chunk (512 token，精确匹配)
```

### Chunk 数据模型

```json
{
    "chunk_id": "ann_20240523_600000_s3_t2",
    "doc_id": "ann_20240523_600000",
    "chunk_type": "table",
    "content_html": "<table>...</table>",
    "content_text": "合并资产负债表 资产总计...",
    "context": {
        "section_title": "三、合并财务报表",
        "prev_chunk_summary": "..."
    },
    "metadata": { "stock_code": "600000", "publish_date": "2024-05-23", "doc_type": "quarterly_report", "industry": "银行" }
}
```

### Embedding 模型

**BGE-M3**（BAAI 开源）：原生中文支持，8192 token 输入，1024 维向量，本地部署。

### 向量数据库

**Milvus**：支持十亿级向量，标量过滤（按公司/行业/日期/文档类型），实现元数据预过滤 + 向量检索。

## 四、知识图谱 Schema

### 实体类型（4 层）

**Layer 1 — 核心（Phase 1）**

| 实体 | 核心属性 |
|------|---------|
| Company | stock_code, full_name, market, board, listing_date, business_scope |
| Person | name, gender, title(董事长/总经理/CFO/独立董事) |
| Industry | sw_code(申万), level(1/2/3), name |
| Event | event_type, date, description, impact_score(-1到1) |
| FinancialIndicator | name(营收/净利润/ROE/EPS/毛利率/资产负债率/经营现金流), value, unit, period, currency |
| Report | doc_id, title, doc_type, publish_date, source |

**Layer 2 — 扩展（Phase 2）**

| 实体 | 核心属性 |
|------|---------|
| Shareholder | type(国有法人/境内机构/境外机构/自然人/高管), share_count, ownership_pct |
| Product | name, category, revenue_contribution_pct |
| Concept | name, type(行业/地域/政策/事件) |
| Policy | issuing_body, doc_number, effective_date, keywords |
| Subsidiary | ownership_pct, registered_capital |
| Location | country, province, city, economic_zone |

**Layer 3 — A 股特有（Phase 2-3）**

| 实体 | 核心属性 |
|------|---------|
| STStatus | status(ST/*ST), trigger_reason, start/end_date |
| SharePledge | pledgor, pledgee, share_count, pledge_ratio |
| ShareFreeze | frozen_party, freezing_court, share_count, freeze_period |
| ExecutiveChange | change_type(离任/新任/兼任), reason |

**Layer 4 — 多模态（Phase 3）**

| 实体 | 核心属性 |
|------|---------|
| TableBlock | caption, html, table_type(资产负债表/利润表/现金流量表/股东变动) |
| ChartImage | chart_type(柱状图/折线图/K线图/组织架构), qwen_vl_description, data_points |
| MarketDataPoint | date, open/high/low/close, volume, change_pct |
| NewsArticle | source, sentiment(positive/neutral/negative), keywords |
| ResearchReport | brokerage, analyst, rating(买入/增持/中性/减持/卖出), target_price |

### 关系类型（6 大类 30+ 关系）

**公司关系**：subsidiary_of, competes_with, supplies_to, partners_with, acquired_by, invests_in

**人物关系**：employs, holds_shares, controls

**事件关系**：triggers, affects, involves_entity

**分类归属**：in_industry, has_concept, produces, located_in, in_market

**文档关联**：published_by, mentions, contains_table, contains_chart, covers_stock

**A 股特殊**：under_status, pledged_shares, frozen_shares, executive_change, affected_by_policy

**指标关系**：reports_metric, benchmarked_against, forecasted_by

### 事件分类（12 类公告事件 + 4 类市场事件）

公告事件：业绩发布、分红送转、增减持、股份回购、股权质押/解押、股权冻结、高管变动、重大资产重组、再融资、ST/退市风险、违规处罚、诉讼仲裁

市场事件：行业政策出台、宏观政策调整、概念热点形成、突发事件

## 五、实体关系抽取 Pipeline

### 分层抽取策略

```
L1 实体 (Company, Person, Industry, Location)
  → 字典匹配 + API 数据直接写入 Neo4j（不做 LLM 抽取）
  原因：公司名录、人物库、申万行业、地域有完整数据源

L2 深层关系 + 事件
  → LangExtract (LLM-based)
  抽取：supplies_to, holds_shares, employs, triggers 等
  事件：12 类公告事件 + 论元角色

L3 财务指标
  → API 直接写入，不抽取
  指标以外部接口数据为唯一真相来源

文档关联
  → 解析阶段自动生成，含 mentions, contains_table, contains_chart
```

### 为什么混合而非全 LLM

- 百万级文档全走 LLM 抽取成本过高
- L1 实体有完整的外部数据源，字典匹配比 LLM 更准确
- LLM 聚焦在深层关系和事件抽取（约占 40% 调用量）
- LangExtract 的 source grounding 确保抽取可追溯原文

## 六、查询引擎与混合检索

### 查询路由

用户问题 → 意图分类 → 4 条路径：全文 QA / 图谱查询 / 指标查询 / 混合查询

### 5 类查询的执行路径

| 查询类型 | 示例 | 路径 |
|---------|------|------|
| 全文 QA | "茅台 Q3 营收多少？" | 向量检索 → LLM → API 校验指标值 |
| 跨文档关联 | "宁德时代的供应链？" | Neo4j 图遍历 → 向量验证出处 |
| 实体事件图谱 | "新能源行业近 3 年并购事件" | Neo4j(Industry→Company→Event) |
| 结构化提取 | "所有银行股的 ROE" | API 直接查询 |
| 时序对比 | "新能源 vs 传统能源研发投入" | API(多期) + 向量(定性) |

### 混合检索流程

1. 问题改写 + 实体链接
2. 并行检索：Milvus(语义) + Neo4j(关系) + API(指标)
3. 上下文融合（API 数据优先）
4. LLM 生成回答

### 数据优先级

- 财务指标数值：API > 图谱 > 文档 chunk
- 关系/事件：图谱 > 文档 chunk
- 定性描述/背景：文档 chunk

## 七、技术栈总览

| 组件 | 选型 | 说明 |
|------|------|------|
| 文档解析 | Docling + Marker + Qwen-VL + GLM-OCR | HTML 输出，保留表格结构 |
| OCR | GLM-OCR | 扫描件，替代 PaddleOCR |
| 图数据库 | Neo4j | 成熟稳定，Cypher 查询 |
| 向量数据库 | Milvus | 亿级向量支持，标量过滤 |
| Embedding | BGE-M3 | 中文，8192 token，本地部署 |
| LLM Proxy | vLLM | 部署 GLM-4 / DeepSeek / Qwen 等 |
| 对象存储 | MinIO | 原始 PDF + HTML |
| 任务队列 | Redis | 异步处理调度 |
| NER/RE | LangExtract | L2 深层关系 + 事件抽取 |
| 图表理解 | Qwen-VL | 财报图表结构化描述 |
| Web 框架 | FastAPI | 查询 API |

## 八、硬件部署

### 推荐配置

| 组件 | 推荐配置 | 用途 |
|------|---------|------|
| CPU | 64 核 | 文档解析、分块 |
| 内存 | **128 GB** | 解析中间态、Neo4j 缓存 |
| GPU | 2× A100/4090 | Embedding + Qwen-VL + GLM-OCR + vLLM |
| 存储 | 8 TB NVMe | 原始文件 + HTML + Milvus 索引 + Neo4j 数据 |

### 存储估算（百万文档）

```
原始 PDF:     100万 × 2MB   = 2 TB
解析后 HTML:  100万 × 0.5MB = 500 GB
Chunks+索引:  约 200 GB
Milvus 向量:  5000万 × 1024维 = 200 GB
Neo4j 图:     5000万节点 + 2亿边 = 500 GB-1 TB
─────────────────────────────────────
合计: 含冗余约 8 TB
```

### 服务部署

Docker Compose: Milvus + Neo4j + MinIO + Redis + vLLM + FastAPI + 解析/Embedding/抽取 Worker

## 九、Phase 划分

### Phase 1：文档解析 + 全文 QA + 指标 API

**目标**：把文档变成可检索的知识库

- Docling + Marker + Qwen-VL 解析成 HTML
- 多粒度分块 + BGE-M3 + Milvus
- 财务指标 API 对接写入 Neo4j
- L1 实体字典匹配写入 Neo4j
- 全文 QA + 指标查询 API

**验证**：10 万文档导入检索，指标类问题返回 API 数据 + 原文引用，召回率 > 90%

### Phase 2：知识图谱构建

**目标**：实体关系 + 事件图谱，支撑跨文档关联

- LangExtract 抽取 L2 深层关系（供应链、股权、任职...）
- 12 类公告事件抽取
- 实体链接 + 图谱去重合并
- 混合检索引擎（Graph + Vector 并行）

**验证**：供应链查询返回关联公司及出处，关系抽取准确率 > 85%

### Phase 3：多模态理解 + 时序分析

**目标**：图表关联 + 时序对比

- ChartImage 与文档引用的自动关联
- 表格 HTML 结构化增强
- MarketDataPoint 行情数据接入
- 财务指标时序对比分析
- 多跳推理查询

### Phase 4：增量摄入 + 生产化

**目标**：系统稳定运行

- 增量文档监听自动解析入库
- 图过期策略（旧事件/概念降权）
- 性能优化（检索延迟 < 2s）
- 前端 Web UI
- 监控 + 告警

## 十、关键设计决策

1. **HTML 替代 Markdown** — 财务报表合并单元格 Markdown 无法表示
2. **Docling 替代 MinerU**（主力） — 资源消耗更低，MinerU 做低置信度兜底
3. **GLM-OCR 替代 PaddleOCR** — 中文金融表格识别更优
4. **分层抽取而非全 LLM** — L1 字典匹配 + L2/L3 LangExtract，降低百万级成本
5. **财务指标 API 为唯一真相来源** — 不做 LLM 抽取，避免幻觉
6. **申万行业分类** — 中国投资研究事实标准，三级 200+ 细分
7. **渐进式交付** — Phase 1 基础能力 → Phase 2 图谱 → Phase 3 多模态 → Phase 4 生产化