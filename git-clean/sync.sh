#!/usr/bin/env bash
# git-clean sync — wyrównuje lokalne gałęzie z gałęzią bazową (origin/<default>).
#
#   * gałąź domyślna (np. master): tylko fast-forward do origin/<default>,
#   * pozostałe gałęzie: merge origin/<default> do gałęzi — WYŁĄCZNIE gdy
#     `git merge-tree --write-tree` potwierdza brak konfliktów,
#   * konflikt / brudny worktree / operacja w toku / gałąź chroniona /
#     gałąź już wmergowana => NIC się nie dzieje, gałąź trafia do raportu.
#
# Nie robi push, nie robi fetcha (fetch zrobił audit.sh), nie używa --force/reset.
# Gałąź niewystawiona w żadnym worktree jest aktualizowana bez dotykania drzewa
# roboczego (commit-tree + update-ref z sprawdzeniem starej wartości) — UWAGA:
# commit-tree nie uruchamia hooków (commit-msg, pre-commit) i nie podpisuje
# commita; skrypt wypisuje to w sekcji UWAGI, jeśli repo ma hooki / gpgsign.
#
# Gałąź wystawiona w worktree:
#   * w BIEŻĄCYM worktree (tam, skąd uruchomiono skrypt) — `git merge` w nim,
#     tylko gdy czyste i bez operacji w toku,
#   * w INNYM worktree — domyślnie SKIP_WORKTREE (ktoś może tam właśnie pracować,
#     np. równoległa sesja agenta); aktualizowana tylko z --sync-worktrees.
#
# Kopia wyjścia ląduje w <git-common-dir>/git-clean/sync-dryrun.txt albo
# sync-apply.txt — z niej report.py buduje raport HTML.
#
# Użycie: sync.sh [--dry-run] [--msg-suffix TEKST] [--trailer TEKST]
#                 [--protected REGEX] [--sync-worktrees]
#   --msg-suffix      doklejany do tematu commita merge (np. " @disable-code-review")
#   --trailer         osobny akapit na końcu commita (np. "Co-Authored-By: ...")
#   --sync-worktrees  aktualizuj też gałęzie wystawione w innych worktree

set -u
export LC_ALL=C
export GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=never

# Kopia wyjścia dla report.py: uruchom się ponownie z tee do .git/git-clean/.
if [ -z "${GIT_CLEAN_TEED:-}" ] && git rev-parse --git-dir >/dev/null 2>&1; then
  OUTDIR="$(cd "$(git rev-parse --git-common-dir)" && pwd -P)/git-clean"
  mkdir -p "$OUTDIR"
  case " $* " in *" --dry-run "*) OUTF=sync-dryrun.txt ;; *) OUTF=sync-apply.txt ;; esac
  GIT_CLEAN_TEED=1 bash "$0" "$@" 2>&1 | tee "$OUTDIR/$OUTF"
  exit "${PIPESTATUS[0]}"
fi

DRY=0; SUFFIX=""; TRAILER=""; SYNC_WT=0
PROTECTED='^(main|master|develop|trunk|release/.*|hotfix/.*)$'
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --sync-worktrees) SYNC_WT=1 ;;
    --msg-suffix) SUFFIX="$2"; shift ;;
    --trailer) TRAILER="$2"; shift ;;
    --protected) PROTECTED="$2"; shift ;;
    *) echo "nieznany argument: $1" >&2 ;;
  esac
  shift
done

git rev-parse --git-dir >/dev/null 2>&1 || { echo "BŁĄD: to nie jest repozytorium git: $(pwd)"; exit 2; }
git merge-tree -h 2>&1 | grep -q -- '--write-tree' || { echo "BŁĄD: git < 2.38 (brak merge-tree --write-tree) — sync niemożliwy"; exit 2; }

section() { printf '\n===== %s =====\n' "$1"; }

# ---------- remote + baza ----------
REMOTES=$(git remote)
[ -z "$REMOTES" ] && { echo "brak remote'ów — nie ma z czym synchronizować"; exit 0; }
if echo "$REMOTES" | grep -qx origin; then R=origin; else R=$(echo "$REMOTES" | head -1); fi

DEF=$(git symbolic-ref --quiet --short "refs/remotes/$R/HEAD" 2>/dev/null | sed "s#^$R/##")
if [ -z "$DEF" ]; then
  for c in main master develop trunk; do
    git show-ref --verify --quiet "refs/remotes/$R/$c" && { DEF=$c; break; }
  done
fi
[ -z "$DEF" ] && { echo "nie udało się ustalić gałęzi domyślnej"; exit 2; }
BASE="$R/$DEF"
git show-ref --verify --quiet "refs/remotes/$BASE" || { echo "brak refs/remotes/$BASE"; exit 2; }
BASE_SHA=$(git rev-parse "$BASE")
TOP=$(git rev-parse --show-toplevel)

# ---------- pomocnicze ----------
norm_path() { printf '%s' "${1%/}" | tr '[:upper:]\\' '[:lower:]/'; }
is_foreign_wt() { # $1 worktree path -> 0, gdy to INNY worktree i nie ma --sync-worktrees
  [ -n "$1" ] && [ "$SYNC_WT" = 0 ] && [ "$(norm_path "$1")" != "$(norm_path "$TOP")" ]
}
squash_merged() { # $1 ref, $2 base
  local mb tmp
  mb=$(git merge-base "$2" "$1" 2>/dev/null) || return 1
  tmp=$(git commit-tree "$1^{tree}" -p "$mb" -m tmp 2>/dev/null) || return 1
  case "$(git cherry "$2" "$tmp" 2>/dev/null)" in -*) return 0 ;; esac
  return 1
}
already_in_base() { # $1 ref
  git merge-base --is-ancestor "$1" "$BASE" 2>/dev/null && return 0
  [ -z "$(git cherry "$BASE" "$1" 2>/dev/null | grep '^+')" ] && return 0
  squash_merged "$1" "$BASE" && return 0
  return 1
}
wt_blocker() { # $1 worktree path -> wypisuje powód blokady albo nic
  local wt="$1" op
  if [ -n "$(git -C "$wt" status --porcelain --untracked-files=no 2>/dev/null)" ]; then
    echo "brudny worktree"; return
  fi
  for op in rebase-merge rebase-apply MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD; do
    if ( cd "$wt" && [ -e "$(git rev-parse --git-path "$op")" ] ); then echo "operacja w toku ($op)"; return; fi
  done
}
msg_for() { # $1 branch
  local m="Merge remote-tracking branch '$BASE' into $1${SUFFIX}"
  [ -n "$TRAILER" ] && m="$m"$'\n\n'"$TRAILER"
  printf '%s' "$m"
}
push_cmd() { # $1 branch -> komenda push albo adnotacja (gałąź po aktualizacji)
  local b="$1" rem merge rname up a bh
  rem=$(git config "branch.$b.remote" 2>/dev/null)
  merge=$(git config "branch.$b.merge" 2>/dev/null)
  if [ -z "$rem" ] || [ -z "$merge" ]; then
    echo "git push -u $R $b"; return
  fi
  rname=${merge#refs/heads/}
  if ! git show-ref --verify --quiet "refs/remotes/$rem/$rname"; then
    echo "# $b: upstream $rem/$rname zniknął z serwera — decyzja ownera, czy wypchnąć ponownie: git push -u $rem $b:$rname"; return
  fi
  set -- $(git rev-list --left-right --count "refs/heads/$b...refs/remotes/$rem/$rname")
  a=$1; bh=$2
  if [ "$bh" -gt 0 ]; then
    echo "# $b: ROZJAZD z $rem/$rname (ahead $a, behind $bh) — najpierw uzgodnij z upstreamem (pull), push zablokowany"; return
  fi
  [ "$a" -eq 0 ] && return
  if [ "$rname" = "$b" ]; then echo "git push $rem $b"; else echo "git push $rem $b:$rname"; fi
}

# ---------- przebieg ----------
ROWS=(); CONFL=(); PUSHES=(); UPDATED=()
section "SYNC (baza: $BASE @ ${BASE_SHA:0:9}) tryb: $([ $DRY = 1 ] && echo dry-run || echo apply)"
echo "# branch|status|behind|ahead|old_sha|new_sha|detail"

while IFS='|' read -r b wt; do
  old=$(git rev-parse "refs/heads/$b")
  set -- $(git rev-list --left-right --count "refs/heads/$b...$BASE"); ahead=$1; behind=$2
  status=""; new="-"; detail=""
  foreign=0; is_foreign_wt "$wt" && foreign=1

  if [ "$b" = "$DEF" ]; then
    if [ "$behind" -eq 0 ]; then status=UP_TO_DATE
    elif [ "$ahead" -gt 0 ]; then status=SKIP_DIVERGED; detail="lokalny $DEF ma $ahead własnych commitów i jest $behind za $BASE — nie ruszam (do ręcznej decyzji)"
    elif [ $foreign = 1 ]; then
      status=SKIP_WORKTREE; detail="fast-forward o $behind commit(ów) możliwy, ale gałąź jest wystawiona w innym worktree ($wt) — pominięta (--sync-worktrees)"
    else
      blk=""; [ -n "$wt" ] && blk=$(wt_blocker "$wt")
      if [ -n "$blk" ]; then status=SKIP_BLOCKED; detail="$blk ($wt)"
      elif [ $DRY = 1 ]; then status=WOULD_FF; detail="fast-forward o $behind commit(ów)"
      else
        if [ -n "$wt" ]; then git -C "$wt" merge --ff-only --quiet "$BASE" >/dev/null 2>&1; rc=$?
        else git update-ref -m "git-clean: ff $b to $BASE" "refs/heads/$b" "$BASE_SHA" "$old"; rc=$?; fi
        if [ $rc -eq 0 ]; then status=FF; new=$(git rev-parse "refs/heads/$b"); UPDATED+=("$b"); detail="fast-forward o $behind commit(ów)"
        else status=ERROR; detail="ff nieudany (rc=$rc)"; fi
      fi
    fi
  elif echo "$b" | grep -Eq "$PROTECTED"; then
    status=SKIP_PROTECTED; detail="gałąź chroniona — bez automatycznych zmian"
  elif [ "$behind" -eq 0 ]; then
    status=UP_TO_DATE
  elif already_in_base "refs/heads/$b"; then
    status=SKIP_ALREADY_IN_BASE; detail="zawartość już jest w $BASE — kandydat do usunięcia, nie do aktualizacji"
  else
    # Cudzy worktree: nie sprawdzamy jego stanu (nie dotkniemy go), ale merge-tree
    # nadal mówi ownerowi, czy czeka go konflikt.
    blk=""; [ -n "$wt" ] && [ $foreign = 0 ] && blk=$(wt_blocker "$wt")
    if [ -n "$blk" ]; then
      status=SKIP_BLOCKED; detail="$blk ($wt)"
    else
      out=$(git merge-tree --write-tree --name-only --no-messages "refs/heads/$b" "$BASE" 2>/dev/null); rc=$?
      if [ $rc -eq 0 ]; then
        tree=$(echo "$out" | head -1)
        if [ $foreign = 1 ]; then status=SKIP_WORKTREE; detail="czysty merge możliwy, ale gałąź jest wystawiona w innym worktree ($wt) — pominięta (--sync-worktrees)"
        elif [ $DRY = 1 ]; then status=WOULD_MERGE; detail="czysty merge, brak konfliktów"
        else
          if [ -n "$wt" ]; then
            git -C "$wt" merge --no-edit -m "$(msg_for "$b")" "$BASE" >/dev/null 2>&1; mrc=$?
            [ $mrc -ne 0 ] && git -C "$wt" merge --abort >/dev/null 2>&1
          else
            nc=$(git commit-tree "$tree" -p "$old" -p "$BASE_SHA" -m "$(msg_for "$b")" 2>/dev/null) && \
              git update-ref -m "git-clean: merge $BASE into $b" "refs/heads/$b" "$nc" "$old"
            mrc=$?
          fi
          if [ $mrc -eq 0 ]; then status=MERGED; new=$(git rev-parse "refs/heads/$b"); UPDATED+=("$b"); detail="merge $BASE (+$behind commit(ów) z bazy), bez konfliktów"
          else status=ERROR; detail="merge nieudany mimo czystego merge-tree (rc=$mrc) — gałąź nietknięta"; fi
        fi
      elif [ $rc -eq 1 ]; then
        status=CONFLICT
        files=$(echo "$out" | tail -n +2 | grep . | sort -u)
        nfiles=$(echo "$files" | grep -c .)
        detail="$nfiles plik(ów) w konflikcie z $BASE"
        owners=$(git log --format='%an <%ae>' "$BASE..refs/heads/$b" 2>/dev/null | sort | uniq -c | sort -rn | head -3 | sed -E 's/^ *([0-9]+) /\1 commit(ów): /' | paste -sd ';' -)
        [ -z "$owners" ] && owners="(brak własnych commitów)"
        CONFL+=("$b|$behind|$ahead|$owners|$(echo "$files" | head -15 | paste -sd ',' -)|$nfiles")
      else
        status=ERROR; detail="merge-tree zwrócił rc=$rc"
      fi
    fi
  fi
  ROWS+=("$b|$status|$behind|$ahead|${old:0:9}|${new:0:9}|$detail")
done < <(git for-each-ref refs/heads --format='%(refname:short)|%(worktreepath)')

printf '%s\n' "${ROWS[@]}"

# ---------- konflikty: informacja dla ownerów ----------
if [ ${#CONFL[@]} -gt 0 ]; then
  section "KONFLIKTY — INFO DLA OWNERA (żaden merge nie został wykonany)"
  for c in "${CONFL[@]}"; do
    IFS='|' read -r b behind ahead owners files nfiles <<<"$c"
    echo "gałąź: $b   (ahead $ahead / behind $behind względem $BASE)"
    echo "  owner (autorzy commitów na gałęzi): $owners"
    echo "  pliki w konflikcie ($nfiles): $files"
    echo "  do ręcznego rozwiązania przez ownera: git switch $b; git merge $BASE"
  done
fi

# ---------- uwagi: czego commit-tree nie robi ----------
# Dotyczy tylko gałęzi niewystawionych (merge przez commit-tree + update-ref).
hp=$(git config core.hooksPath 2>/dev/null)
if [ -n "$hp" ]; then case "$hp" in /*|?:*) ;; *) hp="$TOP/$hp" ;; esac
else hp=$(git rev-parse --git-path hooks); fi
hooks=""
for h in pre-commit prepare-commit-msg commit-msg pre-merge-commit post-commit; do
  [ -f "$hp/$h" ] && hooks="$hooks${hooks:+, }$h"
done
gpg=$(git config --bool commit.gpgsign 2>/dev/null)
if [ -n "$hooks" ] || [ "$gpg" = true ]; then
  section "UWAGI"
  [ -n "$hooks" ] && echo "hooks_bypassed: $hooks — merge gałęzi niewystawionych idzie przez commit-tree i te hooki się NIE uruchamiają ($hp)"
  [ "$gpg" = true ] && echo "unsigned_merges: commit.gpgsign=true, a merge-commity gałęzi niewystawionych NIE są podpisane"
fi

# ---------- push dla zaktualizowanych ----------
if [ ${#UPDATED[@]} -gt 0 ]; then
  section "PUSH — gałęzie zaktualizowane w tym przebiegu"
  for b in "${UPDATED[@]}"; do
    [ "$b" = "$DEF" ] && continue   # ff do origin/$DEF — nie ma czego wypychać
    p=$(push_cmd "$b"); [ -n "$p" ] && echo "$p"
  done
fi

echo
echo "podsumowanie: aktualne=$(printf '%s\n' "${ROWS[@]}" | grep -c '|UP_TO_DATE|') zaktualizowane=${#UPDATED[@]} konflikty=${#CONFL[@]} pominięte=$(printf '%s\n' "${ROWS[@]}" | grep -c '|SKIP_') błędy=$(printf '%s\n' "${ROWS[@]}" | grep -c '|ERROR|')"
