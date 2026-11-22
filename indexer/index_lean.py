"""Static indexer for a Lean 4 project.

Parses every .lean file under SRC without compiling, and writes:
  out/decls.tsv   id, name, kind, module, line, signature
  out/edges.bin   uint32 pairs (src_id, dst_id): "src mentions dst"
  out/modules.tsv module, lines, bytes, imports

Dependencies are resolved by name lookup (namespace + `open` aware),
so they approximate, but do not equal, Lean's real dependency graph.
"""
import os, re, sys, time, array
from multiprocessing import Pool

DECL_KW = ("theorem", "lemma", "def", "abbrev", "structure", "class", "instance",
           "inductive", "opaque", "axiom", "irreducible_def")
MODS = {"private", "protected", "noncomputable", "nonrec", "partial", "unsafe",
        "scoped", "local", "@[", "class"}

ATTR = re.compile(r"^(?:@\[[^\]]*\]\s*)+")
MOD = re.compile(r"^(?:(?:private|protected|noncomputable|nonrec|partial|unsafe|scoped|local)\s+)+")
HEAD = re.compile(r"^(class\s+inductive|theorem|lemma|def|abbrev|structure|class|instance|inductive|opaque|axiom|irreducible_def)\b\s*(?:\([^)]*\)\s*)?(?:\[[^\]]*\]\s*)?([^\s:({\[⦃]+)?")
IDENT = re.compile(r"[^\W\d][\w'!?₀-₉ₐ-ₜᵢ-ᵪ]*(?:\.[^\W\d][\w'!?₀-₉ₐ-ₜᵢ-ᵪ]*)*")
STRIP = re.compile(r"--[^\n]*|/-.*?-/|\"(?:\\.|[^\"\\])*\"", re.S)
TOPSTOP = re.compile(r"^(?:namespace|end|section|noncomputable section|open|variable|universe|import|set_option|attribute|omit|include|mutual|#)\b")


def module_of(path, src):
    return os.path.relpath(path, src)[:-5].replace(os.sep, ".")


def parse_file(path, src):
    """Yield one record per declaration plus file-level info."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    lines = text.split("\n")
    mod = module_of(path, src)
    imports = [l.split()[1] for l in lines if l.startswith("import ")]
    ns_stack = []          # entries: ("ns", parts) or ("sec", None)
    opens = set()
    decls = []             # [name, kind, line, start, end, ns, opens]
    cur = None
    pos = 0
    offsets = []
    for l in lines:
        offsets.append(pos)
        pos += len(l) + 1

    def close(end_line):
        if cur is not None:
            cur[4] = end_line

    pending_attr_line = None
    for i, l in enumerate(lines):
        if not l or l[0] in " \t":
            continue
        s = l
        if s.startswith("@[") and ATTR.match(s) and not ATTR.sub("", s).strip():
            pending_attr_line = i
            continue
        body = MOD.sub("", ATTR.sub("", s))
        m = HEAD.match(body)
        if m:
            close(i)
            kind = m.group(1).split()[-1] if m.group(1).startswith("class") else m.group(1)
            name = m.group(2)
            if kind == "instance" and (not name or name.startswith(("[", "(", ":"))):
                name = None
            ns = ".".join(p for t, p in ns_stack if t == "ns")
            start = pending_attr_line if pending_attr_line is not None else i
            priv = bool(re.match(r"(?:@\[[^\]]*\]\s*)*(?:\w+\s+)*?private\b", s))
            cur = [name, kind, i + 1, start, len(lines), ns, frozenset(opens), priv]
            decls.append(cur)
            pending_attr_line = None
            continue
        pending_attr_line = None
        if TOPSTOP.match(s):
            close(i)
            cur = None
            w = s.split()
            if w[0] == "namespace" and len(w) > 1:
                ns_stack.append(("ns", w[1]))
            elif w[0] == "section" or s.startswith("noncomputable section"):
                ns_stack.append(("sec", None))
            elif w[0] == "end" and ns_stack:
                ns_stack.pop()
            elif w[0] == "open":
                for tok in w[1:]:
                    if tok in ("in", "scoped", "hiding", "renaming") or not tok[:1].isalpha():
                        break
                    opens.add(tok)
    out = []
    for name, kind, line, a, b, ns, ops, priv in decls:
        if not name:
            continue
        if name.startswith("_root_."):
            full = name[7:]
        else:
            full = f"{ns}.{name}" if ns else name
        chunk = "\n".join(lines[a:b])
        # private names are file-local in Lean, so key them by module
        key = f"{mod}::{full}" if priv else full
        out.append((key, kind, line, chunk, ns, ops))
    return mod, len(lines), len(text.encode()), imports, out


def signature(chunk):
    c = STRIP.sub(" ", chunk)
    c = MOD.sub("", ATTR.sub("", c.lstrip()))
    cut = len(c)
    for sep in (":=", " where", "\n  |"):
        k = c.find(sep)
        if k != -1:
            cut = min(cut, k)
    sig = re.sub(r"\s+", " ", c[:cut]).strip()
    return sig[:700]


# ---------- pass 1: declarations ----------
def p1(args):
    path, src = args
    try:
        mod, nl, nb, imps, decls = parse_file(path, src)
    except Exception as e:
        return None
    return mod, nl, nb, imps, [(n, k, ln, signature(ch)) for n, k, ln, ch, _, _ in decls]


# ---------- pass 2: dependencies ----------
NAME2ID = None
UNIQUE_LAST = None   # last name component -> id, only when exactly one decl has it


def init2(name2id):
    global NAME2ID, UNIQUE_LAST
    NAME2ID = name2id
    count, last_id = {}, {}
    for n, i in name2id.items():
        if "::" in n:
            continue
        last = n.rsplit(".", 1)[-1]
        count[last] = count.get(last, 0) + 1
        last_id[last] = i
    UNIQUE_LAST = {k: last_id[k] for k, c in count.items() if c == 1 and len(k) >= 4}


def looks_like_term(head):
    """`hx.foo` or `F.foo`: dot notation on a local term, not a namespace."""
    return len(head) <= 2 or head[0].islower()


def resolve(tok, ns_parts, opens, mod):
    d = resolve_exact(tok, ns_parts, opens, mod)
    if d is None and "." in tok:
        head, rest = tok.split(".", 1)
        if looks_like_term(head):
            d = resolve_exact(rest, ns_parts, opens, mod)
            if d is None:
                d = UNIQUE_LAST.get(rest.rsplit(".", 1)[-1])
    return d


def resolve_exact(tok, ns_parts, opens, mod):
    n2i = NAME2ID
    for cand_tok in (tok, tok.rsplit(".", 1)[0] if "." in tok else None):
        if not cand_tok:
            continue
        for k in range(len(ns_parts), -1, -1):
            pre = ".".join(ns_parts[:k])
            c = f"{pre}.{cand_tok}" if pre else cand_tok
            pc = f"{mod}::{c}"
            if pc in n2i:
                return n2i[pc]
            if c in n2i:
                return n2i[c]
        for o in opens:
            c = f"{o}.{cand_tok}"
            if c in n2i:
                return n2i[c]
    return None


def p2(args):
    path, src = args
    try:
        mod, _, _, _, decls = parse_file(path, src)
    except Exception:
        return array.array("I")
    edges = array.array("I")
    for full, kind, line, chunk, ns, ops in decls:
        sid = NAME2ID.get(full)
        if sid is None:
            continue
        ns_parts = ns.split(".") if ns else []
        # names declared in a namespace are also visible relative to that namespace
        seen = set()
        body = STRIP.sub(" ", chunk)
        for tok in set(IDENT.findall(body)):
            d = resolve(tok, ns_parts, ops, mod)
            if d is not None and d != sid and d not in seen:
                seen.add(d)
                edges.append(sid)
                edges.append(d)
    return edges


EXCLUDE = {"Challenge.lean"}   # added by the checkers; restates the five theorems


def main(src, out, jobs=2):
    os.makedirs(out, exist_ok=True)
    files = sorted(os.path.join(r, f) for r, _, fs in os.walk(src) for f in fs
                   if f.endswith(".lean") and os.path.relpath(os.path.join(r, f), src) not in EXCLUDE)
    print(f"{len(files)} files", flush=True)
    t = time.time()
    name2id, rows = {}, []
    with open(f"{out}/modules.tsv", "w") as mf, Pool(jobs) as pool:
        mf.write("module\tlines\tbytes\timports\n")
        for i, r in enumerate(pool.imap_unordered(p1, [(f, src) for f in files], chunksize=64)):
            if r is None:
                continue
            mod, nl, nb, imps, decls = r
            mf.write(f"{mod}\t{nl}\t{nb}\t{' '.join(imps)}\n")
            for n, k, ln, sig in decls:
                if n in name2id:
                    continue
                name2id[n] = len(rows)
                rows.append((n, k, mod, ln, sig))
            if i % 20000 == 0:
                print(f"  pass1 {i} files, {len(rows)} decls, {time.time()-t:.0f}s", flush=True)
    with open(f"{out}/decls.tsv", "w") as df:
        df.write("id\tname\tkind\tmodule\tline\tsignature\n")
        for i, (n, k, m, ln, sig) in enumerate(rows):
            df.write(f"{i}\t{n}\t{k}\t{m}\t{ln}\t{sig.replace(chr(9), ' ')}\n")
    print(f"pass1 done: {len(rows)} decls in {time.time()-t:.0f}s", flush=True)
    del rows
    t = time.time()
    n_edges = 0
    with open(f"{out}/edges.bin", "wb") as ef, Pool(jobs, initializer=init2, initargs=(name2id,)) as pool:
        for i, e in enumerate(pool.imap_unordered(p2, [(f, src) for f in files], chunksize=64)):
            e.tofile(ef)
            n_edges += len(e) // 2
            if i % 20000 == 0:
                print(f"  pass2 {i} files, {n_edges} edges, {time.time()-t:.0f}s", flush=True)
    print(f"pass2 done: {n_edges} edges in {time.time()-t:.0f}s", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 2)
