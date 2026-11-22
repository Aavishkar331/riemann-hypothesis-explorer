/-
Exact dependency extractor that reads compiled `.olean` files one by one.

It never loads the whole proof: each `.olean` is read on its own with
`readModuleData`, so files can be streamed from an archive and deleted
after use. For every constant in a file it lists every constant used in its
type and value (the proof term). Proof terms contain what Lean filled in by
itself (instances, `simp` lemmas, automation), so these are exact edges.

usage: lean --run ExtractOleans.lean LIST.tsv OUT.tsv
  LIST.tsv: one line per file, `Module.Name <TAB> path/to/file.olean`
  OUT.tsv:  one line per user-facing declaration,
            `module <TAB> name <TAB> dep <TAB> dep ...`
Deps are not filtered here; constants from Mathlib or Lean core are dropped
later by `exact_edges.py`, which knows the project's declarations.
Private names are written `Module::Name`; auto-generated helpers
(`foo.proof_1`, `foo.match_1`, `foo._simp_1`, equation lemmas) fold into `foo`.
-/
import Lean
open Lean

def isInternal (s : String) : Bool :=
  s.startsWith "_" || s.startsWith "proof_" || s.startsWith "match_" ||
  s.startsWith "eq_" || s == "eq_def" || s == "eq_unfold"

/-- Module of a private name `_private.A.B.0.x`, read from the name itself. -/
def privateModule? (n : Name) : Option Name :=
  match n.components with
  | c :: rest =>
    if c == `_private then
      some ((rest.takeWhile fun c => !c.isNum).foldl (· ++ ·) .anonymous)
    else none
  | [] => none

def userKey (n : Name) : String := Id.run do
  let base := (privateToUserName? n).getD n
  let mut kept : Name := .anonymous
  for c in base.components do
    if isInternal (c.toString (escape := false)) then break
    kept := kept ++ c
  if kept.isAnonymous then return ""
  let s := kept.toString (escape := false)
  match privateModule? n with
  | some m => return s!"{m.toString (escape := false)}::{s}"
  | none => return s

def main (args : List String) : IO UInt32 := do
  let listPath := args.getD 0 "list.tsv"
  let out ← IO.FS.Handle.mk (args.getD 1 "deps.tsv") .write
  let mut nFiles := 0
  for line in (← IO.FS.lines listPath) do
    let parts := line.splitOn "\t"
    if parts.length < 2 then continue
    let modName := parts[0]!
    let (md, _) ← readModuleData parts[1]!
    let mut acc : Std.HashMap String (Std.HashSet String) := {}
    for ci in md.constants do
      let src := userKey ci.name
      if src.isEmpty then continue
      let used := ci.type.getUsedConstants ++
        ((ci.value? (allowOpaque := true)).map (·.getUsedConstants)).getD #[]
      let deps := used.foldl (init := acc.getD src {}) fun s d =>
        let k := userKey d
        if k.isEmpty || k == src then s else s.insert k
      acc := acc.insert src deps
    for (src, deps) in acc do
      out.putStrLn (String.intercalate "\t" (modName :: src :: deps.toList))
    nFiles := nFiles + 1
  out.flush
  IO.eprintln s!"{nFiles} files done"
  return 0
