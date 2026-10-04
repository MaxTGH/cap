# Paper finder

Describe a machine-learning problem in plain English and get back recent research papers that could help solve it, ranked by meaning rather than keyword overlap.

```bash
.venv/bin/python find_papers.py "predict which tenants will pay rent late"
.venv/bin/python find_papers.py --json "..."   # one line of JSON (used by CAP's Research panel)
```

`paper_finder.ipynb` runs the same pipeline step by step, with explanations.

## How it works

1. **Query expansion.** With an Anthropic API key, Claude turns the description into short academic search queries of two kinds: `same_domain` (papers about this exact problem) and `analogous` (the same kind of ML problem in another field, e.g. credit default prediction for tenant screening). Without a key, the description's keywords are searched directly.
2. **Candidate retrieval.** Each query runs against [OpenAlex](https://openalex.org) (recent papers with abstracts), and the results are pooled and deduplicated, typically a few hundred candidates.
3. **Semantic re-ranking.** The description and each paper's title and abstract are embedded with [SPECTER2](https://huggingface.co/allenai/specter2), a SciBERT-based model trained for scientific-paper similarity. It uses separate adapters for short queries (`adhoc_query`) and for papers (`proximity`).
4. **Scoring.** SPECTER2 similarities sit in a narrow band, so papers are ranked on the z-score of cosine similarity plus a small, log-scaled citations-per-year bonus. That way well-cited work rises without burying new papers.

Paper embeddings are cached in `cache/`, so repeat searches only embed new papers. Every run saves the full ranking to `results/`.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

The first run downloads about 450 MB of SPECTER2 weights. Both API keys are optional; put them in a `.env` file next to this README (it's gitignored):

```
OPENALEX_API_KEY=...    # free at openalex.org; avoids rate limits
ANTHROPIC_API_KEY=...   # enables Claude query expansion
```

Your description is sent to OpenAlex, and to Anthropic if a key is set.
