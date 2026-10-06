#!/usr/bin/env bash
# git-clean audit — ZBIERA FAKTY, niczego nie usuwa.
# Jedyne zapisy: `git fetch` (odświeża refs/remotes, bez --prune) oraz tymczasowe
# obiekty commit-tree do wykrywania squash-merge (wiszące obiekty, sprząta je gc),
# plus kopia własnego wyjścia w <git-common-dir>/git-clean/audit.txt — z niej
# report.py buduje raport HTML (katalog .git nigdy nie trafia do `git status`).
#
# Użycie: audit.sh [--no-fetch] [--stale-days N] [--fetch-timeout S]
#                  [--remote-limit N] [--no-sync]
#   --remote-limit  pełna detekcja squash/rebase tylko dla N najświeższych gałęzi
#                   remote (domyślnie 100); starsze: tylko tani test „merged",
#                   inaczej merge_status=UNCHECKED
#   --no-sync       dotyczy tylko SKILL.md (krok synchronizacji); tu ignorowany

set -u
source "$(dirname "$0")/common.sh"
export LC_ALL=C
export GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=never
export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -o BatchMode=yes -o ConnectTimeout=8}"

# Kopia wyjścia dla report.py: uruchom się ponownie z tee do .git/git-clean/.
if [ -z "${GIT_CLEAN_TEED:-}" ] && git rev-parse --git-dir >/dev/null 2>&1; then
  OUTDIR="$(cd "$(git rev-parse --git-common-dir)" && pwd -P)/git-clean"
  mkdir -p "$OUTDIR" || exit 2
  GIT_CLEAN_TEED=1 bash "$0" "$@" 2>&1 | tee "$OUTDIR/audit.txt"
  codes=("${PIPESTATUS[@]}")
  [ "${codes[0]}" -ne 0 ] && exit "${codes[0]}"
  exit "${codes[1]}"
fi

FETCH=1; STALE_DAYS=90; FETCH_TIMEOUT=40; REMOTE_LIMIT=100; GRAPH_LIMIT=120
while [ $# -gt 0 ]; do
  case "$1" in
    --no-fetch) FETCH=0 ;;
    --stale-days) STALE_DAYS="${2:-}"; shift ;;
    --fetch-timeout) FETCH_TIMEOUT="${2:-}"; shift ;;
    --remote-limit) REMOTE_LIMIT="${2:-}"; shift ;;
    --graph-limit) GRAPH_LIMIT="${2:-}"; shift ;;
    --no-sync|--sync-worktrees) ;;
    *) echo "nieznany argument: $1" >&2; exit 2 ;;
  esac
  shift
done

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "BŁĄD: to nie jest repozytorium git: $(pwd)"; exit 2
fi

for value in "$STALE_DAYS" "$FETCH_TIMEOUT" "$REMOTE_LIMIT" "$GRAPH_LIMIT"; do
  positive_integer "$value" || { echo "BŁĄD: oczekiwano dodatniej liczby całkowitej" >&2; exit 2; }
done
[ "$GRAPH_LIMIT" -le 1000 ] || { echo "BŁĄD: --graph-limit maksymalnie 1000" >&2; exit 2; }
STALE_DAYS=$((10#$STALE_DAYS)); FETCH_TIMEOUT=$((10#$FETCH_TIMEOUT))
REMOTE_LIMIT=$((10#$REMOTE_LIMIT)); GRAPH_LIMIT=$((10#$GRAPH_LIMIT))
git rev-parse --show-toplevel >/dev/null 2>&1 && git rev-parse --verify HEAD >/dev/null 2>&1 || {
  echo "BŁĄD: potrzebne jest niepuste repozytorium z drzewem roboczym" >&2; exit 2;
}
NOW=$(date +%s)
STALE_SEC=$((STALE_DAYS * 86400))
age_days() { echo $(( (NOW - $1) / 86400 )); }
run_timeout() {
  if command -v timeout >/dev/null 2>&1; then timeout "$@"
  elif command -v gtimeout >/dev/null 2>&1; then gtimeout "$@"
  else shift; "$@"; fi
}
section() { printf '\n===== %s =====\n' "$1"; }

TOP=$(git rev-parse --show-toplevel)
GITDIR=$(git rev-parse --git-dir)
CUR=$(git symbolic-ref --quiet --short HEAD 2>/dev/null || echo "(detached HEAD @ $(git rev-parse --short HEAD 2>/dev/null))")

section "REPO"
echo "format_version: 2"
echo "root: $(encode_field "$TOP")"
echo "current_branch: $(encode_field "$CUR")"
echo "git: $(git --version)"
echo "generated_at: $NOW"

# ---------- remotes + fetch ----------
section "REMOTES"
REMOTES=$(git remote)
R=""
if [ -z "$REMOTES" ]; then
  echo "brak remote'ów — audyt wyłącznie lokalny"
else
  if echo "$REMOTES" | grep -qx origin; then R=origin; else R=$(echo "$REMOTES" | head -1); fi
  git remote -v | awk '$3=="(fetch)"{print $1" "$2}'
  echo "primary_remote: $R"
fi

ONLINE=0
if [ -n "$R" ] && [ "$FETCH" = 1 ]; then
  if out=$(run_timeout "$FETCH_TIMEOUT" git fetch --all --no-prune --quiet 2>&1); then
    ONLINE=1; echo "fetch: OK (stan remote świeży)"
  else
    echo "fetch: NIEUDANY (brak VPN/sieci/autoryzacji?) — dane remote mogą być NIEAKTUALNE"
    echo "$out" | head -5 | sed 's/^/  fetch_err: /'
  fi
elif [ -n "$R" ]; then
  echo "fetch: pominięty (--no-fetch) — dane remote z ostatniego fetcha"
fi
if [ -n "$R" ]; then
  lf=$(git rev-parse --git-path FETCH_HEAD)
  [ -f "$lf" ] && echo "last_fetch_age_days: $(age_days "$(date -r "$lf" +%s 2>/dev/null || stat -c %Y "$lf" 2>/dev/null || echo "$NOW")")"
fi

# ---------- default branch ----------
section "DEFAULT BRANCH"
DEF=""
if [ -n "$R" ]; then
  DEF=$(git symbolic-ref --quiet --short "refs/remotes/$R/HEAD" 2>/dev/null | sed "s#^$R/##")
  if [ -z "$DEF" ] && [ "$ONLINE" = 1 ]; then
    DEF=$(run_timeout 15 git ls-remote --symref "$R" HEAD 2>/dev/null | awk '/^ref:/{sub("refs/heads/","",$2); print $2; exit}')
  fi
fi
if [ -z "$DEF" ]; then
  for c in main master develop trunk; do
    if git show-ref --verify --quiet "refs/heads/$c" || { [ -n "$R" ] && git show-ref --verify --quiet "refs/remotes/$R/$c"; }; then DEF=$c; break; fi
  done
fi
[ -z "$DEF" ] && DEF=$(git symbolic-ref --quiet --short HEAD 2>/dev/null)
BASE="$DEF"
if [ -n "$R" ] && git show-ref --verify --quiet "refs/remotes/$R/$DEF"; then BASE="$R/$DEF"; fi
echo "default_branch: $(encode_field "$DEF")"
echo "comparison_base: $(encode_field "$BASE")"
for c in main master develop trunk; do
  l=$(git show-ref --verify --quiet "refs/heads/$c" && echo local)
  r=$([ -n "$R" ] && git show-ref --verify --quiet "refs/remotes/$R/$c" && echo remote)
  [ -n "$l$r" ] && echo "trunk_like: $c [$l${l:+${r:+,}}$r]"
done
if git show-ref --verify --quiet "refs/heads/$DEF" && [ "$BASE" != "$DEF" ]; then
  set -- $(git rev-list --left-right --count "$DEF...$BASE" 2>/dev/null)
  echo "local_default_vs_remote: ahead=${1:-?} behind=${2:-?}"
fi

# ---------- working tree ----------
section "WORKING TREE"
st=$(git status --porcelain=v1 2>/dev/null)
echo "staged: $(echo "$st" | grep -c '^[MADRC]')"
echo "modified_unstaged: $(echo "$st" | grep -c '^.[MD]')"
echo "untracked: $(echo "$st" | grep -c '^??')"
echo "conflicted: $(echo "$st" | grep -cE '^(UU|AA|DD|AU|UA|DU|UD)')"
for op in rebase-merge rebase-apply MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD BISECT_LOG; do
  [ -e "$GITDIR/$op" ] && echo "IN_PROGRESS: $op"
done

section "WORKTREES"
git worktree list 2>/dev/null
pr=$(git worktree prune --dry-run -v 2>&1)
[ -n "$pr" ] && echo "$pr" | sed 's/^/prunable: /'

# ---------- squash-merge detection ----------
squash_merged() { # $1 branch-ref, $2 base
  local mb tmp
  mb=$(git merge-base "$2" "$1" 2>/dev/null) || return 1
  tmp=$(git -c commit.gpgsign=false commit-tree "$1^{tree}" -p "$mb" -m tmp 2>/dev/null) || return 1
  case "$(git cherry "$2" "$tmp" 2>/dev/null)" in -*) return 0 ;; esac
  return 1
}
# Główna linia bazy (first-parent): czubek gałęzi leżący NA niej to „contained" —
# gałąź nie ma własnych commitów (świeżo założona) albo weszła fast-forwardem.
# Nie da się tych dwóch przypadków odróżnić, więc raport nie kasuje ich hurtem.
FPFILE=$(mktemp 2>/dev/null || echo "${TMPDIR:-/tmp}/git-clean-fp.$$")
git rev-list --first-parent "$BASE" > "$FPFILE" 2>/dev/null
trap 'rm -f "$FPFILE"' EXIT
merge_status() { # $1 ref, $2 base -> contained|merged|rebased|squashed|NOT_MERGED
  if git merge-base --is-ancestor "$1" "$2" 2>/dev/null; then
    if grep -qx "$(git rev-parse "$1^{commit}")" "$FPFILE"; then echo contained; else echo merged; fi
    return
  fi
  local cherry
  cherry=$(git cherry "$2" "$1" 2>/dev/null) || { echo UNKNOWN; return; }
  if ! printf '%s\n' "$cherry" | grep -q '^+'; then echo rebased; return; fi
  if squash_merged "$1" "$2"; then echo squashed; return; fi
  echo NOT_MERGED
}

# ---------- local branches ----------
section "LOCAL BRANCHES"
echo "# name|upstream|track|vs_upstream(ahead/behind)|vs_base(ahead/behind)|merge_status|local_only_commits|age_days|author|worktree|sha|subject"
git for-each-ref refs/heads --format='%(refname:short)%1f%(upstream:short)%1f%(upstream:track)%1f%(committerdate:unix)%1f%(authorname)%1f%(worktreepath)%1f%(objectname)%1f%(subject)' |
while IFS="$SEP" read -r b up track ct author wt sha subj; do
  vu="-"
  if [ -n "$up" ] && git rev-parse -q --verify "$up" >/dev/null; then
    set -- $(git rev-list --left-right --count "$b...$up"); vu="$1/$2"
  fi
  set -- $(git rev-list --left-right --count "$b...$BASE" 2>/dev/null); vb="${1:-?}/${2:-?}"
  if [ "$b" = "$DEF" ]; then ms="(default)"; else ms=$(merge_status "refs/heads/$b" "$BASE"); fi
  lo=$([ -n "$R" ] && git rev-list --count "refs/heads/$b" --not --remotes 2>/dev/null || echo n/a)
  row "$b" "${up:--}" "${track:--}" "$vu" "$vb" "$ms" "$lo" "$(age_days "$ct")" "$author" "${wt:--}" "$sha" "$subj"
done

# ---------- remote branches ----------
if [ -n "$R" ]; then
  section "REMOTE BRANCHES ($R)"
  echo "remote_limit: $REMOTE_LIMIT"
  echo "# name|vs_base(ahead/behind)|merge_status|age_days|author|has_local|sha|subject"
  # Od najświeższych: pełna detekcja squash/rebase (kosztowna — `git cherry` od
  # merge-base) tylko dla pierwszych REMOTE_LIMIT gałęzi.
  i=0
  git for-each-ref --sort=-committerdate "refs/remotes/$R" --format='%(refname:short)%1f%(committerdate:unix)%1f%(authorname)%1f%(objectname)%1f%(subject)' |
  while IFS="$SEP" read -r rb ct author sha subj; do
    [ "$rb" = "$R" ] || [ "$rb" = "$R/HEAD" ] && continue
    i=$((i + 1))
    short=${rb#"$R"/}
    set -- $(git rev-list --left-right --count "$rb...$BASE" 2>/dev/null); vb="${1:-?}/${2:-?}"
    if [ "$rb" = "$BASE" ]; then ms="(default)"
    elif [ "$i" -le "$REMOTE_LIMIT" ]; then ms=$(merge_status "$rb" "$BASE")
    elif git merge-base --is-ancestor "$rb" "$BASE" 2>/dev/null; then
      if grep -qx "$sha" "$FPFILE"; then ms=contained; else ms=merged; fi
    else ms=UNCHECKED; fi
    hl=$(git show-ref --verify --quiet "refs/heads/$short" && echo yes || echo no)
    row "$short" "$vb" "$ms" "$(age_days "$ct")" "$author" "$hl" "$sha" "$subj"
  done

  section "STALE REMOTE-TRACKING REFS (usunięte na serwerze, wiszą lokalnie)"
  if [ "$ONLINE" = 1 ]; then
    git remote prune --dry-run "$R" 2>&1 | grep 'would prune' || echo "(brak)"
  else
    echo "(nie sprawdzono — offline)"
  fi
fi

# ---------- stash ----------
section "STASH"
n=$(git stash list | wc -l | tr -d ' ')
echo "count: $n"
if [ "$n" -gt 0 ]; then
  echo "# ref|age_days|created_on|files|untracked_part|base_reachable_from|identical_in_HEAD|identical_in_base|still_applies_reverse(=już jest w drzewie)|sha|file_list(do 10)|index_state|message"
  git stash list --format='%gd%x1f%ct%x1f%H%x1f%gs' | while IFS="$SEP" read -r ref ct ssha msg; do
    files=$(git diff --name-only "$ref^1" "$ref" 2>/dev/null)
    nf=$(printf '%s\n' "$files" | grep -c .)
    flist=$(printf '%s\n' "$files" | grep . | head -10 | tr '|' '/' | paste -sd ',' -)
    ut=$(git rev-parse -q --verify "$ref^3" >/dev/null && git ls-tree -r --name-only "$ref^3" | wc -l | tr -d ' ' || echo 0)
    base=$(git rev-parse "$ref^1")
    reach=$(git branch -a --contains "$base" --format='%(refname:short)' 2>/dev/null | head -3 | tr '\n' ',' | sed 's/,$//')
    same_head=0; same_base=0
    while IFS= read -r f; do
      [ -z "$f" ] && continue
      s=$(git rev-parse -q --verify "$ref:$f" 2>/dev/null || echo DELETED)
      h=$(git rev-parse -q --verify "HEAD:$f" 2>/dev/null || echo DELETED)
      d=$(git rev-parse -q --verify "$BASE:$f" 2>/dev/null || echo DELETED)
      [ "$s" = "$h" ] && same_head=$((same_head+1))
      [ "$s" = "$d" ] && same_base=$((same_base+1))
    done <<EOF
$files
EOF
    index_state=unknown
    if git rev-parse --verify "$ref^2" >/dev/null 2>&1; then
      if git diff --quiet "$ref^1" "$ref^2"; then index_state=base
      elif git diff --quiet "$ref^2" "$ref"; then index_state=worktree
      else index_state=distinct; fi
    fi
    rev=$(git diff --binary "$ref^1" "$ref" | git apply --check -R 2>/dev/null && echo yes || echo no)
    row "$ref" "$(age_days "$ct")" "$(echo "$msg" | sed -nE 's/^(WIP on|On) ([^:]*):.*/\2/p')" "$nf" "$ut" "${reach:-NIEOSIĄGALNY}" "$same_head/$nf" "$same_base/$nf" "$rev" "$ssha" "${flist:--}" "$index_state" "$msg"
  done
fi

# ---------- tags ----------
if [ -n "$R" ] && [ "$ONLINE" = 1 ]; then
  section "LOCAL TAGS NOT ON REMOTE"
  remote_tags=$(run_timeout 15 git ls-remote --tags --refs "$R" 2>/dev/null | awk '{sub("refs/tags/","",$2); print $2}' | sort)
  git tag --list | sort | comm -23 - <(printf '%s\n' "$remote_tags") | grep . || echo "(brak)"
fi

# ---------- repo health ----------
section "REPO HEALTH"
git count-objects -vH 2>/dev/null | grep -E 'count|size-pack|garbage'
echo "stale_days_threshold: $STALE_DAYS"


# Bounded commit DAG; separate refs retain branch/tag names without parsing decorations.
section "GRAPH COMMITS"
echo "graph_limit: $GRAPH_LIMIT"
echo "# oid|parents|author|subject"
git log HEAD --branches --remotes --tags --topo-order -n "$((GRAPH_LIMIT + 1))" --format='%H%x1f%P%x1f%an%x1f%s' |
while IFS="$SEP" read -r oid parents author subject; do row "$oid" "$parents" "$author" "$subject"; done
section "GRAPH REFS"
echo "# ref|oid"
git for-each-ref refs/heads refs/remotes refs/tags --format='%(refname)%1f%(objectname)%1f%(*objectname)%1f%(objecttype)' |
while IFS="$SEP" read -r ref oid peeled kind; do
  [ "$kind" = tag ] && oid="$peeled"
  row "$ref" "$oid"
done
row HEAD "$(git rev-parse HEAD)"
