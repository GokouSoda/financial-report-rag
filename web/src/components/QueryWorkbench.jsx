import { useState } from "react";
import {
  ArrowUp,
  ArrowUpRight,
  ChevronDown,
  Clock3,
  FileSearch,
  LoaderCircle,
  Quote,
  RotateCcw,
} from "lucide-react";
import ReactMarkdown from "react-markdown";

const SAMPLE_QUESTIONS = [
  "贵州茅台2025年营业收入是多少？",
  "五粮液2025年的研发投入金额是多少？",
  "这些白酒公司中，哪些公司2025年提出了分红方案？",
];

function cleanCell(value) {
  return String(value ?? "").replaceAll("<br>", " ").trim();
}

function compactPreview(result) {
  if (result.chunk_type === "table" && result.rows?.length) {
    return result.rows
      .slice(0, 2)
      .map((row) => row.map(cleanCell).filter(Boolean).join(" · "))
      .filter(Boolean)
      .join(" / ");
  }
  return result.content
    .replace(/^[\s\S]*?正文：\s*/, "")
    .replaceAll("<br>", " ")
    .slice(0, 260);
}

function TablePreview({ rows }) {
  if (!rows?.length) return null;
  const visibleRows = rows.slice(0, 7);
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {visibleRows[0].map((cell, index) => (
              <th key={`${cell}-${index}`}>{cleanCell(cell) || "—"}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {visibleRows.slice(1).map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td key={cellIndex}>{cleanCell(cell) || "—"}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EvidenceCard({ result, compact = false }) {
  return (
    <article className={`evidence-card ${compact ? "is-compact" : ""}`}>
      <header>
        <span className="citation-index">[{result.citation}]</span>
        <div className="evidence-title">
          <strong>{result.company}</strong>
          <span>
            {result.report_year} 年报 · PDF 第 {result.pdf_page_start} 页
          </span>
        </div>
        {result.source_url && (
          <a
            href={result.source_url}
            target="_blank"
            rel="noreferrer"
            aria-label={`打开${result.company}年报原文`}
          >
            <ArrowUpRight size={16} />
          </a>
        )}
      </header>
      <p className="evidence-path">
        {result.chapter}
        {result.subsection ? ` / ${result.subsection}` : ""}
      </p>
      {compact ? (
        <p className="evidence-excerpt">{compactPreview(result)}</p>
      ) : (
        <>
          {result.chunk_type === "table" && <TablePreview rows={result.rows} />}
          {result.chunk_type !== "table" && (
            <p className="evidence-excerpt">{result.content.slice(0, 520)}</p>
          )}
          <details>
            <summary>
              查看召回信息 <ChevronDown size={14} />
            </summary>
            <dl className="score-grid">
              <div>
                <dt>混合得分</dt>
                <dd>{result.hybrid_score?.toFixed(4)}</dd>
              </div>
              <div>
                <dt>向量排名</dt>
                <dd>{result.vector_rank ?? "规则补入"}</dd>
              </div>
              <div>
                <dt>BM25 排名</dt>
                <dd>{result.bm25_rank ?? "规则补入"}</dd>
              </div>
              <div>
                <dt>块类型</dt>
                <dd>{result.chunk_type === "table" ? "表格" : "正文"}</dd>
              </div>
            </dl>
          </details>
        </>
      )}
    </article>
  );
}

export default function QueryWorkbench({
  apiBase,
  health,
  healthError,
  selectedCompanies,
}) {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [view, setView] = useState("answer");
  const [duration, setDuration] = useState(null);

  async function runQuestion(question = query) {
    const normalized = question.trim();
    if (!normalized || loading) return;
    setQuery(normalized);
    setLoading(true);
    setError("");
    setView("answer");
    const started = performance.now();
    try {
      const response = await fetch(`${apiBase}/api/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: normalized,
          companies: selectedCompanies,
          top_k: 8,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "检索请求失败");
      }
      setResult(payload);
      setDuration(((performance.now() - started) / 1000).toFixed(1));
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setLoading(false);
    }
  }

  function onKeyDown(event) {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      runQuestion();
    }
  }

  const scopeLabel =
    selectedCompanies.length === 0
      ? "全部 12 家公司"
      : `${selectedCompanies.length} 家公司`;

  return (
    <section className="query-stage">
      <div className="stage-scroll">
        <div className="stage-intro">
          <div>
            <h1>问财报，读原文。</h1>
            <p>
              同一问句背后，不只给出结论。每条答案都能回到公司、报告与页码。
            </p>
          </div>
          <div className="index-state">
            <span>FAISS</span>
            <span className="index-cross">+</span>
            <span>BM25</span>
          </div>
        </div>

        <form
          className={`query-box ${loading ? "is-loading" : ""}`}
          onSubmit={(event) => {
            event.preventDefault();
            runQuestion();
          }}
        >
          <label htmlFor="report-question">你想从年报中确认什么？</label>
          <textarea
            id="report-question"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={onKeyDown}
            placeholder="例如：比较贵州茅台和五粮液2025年的营业收入。"
            rows={3}
            maxLength={500}
          />
          <div className="query-controls">
            <span className="scope-readout">
              <FileSearch size={15} aria-hidden="true" />
              {scopeLabel}
            </span>
            <span className="shortcut-hint">Ctrl + Enter</span>
            <button
              className="submit-button"
              type="submit"
              disabled={loading || !query.trim() || !health}
            >
              {loading ? (
                <LoaderCircle className="spin" size={17} />
              ) : (
                <ArrowUp size={17} />
              )}
              {loading ? "正在检索" : "开始检索"}
            </button>
          </div>
        </form>

        {healthError && (
          <div className="error-banner">
            <span>知识库服务未连接。</span>
            <code>python -m uvicorn api.main:app --port 8000</code>
          </div>
        )}
        {error && <div className="error-banner">{error}</div>}

        {!result && !loading && (
          <div className="empty-state">
            <div className="sample-block">
              <p className="section-label">可以这样问</p>
              <div className="sample-list">
                {SAMPLE_QUESTIONS.map((question, index) => (
                  <button
                    type="button"
                    key={question}
                    onClick={() => runQuestion(question)}
                  >
                    <span>{String(index + 1).padStart(2, "0")}</span>
                    <strong>{question}</strong>
                    <ArrowUpRight size={16} aria-hidden="true" />
                  </button>
                ))}
              </div>
            </div>
            <div className="method-line">
              <div>
                <span>01</span>
                <strong>表格按行列还原</strong>
                <p>保留表头、单位与原始数值，避免 PDF 文本错位。</p>
              </div>
              <div>
                <span>02</span>
                <strong>双索引混合召回</strong>
                <p>语义相似与精确术语互补，再由业务规则校正主表。</p>
              </div>
              <div>
                <span>03</span>
                <strong>回答落到证据</strong>
                <p>每个关键结论对应可展开的召回块和公告原文。</p>
              </div>
            </div>
          </div>
        )}

        {loading && (
          <div className="loading-state" aria-live="polite">
            <LoaderCircle className="spin" size={28} />
            <div>
              <strong>正在年报中定位证据</strong>
              <span>并行检索向量索引与 BM25，并校正关键财务主表。</span>
            </div>
          </div>
        )}

        {result && !loading && (
          <div className="results-layout">
            <section className="answer-column">
              <div className="result-toolbar">
                <div className="view-tabs" role="tablist" aria-label="结果视图">
                  <button
                    type="button"
                    className={view === "answer" ? "is-active" : ""}
                    onClick={() => setView("answer")}
                    role="tab"
                    aria-selected={view === "answer"}
                  >
                    回答
                  </button>
                  <button
                    type="button"
                    className={view === "recall" ? "is-active" : ""}
                    onClick={() => setView("recall")}
                    role="tab"
                    aria-selected={view === "recall"}
                  >
                    召回详情
                  </button>
                </div>
                <button
                  className="reset-button"
                  type="button"
                  onClick={() => {
                    setResult(null);
                    setQuery("");
                  }}
                >
                  <RotateCcw size={14} />
                  新问题
                </button>
              </div>

              {view === "answer" ? (
                <article className="answer-sheet">
                  <div className="answer-meta">
                    <span className="answer-rule" />
                    <span>
                      {result.mode === "llm" ? "模型回答" : "抽取式回答"}
                    </span>
                    <span className="answer-time">
                      <Clock3 size={13} />
                      {duration}s
                    </span>
                  </div>
                  <div className="answer-markdown">
                    <ReactMarkdown>{result.answer}</ReactMarkdown>
                  </div>
                  <div className="answer-evidence-strip">
                    <Quote size={18} aria-hidden="true" />
                    <p>
                      回答严格受本次召回材料约束。右侧展示原始块，可核对章节、页码与表格数值。
                    </p>
                  </div>
                </article>
              ) : (
                <div className="recall-detail">
                  <div className="recall-explainer">
                    <strong>本次查询：</strong>
                    <span>{query}</span>
                  </div>
                  {result.results.map((item) => (
                    <EvidenceCard
                      key={item.chunk_id}
                      result={item}
                      compact={false}
                    />
                  ))}
                </div>
              )}
            </section>

            <aside className="source-rail">
              <header>
                <div>
                  <p className="section-label">答案出处</p>
                  <strong>{result.results.length} 个证据块</strong>
                </div>
                <span className="source-count">
                  {new Set(result.results.map((item) => item.company)).size}
                  <small> 家公司</small>
                </span>
              </header>
              <div className="source-list">
                {result.results.slice(0, 6).map((item) => (
                  <EvidenceCard key={item.chunk_id} result={item} compact />
                ))}
              </div>
              {result.results.length > 6 && (
                <button
                  className="show-all-button"
                  type="button"
                  onClick={() => setView("recall")}
                >
                  查看全部 {result.results.length} 个召回块
                  <ArrowUpRight size={15} />
                </button>
              )}
            </aside>
          </div>
        )}
      </div>
    </section>
  );
}
