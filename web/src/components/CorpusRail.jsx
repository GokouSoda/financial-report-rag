import { Check, Database, FileText, Layers3 } from "lucide-react";

export default function CorpusRail({
  health,
  selectedCompanies,
  toggleCompany,
  clearScope,
  open,
}) {
  const allSelected = selectedCompanies.length === 0;
  return (
    <aside className={`corpus-rail ${open ? "is-open" : ""}`}>
      <div className="rail-heading">
        <div>
          <span className="rail-label">语料范围</span>
          <strong>{health?.documents ?? 12} 家公司</strong>
        </div>
        <Database size={18} strokeWidth={1.7} aria-hidden="true" />
      </div>

      <button
        className={`company-row all-companies ${allSelected ? "is-selected" : ""}`}
        type="button"
        onClick={clearScope}
        aria-pressed={allSelected}
      >
        <span className="check-box">{allSelected && <Check size={13} />}</span>
        <span>全部公司</span>
        <span className="company-index">12</span>
      </button>

      <div className="company-list" aria-label="公司筛选">
        {(health?.companies ?? []).map((company, index) => {
          const selected = selectedCompanies.includes(company);
          return (
            <button
              className={`company-row ${selected ? "is-selected" : ""}`}
              type="button"
              key={company}
              onClick={() => toggleCompany(company)}
              aria-pressed={selected}
            >
              <span className="check-box">{selected && <Check size={13} />}</span>
              <span>{company}</span>
              <span className="company-index">
                {String(index + 1).padStart(2, "0")}
              </span>
            </button>
          );
        })}
      </div>

      <div className="rail-metrics">
        <div>
          <FileText size={15} aria-hidden="true" />
          <span>2,100 页</span>
        </div>
        <div>
          <Layers3 size={15} aria-hidden="true" />
          <span>{health?.chunks?.toLocaleString("zh-CN") ?? "12,227"} 个块</span>
        </div>
      </div>

      <p className="rail-note">
        原始文件来自巨潮资讯公开披露。回答中的页码同时标注 PDF 页与报告印刷页。
      </p>
    </aside>
  );
}
