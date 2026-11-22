# rh-explorer

A browsable map of the Lean 4 proof of the Riemann Hypothesis (and GRH for Dirichlet L-functions) announced by Levent Alpöge with Claude on 20 November 2026.

The proof is about 164k files and 16.7M lines. This project indexes all of it and builds a dependency graph you can explore in the browser, starting from the five main theorems in `Main.lean`.

## What you get

- **Which results carry the proof**: a dominator analysis of the exact dependency graph. A result "owns" the declarations that exist only to prove it; the biggest owners form the proof's outline
- **The main line** from the Riemann Hypothesis down to the core, with plain-English summaries (marked as written by Claude from the Lean statements)
- **The 20 steps of the announcement**, each with the code whose names match its technical terms (name matching, unverified)
- **Published mathematics inside the proof**: 446 classical results the proof states as propositions and proves (Local Langlands, Casselman–Wallach, Howe duality…), with how often each is used and how large its proof is

- Search over declarations
- A page for each declaration: its statement, kind, depth from the main theorems, how many declarations it uses and how many use it, and a link to the exact line on GitHub
- An expandable "what it uses" tree, with cycles marked
- A chart of how many declarations sit at each depth
- Lines of code per library, and how much of each library the main theorems use

## Two kinds of edges

| Mode | Source | Needs | Accuracy |
|---|---|---|---|
| **Exact** | Lean's compiled proof terms, via `extractor/ExtractDeps.lean` | the built proof (community cache, about 5 GB download) | Every constant in a declaration's type or proof, including type class instances, `simp` lemmas and automation |
| By name | text parsing, `indexer/index_lean.py` | only the source | Misses what Lean fills in by itself; a lower bound |

The page says which mode its data came from.

## Exact mode on GitHub Actions (free)

1. Push this repo to GitHub (public repos get free Actions minutes).
2. Open **Actions → Exact dependencies → Run workflow**.
3. When it finishes, download the `exact-deps` artifact and copy its `data.json` into `docs/`.

The compiled proof is about 28.6 GB compressed and well over 100 GB unpacked, more than a free runner's disk. So the workflow never unpacks it whole: `extractor/stream_extract.py` downloads the published `.olean` archive as a stream, unpacks a batch of files, runs `extractor/ExtractOleans.lean` on it and deletes it. `ExtractOleans.lean` reads each `.olean` on its own (`readModuleData`), so it needs neither Mathlib nor the rest of the build.

The archive is Jack McCarthy's published build of the original submission (commit `40e56bab`, Lean 4.33.1), so the map describes the proof exactly as published.

## By-name mode locally

```bash
git clone --depth 1 https://github.com/leanprover-community/riemann-hypothesis ../riemann-hypothesis

# Index every .lean file (about 4 minutes on 2 cores, about 500 MB of output)
python3 indexer/index_lean.py ../riemann-hypothesis/src data 2

# Build the JSON the page loads
python3 indexer/build_site_data.py data docs/data.json $(git -C ../riemann-hypothesis rev-parse HEAD) 8000

cd docs && python3 -m http.server 8000
```

Needs Python 3.10+ and NumPy.

## Exact mode locally

Needs `zstd`, Lean 4.33.1 and about 10 GB of free disk:

```bash
python3 extractor/stream_extract.py \
  https://huggingface.co/datasets/JackMcCarthy/riemann-hypothesis-build/resolve/9036e64326acf4acfae159b96664e9708445c1d1/oleans.tar.zst \
  deps.tsv.gz --lean "$(which lean)" --extractor extractor/ExtractOleans.lean
python3 indexer/index_lean.py ../riemann-hypothesis/src data 2     # source at commit 40e56bab
python3 indexer/exact_edges.py data deps.tsv.gz
python3 indexer/dominators.py data          # who owns which part of the proof
python3 indexer/build_insights.py data      # outline, literature, steps, summaries
python3 indexer/build_site_data.py data docs/data.json <full commit hash> 8000
```

`extractor/ExtractDeps.lean` does the same from a fully built project (`lake env lean --run ...`) if you have one.

## How it works

- `index_lean.py` finds every declaration, tracks `namespace`/`section`/`end` and `open`, and records full names, statements and source lines. `private` names are scoped to their file, as in Lean. Its name-based edges resolve identifiers through the namespaces in scope.
- `ExtractOleans.lean` reads each compiled `.olean` and, for each constant, collects the constants used in its type and value. `exact_edges.py` then drops the ones from Mathlib and Lean core. Auto-generated helpers (`foo.proof_1`, `foo.match_1`, `foo._simp_1`, equation lemmas) are folded into `foo`.
- `exact_edges.py` maps those names onto the index, folding a structure's `mk`, `rec` and fields into the structure, and adds declarations the parser cannot see (such as instances Lean named automatically).
- `dominators.py` computes the dominator tree from the five main theorems (Cooper–Harvey–Kennedy). X owns Y when every chain of uses from the top to Y passes through X.
- `build_insights.py` builds the outline, the list of published results with the theorems that prove them, the step-to-code matches and the summaries.
- `build_site_data.py` runs a breadth-first search from the five main theorems and writes the nearest ~8,000 declarations plus the 300 most reused ones to `docs/data.json`.

## Limits

- `simp` lemmas proved by `rfl` leave no trace in proof terms, so even exact mode cannot see them. That is how Lean works, not a gap in the extractor.
- This shows structure, not meaning, and it is not a proof check.

## Next steps

- Plain-English summaries of the top few hundred declarations, generated bottom-up with a free LLM (Gemini free tier or Ollama)
- Load the full graph from SQLite instead of the 8k subset

## Credits

The proof is by Levent Alpöge with Claude. The source is from [leanprover-community/riemann-hypothesis](https://github.com/leanprover-community/riemann-hypothesis).
