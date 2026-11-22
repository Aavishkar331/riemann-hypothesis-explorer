# rh-explorer

A browsable map of the Lean 4 proof of the Riemann Hypothesis (and GRH for Dirichlet L-functions) announced by Levent Alpöge with Claude on 20 November 2026.

The proof is about 164k files and 16.7M lines. This project indexes all of it and builds a dependency graph you can explore in the browser, starting from the five main theorems in `Main.lean`.

## What you get

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

The workflow frees disk space on the runner, installs Lean with elan, downloads the community build cache, runs the extractor, then runs the indexer and site builder. The extractor has been tested on a small project; the first full run is the real test. If the runner runs out of disk, memory or time, run the same steps on any Linux machine with about 100 GB free disk and 16 GB RAM.

The community cache includes builds from volunteer machines. That is fine for a map; it is not a proof check.

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

With the proof built (`lake exe cache get && lake build --no-build` inside the proof repo):

```bash
cd ../riemann-hypothesis
cp ../rh-explorer/extractor/ExtractDeps.lean .
ulimit -s unlimited
lake env lean --run ExtractDeps.lean ../deps.tsv Main \
  BuildAid,CompanionTheory,Development,Formalism,GroundTheory,Lemmata,PositivityTheory,ReciprocityTheory,Supplements,Statements,Main
cd ../rh-explorer
python3 indexer/index_lean.py ../riemann-hypothesis/src data 2
python3 indexer/exact_edges.py data ../deps.tsv
python3 indexer/build_site_data.py data docs/data.json $(git -C ../riemann-hypothesis rev-parse HEAD) 8000
```

## How it works

- `index_lean.py` finds every declaration, tracks `namespace`/`section`/`end` and `open`, and records full names, statements and source lines. `private` names are scoped to their file, as in Lean. Its name-based edges resolve identifiers through the namespaces in scope.
- `ExtractDeps.lean` imports the compiled environment and, for each project constant, collects the project constants used in its type and value. Auto-generated helpers (`foo.proof_1`, `foo.match_1`, `foo._simp_1`, equation lemmas) are folded into `foo`.
- `exact_edges.py` maps those names onto the index, folding a structure's `mk`, `rec` and fields into the structure, and adds declarations the parser cannot see (such as instances Lean named automatically).
- `build_site_data.py` runs a breadth-first search from the five main theorems and writes the nearest ~8,000 declarations plus the 300 most reused ones to `docs/data.json`.

## Limits

- `simp` lemmas proved by `rfl` leave no trace in proof terms, so even exact mode cannot see them. That is how Lean works, not a gap in the extractor.
- This shows structure, not meaning, and it is not a proof check.

## Next steps

- Plain-English summaries of the top few hundred declarations, generated bottom-up with a free LLM (Gemini free tier or Ollama)
- Load the full graph from SQLite instead of the 8k subset

## Credits

The proof is by Levent Alpöge with Claude. The source is from [leanprover-community/riemann-hypothesis](https://github.com/leanprover-community/riemann-hypothesis).
