"""Dominator analysis of the proof graph.

A declaration D dominates X when every chain of uses from the main theorems
down to X passes through D. The set D dominates is the part of the proof that
exists only to serve D: its private sub-proof. Big dominated sets mark the
load-bearing results; the dominator tree is a natural table of contents.

usage: dominators.py DATA_DIR  ->  DATA_DIR/dom.npz (idom, owned, depth)
Algorithm: Cooper, Harvey and Kennedy, "A Simple, Fast Dominance Algorithm".
"""
import sys, time
import numpy as np

ROOTS = ["riemannHypothesis", "riemannZeta_eq_zero_re", "LFunction_ne_zero_of_half_lt_re",
         "LFunction_eq_zero_re", "LFunction_eq_zero_re_of_isPrimitive"]


def load(data):
    names = []
    with open(f"{data}/decls.tsv", encoding="utf-8") as f:
        next(f)
        for row in f:
            names.append(row.split("\t", 2)[1])
    e = np.fromfile(f"{data}/edges.bin", dtype=np.uint32).reshape(-1, 2).astype(np.int64)
    return names, e


def main(data):
    t = time.time()
    names, e = load(data)
    N = len(names)
    S = N                                   # virtual root above the five theorems
    idx = {n: i for i, n in enumerate(names)}
    roots = [idx[r] for r in ROOTS if r in idx]
    src = np.concatenate([e[:, 0], np.full(len(roots), S)])
    dst = np.concatenate([e[:, 1], roots])
    V = N + 1
    o = np.argsort(src, kind="stable"); succ = dst[o]; sp = np.concatenate([[0], np.cumsum(np.bincount(src, minlength=V))])
    # reverse postorder by iterative DFS from S
    post, seen = [], np.zeros(V, bool)
    stack = [(S, 0)]; seen[S] = True
    while stack:
        v, k = stack[-1]
        if k < sp[v + 1] - sp[v]:
            stack[-1] = (v, k + 1)
            w = succ[sp[v] + k]
            if not seen[w]:
                seen[w] = True; stack.append((w, 0))
        else:
            stack.pop(); post.append(v)
    rpo = post[::-1]
    order = np.full(V, -1, np.int64); order[rpo] = np.arange(len(rpo))
    reach = order >= 0
    keep = reach[src] & reach[dst]
    ps, pd = src[keep], dst[keep]
    o = np.argsort(pd, kind="stable"); pred = ps[o]; pp = np.concatenate([[0], np.cumsum(np.bincount(pd, minlength=V))])
    print(f"{len(rpo) - 1} reachable, graph ready in {time.time() - t:.0f}s", flush=True)
    idom = np.full(V, -1, np.int64); idom[S] = S
    po = np.full(V, -1, np.int64); po[post] = np.arange(len(post))   # postorder number

    def intersect(a, b):
        while a != b:
            while po[a] < po[b]: a = idom[a]
            while po[b] < po[a]: b = idom[b]
        return a

    changed, it = True, 0
    while changed:
        changed, it = False, it + 1
        for v in rpo[1:]:
            new = -1
            for p in pred[pp[v]:pp[v + 1]]:
                if idom[p] != -1:
                    new = p if new == -1 else intersect(p, new)
            if new != idom[v]:
                idom[v] = new; changed = True
        print(f"  pass {it}, {time.time() - t:.0f}s", flush=True)
    # dominated-set sizes: accumulate in reverse RPO (children before parents)
    owned = np.zeros(V, np.int64)
    owned[reach] = 1
    for v in reversed(rpo[1:]):
        owned[idom[v]] += owned[v]
    dd = np.full(V, -1, np.int64); dd[S] = 0
    for v in rpo[1:]:
        dd[v] = dd[idom[v]] + 1
    np.savez(f"{data}/dom.npz", idom=idom[:N], owned=owned[:N], domdepth=dd[:N], S=S)
    print(f"done in {time.time() - t:.0f}s; top owners:")
    for i in np.argsort(-owned[:N])[:25]:
        print(f"  {owned[i]:>8}  {names[i]}")


if __name__ == "__main__":
    main(sys.argv[1])
