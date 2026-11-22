"""Replace the name-based edges with exact ones from ExtractDeps.lean.

usage: exact_edges.py DATA_DIR DEPS_TSV[.gz]

Each extractor key is mapped onto the indexer's declarations. Keys the indexer
does not know (a structure's `Foo.mk`, `Foo.rec`, a field `Foo.w`) are folded
into the nearest known parent name. Keys with no known parent, such as
instances Lean named automatically, are added as new declarations.

Writes DATA_DIR/edges.bin (the old one is kept as edges_by_name.bin),
appends any new declarations to decls.tsv and writes mode.txt = "exact".
"""
import array, gzip, os, sys


def main(data, deps_path):
    name2id, n = {}, 0
    with open(f"{data}/decls.tsv", encoding="utf-8") as f:
        next(f)
        for row in f:
            name2id[row.split("\t", 2)[1]] = n
            n += 1
    new_rows = []

    memo = {}

    def lookup(key):
        if key in memo:
            return memo[key]
        r = memo[key] = lookup_uncached(key)
        return r

    def lookup_uncached(key):
        if key in name2id:
            return name2id[key]
        mod, sep, name = key.rpartition("::")
        if sep and name in name2id:      # private auxiliary of a public declaration
            return name2id[name]
        parts = name.split(".")
        for k in range(len(parts) - 1, 0, -1):
            cand = f"{mod}{sep}{'.'.join(parts[:k])}"
            if cand in name2id:
                return name2id[cand]
        return None

    def ensure(key, module):
        i = lookup(key)
        # Only instances Lean named itself (`instFoo`) and private helpers are new
        # declarations. Anything else unknown is an equation lemma Lean generated
        # in this module for someone else's definition (e.g. Mathlib's), not ours.
        last = key.rsplit("::", 1)[-1].rsplit(".", 1)[-1]
        if i is None and not (last.startswith("inst") or "::" in key):
            return None
        if i is None:
            i = name2id[key] = n + len(new_rows)
            memo.clear()
            kind = "instance" if key.rsplit(".", 1)[-1].startswith("inst") else "def"
            new_rows.append((key, kind, module))
        return i

    opener = gzip.open if deps_path.endswith(".gz") else open

    def rows():
        with opener(deps_path, "rt", encoding="utf-8") as f:
            for row in f:
                p = row.rstrip("\n").split("\t")
                if len(p) >= 2:
                    yield p[0], p[1], p[2:]

    # pass 1: register every source first, so later lines can point at earlier ones
    for module, src, _ in rows():
        ensure(src, module)
    edges, lines = array.array("I"), 0
    for module, src, deps in rows():
        s = lookup(src)
        if s is None:
            continue
        out = set()
        for d in deps:
            t = lookup(d)
            if t is not None and t != s:
                out.add(t)
        for t in out:
            edges.append(s); edges.append(t)
        lines += 1
        if lines % 200000 == 0:
            print(f"  {lines} lines, {len(edges)//2} edges", flush=True)
    if os.path.exists(f"{data}/edges.bin") and not os.path.exists(f"{data}/edges_by_name.bin"):
        os.rename(f"{data}/edges.bin", f"{data}/edges_by_name.bin")
    with open(f"{data}/edges.bin", "wb") as f:
        edges.tofile(f)
    with open(f"{data}/decls.tsv", "a", encoding="utf-8") as f:
        for k, (key, kind, module) in enumerate(new_rows):
            f.write(f"{n + k}\t{key}\t{kind}\t{module}\t0\t\n")
    with open(f"{data}/mode.txt", "w") as f:
        f.write("exact\n")
    print(f"{lines} extractor lines, {len(edges)//2} exact edges, {len(new_rows)} new declarations")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
