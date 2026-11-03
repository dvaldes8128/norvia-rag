"""Validate Norvia hybrid retrieval on InsuranceQA-v2 with local Ollama embeds.

Dataset
-------
``deccan-ai/insuranceQA-v2`` (Feng et al. InsuranceQA, reconstructed on HF).
Theme: real insurance-customer questions + professional answers — closest
well-known public retrieval corpus to Norvia's policy-document domain.

Protocol (RAG-style, same shape as production retrieval)
--------------------------------------------------------
* Corpus = every answer in the **test** split (3 308 passages).
* Queries = unique questions in the test split (~2 000).
* Gold = all answers written for that exact question text.
* Near-copy gate disabled (ratio=0): open NL questions are not near-quotes.

Modes per embedding model
-------------------------
1. **dense** — cosine over Ollama embeddings (with model-specific task prefixes).
2. **hybrid** — Norvia ``fuse_scores`` at production weights (vector 0.6 / text 0.4)
   over dense cosine + a BM25 lexical channel (stands in for Postgres ``ts_rank``).

Usage
-----
    cd backend
    uv run python -m eval.experiments.insuranceqa_ollama
    uv run python -m eval.experiments.insuranceqa_ollama --max-queries 200  # smoke
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.retrieval.hybrid import fuse_scores
from app.retrieval.near_copy import is_near_copy

HERE = Path(__file__).resolve().parent
DATA_PATH = HERE / "data" / "insuranceqa_v2_test.jsonl"
OUT_DIR = HERE / "out"
CACHE_DIR = HERE / "cache"
HF_TEST_URL = (
    "https://huggingface.co/datasets/deccan-ai/insuranceQA-v2/resolve/main/test.jsonl"
)

DEFAULT_MODELS = ("nomic-embed-text", "embeddinggemma")
DEFAULT_K_LIST = (1, 3, 5, 10)
VECTOR_WEIGHT = 0.6
TEXT_WEIGHT = 0.4
CANDIDATE_POOL = 80  # like retrieve(): max(k*4, 20) with room for k=10
NEAR_COPY_MIN_RATIO = 0.0  # disable for open QA
BATCH_SIZE = 8
OLLAMA_URL = "http://127.0.0.1:11434"
# Defaults sized for local Ollama on CPU (~0.2–0.3 docs/s for nomic; gemma slower).
DEFAULT_MAX_QUERIES = 100
DEFAULT_CORPUS_SIZE = 250
DEFAULT_EMBED_MAX_CHARS = 512  # BM25 still sees full text; dense uses a head window
RNG_SEED = 7

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)


@dataclass(frozen=True)
class Doc:
    doc_id: str
    text: str


@dataclass
class QueryItem:
    query_id: str
    text: str
    relevant_doc_ids: list[str]


def _ensure_dataset(path: Path) -> None:
    if path.exists() and path.stat().st_size > 0:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {HF_TEST_URL} → {path}", flush=True)
    with httpx.stream("GET", HF_TEST_URL, follow_redirects=True, timeout=120.0) as resp:
        resp.raise_for_status()
        with path.open("wb") as fh:
            for chunk in resp.iter_bytes():
                fh.write(chunk)


def load_insuranceqa(path: Path) -> tuple[list[Doc], list[QueryItem]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    docs: list[Doc] = []
    q_to_docs: dict[str, list[str]] = defaultdict(list)
    for i, row in enumerate(rows):
        doc_id = f"a{i:04d}"
        text = " ".join(str(row["output"]).split())
        docs.append(Doc(doc_id=doc_id, text=text))
        q = " ".join(str(row["input"]).split())
        q_to_docs[q].append(doc_id)
    queries = [
        QueryItem(query_id=f"q{i:04d}", text=q, relevant_doc_ids=list(ids))
        for i, (q, ids) in enumerate(sorted(q_to_docs.items(), key=lambda x: x[0]))
    ]
    return docs, queries


def subsample_retrieval_set(
    docs: list[Doc],
    queries: list[QueryItem],
    *,
    max_queries: int,
    corpus_size: int,
    seed: int = RNG_SEED,
) -> tuple[list[Doc], list[QueryItem], dict]:
    """Keep a fair RAG slice: all golds for selected queries + random negatives.

    Absolute scores are not comparable to a full-corpus paper number; relative
    ranking of embedding models under the same slice is still meaningful.
    """
    rng = random.Random(seed)
    selected_queries = list(queries)
    if max_queries and max_queries < len(selected_queries):
        selected_queries = rng.sample(selected_queries, max_queries)
        selected_queries.sort(key=lambda q: q.query_id)

    gold_ids: set[str] = set()
    for q in selected_queries:
        gold_ids.update(q.relevant_doc_ids)

    by_id = {d.doc_id: d for d in docs}
    gold_docs = [by_id[i] for i in sorted(gold_ids)]
    negatives = [d for d in docs if d.doc_id not in gold_ids]
    rng.shuffle(negatives)

    target = corpus_size if corpus_size > 0 else len(docs)
    if target < len(gold_docs):
        target = len(gold_docs)
    fill_n = max(0, target - len(gold_docs))
    corpus = gold_docs + negatives[:fill_n]
    corpus.sort(key=lambda d: d.doc_id)

    meta = {
        "max_queries_requested": max_queries,
        "corpus_size_requested": corpus_size,
        "n_gold_docs": len(gold_docs),
        "n_negative_docs": len(corpus) - len(gold_docs),
        "seed": seed,
        "full_test_docs": len(docs),
        "full_test_queries": len(queries),
    }
    return corpus, selected_queries, meta


def _cache_key(model: str, docs: list[Doc], queries: list[QueryItem]) -> str:
    h = hashlib.sha1()
    h.update(model.encode())
    h.update(str(len(docs)).encode())
    h.update(str(len(queries)).encode())
    if docs:
        h.update(docs[0].doc_id.encode())
        h.update(docs[-1].doc_id.encode())
        h.update(docs[len(docs) // 2].text[:80].encode())
    if queries:
        h.update(queries[0].query_id.encode())
        h.update(queries[-1].text[:80].encode())
    return f"{model.replace(':', '_')}_{h.hexdigest()[:10]}"


def _prefix_pair(model: str) -> tuple[str, str]:
    """Return (query_prefix, document_prefix) for known Ollama embedders."""
    name = model.lower()
    if "nomic" in name:
        return "search_query: ", "search_document: "
    if "embeddinggemma" in name or "gemma" in name:
        return "task: search result | query: ", "title: none | text: "
    return "", ""


def embed_texts(
    client: httpx.Client,
    *,
    model: str,
    texts: list[str],
    batch_size: int = BATCH_SIZE,
    label: str = "",
) -> list[list[float]]:
    out: list[list[float]] = []
    total = len(texts)
    t0 = time.perf_counter()
    for start in range(0, total, batch_size):
        batch = texts[start : start + batch_size]
        resp = client.post(
            f"{OLLAMA_URL}/api/embed",
            json={"model": model, "input": batch},
            timeout=180.0,
        )
        resp.raise_for_status()
        vectors = resp.json()["embeddings"]
        if len(vectors) != len(batch):
            raise RuntimeError(f"Ollama returned {len(vectors)} vectors for {len(batch)} inputs")
        out.extend(vectors)
        done = min(start + batch_size, total)
        if done == total or done % (batch_size * 8) == 0:
            rate = done / max(time.perf_counter() - t0, 1e-6)
            print(
                f"  [{label}] embedded {done}/{total} ({rate:.1f}/s)",
                flush=True,
            )
    return out


def _l2_normalize(mat: list[list[float]]) -> list[list[float]]:
    normed: list[list[float]] = []
    for row in mat:
        s = math.sqrt(sum(x * x for x in row)) or 1.0
        normed.append([x / s for x in row])
    return normed


def cosine_scores(query: list[float], corpus: list[list[float]]) -> list[float]:
    # corpus rows assumed L2-normalised; query too → dot product
    return [sum(a * b for a, b in zip(query, doc, strict=True)) for doc in corpus]


class BM25Index:
    """Lightweight BM25Okapi (k1=1.5, b=0.75) for the lexical channel."""

    def __init__(self, documents: list[str], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.docs = [_tokenize(d) for d in documents]
        self.doc_len = [len(toks) for toks in self.docs]
        self.avgdl = sum(self.doc_len) / max(len(self.docs), 1)
        df: Counter[str] = Counter()
        for toks in self.docs:
            df.update(set(toks))
        n = len(self.docs)
        self.idf = {
            t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()
        }
        self.tf = [Counter(toks) for toks in self.docs]

    def scores(self, query: str) -> list[float]:
        q_toks = _tokenize(query)
        out: list[float] = []
        for i, tf in enumerate(self.tf):
            score = 0.0
            dl = self.doc_len[i]
            for t in q_toks:
                if t not in tf:
                    continue
                freq = tf[t]
                idf = self.idf.get(t, 0.0)
                denom = freq + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                score += idf * (freq * (self.k1 + 1)) / denom
            out.append(score)
        return out


def _tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in _TOKEN_RE.finditer(text)]


def _dcg(rels: list[float], k: int) -> float:
    total = 0.0
    for i, rel in enumerate(rels[:k], start=1):
        total += (2**rel - 1) / math.log2(i + 1)
    return total


def ndcg_at_k(ranked_ids: list[str], relevant: set[str], k: int) -> float:
    gains = [1.0 if d in relevant else 0.0 for d in ranked_ids[:k]]
    ideal = sorted(gains, reverse=True)
    idcg = _dcg(ideal, k)
    if idcg <= 0:
        return 0.0
    return _dcg(gains, k) / idcg


def recall_at_k(ranked_ids: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    hit = sum(1 for d in ranked_ids[:k] if d in relevant)
    return hit / len(relevant)


def accuracy_at_k(ranked_ids: list[str], relevant: set[str], k: int) -> float:
    return 1.0 if any(d in relevant for d in ranked_ids[:k]) else 0.0


def mrr_at_k(ranked_ids: list[str], relevant: set[str], k: int) -> float:
    for i, d in enumerate(ranked_ids[:k], start=1):
        if d in relevant:
            return 1.0 / i
    return 0.0


def _topk_indices(scores: list[float], k: int) -> list[int]:
    indexed = list(enumerate(scores))
    indexed.sort(key=lambda x: x[1], reverse=True)
    return [i for i, _ in indexed[:k]]


def rank_dense(query_vec: list[float], corpus: list[list[float]], k: int) -> list[int]:
    scores = cosine_scores(query_vec, corpus)
    return _topk_indices(scores, k)


def rank_hybrid(
    *,
    query_text: str,
    query_vec: list[float],
    corpus_vecs: list[list[float]],
    bm25: BM25Index,
    doc_ids: list[str],
    docs_by_id: dict[str, str],
    k: int,
    candidate_pool: int,
    near_copy_min_ratio: float,
) -> list[int]:
    dense = cosine_scores(query_vec, corpus_vecs)
    lexical = bm25.scores(query_text)

    # Candidate union: top pool by dense + top pool by lexical (Norvia retrieve shape)
    dense_idx = set(_topk_indices(dense, candidate_pool))
    lex_idx = set(_topk_indices(lexical, candidate_pool))
    cand = sorted(dense_idx | lex_idx)

    v_scores = [dense[i] for i in cand]
    t_scores = [lexical[i] for i in cand]
    fused = fuse_scores(
        v_scores,
        t_scores,
        vector_weight=VECTOR_WEIGHT,
        text_weight=TEXT_WEIGHT,
    )
    ranked = sorted(zip(cand, fused, strict=True), key=lambda x: x[1], reverse=True)

    kept: list[int] = []
    for idx, _score in ranked:
        content = docs_by_id[doc_ids[idx]]
        if not is_near_copy(query_text, content, min_ratio=near_copy_min_ratio):
            continue
        kept.append(idx)
        if len(kept) >= k:
            break
    return kept


def aggregate_metrics(
    per_query: list[dict],
    *,
    k_list: tuple[int, ...],
) -> dict[str, float]:
    summary: dict[str, float] = {"n_queries": float(len(per_query))}
    for k in k_list:
        summary[f"accuracy@{k}"] = sum(r[f"accuracy@{k}"] for r in per_query) / len(per_query)
        summary[f"recall@{k}"] = sum(r[f"recall@{k}"] for r in per_query) / len(per_query)
        summary[f"ndcg@{k}"] = sum(r[f"ndcg@{k}"] for r in per_query) / len(per_query)
        summary[f"mrr@{k}"] = sum(r[f"mrr@{k}"] for r in per_query) / len(per_query)
    return summary


def _clip(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars]


def evaluate_model(
    *,
    model: str,
    docs: list[Doc],
    queries: list[QueryItem],
    k_list: tuple[int, ...],
    client: httpx.Client,
    reuse_cache: bool,
    batch_size: int = BATCH_SIZE,
    embed_max_chars: int = DEFAULT_EMBED_MAX_CHARS,
) -> dict:
    max_k = max(k_list)
    q_prefix, d_prefix = _prefix_pair(model)
    cache_path = CACHE_DIR / f"{_cache_key(model, docs, queries)}_c{embed_max_chars}.json"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    doc_ids = [d.doc_id for d in docs]
    docs_by_id = {d.doc_id: d.text for d in docs}
    bm25 = BM25Index([d.text for d in docs])

    if reuse_cache and cache_path.exists():
        print(f"[{model}] loading cached embeddings from {cache_path}", flush=True)
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        corpus_vecs = cached["corpus"]
        query_vecs = cached["queries"]
        if len(corpus_vecs) != len(docs) or len(query_vecs) != len(queries):
            raise RuntimeError(
                f"Cache size mismatch for {model}: "
                f"corpus {len(corpus_vecs)}/{len(docs)}, queries {len(query_vecs)}/{len(queries)}"
            )
    else:
        print(
            f"[{model}] embedding corpus ({len(docs)} docs, max_chars={embed_max_chars}) …",
            flush=True,
        )
        corpus_raw = embed_texts(
            client,
            model=model,
            texts=[d_prefix + _clip(d.text, embed_max_chars) for d in docs],
            batch_size=batch_size,
            label=f"{model}/docs",
        )
        print(f"[{model}] embedding queries ({len(queries)}) …", flush=True)
        query_raw = embed_texts(
            client,
            model=model,
            texts=[q_prefix + _clip(q.text, embed_max_chars) for q in queries],
            batch_size=batch_size,
            label=f"{model}/queries",
        )
        corpus_vecs = _l2_normalize(corpus_raw)
        query_vecs = _l2_normalize(query_raw)
        cache_path.write_text(
            json.dumps({"corpus": corpus_vecs, "queries": query_vecs}),
            encoding="utf-8",
        )
        print(f"[{model}] wrote cache → {cache_path}", flush=True)

    modes = ("dense", "hybrid")
    mode_rows: dict[str, list[dict]] = {m: [] for m in modes}

    t0 = time.perf_counter()
    for qi, q in enumerate(queries):
        relevant = set(q.relevant_doc_ids)
        qv = query_vecs[qi]

        dense_idx = rank_dense(qv, corpus_vecs, max_k)
        hybrid_idx = rank_hybrid(
            query_text=q.text,
            query_vec=qv,
            corpus_vecs=corpus_vecs,
            bm25=bm25,
            doc_ids=doc_ids,
            docs_by_id=docs_by_id,
            k=max_k,
            candidate_pool=CANDIDATE_POOL,
            near_copy_min_ratio=NEAR_COPY_MIN_RATIO,
        )

        for mode, idxs in (("dense", dense_idx), ("hybrid", hybrid_idx)):
            ranked_ids = [doc_ids[i] for i in idxs]
            row: dict = {
                "query_id": q.query_id,
                "question": q.text,
                "n_relevant": len(relevant),
                "retrieved": ranked_ids,
            }
            for k in k_list:
                row[f"accuracy@{k}"] = accuracy_at_k(ranked_ids, relevant, k)
                row[f"recall@{k}"] = recall_at_k(ranked_ids, relevant, k)
                row[f"ndcg@{k}"] = ndcg_at_k(ranked_ids, relevant, k)
                row[f"mrr@{k}"] = mrr_at_k(ranked_ids, relevant, k)
            mode_rows[mode].append(row)

        if (qi + 1) % 200 == 0 or qi + 1 == len(queries):
            print(
                f"  [{model}] scored {qi + 1}/{len(queries)} "
                f"({(qi + 1) / max(time.perf_counter() - t0, 1e-6):.1f} q/s)",
                flush=True,
            )

    result = {
        "model": model,
        "query_prefix": q_prefix,
        "document_prefix": d_prefix,
        "embedding_dim": len(corpus_vecs[0]) if corpus_vecs else 0,
        "modes": {
            mode: {
                "summary": aggregate_metrics(rows, k_list=k_list),
                "per_query": rows,
            }
            for mode, rows in mode_rows.items()
        },
    }
    return result


def render_html(payload: dict, path: Path) -> None:
    models = payload["models"]
    k_list = payload["k_list"]
    generated = payload["generated_at"]

    def pct(x: float) -> str:
        return f"{100 * x:.1f}%"

    def cell(x: float) -> str:
        return f"{x:.3f}"

    # Summary table rows
    summary_rows = []
    for m in models:
        for mode in ("dense", "hybrid"):
            s = m["modes"][mode]["summary"]
            cells = "".join(
                f"<td>{cell(s[f'accuracy@{k}'])}</td>"
                f"<td>{cell(s[f'recall@{k}'])}</td>"
                f"<td>{cell(s[f'ndcg@{k}'])}</td>"
                f"<td>{cell(s[f'mrr@{k}'])}</td>"
                for k in k_list
            )
            summary_rows.append(
                f"<tr><td><code>{m['model']}</code></td><td>{mode}</td>{cells}</tr>"
            )

    metric_headers = "".join(
        f"<th colspan='4'>@{k}</th>" for k in k_list
    )
    sub_headers = "".join(
        "<th>Acc</th><th>Rec</th><th>nDCG</th><th>MRR</th>" for _ in k_list
    )

    # Bar chart data for accuracy@5 / ndcg@10
    bars = []
    for m in models:
        for mode in ("dense", "hybrid"):
            s = m["modes"][mode]["summary"]
            label = f"{m['model']} · {mode}"
            bars.append(
                {
                    "label": label,
                    "acc5": s["accuracy@5"],
                    "ndcg10": s["ndcg@10"],
                    "mrr10": s["mrr@10"],
                }
            )

    max_bar = max(max(b["acc5"], b["ndcg10"], b["mrr10"]) for b in bars) or 1.0
    bar_html = []
    for b in bars:
        bar_html.append(
            "<div class='bar-group'>"
            f"<div class='bar-label'>{b['label']}</div>"
            "<div class='bar-tracks'>"
            f"<div class='track'><span class='fill acc' style='width:{100*b['acc5']/max_bar:.1f}%'></span>"
            f"<em>acc@5 {pct(b['acc5'])}</em></div>"
            f"<div class='track'><span class='fill ndcg' style='width:{100*b['ndcg10']/max_bar:.1f}%'></span>"
            f"<em>ndcg@10 {pct(b['ndcg10'])}</em></div>"
            f"<div class='track'><span class='fill mrr' style='width:{100*b['mrr10']/max_bar:.1f}%'></span>"
            f"<em>mrr@10 {pct(b['mrr10'])}</em></div>"
            "</div></div>"
        )

    # Winner callouts
    best_hybrid = max(
        ((m["model"], m["modes"]["hybrid"]["summary"]["ndcg@10"]) for m in models),
        key=lambda x: x[1],
    )
    best_dense = max(
        ((m["model"], m["modes"]["dense"]["summary"]["ndcg@10"]) for m in models),
        key=lambda x: x[1],
    )

    # Miss examples: queries where dense fails@5 for both, or delta between models
    miss_rows = []
    if len(models) >= 2:
        a, b = models[0], models[1]
        a_map = {r["query_id"]: r for r in a["modes"]["hybrid"]["per_query"]}
        b_map = {r["query_id"]: r for r in b["modes"]["hybrid"]["per_query"]}
        deltas = []
        for qid, ra in a_map.items():
            rb = b_map[qid]
            deltas.append(
                (
                    rb["ndcg@10"] - ra["ndcg@10"],
                    ra["question"],
                    ra["ndcg@10"],
                    rb["ndcg@10"],
                )
            )
        deltas.sort(key=lambda x: x[0])
        for delta, q, na, nb in deltas[:8] + deltas[-8:]:
            miss_rows.append(
                f"<tr><td>{delta:+.2f}</td><td>{na:.2f}</td><td>{nb:.2f}</td>"
                f"<td>{_escape(q)}</td></tr>"
            )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Norvia retrieval validation — InsuranceQA-v2</title>
<style>
:root {{
  --bg: #f6f3ee;
  --ink: #1c1916;
  --muted: #5c554c;
  --line: #d9d0c3;
  --card: #fffdf8;
  --acc: #0f6b5c;
  --ndcg: #8a4b1f;
  --mrr: #2f4d7a;
  --accent: #9c2f2f;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
  background:
    radial-gradient(1200px 600px at 10% -10%, #efe4d4 0%, transparent 60%),
    radial-gradient(900px 500px at 100% 0%, #dfe8e4 0%, transparent 55%),
    var(--bg);
  color: var(--ink); line-height: 1.45;
}}
main {{ max-width: 1100px; margin: 0 auto; padding: 2.5rem 1.25rem 4rem; }}
h1 {{ font-family: "IBM Plex Serif", Georgia, serif; font-weight: 600; font-size: 2rem; margin: 0 0 .4rem; }}
h2 {{ font-family: "IBM Plex Serif", Georgia, serif; font-size: 1.35rem; margin: 2.2rem 0 .75rem; }}
.lede {{ color: var(--muted); max-width: 62ch; }}
.meta {{ display: flex; flex-wrap: wrap; gap: .5rem .9rem; margin: 1.2rem 0 1.8rem; color: var(--muted); font-size: .92rem; }}
.meta span {{ background: var(--card); border: 1px solid var(--line); padding: .25rem .55rem; border-radius: 4px; }}
.verdict {{
  background: var(--card); border-left: 4px solid var(--accent);
  padding: 1rem 1.1rem; margin: 1rem 0 1.5rem; border-radius: 0 6px 6px 0;
}}
table {{ width: 100%; border-collapse: collapse; background: var(--card); font-size: .86rem; }}
th, td {{ border: 1px solid var(--line); padding: .4rem .45rem; text-align: right; }}
th {{ background: #efe8dc; font-weight: 600; }}
td:first-child, td:nth-child(2), th:first-child, th:nth-child(2) {{ text-align: left; }}
.bar-group {{ margin: .85rem 0 1.1rem; }}
.bar-label {{ font-size: .9rem; margin-bottom: .25rem; }}
.track {{ position: relative; height: 1.55rem; background: #ebe4d8; border-radius: 3px; margin: .2rem 0; overflow: hidden; }}
.fill {{ display: block; height: 100%; }}
.fill.acc {{ background: var(--acc); }}
.fill.ndcg {{ background: var(--ndcg); }}
.fill.mrr {{ background: var(--mrr); }}
.track em {{ position: absolute; left: .5rem; top: 0; bottom: 0; display: flex; align-items: center;
  font-style: normal; font-size: .78rem; color: #fff; text-shadow: 0 1px 1px rgba(0,0,0,.35); }}
code {{ font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: .9em; }}
.note {{ color: var(--muted); font-size: .9rem; }}
</style>
</head>
<body>
<main>
  <h1>Norvia retrieval validation</h1>
  <p class="lede">
    Offline A/B of the hybrid retrieval pipeline (dense + lexical fuse, same weights as
    production) on <strong>InsuranceQA-v2</strong> — the closest well-known public
    retrieval corpus to insurance / policy Q&amp;A — using the two Ollama embedding models
    already pulled locally.
  </p>
  <div class="meta">
    <span>Generated { _escape(generated) }</span>
    <span>Corpus: {payload['n_docs']} answers</span>
    <span>Queries: {payload['n_queries']}</span>
    <span>Near-copy gate: {payload['near_copy_min_ratio']} (off)</span>
    <span>Hybrid weights: vector {payload['vector_weight']} / text {payload['text_weight']}</span>
    <span>Embed window: {payload.get('embed_max_chars', '—')} chars</span>
    <span>Ollama: {payload.get('ollama_processor', 'local')}</span>
  </div>

  <div class="verdict">
    <strong>Headline.</strong>
    Best hybrid nDCG@10: <code>{_escape(best_hybrid[0])}</code> at {best_hybrid[1]:.3f}.
    Best dense nDCG@10: <code>{_escape(best_dense[0])}</code> at {best_dense[1]:.3f}.
    Compare hybrid vs dense within each model to see whether the lexical channel helps
    on this insurance FAQ-style corpus the same way it does on Norvia’s policy PDFs.
  </div>

  <h2>Protocol</h2>
  <ul class="note">
    <li>Dataset: <code>deccan-ai/insuranceQA-v2</code> test split (Feng et al. InsuranceQA).</li>
    <li>Slice: {payload['n_queries']} random unique questions; corpus = all their gold answers + random negatives → {payload['n_docs']} passages (CPU-friendly; relative model comparison).</li>
    <li>Gold = answers written for that exact question text.</li>
    <li>Dense: cosine on L2-normalised Ollama embeddings with model task prefixes.</li>
    <li>Hybrid: Norvia <code>fuse_scores</code> over dense ∪ BM25 candidate pools (stand-in for pgvector + FTS).</li>
    <li>This run is an experiment harness — not the CI pytest suite.</li>
  </ul>

  <h2>Summary metrics</h2>
  <table>
    <thead>
      <tr><th rowspan="2">Model</th><th rowspan="2">Mode</th>{metric_headers}</tr>
      <tr>{sub_headers}</tr>
    </thead>
    <tbody>
      {''.join(summary_rows)}
    </tbody>
  </table>

  <h2>Accuracy@5 · nDCG@10 · MRR@10</h2>
  {''.join(bar_html)}

  <h2>Model prefixes used</h2>
  <table>
    <thead><tr><th>Model</th><th>Query prefix</th><th>Document prefix</th><th>Dim</th></tr></thead>
    <tbody>
      {''.join(
        f"<tr><td><code>{_escape(m['model'])}</code></td>"
        f"<td><code>{_escape(m['query_prefix'])}</code></td>"
        f"<td><code>{_escape(m['document_prefix'])}</code></td>"
        f"<td>{m['embedding_dim']}</td></tr>"
        for m in models
      )}
    </tbody>
  </table>

  <h2>Hybrid nDCG@10 deltas ({_escape(models[0]['model'] if models else '')} → {_escape(models[1]['model'] if len(models)>1 else '')})</h2>
  <p class="note">Largest negative / positive per-query swings (hybrid mode). Useful to spot systematic failures.</p>
  <table>
    <thead><tr><th>Δ nDCG@10</th><th>{_escape(models[0]['model']) if models else 'A'}</th><th>{_escape(models[1]['model']) if len(models)>1 else 'B'}</th><th>Question</th></tr></thead>
    <tbody>{''.join(miss_rows) if miss_rows else '<tr><td colspan="4">n/a</td></tr>'}</tbody>
  </table>

  <h2>Raw artefact</h2>
  <p class="note">Machine-readable results: <code>{_escape(str(payload.get('results_path', 'results.json')))}</code></p>
</main>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def _escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", default=list(DEFAULT_MODELS))
    parser.add_argument(
        "--max-queries",
        type=int,
        default=DEFAULT_MAX_QUERIES,
        help="Unique questions to evaluate (0 = all). Default subsample for CPU Ollama.",
    )
    parser.add_argument(
        "--corpus-size",
        type=int,
        default=DEFAULT_CORPUS_SIZE,
        help="Corpus size after including all golds + random negatives (0 = all answers).",
    )
    parser.add_argument("--seed", type=int, default=RNG_SEED)
    parser.add_argument("--k", nargs="+", type=int, default=list(DEFAULT_K_LIST))
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument(
        "--embed-max-chars",
        type=int,
        default=DEFAULT_EMBED_MAX_CHARS,
        help="Truncate embed inputs (0 = full). Lexical/BM25 still uses full text.",
    )
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--data", type=Path, default=DATA_PATH)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args(argv)

    k_list = tuple(sorted(set(args.k)))
    _ensure_dataset(args.data)
    all_docs, all_queries = load_insuranceqa(args.data)
    docs, queries, slice_meta = subsample_retrieval_set(
        all_docs,
        all_queries,
        max_queries=args.max_queries,
        corpus_size=args.corpus_size,
        seed=args.seed,
    )

    print(
        f"InsuranceQA-v2 slice: {len(docs)} docs ({slice_meta['n_gold_docs']} gold + "
        f"{slice_meta['n_negative_docs']} neg), {len(queries)} queries "
        f"(full test={slice_meta['full_test_docs']}×{slice_meta['full_test_queries']}; "
        f"models={args.models})",
        flush=True,
    )

    # Sanity: Ollama up
    with httpx.Client(timeout=30.0) as client:
        try:
            tags = client.get(f"{OLLAMA_URL}/api/tags").json()
        except httpx.HTTPError as exc:
            print(f"Ollama not reachable at {OLLAMA_URL}: {exc}", file=sys.stderr)
            return 2
        available = {m["name"] for m in tags.get("models", [])}
        available_base = {n.split(":", 1)[0] for n in available}
        for model in args.models:
            base = model.split(":", 1)[0]
            if model not in available and base not in available_base:
                print(f"Model not in Ollama: {model}. Have: {sorted(available)}", file=sys.stderr)
                return 2

        model_results = []
        for model in args.models:
            model_results.append(
                evaluate_model(
                    model=model,
                    docs=docs,
                    queries=queries,
                    k_list=k_list,
                    client=client,
                    reuse_cache=not args.no_cache,
                    batch_size=args.batch_size,
                    embed_max_chars=args.embed_max_chars,
                )
            )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    results_path = args.out_dir / "results.json"
    html_path = args.out_dir / "report.html"
    payload = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ"),
        "dataset": "deccan-ai/insuranceQA-v2",
        "dataset_split": "test",
        "protocol": (
            "subsample: random unique test questions; corpus = all gold answers for "
            "those questions + random negatives to corpus_size; "
            "gold=answers for identical question text; near_copy disabled; "
            "hybrid uses Norvia fuse_scores(0.6/0.4) over dense∪BM25 pools"
        ),
        "slice": slice_meta,
        "n_docs": len(docs),
        "n_queries": len(queries),
        "k_list": list(k_list),
        "vector_weight": VECTOR_WEIGHT,
        "text_weight": TEXT_WEIGHT,
        "candidate_pool": CANDIDATE_POOL,
        "near_copy_min_ratio": NEAR_COPY_MIN_RATIO,
        "embed_max_chars": args.embed_max_chars,
        "ollama_url": OLLAMA_URL,
        "ollama_processor": "cpu",
        "models": [
            {
                "model": m["model"],
                "query_prefix": m["query_prefix"],
                "document_prefix": m["document_prefix"],
                "embedding_dim": m["embedding_dim"],
                "modes": {
                    mode: {
                        "summary": m["modes"][mode]["summary"],
                        # Keep a short sample of misses in the HTML-facing JSON;
                        # full per-query lives beside for deep dives.
                        "per_query": m["modes"][mode]["per_query"],
                    }
                    for mode in m["modes"]
                },
            }
            for m in model_results
        ],
        "results_path": str(results_path),
    }

    # Write a lean summary JSON plus a heavy full dump
    lean = {
        **{k: v for k, v in payload.items() if k != "models"},
        "models": [
            {
                "model": m["model"],
                "query_prefix": m["query_prefix"],
                "document_prefix": m["document_prefix"],
                "embedding_dim": m["embedding_dim"],
                "modes": {
                    mode: {"summary": m["modes"][mode]["summary"]}
                    for mode in m["modes"]
                },
            }
            for m in payload["models"]
        ],
    }
    results_path.write_text(json.dumps(lean, indent=2), encoding="utf-8")
    full_path = args.out_dir / "results_full.json"
    # Full file can be large; still useful
    full_path.write_text(json.dumps(payload), encoding="utf-8")
    render_html(payload, html_path)

    print("\n=== Summary ===", flush=True)
    print(json.dumps(lean["models"], indent=2), flush=True)
    print(f"\nWrote {results_path}", flush=True)
    print(f"Wrote {full_path}", flush=True)
    print(f"Wrote {html_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
