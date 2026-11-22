"""Mathematician-facing views of the proof graph.

usage: build_insights.py DATA_DIR  ->  DATA_DIR/insights.json
Needs decls.tsv, edges.bin (exact) and dom.npz (from dominators.py).

  outline     the dominator tree near the top: each result with the part of
              the proof that exists only to serve it ("owns")
  literature  named published results the proof states as Props and proves,
              with the theorem that proves each and how often it is used
  steps       the 20 steps of the announcement, with the code whose names
              match each step's technical terms (name matching, unverified)
  summaries   plain-English summaries of the main results, written by Claude
              from the Lean statements; marked as such on the site
"""
import collections, json, re, sys
import numpy as np

SUMMARIES = {
    "allChi": "The whole proof in one statement: for every Dirichlet character χ, L(χ, s) ≠ 0 whenever Re(s) > ½ (leaving out the pole of ζ at s = 1). RH and GRH follow from this.",
    "rhOfAll": "Mathlib's Riemann Hypothesis, obtained from the statement for every character by taking the trivial character.",
    "Formalism.VW.rh_of_every": "Turns 'no zeros right of ½ for every character' into Mathlib's RiemannHypothesis.",
    "Formalism.VW.critLine": "Turns the same statement into 'zeros of a primitive L-function in the critical strip lie on Re(s) = ½', using the functional equation.",
    "UpperTheory.EveryCharacter": "The central claim: L(χ, s) ≠ 0 for every Dirichlet character χ and every s with Re(s) > ½ (except ζ at s = 1).",
    "UpperTheory.FinalTheorems.everyCharacter": "Proves the central claim by feeding the Galois-representation statement (Row0b) into the main argument.",
    "UpperTheory.FinalTheorems.everyCharacter_of_row": "Reduces the central claim to Row0b: attaching ℓ-adic Galois representations with prescribed properties to regular algebraic polarized cuspidal representations over CM fields.",
    "UpperTheory.LiteratureTheorems.every_character_of_literature_of_vWin": "Derives the central claim from a bundle of literature statements (local Langlands existence, Galois representations of polarized pairs) together with VWin, a bound for every character.",
    "UpperTheory.Lit.every_character_of_theta_integrals_local_matching": "The analytic core, by size: the central claim follows from hypotheses on unitary groups at a third place, local theta inputs, agreement of theta integrals, local matching, a covolume bound, local Langlands existence and VWin.",
    "UpperTheory.Lit.nonempty_hyps_definite_side_of_closed_bound": "Shows that the family of objects needed on the definite side can actually be built from those inputs. About a third of the whole proof sits under this one result.",
    "GlobalTheory.Fc.S0.StageU.hypotheses_nonempty_of_unramified_exponents_alt": "Builds the required objects from unramified exponents for unitary groups.",
    "GlobalTheory.Fc.S0.ontoX_and_lamLow_of_unitaryGroupHypotheses'": "From the unitary-group hypotheses, proves a surjectivity statement and a lower bound for a quantity Λ.",
    "GlobalTheory.T.open0_of_unitary_group_hypotheses": "Proves an open-orbit statement for the parameters from the unitary-group hypotheses.",
    "UpperTheory.Top.every_character_of_green_v_win": "Closes the argument from a 'Green' condition, VWin and the non-emptiness of the definite-side hypotheses.",
    "SelfIntersectionVolumeEstimates.topCovolSlim2_use_alt_alt": "A covolume bound from arithmetic geometry: resolution and principalisation in characteristic 0, Moriwaki bigness, Fargues, Zarhin and nef Riemann–Roch statements.",
    "PositivityTheory.HtPt.Ah.deep_slim_use": "Packages the Arakelov-geometry inputs into the statement used for the volume bound.",
    "GlobalTheory.CompanionTheory.Ar.Link.good_tower_volume_theorem_bis": "Existence of a good tower together with a volume theorem, from arithmetic intersection theory.",
    "SelfIntersectionVolumeEstimates.topCovolG_alt_alt": "The covolume bound used in the core, from volume estimates, Hodge bundle theorems and Grothendieck deformation theory.",
    "UpperTheory.One.vwin_of_row": "Proves VWin, the bound for every character, from the Galois-representation statement Row0b.",
    "UpperTheory.One.Join.automorphic_window_of_inputs": "VWin from an open-image condition, isobaric base change and a Galois input.",
    "UpperTheory.V.v_window_of_literal_automorphy_n": "VWin from an automorphy statement in rank n.",
    "UpperTheory.Gal.Int.galoisLocalGlobalStrong_recParameter": "Proves Row0b: Galois representations with the required local–global compatibility, with local parameters given by local Langlands.",
    "UpperTheory.Gal.Int.galoisRepresentations_of_thetaLift": "Constructs those Galois representations by way of theta lifts.",
    "UpperTheory.Gal.Int.Geo.geoOne_holds": "Geometric realization in weight one, a step in building the Galois representations.",
    "UpperTheory.Gal.Int.Geo.geometric_realization_of_weight_one": "Geometric realization in weight one, from a holomorphic Lefschetz formula.",
    "UpperTheory.Gal.Int.Geo.kodaira_spencer_of_weight_one": "A Kodaira–Spencer statement in weight one.",
}

STEPS = [
    (1, "6 Oct", "A Stepanov-type determinant.", ["Stepanov", "Determinant"]),
    (2, "9 Oct", "Vanishing of D^p on a CM curve when p is inert, and a divisibility bound with an O(log a) error.", ["Inert", "CMCurve"]),
    (3, "19 Oct", "Rewriting q^N = M^k + R with a quadric form, aiming at automorphy through a theta-series period on a sixfold cover of GL5.", ["GL5", "Sixfold", "Quadric"]),
    (4, "6 Oct", "W(1_S) ≥ 0 via a determinant, read as Stepanov's method at multiplicity one; a bootstrap.", ["Bootstrap"]),
    (5, "20 Oct", "A weighted von Mangoldt sum, a Guinand–Weil sign and a variance trick; Bertini gives a sign, iterated Parseval gives square-root cancellation.", ["Mangoldt", "Guinand", "Bertini", "Parseval", "Variance"]),
    (6, "8 Oct", "W applied to combinations of indicator functions, for a lower bound above 1 − η.", ["Indicator"]),
    (7, "14 Oct", "Determinants of W-functions containing GGP periods, taking values 0 or 1 (interlacing).", ["GGP", "Interlac"]),
    (8, "15 Nov", "Iterated theta lifts between totally definite unitary groups, each adding a Hecke twist; about √X lifts give multiplicity m.", ["ThetaLift", "IteratedTheta", "IteratedLift"]),
    (9, "15 Nov", "Norm and level estimates for the lifts using Chowla–Selberg, Weyl and the Siegel mass formula.", ["ChowlaSelberg", "Chowla", "SiegelMass", "MassFormula", "Weyl"]),
    (10, "15 Nov", "A lower bound on the divisibility of the m-fold iterated lift.", ["Divisib"]),
    (11, "6 Oct", "An Iwasawa tower, by analogy with pigeonhole over F_{q^n}/F_q.", ["Iwasawa"]),
    (12, "15 Nov", "Seesaw: the period of the iterated lift is a Bessel period independent of the Hecke characters (Rallis).", ["Seesaw", "Bessel", "Rallis"]),
    (13, "6 Oct", "The Bost slope inequality.", ["Bost", "Slope"]),
    (14, "15 Nov", "The cost of each lift; a priori stopping point 2/3, needing a main term and a division step.", ["Cost"]),
    (15, "15 Nov", "Gluing an integral structure across Hecke characters, a gcd-like average.", ["IntegralStructure", "Glue", "Gluing"]),
    (16, "14 Oct", "A relative trace formula; Cauchy–Schwarz reduces to a norm bound on a projected Poincaré series.", ["RelativeTrace", "Poincare"]),
    (17, "15 Nov", "Galois cohomology classes in H¹ that twisting cannot kill: a weak form of Vandiver's conjecture.", ["Vandiver", "GaloisCohomology"]),
    (18, "15 Nov", "Covolumes, the index of theta series, and congruences between lifts and forms.", ["Covol", "Congruence"]),
    (19, "19 Oct", "The choice of Iwasawa tower, with a Behrend-type trick.", ["Behrend"]),
    (20, "16 Nov", "GRH.", []),
]


def title(name):
    last = name.split(".")[-1]
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", last).replace("G L", "GL")


def main(data):
    names, kinds, mods, sigs = [], [], [], []
    with open(f"{data}/decls.tsv", encoding="utf-8") as f:
        next(f)
        for row in f:
            p = row.rstrip("\n").split("\t", 5)
            names.append(p[1]); kinds.append(p[2]); mods.append(p[3]); sigs.append(p[5] if len(p) > 5 else "")
    N = len(names)
    e = np.fromfile(f"{data}/edges.bin", dtype=np.uint32).reshape(-1, 2)
    used_by = np.bincount(e[:, 1], minlength=N)
    d = np.load(f"{data}/dom.npz"); idom, owned, S = d["idom"], d["owned"], int(d["S"])
    reach = owned > 0
    idx = {n: i for i, n in enumerate(names)}

    # outline: dominator tree, big branches only
    kids = collections.defaultdict(list)
    for v in np.nonzero(reach)[0]:
        kids[int(idom[v])].append(int(v))
    outline = []

    def walk(v, depth):
        for c in sorted(kids.get(v, []), key=lambda c: -owned[c]):
            if owned[c] >= 10000 and depth < 9:
                outline.append({"name": names[c], "parent": names[v] if v != S else None, "owns": int(owned[c]), "depth": depth})
                walk(c, depth + 1)
    walk(S, 0)

    # literature: Props named as published results, and the theorems proving them
    pub = [i for i, n in enumerate(names) if reach[i] and kinds[i] in ("def", "abbrev", "structure")
           and re.search(r"(^|\.)(Published|Pub)\.", n)]
    by_last = collections.defaultdict(list)
    for i in pub:
        by_last[names[i].split(".")[-1]].append(i)
    provers = collections.defaultdict(list)
    for i, s in enumerate(sigs):
        if not reach[i] or kinds[i] not in ("theorem", "lemma"):
            continue
        m = re.search(r":\s*(?:_root_\.)?([\w.₀-₉']+)\s*$", s)
        if not m:
            continue
        t = m.group(1)
        for p in by_last.get(t.split(".")[-1], []):
            if names[p] == t or names[p].endswith("." + t):
                provers[p].append(i)
    pub.sort(key=lambda i: -used_by[i])
    # transitive proof size: how many project declarations a proof rests on
    src = e[:, 0].astype(np.int64); dst = e[:, 1].astype(np.int64)
    o = np.argsort(src, kind="stable"); succ = dst[o]
    ptr = np.concatenate([[0], np.cumsum(np.bincount(src, minlength=N))])

    def closure(v):
        seen = np.zeros(N, bool); seen[v] = True; front = np.array([v])
        while len(front):
            starts, ends = ptr[front], ptr[front + 1]
            nxt = np.concatenate([succ[a:b] for a, b in zip(starts, ends)]) if len(front) else front
            nxt = np.unique(nxt); nxt = nxt[~seen[nxt]]
            seen[nxt] = True; front = nxt
        return int(seen.sum()) - 1
    literature = []
    for i in pub[:220]:
        pv = sorted(provers.get(i, []), key=lambda j: -owned[j])[:2]
        literature.append({"name": names[i], "title": title(names[i]), "usedBy": int(used_by[i]),
                           "provers": [names[j] for j in pv], "proofSize": closure(pv[0]) if pv else 0})

    # steps: name matching on reachable declarations and their module paths
    steps = []
    for num, date, text, kws in STEPS:
        entry = {"n": num, "date": date, "text": text, "areas": [], "top": [], "count": 0}
        if num == 20:
            entry["top"] = ["allChi"]
        elif kws:
            rx = re.compile("|".join(kws), re.I)
            areas, hits = collections.Counter(), []
            for i in np.nonzero(reach)[0]:
                m, short = mods[i], names[i].split("::")[-1]
                if rx.search(m) or rx.search(short):
                    hits.append(i)
                    parts = m.split(".")
                    for k, pt in enumerate(parts):
                        if rx.search(pt):
                            areas[".".join(parts[:k + 1])] += 1; break
            hits.sort(key=lambda i: -owned[i])
            entry.update(count=len(hits), areas=[[a, c] for a, c in areas.most_common(3)],
                         top=[names[i] for i in hits[:3]])
        steps.append(entry)

    out = {"outline": outline, "literature": literature, "steps": steps,
           "summaries": {k: v for k, v in SUMMARIES.items() if k in idx},
           "litTotal": len(pub)}
    with open(f"{data}/insights.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"outline {len(outline)}, literature {len(literature)} of {len(pub)}, steps {len(steps)}, summaries {len(out['summaries'])}")


if __name__ == "__main__":
    main(sys.argv[1])
