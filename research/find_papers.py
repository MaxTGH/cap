"""Paper finder from the command line (same pipeline as paper_finder.ipynb).

    .venv/bin/python find_papers.py "detect fraud in credit card transactions"
    .venv/bin/python find_papers.py --json "..."     # one line of JSON on stdout (used by CAP)

Describe an ML problem; get back recent papers ranked by SPECTER2 similarity.
If ANTHROPIC_API_KEY is set (shell or .env), Claude expands the description into
search queries; otherwise its keywords are searched directly. Progress goes to
stderr. Ranked results are saved to results/ like the notebook does.
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from paper import Paper

ROOT = Path(__file__).resolve().parent
OPENALEX_URL = "https://api.openalex.org/works"
FIELDS = "id,doi,title,publication_year,cited_by_count,type,abstract_inverted_index,primary_location,authorships"
CACHE = ROOT / "cache" / "paper_embeddings.npz"
STOPWORDS = set("""a an and are as at be based build by can could create detect do does find for from how i if in into
is it its make me model my of on or our predict should so some that the their them this to use using want we what
when whether which who will with would you your algorithm machine learning ml""".split())

EXPANSION_SCHEMA = {
    "type": "object",
    "properties": {
        "same_domain": {"type": "array", "items": {"type": "string"}},
        "analogous": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["same_domain", "analogous"],
    "additionalProperties": False,
}

EXPANSION_PROMPT = """I'm searching the academic literature (via the OpenAlex keyword search API) for recent papers that would help me build this machine learning system:

<problem>
{problem}
</problem>

Write short keyword search queries (2-5 words each, the way researchers would phrase titles and abstracts, not how a layperson would):
- same_domain: 4-6 queries for papers about this exact application, using the terminology and synonyms researchers in that field use.
- analogous: 4-6 queries for papers that solve the same kind of ML problem in a different domain, where methods, datasets, or lessons would transfer. Include an angle on fairness, bias, or regulation if the application affects people.

Avoid overly generic queries like "machine learning" on their own; each query should narrow to a useful set of papers."""


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def load_env() -> None:
    """Load KEY=value lines from .env (gitignored) without overriding the shell environment."""
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"\''))


def expand_with_claude(problem: str) -> dict:
    import anthropic
    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model="claude-opus-5",
        max_tokens=2000,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": EXPANSION_SCHEMA}},
        # If the request is ever declined by a safety classifier, retry on a fallback model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": EXPANSION_PROMPT.format(problem=problem.strip())}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined the query-expansion request")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def keyword_queries(problem: str) -> dict:
    """Without Claude: search the description's keywords, then shorter slices of them."""
    words = [w for w in re.findall(r"[a-z0-9][a-z0-9-]*", problem.lower()) if w not in STOPWORDS]
    words = list(dict.fromkeys(words))  # dedupe, keep order
    if not words:
        return {"same_domain": [problem.strip()]}
    queries = [" ".join(words[:6])]
    if len(words) > 3:
        queries += [" ".join(words[:3]), " ".join(words[-3:])]
    return {"same_domain": list(dict.fromkeys(queries))}


def openalex_search(query: str, since_year: int, n: int, max_retries: int = 25) -> list:
    params = {
        "search": query,
        "filter": f"from_publication_date:{since_year}-01-01,has_abstract:true,type:article|preprint|review",
        "per_page": min(n, 200),
        "select": FIELDS,
    }
    if os.environ.get("OPENALEX_API_KEY"):
        params["api_key"] = os.environ["OPENALEX_API_KEY"]
    for attempt in range(max_retries):
        r = requests.get(OPENALEX_URL, params=params, timeout=60)
        if r.status_code == 429 or r.status_code >= 500:
            try:
                wait = float(r.json().get("retryAfter") or r.headers.get("retry-after") or 5)
            except ValueError:
                wait = 5 * (attempt + 1)
            log(f"  OpenAlex {r.status_code} on '{query}', retrying in {wait:.0f}s...")
            time.sleep(wait + 1)
            continue
        r.raise_for_status()
        return r.json()["results"]
    log(f"  giving up on '{query}' after {max_retries} tries (set OPENALEX_API_KEY to avoid rate limits)")
    return []


def load_specter():
    import torch
    from adapters import AutoAdapterModel
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained("allenai/specter2_base")
    model = AutoAdapterModel.from_pretrained("allenai/specter2_base")
    model.load_adapter("allenai/specter2", source="hf", load_as="proximity", set_active=False)  # embedding papers
    model.load_adapter("allenai/specter2_adhoc_query", source="hf", load_as="adhoc_query", set_active=False)  # short search text
    model.eval()
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model.to(device)

    def embed(texts: list, adapter: str, batch_size: int = 16) -> np.ndarray:
        model.set_active_adapters(adapter)
        out = []
        for i in range(0, len(texts), batch_size):
            if len(texts) > batch_size:
                log(f"  embedding papers {min(i + batch_size, len(texts))}/{len(texts)}")
            batch = tokenizer(texts[i:i + batch_size], padding=True, truncation=True, max_length=512,
                              return_tensors="pt", return_token_type_ids=False).to(device)
            with torch.no_grad():
                out.append(model(**batch).last_hidden_state[:, 0, :].cpu().numpy())  # [CLS] token
        return np.vstack(out)

    return tokenizer, embed


def find_papers(problem: str, since_year: int, per_query: int, top_k: int, citation_weight: float) -> dict:
    used_claude = False
    queries = None
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            log("Expanding the description into search queries with Claude...")
            queries, used_claude = expand_with_claude(problem), True
        except Exception as e:
            log(f"Claude expansion failed ({type(e).__name__}: {e}); searching keywords instead.")
    if queries is None:
        queries = keyword_queries(problem)
    for kind, qs in queries.items():
        log(f"{kind} queries: " + "; ".join(qs))

    papers: dict[str, Paper] = {}  # OpenAlex id -> Paper
    all_queries = [(kind, q) for kind, qs in queries.items() for q in qs]
    for i, (kind, q) in enumerate(all_queries, 1):
        log(f"Searching OpenAlex ({i}/{len(all_queries)}): {q}")
        for w in openalex_search(q, since_year, per_query):
            if w["id"] not in papers:
                paper = Paper.from_openalex(w)
                if not paper.title or not paper.abstract:
                    continue
                papers[paper.id] = paper
            papers[w["id"]].kinds.add(kind)
            papers[w["id"]].matched_queries.add(q)
    log(f"{len(papers)} unique candidate papers")
    if not papers:
        return {"problem": problem, "queries": queries, "used_claude": used_claude, "candidates": 0, "papers": []}

    log("Loading SPECTER2...")
    tokenizer, embed = load_specter()
    CACHE.parent.mkdir(exist_ok=True)
    cache = dict(np.load(CACHE)) if CACHE.exists() else {}
    ids = list(papers)
    todo = [i for i in ids if i.split("/")[-1] not in cache]
    if todo:
        texts = [papers[i].title + tokenizer.sep_token + papers[i].abstract for i in todo]
        for i, v in zip(todo, embed(texts, "proximity")):
            cache[i.split("/")[-1]] = v
        np.savez(CACHE, **cache)
    log(f"Embedded {len(todo)} new papers ({len(ids) - len(todo)} from cache). Ranking...")

    paper_vecs = np.vstack([cache[i.split("/")[-1]] for i in ids])
    query_vec = embed([" ".join(problem.split())], "adhoc_query")[0]
    normalize = lambda m: m / np.linalg.norm(m, axis=-1, keepdims=True)

    df = pd.DataFrame([papers[i] for i in ids])
    df["similarity"] = normalize(paper_vecs) @ normalize(query_vec)
    # SPECTER similarities sit in a narrow band, so rank on z-scores and add a mild citation bonus
    # (log-scaled, and per year since publication so new papers aren't buried).
    z = lambda s: (s - s.mean()) / (s.std() or 1)
    age = (pd.Timestamp.now().year - df["year"]).clip(lower=0) + 1
    df["score"] = z(df["similarity"]) + citation_weight * z(np.log1p(df["citations"] / age))
    df["kind"] = df["kinds"].map(lambda k: " + ".join(sorted(k)))
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
    df.index += 1

    (ROOT / "results").mkdir(exist_ok=True)
    out = ROOT / "results" / f"papers_{pd.Timestamp.now():%Y%m%d_%H%M}.csv"
    df.drop(columns=["kinds", "matched_queries"]).assign(
        matched_queries=df["matched_queries"].map(lambda q: "; ".join(sorted(q)))
    ).to_csv(out)

    # pandas turns a missing value into NaN, which isn't valid JSON for a browser (CAP); send null instead.
    text = lambda v: None if pd.isna(v) else v
    top = [{
        "title": p["title"],
        "url": text(p["url"]),
        "year": None if pd.isna(p["year"]) else int(p["year"]),
        "venue": text(p["venue"]),
        "first_author": text(p["first_author"]),
        "citations": int(p["citations"]),
        "kind": p["kind"],
        "similarity": round(float(p["similarity"]), 3),
        "score": round(float(p["score"]), 2),
        "abstract": p["abstract"][:600] + ("..." if len(p["abstract"]) > 600 else ""),
    } for _, p in df.head(top_k).iterrows()]
    return {"problem": problem, "queries": queries, "used_claude": used_claude,
            "candidates": len(df), "saved_to": str(out.relative_to(ROOT)), "papers": top}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("problem", help="the ML problem, in plain English")
    ap.add_argument("--since", type=int, default=2021, help="only papers published in or after this year")
    ap.add_argument("--per-query", type=int, default=200, help="OpenAlex results per search query (max 200)")
    ap.add_argument("--top", type=int, default=15, help="how many papers to show")
    ap.add_argument("--citation-weight", type=float, default=0.15, help="0 = rank purely by similarity")
    ap.add_argument("--json", action="store_true", help="print results as one line of JSON")
    args = ap.parse_args()

    load_env()
    r = find_papers(args.problem, args.since, args.per_query, args.top, args.citation_weight)
    if args.json:
        print(json.dumps(r))
        return
    if not r["papers"]:
        sys.exit("No papers found. Try different wording.")
    for rank, p in enumerate(r["papers"], 1):
        print(f"#{rank}  {p['title']}  ({p['year']}, {p['venue']}, {p['citations']} citations)")
        print(f"    {p['url']}   [{p['kind']}]")
        print(f"    {p['abstract']}\n")
    print(f"All {r['candidates']} ranked papers saved to {r['saved_to']}")


if __name__ == "__main__":
    main()
