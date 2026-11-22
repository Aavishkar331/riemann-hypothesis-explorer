"""Turn the raw index into compact JSON for the web explorer.

usage: build_site_data.py DATA_DIR OUT_JSON COMMIT [MAX_NODES] [ROOT1,ROOT2,...]
"""
import json, os, sys, collections
import numpy as np

ROOTS = ["riemannHypothesis", "riemannZeta_eq_zero_re", "LFunction_ne_zero_of_half_lt_re",
         "LFunction_eq_zero_re", "LFunction_eq_zero_re_of_isPrimitive"]


def main(data, out, commit, max_nodes=8000, roots_names=ROOTS):
    names, kinds, mods, lines, sigs = [], [], [], [], []
    with open(f"{data}/decls.tsv", encoding="utf-8") as f:
        next(f)
        for row in f:
            p = row.rstrip("\n").split("\t", 5)
            names.append(p[1]); kinds.append(p[2]); mods.append(p[3]); lines.append(int(p[4]))
            sigs.append(p[5] if len(p) > 5 else "")
    N = len(names)
    e = np.fromfile(f"{data}/edges.bin", dtype=np.uint32).reshape(-1, 2)
    src, dst = e[:, 0].astype(np.int64), e[:, 1].astype(np.int64)
    used_by = np.bincount(dst, minlength=N)
    uses = np.bincount(src, minlength=N)
    order = np.argsort(src, kind="stable")
    dst_sorted = dst[order]
    ptr = np.concatenate([[0], np.cumsum(uses)])

    def children(i):
        return dst_sorted[ptr[i]:ptr[i + 1]]

    idx = {n: i for i, n in enumerate(names)}
    roots = [idx[r] for r in roots_names if r in idx]
    mode = open(f"{data}/mode.txt").read().strip() if os.path.exists(f"{data}/mode.txt") else "by-name"

    # breadth-first search from the five main theorems
    depth = np.full(N, -1, dtype=np.int32)
    q = collections.deque()
    for r in roots:
        depth[r] = 0; q.append(r)
    bfs = []
    while q:
        i = q.popleft(); bfs.append(i)
        for c in children(i):
            if depth[c] < 0:
                depth[c] = depth[i] + 1; q.append(c)
    reach = depth >= 0
    print(f"{N} decls, {len(e)} edges, {reach.sum()} reachable, max depth {depth.max()}")

    # choose which nodes ship to the browser: closest to the root first,
    # most reused first within a depth level, plus the globally most reused
    by_level = sorted(bfs, key=lambda i: (depth[i], -used_by[i]))
    keep = by_level[:max_nodes]
    top_used = [int(i) for i in np.argsort(-used_by)[:300]]
    keep_set = set(keep) | set(top_used)
    keep = sorted(keep_set, key=lambda i: (depth[i] if depth[i] >= 0 else 999, -used_by[i]))
    local = {g: k for k, g in enumerate(keep)}

    nodes = []
    for g in keep:
        ch = children(g)
        nodes.append({
            "n": names[g].split("::")[-1], "k": kinds[g],
            **({"p": 1} if "::" in names[g] else {}), "m": mods[g], "l": lines[g],
            "s": sigs[g][:400], "d": int(depth[g]),
            "c": [local[c] for c in ch if c in local], "nc": int(len(ch)),
            "u": int(used_by[g]),
        })

    # size per library and per sub-area
    mod_rows = {}
    with open(f"{data}/modules.tsv", encoding="utf-8") as f:
        next(f)
        for row in f:
            p = row.rstrip("\n").split("\t")
            mod_rows[p[0]] = (int(p[1]), int(p[2]))
    decl_per_mod = collections.Counter(mods)
    reach_per_mod = collections.Counter(mods[i] for i in np.nonzero(reach)[0])

    def area_stats(level):
        a = collections.defaultdict(lambda: [0, 0, 0, 0])
        for m, (nl, nb) in mod_rows.items():
            key = ".".join(m.split(".")[:level])
            s = a[key]; s[0] += 1; s[1] += nl; s[2] += decl_per_mod[m]; s[3] += reach_per_mod[m]
        return [{"a": k, "files": v[0], "lines": v[1], "decls": v[2], "reach": v[3]}
                for k, v in sorted(a.items(), key=lambda kv: -kv[1][1])]

    depth_hist = np.bincount(depth[reach]).tolist()
    kind_hist = collections.Counter(kinds)
    stats = {
        "mode": mode, "decls": N, "edges": int(len(e)), "reachable": int(reach.sum()),
        "files": len(mod_rows), "lines": sum(v[0] for v in mod_rows.values()),
        "maxDepth": int(depth.max()), "depthHist": depth_hist, "kinds": dict(kind_hist),
        "libs": area_stats(1), "areas": area_stats(2)[:60],
    }
    doc = {"commit": commit, "roots": [local[r] for r in roots], "stats": stats,
           "topUsed": [local[i] for i in top_used[:100]], "nodes": nodes}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {len(nodes)} nodes to {out}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 8000,
         sys.argv[5].split(",") if len(sys.argv) > 5 else ROOTS)
