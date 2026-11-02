import { useEffect, useState } from "react";
import { BookOpenCheck, Menu, X } from "lucide-react";
import CorpusRail from "./components/CorpusRail";
import QueryWorkbench from "./components/QueryWorkbench";

const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

export default function App() {
  const [health, setHealth] = useState(null);
  const [healthError, setHealthError] = useState("");
  const [selectedCompanies, setSelectedCompanies] = useState([]);
  const [mobileRailOpen, setMobileRailOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/api/health`)
      .then((response) => {
        if (!response.ok) throw new Error("知识库服务未就绪");
        return response.json();
      })
      .then((data) => {
        if (!cancelled) setHealth(data);
      })
      .catch((error) => {
        if (!cancelled) setHealthError(error.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function toggleCompany(company) {
    setSelectedCompanies((current) =>
      current.includes(company)
        ? current.filter((item) => item !== company)
        : [...current, company],
    );
  }

  function clearScope() {
    setSelectedCompanies([]);
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="财报镜鉴首页">
          <span className="brand-mark" aria-hidden="true">
            财
          </span>
          <span className="brand-name">财报镜鉴</span>
        </a>
        <div className="topbar-context">
          <BookOpenCheck size={16} strokeWidth={1.8} aria-hidden="true" />
          <span>A股白酒 · 2025 年报</span>
        </div>
        <div className="topbar-status" aria-live="polite">
          <span className={`status-dot ${health ? "is-online" : ""}`} />
          {health ? "知识库在线" : healthError ? "服务未连接" : "正在连接"}
        </div>
        <button
          className="mobile-menu"
          type="button"
          onClick={() => setMobileRailOpen((open) => !open)}
          aria-label={mobileRailOpen ? "关闭语料范围" : "打开语料范围"}
        >
          {mobileRailOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
      </header>

      <main className="workspace">
        <CorpusRail
          health={health}
          selectedCompanies={selectedCompanies}
          toggleCompany={toggleCompany}
          clearScope={clearScope}
          open={mobileRailOpen}
        />
        <QueryWorkbench
          apiBase={API_BASE}
          health={health}
          healthError={healthError}
          selectedCompanies={selectedCompanies}
        />
      </main>
    </div>
  );
}
