from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Iterable

import requests
from dotenv import load_dotenv

try:
    from retrieval import (
        METRIC_ALIASES,
        SearchResult,
        is_primary_metric_query,
        tokenize,
    )
except ModuleNotFoundError:
    from scripts.retrieval import (
        METRIC_ALIASES,
        SearchResult,
        is_primary_metric_query,
        tokenize,
    )

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


SYSTEM_PROMPT = """你是上市公司财报问答助手。
只能使用用户提供的材料回答，不得补充材料之外的数字、结论或公司信息。
每个关键事实后必须用 [1]、[2] 这样的编号标注出处。
如果材料不足，明确回答“材料不足以确认”，不要猜测。
跨公司比较要说明覆盖了哪些公司，不得把未检索到的公司当作已比较。
回答简洁，先给结论，再给必要依据。"""

OUT_OF_SCOPE_PATTERNS = (
    "2026年第一季度",
    "2026年一季报",
    "2026年第一季度报告",
    "2026年半年报",
    "2026年三季度",
    "2027年",
)


def build_context(results: Iterable[SearchResult], max_chars: int = 12000) -> str:
    sections = []
    used = 0
    for index, result in enumerate(results, start=1):
        chunk = result.chunk
        header = (
            f"[{index}] 公司={chunk['company']}；股票代码={chunk['stock_code']}；"
            f"报告={chunk['report_year']}年年报；"
            f"PDF页={chunk['pdf_page_start']}；"
            f"报告页={chunk['printed_page_start']}；"
            f"章节={chunk['chapter']}；小节={chunk['subsection']}；"
            f"类型={chunk['chunk_type']}"
        )
        body = chunk["content"]
        section = f"{header}\n{body}"
        if used + len(section) > max_chars:
            remaining = max_chars - used
            if remaining > 300:
                sections.append(section[:remaining])
            break
        sections.append(section)
        used += len(section)
    return "\n\n".join(sections)


def call_openai_compatible(
    question: str,
    results: list[SearchResult],
    timeout: int = 120,
) -> str | None:
    api_key = os.getenv("LLM_API_KEY", "")
    base_url = os.getenv("LLM_BASE_URL", "").rstrip("/")
    model = os.getenv("LLM_MODEL", "")
    if not base_url or not model:
        return None

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"问题：{question}\n\n"
                    f"可用材料：\n{build_context(results)}\n\n"
                    "请依据材料作答，并在每个关键结论后标注方括号编号。"
                ),
            },
        ],
    }
    endpoint = f"{base_url}/chat/completions"
    response = requests.post(
        endpoint,
        headers=headers,
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


def sentence_terms(question: str) -> set[str]:
    ignored = {
        "公司",
        "年报",
        "2025",
        "年度",
        "报告",
        "多少",
        "什么",
        "如何",
        "请问",
        "一家",
    }
    terms = {token for token in tokenize(question) if token not in ignored}
    if any(term in question for term in ("审计机构", "会计师事务所")):
        terms.add("会计师事务所")
    if "中期分红" in question:
        terms.add("利润分配")
    return terms


def table_excerpt(question: str, chunk: dict[str, Any]) -> str | None:
    rows = chunk.get("rows") or []
    if len(rows) < 2:
        return None
    terms = sentence_terms(question)
    header = rows[0]
    scored = []
    for row in rows:
        text = " ".join(row)
        score = sum(term in text for term in terms)
        first_nonempty = next((cell.strip() for cell in row if cell.strip()), "")
        for qualifier in ("直销", "批发代理", "国内", "国外"):
            if qualifier in question and first_nonempty == qualifier:
                score += 5
        numbers = [numeric_value(cell) for cell in row if numeric_value(cell) is not None]
        if asks_for_numeric_answer(question) and not numbers:
            score -= 8
        if "研发投入" in question and any(
            label in text
            for label in ("研发投入合计", "研发投入金额")
        ):
            score += 6
        for metric, aliases in METRIC_ALIASES.items():
            if metric not in question:
                continue
            if any(alias in text for alias in aliases):
                score += 3
            if "研发费用" in question:
                if "资本化" in text and "资本化" not in question:
                    score -= 3
                if any(token in text for token in ("合计", "研发费用", "研发投入金额")):
                    score += 1
            if "营业收入" in question and any(
                token in text for token in ("贸易业务", "营业收入构成")
            ):
                score -= 2
        if numbers:
            score += 0.2
        scored.append((score, row))
    score, best = max(scored, key=lambda item: item[0])
    if score <= 0:
        return None
    values = []
    for column, cell in enumerate(best):
        if cell and column < len(header):
            values.append(f"{header[column]}={cell}")
    return "；".join(values[:8])


def text_excerpt(question: str, chunk: dict[str, Any]) -> str:
    text = chunk.get("text") or chunk["content"]
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    terms = sentence_terms(question)
    scored = []
    for line in lines:
        score = sum(term in line for term in terms)
        if re.search(r"\d", line):
            score += 0.25
        scored.append((score, line))
    candidates = sorted(scored, key=lambda item: item[0], reverse=True)
    selected = [line for _, line in candidates[:2] if line]
    if asks_for_numeric_answer(question):
        selected = [line for line in selected if re.search(r"\d", line)]
    return " ".join(selected)[:400]


def asks_for_numeric_answer(question: str) -> bool:
    return any(term in question for term in ("多少", "金额", "是多少", "几", "数值"))


def numeric_value(value: str) -> float | None:
    compact = value.replace(",", "").replace("%", "").strip()
    try:
        return float(compact)
    except ValueError:
        return None


def format_amount(value: float, unit_hint: str = "元") -> str:
    if unit_hint == "元" and abs(value) >= 100_000_000:
        return f"{value / 100_000_000:,.2f} 亿元（{value:,.2f} 元）"
    absolute = f"{value:,.2f}"
    if unit_hint and unit_hint not in absolute:
        return f"{absolute} {unit_hint}"
    return absolute


def metric_data(
    question: str,
    result: SearchResult,
) -> tuple[str, list[float]] | None:
    chunk = result.chunk
    rows = chunk.get("rows") or []
    if chunk.get("chunk_type") != "table" or len(rows) < 2:
        return None

    requested_metrics = [
        metric for metric in METRIC_ALIASES if metric in question
    ]
    if not requested_metrics:
        return None

    best_row = None
    best_score = -1
    metric_label = requested_metrics[0]
    for row in rows:
        row_text = " ".join(row)
        score = 0
        for metric in requested_metrics:
            for alias in METRIC_ALIASES[metric]:
                if alias in row_text:
                    score += 4
                if any(cell.strip() == alias for cell in row):
                    score += 3
        if "研发投入" in question and any(
            label in row_text
            for label in ("研发投入合计", "研发投入金额")
        ):
            score += 6
        if (
            any(term in question for term in ("研发费用", "研发投入"))
            and "资本化" in row_text
            and "资本化" not in question
        ):
            score -= 4
        if "营业收入" in question and "贸易业务" in row_text:
            score -= 3
        numbers = [numeric_value(cell) for cell in row if numeric_value(cell) is not None]
        if not numbers:
            continue
        score += 1
        if score > best_score:
            best_score = score
            best_row = row

    if best_row is None or best_score <= 0:
        return None

    label = next(
        (
            cell.strip().replace("\n", "")
            for cell in best_row
            if cell.strip() and numeric_value(cell) is None
        ),
        metric_label,
    )
    values = [
        value for cell in best_row if (value := numeric_value(cell)) is not None
    ]
    if not values:
        return None
    return label, values


def metric_answer(
    question: str,
    result: SearchResult,
) -> str | None:
    if not is_primary_metric_query(question):
        return None
    extracted = metric_data(question, result)
    if not extracted:
        return None
    label, values = extracted
    chunk = result.chunk

    amount = format_amount(values[0])
    sentence = (
        f"{chunk['company']}《{chunk['report_year']}年年报》披露，"
        f"{label}为 **{amount}**"
    )
    if len(values) >= 2:
        sentence += f"，上年同期为 {format_amount(values[1])}"
    if len(values) >= 3 and -1000 < values[2] < 1000:
        direction = "增长" if values[2] > 0 else "下降"
        sentence += f"，同比{direction} {abs(values[2]):.2f}%"
    sentence += (
        f"。[1]"
        f"（PDF第{chunk['pdf_page_start']}页；"
        f"报告第{chunk['printed_page_start'] or '?'}页）"
    )
    return sentence


def cross_company_metric_answer(
    question: str,
    results: list[SearchResult],
) -> str | None:
    if len({result.chunk["company"] for result in results}) < 2:
        return None
    rows = []
    seen = set()
    for index, result in enumerate(results, start=1):
        company = result.chunk["company"]
        if company in seen:
            continue
        extracted = metric_data(question, result)
        if not extracted:
            continue
        seen.add(company)
        label, values = extracted
        rows.append((company, label, values, index, result))
    if len(rows) < 2:
        return None

    if "最低" in question:
        rows.sort(key=lambda item: item[2][0])
        order_text = "从低到高"
    else:
        rows.sort(key=lambda item: item[2][0], reverse=True)
        order_text = "从高到低"

    compared_count = len(rows)
    if any(term in question for term in ("前三", "前3", "前三家", "三家")):
        rows = rows[:3]
    elif any(term in question for term in ("前五", "前5", "前五家")):
        rows = rows[:5]
    elif any(term in question for term in ("最高", "最低")):
        rows = rows[:1]

    lines = [
        f"按{rows[0][1]}{order_text}，本次检索结果为：",
        "",
    ]
    for rank, (company, _, values, citation, result) in enumerate(rows, start=1):
        line = (
            f"{rank}. **{company}**：{format_amount(values[0])} "
            f"[{citation}]（PDF第{result.chunk['pdf_page_start']}页）"
        )
        if len(values) >= 3 and -1000 < values[2] < 1000:
            direction = "增长" if values[2] > 0 else "下降"
            line += f"，同比{direction} {abs(values[2]):.2f}%"
        lines.append(line)
    lines.extend(
        ["", f"比较覆盖 {compared_count} 家公司；未覆盖公司不作排名。"]
    )
    return "\n".join(lines)


def audit_institution_answer(
    question: str,
    results: list[SearchResult],
) -> str | None:
    if not any(term in question for term in ("审计机构", "会计师事务所")):
        return None
    pattern = re.compile(
        r"([\u4e00-\u9fff]{2,20}会计师事务所(?:[（(]特殊普通合伙[）)])?)"
    )
    generic_prefixes = (
        "公司聘请",
        "聘任",
        "解聘",
        "前任",
        "现任",
        "名称",
        "审计期间",
    )
    for index, result in enumerate(results, start=1):
        name = next(
            (
                match.group(1)
                for match in pattern.finditer(result.chunk["content"])
                if not match.group(1).startswith(generic_prefixes)
                and len(match.group(1)) <= 30
            ),
            None,
        )
        if not name:
            continue
        chunk = result.chunk
        return (
            f"{chunk['company']}《{chunk['report_year']}年年报》披露，"
            f"审计机构为 **{name}**。[{index}]"
            f"（PDF第{chunk['pdf_page_start']}页；"
            f"报告第{chunk['printed_page_start'] or '?'}页）"
        )
    return None


def extractive_answer(question: str, results: list[SearchResult]) -> str:
    entity_answer = audit_institution_answer(question, results)
    if entity_answer:
        return entity_answer
    cross_answer = cross_company_metric_answer(question, results)
    if cross_answer:
        return cross_answer
    if results and asks_for_numeric_answer(question):
        exact = metric_answer(question, results[0])
        if exact:
            return exact
    bullets = []
    seen_companies = set()
    bullet_limit = 1 if asks_for_numeric_answer(question) else 3
    for index, result in enumerate(results[:12], start=1):
        chunk = result.chunk
        is_cross_company = len({item.chunk["company"] for item in results}) > 1
        if is_cross_company and chunk["company"] in seen_companies:
            continue
        seen_companies.add(chunk["company"])
        excerpt = (
            table_excerpt(question, chunk)
            if chunk["chunk_type"] == "table"
            else None
        ) or text_excerpt(question, chunk)
        if asks_for_numeric_answer(question) and not re.search(r"\d", excerpt or ""):
            continue
        if excerpt:
            bullets.append(
                f"- {chunk['company']}：{excerpt} "
                f"[{index}]（PDF第{chunk['pdf_page_start']}页）"
            )
        if not is_cross_company and len(bullets) >= bullet_limit:
            break
    if not bullets:
        return "当前检索材料不足以确认该问题。"
    return (
        "根据检索到的财报原文：\n\n"
        + "\n".join(bullets)
        + "\n\n完整证据见下方出处。"
    )


def answer_question(
    question: str,
    results: list[SearchResult],
) -> tuple[str, str]:
    if any(pattern in question for pattern in OUT_OF_SCOPE_PATTERNS):
        return (
            "材料不足以确认：当前知识库仅收录 2025 年年度报告，"
            "无法回答 2026 年季度报告或 2027 年的数据。",
            "extractive",
        )
    generated = call_openai_compatible(question, results)
    if generated:
        return generated, "llm"
    return extractive_answer(question, results), "extractive"
