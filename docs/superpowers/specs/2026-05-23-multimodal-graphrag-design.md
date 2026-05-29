# 多模态金融 GraphRAG 系统设计

## 项目概况

- **场景**：金融文档分析（A 股公告、研报、个股新闻、港股美股公告/新闻）
- **规模**：百万级 PDF/文本，持续增量摄入
- **用户**：小团队内部使用
- **查询能力**：全文 QA + 跨文档关联 + 实体/事件图谱 + 结构化提取 + 时序对比
- **技术路线**：方案 B — 可控 Graph（Docling + Neo4j + Milvus + ES 混合检索），Phase 1 先跑检索管线，Phase 2 加入图谱

## 一、顶层架构

```
完整架构（Phase 2+ 目标状态）：
查询层 → 查询路由 → 混合检索(ES+Milvus+Neo4j) → 结果合成 → LLM 回答
图谱层 → LangExtract + LLM 抽取 → Neo4j 知识图谱 → Cypher 查询
向量层 → HTML 分块 → jina-embeddings-v5 → Milvus 稠密向量检索
全文层 → HTML 分块 → IK 分词 + BM25 → Elasticsearch 关键词检索
解析层 → PyMuPDF(非表页) + Docling(表页) → 合并 HTML

Phase 1 范围：解析层 + 向量层 + 全文层 + 查询层（不含 Neo4j）
Phase 2 加入：图谱层 + 混合检索中的 Neo4j 路径
```

**核心数据流（Phase 1）**：原始文档 → HTML 解析 → 分块+Embedding(→Milvus) + ES 索引(→Elasticsearch) → 双路检索(RRF) → LLM 生成

**Phase 2 加入**：实体关系抽取(→Neo4j) → 混合检索(Graph+Vector)

## 二、多模态文档解析层

### 工具链

| 工具 | 用途 | Phase 1 策略 |
|------|------|-------------|
| **Docling** | PDF/图片 → HTML，保留 rowspan/colspan | 仅处理**含表格的页**，经 PyMuPDF 路由后调用 |
| **PyMuPDF** | PDF → HTML（`get_text("html")`） | 非表格页快速提取 HTML，~62 p/s |
| **Marker** | Docling 解析失败时的兜底 | Phase 2 后按需引入 |
| **Qwen-VL** | 图表/截图理解，生成结构化描述 | Phase 3 引入 |
| **GLM-OCR** | 扫描件 OCR（API 调用） | Phase 2 后按需引入 |
| **Pandas** | Excel/CSV 直接解析 | Phase 1 启用 |

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
    "images": [{"id": "img_001", "description": null, "minio_path": "minio://images/ann_20240523_600000/img_001.png", "bbox": [...]}],
    "tables": [{"id": "tab_001", "caption": "合并资产负债表", "html": "<table>...</table>"}],
    "parse_confidence": 0.95
}
```

### 设计决策：HTML 而非 Markdown

财务报表存在大量合并单元格（rowspan/colspan），Markdown 不支持。HTML 完整保留表格语义，下游分块和 Embedding 时 strip 标签取纯文本即可，LLM 对 HTML 理解良好。

### 解析器策略

**Hybrid 按页路由：PyMuPDF + Docling**

```
PDF 文档（N 页）
       │
       ├── PyMuPDF 逐页扫描，检测表格
       │   ├── 连续无表格 → 合并后 get_text("html") 批量提取
       │   ├── 连续有表格 → 合并后整段送入 Docling 解析
       │   └── 有表格页前后各补 1 页上下文 → 避免表格边界判断错误
       │
       └── 按页序合并 → 统一 HTML 文档（下游不感知页来源）

**路由规则：** 连续表格页合并为一段，整段送 Docling，确保跨页表格（如资产负债表上下两页）被完整解析。非表格页按连续段落合并，批量用 PyMuPDF 提取 HTML。
```

**为什么 Hybrid：**

| 维度 | Docling 全量 | PyMuPDF + Docling 路由 |
|------|-------------|----------------------|
| 速度 | 慢，每页都走完整管线 | PyMuPDF ~62 p/s，Docling 仅跑 ~10-20% 的页 |
| 内存 | 全量加载，内存泄漏风险高 | Docling 单次只处理几页，用完就释放 |
| HTML 输出 | 原生 HTML | 统一 HTML，非表格页 `get_text("html")`，表格页 Docling HTML |
| 10 万文档耗时 | ~30-50 天 | ~10-15 天 |

**兜底策略：** PyMuPDF `find_tables()` 基于线检测，对无线表可能漏检。对检测到多列数字对齐但无边框线的页面，也送入 Docling 处理作为补充。

### 图片处理策略

PDF 中的图片（K 线图、营收柱状图、组织架构图等）分两阶段处理：

**Phase 1：提取 + 存储，不做理解**
- PyMuPDF / Docling 解析时检测图片区域，提取原始图片
- 图片存入 MinIO，路径格式：`minio://images/{doc_id}/img_{page}_{idx}.png`
- HTML 中留 `<img src="minio://images/{doc_id}/img_{page}_{idx}.png">` 占位
- Chunk 中的 content_text 不含图片内容（纯文本字段无可描述）

**Phase 3：Qwen-VL（API 或本地）理解图片**
- 读取 MinIO 中已存储的图片，走 Qwen-VL 生成结构化描述
- 描述内容写回对应 chunk 的 context 字段（如 `chart_description`）
- 无需重新解析 PDF，仅增量处理已存的图片

**优势：** Phase 1 不受视觉能力限制，Phase 3 不需要回溯解析管线。

## 三、文本分块 + 向量存储 + 全文索引

### 多粒度分块策略

```
完整 HTML 文档
  ├── 按 <h1>-<h6> 切分 → Section Chunk (500-2000 token，table 不拆散)
  │   └── 相邻 Section Chunk 间 100 token 交叉，避免边界信息丢失
  └── 独立提取 <table> → Table Chunk (完整 HTML table + 章节上下文)
```

Section Chunk chunk_id 格式：`{doc_id}_s{section_idx}`
Table Chunk chunk_id 格式：`{doc_id}_t{table_idx}`（不另占一份向量/索引空间，仅作为 Section Chunk 的独立入口）

预估输出（10 万文档 × 平均 8 Section Chunk + 3 Table Chunk）：**约 110 万 / 10 万文档**

### Chunk 数据模型

```json
{
    "chunk_id": "ann_20240523_600000_t2",
    "doc_id": "ann_20240523_600000",
    "chunk_type": "table",
    "simhash": "1a2b3c4d5e6f7890",           ← content_text 的 simhash 指纹
    "content_html": "<table>...</table>",
    "content_text": "合并资产负债表 资产总计...",
    "context": {
        "section_title": "三、合并财务报表",
        "prev_chunk_summary": "..."
    },
    "metadata": { "stock_code": "600000", "publish_date": "2024-05-23", "doc_type": "quarterly_report", "industry": "银行" }
}
```

**Chunk 去重**：simhash 为 content_text 的 64 位指纹，写入前检查 ES/Milvus 是否已存在相同 simhash：
- 同一文档重复提交 → chunk_id 完全一致，覆盖写入即可
- 跨文档近似重复（如多篇新闻稿内容高度雷同）→ simhash 海明距离 < 3 视为重复，跳过写入，检索时保留最先入库的那份

### Embedding 模型

**jina-embeddings-v5-text-small**（Jina AI / Qwen3-0.6B）：

| 特性 | 参数 |
|------|------|
| 上下文窗口 | **32,768 token**（4 × BGE-M3） |
| 默认向量维度 | 1024（可截断至 32/64/128/256/512/768） |
| 基础模型 | Qwen3-0.6B（阿里 Qwen3 系列，原生中文支持） |
| 池化方式 | Last-token pooling |
| 部署 | Sentence Transformers / HuggingFace（本地，CPU 可运行） |

**选择理由：**

- **32K context：** HTML 表格（尤其含 rowspan/colspan 的复杂表）轻松放入单次 Embedding，无需截断或拆分
- **保留 HTML 标记语义：** 既然确定 content_html 对表格识别有价值，那就需要模型能"看到"完整的 `<table>` `<tr>` `<td>` 结构——8192 token 的 BGE-M3 在处理此类输入时窗口吃紧
- **俄罗斯套娃向量（Matryoshka）：** 支持 32/64/128/256/512/768/1024 维截断，同一向量可降维存储而不重训。Phase 1 先用 1024 维保精度，后续可根据检索质量与存储成本的权衡切到 512/256 维

**注意事项：**

- 许可证为 CC BY-NC 4.0，内部使用无限制；如需商业分发需联系 Jina AI
- 采用 Adapter 架构（Retrieval / Matching / Clustering），Embedding 时需指定 `task="retrieval"` 并分别使用 `Query:` 和 `Document:` 前缀

**意图知识库复用**：同一模型同时服务于 chunk Embedding 和意图知识库检索（query → intent 相似度匹配）。

### 向量数据库

**Milvus**：支持十亿级向量，标量过滤（按公司/行业/日期/文档类型），检索阶段不做硬过滤，全量打分后按语义排序。

### 全文检索引擎

**Elasticsearch**：BM25 稀疏向量检索，与 Milvus 稠密向量互补：

| 维度 | Elasticsearch (BM25) | Milvus (jina-embeddings-v5) |
|------|---------------------|------------------------------|
| 匹配方式 | 关键词精确匹配 + TF-IDF | 语义相似度 |
| 优势 | 股票代码、公司全称、法规编号等精确查找 | 同义词、改写、模糊语义理解 |
| 分词 | IK 中文分词器 + 金融词典（每日自动更新） | 32K 窗口原生语义编码 |
| 典型场景 | "600519.SH 2024年年报" | "茅台去年业绩怎么样" |

ES 索引与 Milvus Vector 共用同一套 Chunk（相同的 chunk_id），content_text 同时写入 ES 和 Milvus，检索后按 chunk_id 统一排序。

### 双写一致性

Chunk 写入 ES 和 Milvus 采用**事务协调器**保证原子性：

```
分块 → simhash 查重 → Embedding
       │
       ├── 写 Milvus → 成功 → 写 ES → 成功 → ✓ 提交
       │       │                    │
       │       │                    └── 失败 → 回滚 Milvus（delete by chunk_id）
       │       │
       │       └── 失败 → 跳过 ES，整体失败
       │
       └── 任意一步失败 → chunk 标记为"未写入"，下次重试
```

- 先写 Milvus、后写 ES：Milvus 写操作轻量（纯向量插入），ES 写操作重（分词+建索引）。轻的先做，失败成本低；重的后做，成功率高
- 回滚手段：Milvus 按 `chunk_id` 标量过滤删除，ES 按 `chunk_id` 执行 `delete_by_query`
- 批量写入时逐 chunk 独立事务，一条失败不影响同批次其他 chunk

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

用户问题 → 实体链接 → 意图分类 → 4 条路径：全文 QA / 图谱查询 / 指标查询 / 混合查询

```
用户问题 "茅台 Q3 营收多少"
       │
       ├── 实体链接（详见下方管道）
       │   → 解析出 {stock_code, period, metric} 供后段使用
       │
       ├── 意图分类（Few-shot + LLM）
       │   ├── 意图知识库（已有）: 存储 {query, intent 标签, 人工修正} 历史记录
       │   ├── Embedding 检索知识库 → top 5 最相似 query + 对应 intent
       │   └── LLM prompt: 用户问题 + 5 个 few-shot 示例 → 输出意图标签
       │
       └── 路由: 根据意图标签分发到对应执行路径
```

**意图知识库的设计：**

| 组件 | 说明 |
|------|------|
| 存储 | 向量库（复用 jina-embeddings-v5/Milvus 或独立的小型向量库） |
| 数据格式 | `{query_text, intent_label, embedding, 人工修正标记}` |
| 检索 | 用户 query Embedding → 余弦相似度 top 5 |
| 初始种子 | 各意图类型人工构造 10-20 条典型 query 作为冷启动 |
| 改进闭环 | 发现分类错误 → 人工标注正确 intent → 写入知识库 → 下次命中相同的错误 query 时 few-shot 会给出反例引导 |

**为什么 Few-shot + 知识库 而非直接 LLM 分类？**

- 金融查询意图边界模糊——"茅台 Q3 营收" 既像全文 QA 又像指标查询，few-shot 示例让 LLM 看到历史同类 query 的处理方式
- 知识库可迭代——发现一次错误就丢一条标注数据进去，不需要重新训练或调 prompt
- 新意图类型只需在知识库中新增示例即可支持，无需改代码

**调用约定**：意图分类调用 Doubao Lite（火山引擎）API，temperature=0。抽取类任务用 Lite，回答生成用 Pro。

### 实体链接管道

指标查询和混合查询需要将自然语言中的指代映射为结构化参数（股票代码、时间、指标名），分三步进行：

```
用户问题 "茅台 Q3 营收多少"
       │
       ├── Step 1: 实体抽取（LLM）
       │   输出: { "entities": ["茅台"], "time": "Q3", "metric": "营收" }
       │   prompt: 从用户问题中抽取股票/公司名、时间表达式、财务指标名
       │   temperature: 0（确定性抽取）
       │
       ├── Step 2: 实体查询（模糊匹配接口，已有）
       │   输入 "茅台" → 模糊匹配已有公司库
       │   输出: [
       │     { code: "600519", name: "贵州茅台", market: "SH", match_score: 0.95 },
       │     { code: "600197", name: "伊力特", market: "SH", match_score: 0.60 },
       │     ...
       │   ]
       │   时间解析: "Q3" → 本期最新 Q3（或指定年份的 Q3）
       │   指标映射: "营收" → 营业收入（同义词表: 营收/收入/营业额/销售收入...）
       │
       └── Step 3: 实体消歧 + 查询确认（LLM）
           输入: 用户问题 + Step 2 候选列表
           输出: {
             stock_code: "600519.SH",
             period: "2024Q3",
             metric: "营业收入",
             confidence: 0.97
           }
           prompt: 结合用户上下文，从候选列表中选择最匹配的实体，
                   输出结构化查询参数
           temperature: 0
```

**为什么用两次 LLM 而非一次完成？**

| 方案 | 问题 |
|------|------|
| 一次 LLM 直接输出结构化参数 | 无法利用外部公司库，$T$茅" → 600519 这种映射 LLM 知识可能过期 |
| 模糊匹配 → 硬编码取 top 1 | 同名多实体（"茅台" = 股票/酒/地点）无法消歧 |
| 模糊匹配 → LLM 消歧（当前方案） | 结合候选列表的上下文，既利用外部库的准确映射，又保留 LLM 的语义理解 |

**调用约定**：Step 1 和 Step 3 调用 Doubao Lite（火山引擎）API，temperature=0。回答生成用 Doubao Pro，temperature=0.3-0.7。抽取与生成按任务选型，互不影响。

### 全文 QA 的双路检索

```
问题 "600519 2024年年报披露的营收"
       │
       ├─→ ES (BM25): "600519" "2024" "年报" "营收" → 精确 hit top 20
       │
       └─→ Milvus (稠密): "600519 2024年年报披露的营收" → 语义相似 top 20
              │
              └─→ RRF (Reciprocal Rank Fusion) 融合排序 → top 10
                     │
                     └─→ LLM 生成回答
```

### RRF 加权融合策略

RRF 中的 ES 和 Milvus 权重由意图分类结果控制，不等权融合：

```
RRF_score(d) = w_es × 1/(k + rank_es(d)) + w_milvus × 1/(k + rank_milvus(d))
k = 60（标准值）
w_milvus = 1 - w_es
```

权重通过 200 条测试集网格搜索确定：

```
对每种意图，遍历 w_es ∈ [0, 0.1, 0.2, ..., 1.0]：
  计算该意图下所有测试 query 的 top 10 召回率
  取召回率最高的 w_es
```

**预期结果示例**（首次测试集跑完后更新）：

| 意图 | w_es | w_milvus | 说明 |
|------|------|----------|------|
| 精确代码查询 | 0.8 | 0.2 | ES BM25 对股票代码/公司全称几乎必中，Milvus 做语义兜底 |
| 语义搜索 | 0.2 | 0.8 | 模糊描述依赖语义匹配 |
| 混合查询 | 0.5 | 0.5 | 标准 RRF，两者权重相等 |

**动态跳过**：当 w_es ≥ 0.9 或 w_milvus ≥ 0.9 时，跳过另一路检索，减少 Latency。比如精确代码查询可以只跑 ES。

**权重维护**：测试集每扩充一次，网格搜索重新跑一次。如果某意图最优权重下的召回率仍低于 90%，说明问题不在融合权重而在检索源或路由逻辑。

### 检索过滤策略

检索阶段不做硬过滤（metadata 预过滤 / ES bool filter），全量打分后按语义排序：

```
query "银行股 2024年 ROE"
  → ES BM25 全量打分（"银行"+"2024"+"ROE" 自然命中行业+年份+指标）
  → Milvus 全量向量搜索（语义编码已经包含了行业和时间信息）
  → RRF 融合 → top 15 → LLM 生成
```

**理由：**

| 方案 | 问题 |
|------|------|
| 元数据预过滤 | 实体链接错误 → 过滤条件错误 → 检索漏掉正确文档 |
| 不做过滤（当前方案） | 实体链接错误只影响 API 指标查询路径，不殃及检索召回 |

**可选后处理（Phase 2 评估后决定）：**

当测试集 MRR < 0.8 时，在 RRF 后加轻量 rerank：

```
ES top 20 + Milvus top 20 → RRF top 30 → rerank(query, candidate) → top 10 → LLM
```

rerank 可用 BGE-reranker 或 query-chunk 余弦相似度。Phase 1 先用纯 RRF 跑 baseline。

### 5 类查询的执行路径

| 查询类型 | 示例 | Phase 1 路径 | Phase 2+ 增强 |
|---------|------|-------------|---------------|
| 全文 QA | "茅台 Q3 营收多少？" | ES(精确)+Milvus(语义) 双路检索 → RRF → LLM → API 校验指标值 | + Neo4j 实体上下文 |
| 跨文档关联 | "宁德时代的供应链？" | —（Phase 2 支持） | Neo4j 图遍历 → ES+向量验证出处 |
| 实体事件图谱 | "新能源行业近 3 年并购事件" | —（Phase 2 支持） | Neo4j(Industry→Company→Event) |
| 结构化提取 | "所有银行股的 ROE" | API 直接查询 | + Neo4j 补充关联 |
| 时序对比 | "新能源 vs 传统能源研发投入" | API(多期) + 向量(定性) | + 图谱实体关联 |

### 混合检索流程

1. 问题改写 + 实体链接（详见上方实体链接管道）
2. 并行检索：ES(关键词) + Milvus(语义) [Phase 2+ 加入 Neo4j(关系) + API(指标)]
3. RRF 融合 ES + Milvus 结果，Neo4j 结果补充实体上下文
4. 上下文融合（API 数据优先）
5. LLM 生成回答

### 数据优先级

- 财务指标数值：API > 图谱 > 文档 chunk
- 关系/事件：图谱 > 文档 chunk
- 定性描述/背景：文档 chunk

## 七、技术栈总览

| 组件 | 选型 | 说明 |
|------|------|------|
| 文档解析 | PyMuPDF + Docling 混合 | PyMuPDF 快速扫描+按页路由，Docling 仅处理含表格的页，合并输出统一 HTML |
| OCR | GLM-OCR（API 调用） | 扫描件，替代 PaddleOCR |
| 图数据库 | Neo4j | Phase 2 引入，Cypher 查询 |
| 向量数据库 | Milvus | 亿级向量，检索不做硬过滤，全量打分按语义排序 |
| 全文检索引擎 | Elasticsearch | BM25 + IK 中文分词，关键词精确匹配；支持 simhash 字段查重 |
| Embedding | jina-embeddings-v5-text-small | 32K context，原生中文，Matryoshka 多维度截断；同时用于意图知识库检索 |
| Chunk 去重 | simhash（64 位指纹） | 写入前查重，海明距离 < 3 视为近似重复跳过 |
| LLM API | Doubao Pro(生成) + Doubao Lite(抽取/分类) | Lite 用于意图分类、实体抽取/消歧、NER/RE（temperature=0）；Pro 用于回答生成（temperature=0.3-0.7）。按任务选型，成本隔离开 |
| 对象存储 | MinIO | 原始 PDF + HTML |
| 任务队列 | Redis | 3 个独立队列，三阶段 worker pool 解耦 |
| NER/RE | LangExtract（调用 Doubao Lite） | L2 深层关系 + 事件抽取 |
| 图表理解 | Qwen-VL | 财报图表结构化描述 |
| Web 框架 | FastAPI | 查询 API |
| 实体链接 | LLM(Doubao Lite) + 模糊匹配接口 | Step1 抽取 → Step2 模糊匹配 → Step3 消歧，temperature=0 |

## 八、硬件部署

### 推荐配置

| 组件 | 推荐配置 | 用途 |
|------|---------|------|
| CPU | 64 核 | PyMuPDF 批量扫描 + Docling 按页解析 + 分块 |
| 内存 | **64 GB**（Phase 1 够用，128 GB Phase 2+） | ES 堆内存 16GB；Docling 每 worker ~4GB，余量充足 |
| GPU | **RTX 3090 24GB** | Docling 表格页解析加速（CPU 也可行，速度降 2-3 倍） |
| 存储 | 10 TB NVMe | 原始文件 + HTML + Milvus 索引 + ES 索引 + Neo4j 数据 |

**处理参数（RTX 3090 / 64GB 基准）：**

| 参数 | 建议值 | 说明 |
|------|--------|------|
| 连续表格页批大小 | 12 页 | VRAM 24GB ÷ ~1.5GB/页，留余量 |
| 跨批补页 | 每批前后各补 2 页 | 避免跨批表格被切碎 |
| parse_task 并发 | 2-3 workers | 64GB 内存下每 worker ~4GB，不影响 ES |
| 单文档超时 | 120 秒 | 12 页 × ~8 秒/页（含模型加载） |
| 吞吐量 | ~100-150 文档/天/worker | 纯解析，不含扫描和索引；100k ≈ 4-6 周 |

### 存储估算

**Phase 1（10 万文档）：**
```
原始 PDF:      10万 × 2MB    = 200 GB
解析后 HTML:   10万 × 0.5MB  = 50 GB
Milvus 向量:   110万 × 1024维 = 4.5 GB
ES 索引:       110万 × 约 1KB = 1.1 GB
──────────────────────────────
合计: 约 260 GB
```

**Phase 2+ 目标（百万文档）：**
```
原始 PDF:      100万 × 2MB    = 2 TB
解析后 HTML:   100万 × 0.5MB  = 500 GB
Milvus 向量:   1100万 × 1024维 = 45 GB
ES 索引:       1100万 × 约 1KB = 11 GB
Neo4j 图:      5000万节点 + 2亿边 = 500 GB-1 TB
──────────────────────────────────────
合计: 含冗余约 3-4 TB（不含 Neo4j 约 3 TB）
```

### 异步处理管线（三阶段队列）

针对解析管线各步骤资源需求差异大（PyMuPDF CPU 密集、Docling 内存敏感、索引 IO 密集），设计三个独立 worker pool：

```
                     ┌─────────────────────┐
                     │   Raw PDF files      │
                     └──────────┬──────────┘
                                │
                    ┌───────────▼───────────┐
                    │  🔵 scan_task pool     │  ← 20-30 workers
                    │  PyMuPDF: 检测表格页   │     CPU only
                    │  输出文档: 无表页 HTML  │     失败重试成本极低
                    │          + 表格页范围    │
                    └───────────┬───────────┘
                                │ PDF + 表格页范围
                    ┌───────────▼───────────┐
                    │  🟡 parse_task pool     │  ← 4-8 workers
                    │  Docling: 解析表格页    │     关注内存
                    │  合并为完整 HTML 文档    │     worker 用完销毁
                    └───────────┬───────────┘
                                │ HTML
                    ┌───────────▼───────────┐
                    │  🟢 index_task pool     │  ← 10-15 workers
                    │  分块 + Embedding        │     幂等写入
                    │  simhash 查重             │
                    │  事务协调 → ES+Milvus     │
                    └────────────────────────┘
```

| Pool | 资源瓶颈 | 并发 | 失败处理 |
|------|---------|------|---------|
| scan_task | CPU 核数 | 20-30，全核跑满 | 整段重跑，成本极低 |
| parse_task | 内存 | 4-8，每次用完销毁重建，避免 Docling 泄漏 | 仅重试表格页，保留已有扫描结果 |
| index_task | IO（ES+Milvus 写入） | 10-15，幂等写入 | 单独重试失败 chunk，不波及整文档 |

三阶段通过 Redis 队列解耦，每个队列独立消费，不互相阻塞。

### 服务部署

Docker Compose：
- **Phase 1**: Elasticsearch + Milvus + MinIO + Redis（3 个队列）+ FastAPI + 3 个 Worker Pool（scan/parse/index）
- **Phase 2 加入**: Neo4j + 抽取 Worker
- **LLM**: Doubao API：抽取/分类用 Lite，回答生成用 Pro

## 九、Phase 划分

### Phase 1：文档解析 + 全文 QA + 指标 API

**目标**：把文档变成可检索的知识库

- PyMuPDF 快速扫描每页，无表格页 `get_text("html")`，有表格页路由 Docling 解析成 HTML → 合并为统一 HTML 文档
- 多粒度分块 + jina-embeddings-v5 + Milvus + Elasticsearch（双路检索）
- 分块时每 chunk 生成 simhash 指纹，写入前查重（跨文档近似重复跳过）
- IK 分词器 + 金融词典扩展——每日自动更新，对比数据库增量获取新股代码+简称+新金融术语
- 全文 QA + 指标查询 API（指标直连外部接口，不写数据库）

**验证**：10 万文档导入后，构建 200 条 QA 测试集评估检索质量：
- **140 条**：多 LLM 生成后随机抽取，覆盖常见问法
- **60 条**：人工构造边缘场景（模糊指代、多条件组合、非标准表述）
- **指标**：
- 检索 top 10 召回率 > 90%（正确答案是否在 top 10 内）
- MRR（平均倒数排名）> 0.75（正确答案排在 top 10 前列，@2026-09-01 先用 top 10 召回率，观察 baseline 后再加入 MRR）

**不包含**：Neo4j 写入/查询、知识图谱——全部留到 Phase 2

### Phase 2：知识图谱构建

**目标**：实体关系 + 事件图谱，支撑跨文档关联

- L1 实体（Company, Person, Industry, Location）字典匹配首次写入 Neo4j
- 财务指标 API 对接写入 Neo4j（作为结构化事实层）
- LangExtract 抽取 L2 深层关系（供应链、股权、任职...）
- 12 类公告事件抽取
- 实体链接 + 图谱去重合并
- 混合检索引擎（Graph + Vector 并行）

**验证**：从测试集中选取含关系/事件的 query，构建标注数据集评估 LangExtract 抽取质量，关系抽取准确率 > 85%

### Phase 3：多模态理解 + 时序分析

**目标**：图表关联 + 时序对比

- 读取 MinIO 中 Phase 1 存储的图片，Qwen-VL 生成结构化描述写入 chunk context
- 表格 HTML 结构化增强
- MarketDataPoint 行情数据接入
- 财务指标时序对比分析
- 多跳推理查询

### Phase 4：增量摄入 + 生产化

**目标**：系统稳定运行

- 每日定时扫描源目录，对比文件修改时间与上次扫描时间，新/变更的文档自动进入 scan → parse → index 管线
- 图过期策略（旧事件/概念降权）
- 性能优化（检索延迟 < 2s）
- 前端 Web UI
- 监控 + 告警

## 十、关键设计决策

1. **HTML 替代 Markdown** — 财务报表合并单元格 Markdown 无法表示
2. **Hybrid 路由解析：PyMuPDF + Docling** — PyMuPDF 快速扫描按页路由，无表格页直接 `get_text("html")`，有表格页走 Docling。既避免 Docling 全量解析的性能和内存泄漏问题，又保持统一 HTML 输出
3. **GLM-OCR 替代 PaddleOCR** — 中文金融表格识别更优
4. **分层抽取而非全 LLM** — L1 字典匹配 + L2/L3 LangExtract，降低百万级成本
5. **财务指标 API 为唯一真相来源** — 不做 LLM 抽取，避免幻觉
6. **申万行业分类** — 中国投资研究事实标准，三级 200+ 细分
7. **ES BM25 + Milvus 稠密向量双路检索** — 关键词精确匹配与语义理解互补，RRF 融合排序
8. **Neo4j 推迟到 Phase 2** — Phase 1 仅 ES+Milvus 双路检索，查询不经图谱。L1 实体写入和指标入库全部后移，减少 Phase 1 维护面
9. **渐进式交付** — Phase 1 基础能力 → Phase 2 图谱 → Phase 3 多模态 → Phase 4 生产化