# Financial Report RAG

面向 A 股白酒行业年报的混合检索问答项目。当前阶段固定语料范围：12 家 A 股白酒公司的 2025 年年度报告全文。

页面由 React + Vite 构建，Python FastAPI 提供检索与回答接口。知识库使用 FAISS 向量索引和 BM25 关键词索引，不使用外部数据服务即可完成检索。

## Corpus

- 报告类型：年度报告全文
- 报告年度：2025
- 公司数量：12
- 来源：巨潮资讯网公开公告接口
- 本地 PDF 目录：`data/raw/`，不提交到 Git
- 下载清单：`data/downloads.csv`

公司范围见 `data/companies.csv`。选择白酒行业是为了让跨公司比较问题仍然落在同一业务语境中，同时保留公司规模、产品结构和区域市场的差异。

## Reproduce the download

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts/download_reports.py
```

校验已下载语料、页数、文字层和 SHA-256：

```powershell
python scripts/verify_corpus.py
```

只查询公告并生成清单、不下载 PDF：

```powershell
python scripts/download_reports.py --metadata-only
```

脚本会按股票代码查询巨潮资讯，筛选 2025 年年度报告全文，排除摘要和英文版，下载文件，并校验 PDF 文件头和 SHA-256。重复运行时会跳过已经下载且校验通过的文件；使用 `--force` 可强制重新下载。

`data/corpus_audit.csv` 记录每份 PDF 的页数、前几页文字层检查和校验结果。

## Extract one report

先抽取贵州茅台年报，验证正文、标题层级、页码和表格结构：

```powershell
python scripts/extract_pdf.py data/raw/600519_2025_annual.pdf
```

默认输出：

- `data/processed/600519_2025_blocks.jsonl`
- `data/processed/600519_2025_extraction_audit.json`

抽取结果以块为单位，保留公司、股票代码、报告年度、章节、PDF 页码、报告印刷页码、表格二维行列数据及 Markdown 表格。

批量抽取全部 12 份年报：

```powershell
python scripts/extract_all.py
```

按页面和章节生成正文块、独立表格块：

```powershell
python scripts/chunk_documents.py
```

文本块最多 800 字并保留 80 字重叠；表格块按行切分，但每次重复表头，并保存二维行列数据。

建立 FAISS 向量索引和 BM25 索引：

```powershell
$env:HF_ENDPOINT = "https://hf-mirror.com"
python scripts/build_index.py
```

默认嵌入模型为 `BAAI/bge-small-zh-v1.5`，索引输出到 `data/index/`。索引和原文数据均不提交到 Git，可通过脚本重新生成。

命令行检索与带出处回答：

```powershell
python scripts/retrieval.py "贵州茅台2025年营业收入是多少？"
python scripts/ask.py "贵州茅台2025年营业收入是多少？"
```

在 `.env` 中配置 OpenAI 兼容的生成模型后，回答会使用大模型；未配置时保留检索证据并生成抽取式回答：

```text
LLM_BASE_URL=https://your-provider.example/v1
LLM_API_KEY=...
LLM_MODEL=your-model-name
```

运行固定的 10 道评测题并记录召回块：

```powershell
python scripts/evaluate.py
```

详细结果保存在 `eval/results.json` 和 `eval/results.csv`。

## Run the application

首次运行需要安装前后端依赖：

```powershell
python -m pip install -r requirements.txt
Push-Location web
npm install
Pop-Location
```

启动页面：

```powershell
.\start.ps1
```

浏览器打开 `http://127.0.0.1:5173`。页面支持公司范围筛选、示例问题、带页码答案、原始表格预览、向量/BM25 排名与 PDF 原文链接。

如果未配置生成模型，页面使用受证据约束的抽取式回答。配置任意 OpenAI 兼容接口后，同一批召回结果会交给生成模型作答：

```powershell
Copy-Item .env.example .env
```

在 `.env` 中设置 `LLM_BASE_URL`、`LLM_API_KEY` 和 `LLM_MODEL`。

## Deliverables

- `deliverables/screenshot-qa-desktop.png`
- `deliverables/screenshot-qa-mobile.png`
- `deliverables/conclusion.pdf`
- `eval/results.csv`
- `eval/results.json`
- `eval/manual_reviews.json`

重新生成一页结论：

```powershell
python scripts/make_conclusion.py
```

## Evaluation snapshot

固定评测共 11 题，其中 3 道跨公司题。当前抽取式回答得到 10/11 正确，关键证据关键词命中 17/19，跨公司题的公司覆盖为 100%。失败题是“归母净利率最高”：系统覆盖了 12 家公司，却没有把收入与净利润对齐并执行计算。这个问题需要结构化指标层或查询计划，不能只靠增大 Top-K。

## Repository rules

- 不提交 PDF、`.env`、API key、Cookie 或账号信息。
- 财报只通过脚本和下载清单复现。
- 后续抽取、切块和检索结果必须保留公司、报告、章节和页码元数据。

