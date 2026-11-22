/-
Exact dependency extractor.

Loads the compiled environment of a Lean project and, for every constant
defined in the project, lists the project constants that appear in its type
or its value (the proof term). Proof terms contain everything Lean filled in
on its own: type class instances, `simp` lemmas, automation output, so this
is the real dependency graph, not a guess from names.

Run from inside the built project:
  lake env lean --run ExtractDeps.lean OUT.tsv ROOT_MODULE LIB1,LIB2,...

Output, one line per user-facing declaration:
  module <TAB> name <TAB> dep <TAB> dep ...
Private names are written as `Module::Name` and auto-generated auxiliaries
(`foo.proof_1`, `foo.match_1`, `foo._simp_1`, ...) are folded into `foo`.
-/
import Lean
open Lean

/-- Auto-generated name components: everything from one of these on is dropped. -/
def isInternal (s : String) : Bool :=
  s.startsWith "_" || s.startsWith "proof_" || s.startsWith "match_" ||
  s.startsWith "eq_" || s == "eq_def" || s == "eq_unfold"

/-- The key the Python indexer uses for a constant, or "" for pure internals. -/
def userKey (env : Environment) (n : Name) : String := Id.run do
  let (base, priv) := match privateToUserName? n with
    | some u => (u, true)
    | none => (n, false)
  let mut kept : Name := .anonymous
  for c in base.components do
    let s := c.toString (escape := false)
    if isInternal s then break
    kept := kept ++ c
  if kept.isAnonymous then return ""
  let s := kept.toString (escape := false)
  -- equation lemmas etc. of a public declaration can be generated as private
  -- constants in another module: fold those into the public name
  if priv && !env.contains kept then
    if let some i := env.getModuleIdxFor? n then
      return s!"{env.header.moduleNames[i.toNat]!}::{s}"
  return s

def main (args : List String) : IO UInt32 := do
  let out := args.getD 0 "deps.tsv"
  let root := (args.getD 1 "Main").toName
  let libs := (args.getD 2 "Main").splitOn ","
  initSearchPath (← findSysroot)
  IO.eprintln s!"importing {root} ..."
  let env ← importModules #[{ module := root }] {} (trustLevel := 1024)
  let mods := env.header.moduleNames
  let isProj : Array Bool := mods.map fun m => libs.contains (m.getRoot.toString (escape := false))
  IO.eprintln s!"{mods.size} modules, {isProj.filter id |>.size} in the project"
  let h ← IO.FS.Handle.mk out .write
  let mut nDecl := 0
  let mut nEdge := 0
  for i in [0:mods.size] do
    if !isProj[i]! then continue
    -- aggregate per module: auxiliaries live in the same module as their parent
    let mut acc : Std.HashMap String (Std.HashSet String) := {}
    for c in env.header.moduleData[i]!.constNames do
      let some ci := env.find? c | continue
      let src := userKey env c
      if src.isEmpty then continue
      let used := ci.type.getUsedConstants ++ ((ci.value? (allowOpaque := true)).map (·.getUsedConstants)).getD #[]
      let deps := used.foldl (init := acc.getD src {}) fun s d =>
        match env.getModuleIdxFor? d with
        | some j =>
          if isProj[j.toNat]! then
            let k := userKey env d
            if k.isEmpty || k == src then s else s.insert k
          else s
        | none => s
      acc := acc.insert src deps
    let m := mods[i]!.toString (escape := false)
    for (src, deps) in acc do
      h.putStrLn (String.intercalate "\t" (m :: src :: deps.toList))
      nDecl := nDecl + 1
      nEdge := nEdge + deps.size
    if i % 5000 == 0 then
      IO.eprintln s!"  module {i}/{mods.size}: {nDecl} declarations, {nEdge} edges"
  h.flush
  IO.eprintln s!"done: {nDecl} declarations, {nEdge} edges -> {out}"
  return 0
