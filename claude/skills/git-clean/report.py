#!/usr/bin/env python3
"""git-clean report — raport HTML + streszczenie tekstowe z wyjścia audit.sh / sync.sh.

Czyta to, co audit.sh i sync.sh zapisały w <git-common-dir>/git-clean/
(audit.txt, sync-dryrun.txt, sync-apply.txt), klasyfikuje gałęzie i stashe
DETERMINISTYCZNIE (te same reguły co tabela w SKILL.md), buduje plan sprzątania
(bloki A–E) i zapisuje:

  <git-common-dir>/git-clean/report.html     — strona do obejrzenia w przeglądarce
  <git-common-dir>/git-clean/history/*.json  — migawki do porównania „przed → po"

Na stdout wypisuje zwięzłe streszczenie z planem — to czyta model, nie HTML.
Niczego w repozytorium nie zmienia; jedyne wywołanie git to `rev-parse`.

Użycie: report.py [--sync auto|dryrun|apply|none] [--protected REGEX] [--open]
  --sync auto   (domyślnie) nowszy z sync-dryrun/sync-apply, o ile nie jest
                starszy od audit.txt o więcej niż 30 min
  --open        otwórz raport w domyślnej przeglądarce
"""

from __future__ import annotations

import argparse
import html
import json
import re
import os
import shlex
from urllib.parse import unquote

import graph
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

PROTECTED_DEFAULT = r"^(main|master|develop|trunk|release/.*|hotfix/.*)$"
HISTORY_KEEP = 20
SYNC_MAX_LAG_S = 1800
MERGED_LIKE = ("merged", "rebased", "squashed")


# ---------------------------------------------------------------- parsowanie
def parse_sections(text: str) -> dict[str, list[str]]:
    secs: dict[str, list[str]] = {}
    cur = None
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        m = re.match(r"^===== (.*) =====$", line)
        if m:
            cur = m.group(1)
            secs[cur] = []
        elif cur is not None and line.strip():
            secs[cur].append(line)
    return secs


def find(secs: dict[str, list[str]], prefix: str) -> tuple[str, list[str]]:
    for k, v in secs.items():
        if k.startswith(prefix):
            return k, v
    return "", []


def kv(lines: list[str]) -> dict[str, str]:
    d: dict[str, str] = {}
    for line in lines:
        m = re.match(r"^([A-Za-z_]+): (.*)$", line)
        if m:
            d.setdefault(m.group(1), m.group(2))
    return d


def rows(lines: list[str], names: list[str], encoded: bool = False) -> list[dict[str, str]]:
    out, started = [], False
    for line in lines:
        if line.startswith("# "):
            started = True
            continue
        if not started or line.startswith("#") or "|" not in line:
            continue
        parts = line.split("|", len(names) - 1)
        parts += [""] * (len(names) - len(parts))
        if encoded:
            parts = [unquote(p) for p in parts]
        out.append(dict(zip(names, parts)))
    return out


def pair(s: str) -> tuple[int | None, int | None]:
    m = re.match(r"^(\d+)/(\d+)$", s or "")
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def to_int(s: str, default: int = 0) -> int:
    try:
        return int(s)
    except (TypeError, ValueError):
        return default


LOCAL_F = ["name", "upstream", "track", "vs_upstream", "vs_base", "ms", "local_only",
           "age", "author", "worktree", "sha", "subject"]
REMOTE_F = ["name", "vs_base", "ms", "age", "author", "has_local", "sha", "subject"]
STASH_F = ["ref", "age", "created_on", "files", "untracked", "reach", "same_head",
           "same_base", "rev_applies", "sha", "file_list", "index_state", "message"]
SYNC_F = ["branch", "status", "behind", "ahead", "old_sha", "new_sha", "detail"]


def parse_audit(text: str) -> dict:
    s = parse_sections(text)
    repo = kv(s.get("REPO", []))
    encoded = repo.get("format_version") == "2"
    if encoded:
        repo = {k: unquote(v) for k, v in repo.items()}
    rem_lines = s.get("REMOTES", [])
    rem = kv(rem_lines)
    fetch = rem.get("fetch", "")
    if any("brak remote" in x for x in rem_lines):
        net = "none"
    elif fetch.startswith("OK"):
        net = "fresh"
    elif fetch.startswith("NIEUDANY"):
        net = "failed"
    else:
        net = "skipped"
    deflines = s.get("DEFAULT BRANCH", [])
    d = kv(deflines)
    if encoded:
        d = {k: unquote(v) for k, v in d.items()}
    trunk = [x.split(": ", 1)[1] for x in deflines if x.startswith("trunk_like: ")]
    wt_lines = s.get("WORKING TREE", [])
    wtree = kv(wt_lines)
    in_progress = [x.split(": ", 1)[1] for x in wt_lines if x.startswith("IN_PROGRESS: ")]
    wts = [x for x in s.get("WORKTREES", []) if not x.startswith("prunable: ")]
    prunable = [x[len("prunable: "):] for x in s.get("WORKTREES", []) if x.startswith("prunable: ")]
    rkey, rlines = find(s, "REMOTE BRANCHES")
    _, stale = find(s, "STALE REMOTE-TRACKING")
    stash_lines = s.get("STASH", [])
    tag_lines = s.get("LOCAL TAGS NOT ON REMOTE")
    health = kv(s.get("REPO HEALTH", []))
    graph_lines = s.get("GRAPH COMMITS", [])
    graph_limit = min(1000, max(1, to_int(kv(graph_lines).get("graph_limit", "120"), 120)))
    commits = rows(graph_lines, ["oid", "parents", "author", "subject"], encoded)
    commits = [c for c in commits if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", c['oid'])
               and all(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", p) for p in c['parents'].split())]
    stash_fields = STASH_F if encoded else [f for f in STASH_F if f != 'index_state']
    stashes = rows(stash_lines, stash_fields, encoded)
    for st in stashes:
        st.setdefault('index_state', 'unknown')
    return {
        "root": repo.get("root", ""),
        "current": repo.get("current_branch", ""),
        "generated_at": to_int(repo.get("generated_at", "0")),
        "remote": rem.get("primary_remote", ""),
        "net": net,
        "fetch_line": fetch,
        "fetch_errors": [x.strip()[len("fetch_err: "):] for x in rem_lines if x.strip().startswith("fetch_err: ")],
        "fetch_age_days": rem.get("last_fetch_age_days"),
        "default": d.get("default_branch", ""),
        "base": d.get("comparison_base", ""),
        "trunk_like": trunk,
        "local_default_vs_remote": d.get("local_default_vs_remote", ""),
        "wt_counts": {k: to_int(wtree.get(k, "0")) for k in ("staged", "modified_unstaged", "untracked", "conflicted")},
        "in_progress": in_progress,
        "worktrees": wts,
        "prunable": prunable,
        "local": rows(s.get("LOCAL BRANCHES", []), LOCAL_F, encoded),
        "remote_rows": rows(rlines, REMOTE_F, encoded),
        "remote_limit": kv(rlines).get("remote_limit", ""),
        "stale_refs": [x.strip() for x in stale if "would prune" in x],
        "stale_checked": not any("nie sprawdzono" in x for x in stale),
        "stash": stashes,
        "graph": commits[:graph_limit],
        "graph_truncated": len(commits) > graph_limit,
        "graph_refs": rows(s.get("GRAPH REFS", []), ["ref", "oid"], encoded),
        "tags_unpushed": None if tag_lines is None else [x for x in tag_lines if x != "(brak)"],
        "health": health,
        "stale_days": to_int(health.get("stale_days_threshold", "90"), 90),
    }


def parse_sync(text: str, mtime: float) -> dict:
    s = parse_sections(text)
    key, lines = find(s, "SYNC")
    if not key:
        first = [x for x in text.splitlines() if x.strip()][:3]
        return {"error": " / ".join(first) or "pusty wynik sync.sh", "mtime": mtime}
    m = re.search(r"baza: (\S+) @ (\w+)\) tryb: (\S+)", key)
    conflicts, cur = [], None
    for line in find(s, "KONFLIKTY")[1]:
        if line.startswith("gałąź: "):
            cur = {"branch": line[len("gałąź: "):].split()[0], "where": line, "owners": "", "files": "", "cmd": ""}
            conflicts.append(cur)
        elif cur and "do ręcznego" in line:
            cur["cmd"] = line.split(": ", 1)[-1]
        elif cur and "pliki w konflikcie" in line:
            cur["nfiles"] = (re.search(r"\((\d+)\)", line) or [None, "?"])[1]
            cur["files"] = line.split("): ", 1)[-1]
        elif cur and "autorzy commitów" in line:
            cur["owners"] = line.split("): ", 1)[-1]
    push = [x for x in find(s, "PUSH")[1] if not x.startswith("podsumowanie:")]
    summary = next((x for x in text.splitlines() if x.startswith("podsumowanie:")), "")
    return {
        "mode": m.group(3) if m else "?",
        "base": m.group(1) if m else "?",
        "base_sha": m.group(2) if m else "",
        "rows": rows(lines, SYNC_F, "format_version: 2" in text.splitlines()),
        "conflicts": conflicts,
        "push": push,
        "notes": {k: v for k, v in kv(find(s, "UWAGI")[1]).items() if k != "podsumowanie"},
        "summary": summary,
        "mtime": mtime,
    }


# ---------------------------------------------------------------- klasyfikacja
CAT_LABEL = {
    "safe": "do usunięcia",
    "gone": "upstream zniknął",
    "abandoned": "porzucona",
    "diverged": "rozjazd",
    "local_only": "tylko lokalnie",
    "decide": "do decyzji",
    "default": "domyślna",
    "protected": "chroniona",
    "current": "bieżąca",
    "worktree": "w worktree",
    "active": "aktywna",
}


def quote_arg(value: str, shell: str = "bash") -> str:
    return "'" + value.replace("'", "''") + "'" if shell == "powershell" else shlex.quote(value)


def git_command(*args: str, shell: str = "bash") -> str:
    return "git " + " ".join(quote_arg(arg, shell) for arg in args)


def translate_command(command: str, shell: str) -> str:
    if command.startswith('#') or shell == 'bash':
        return command
    # sync.sh emits Bash-quoted commands. Convert the argument vector, never eval it.
    return " ".join(quote_arg(arg, shell) for arg in shlex.split(command))


def classify(a: dict, protected: str, shell: str = "bash") -> dict:
    def command(*args):
        return git_command(*args, shell=shell)
    prot = re.compile(protected)
    cur, default = a["current"], a["default"]
    plan = {k: [] for k in "ABCDE"}
    notes_by_branch: dict[str, list[str]] = {}

    for b in a["local"]:
        name = b["name"]
        cats, notes = [], []
        ahead_u, behind_u = pair(b["vs_upstream"])
        ahead_b, behind_b = pair(b["vs_base"])
        lo = to_int(b["local_only"], 0)
        age = to_int(b["age"], 0)
        in_wt = b["worktree"] not in ("", "-")
        merged = b["ms"] in MERGED_LIKE
        b["lo_int"], b["age_int"] = lo, age
        if name == default:
            cats.append("default")
        elif prot.search(name):
            cats.append("protected")
        if name == cur:
            cats.append("current")
        if in_wt:
            cats.append("worktree")
        if "gone" in b["track"]:
            cats.append("gone")
        if ahead_u and behind_u:
            cats.append("diverged")
            notes.append(f"rozjazd z upstreamem: ahead {ahead_u}, behind {behind_u}")
        if b["upstream"] == "-" and b["ms"] == "NOT_MERGED" and (ahead_b or 0) > 0:
            cats.append("diverged")
            notes.append("ma własne commity i nie ma upstreamu")
        if lo > 0 and b["ms"] == "NOT_MERGED":
            cats.append("local_only")
        if b["ms"] == "NOT_MERGED" and age > a["stale_days"]:
            cats.append("abandoned")

        if b["ms"] == "contained" and not ({"default", "protected", "current", "worktree"} & set(cats)):
            cats.append("decide")
            plan["E"].append({"text": f"{name} — czubek leży na głównej linii {a['base']} (brak własnych commitów): świeżo założona "
                                      "albo zmergowana fast-forwardem; usunięcie nie traci żadnej pracy",
                              "cmd": command("branch", "-d", "--", name), "sha": b["sha"]})
        elif merged and not ({"default", "protected"} & set(cats)):
            sha = b["sha"]
            if name == cur:
                cats.append("decide")
                plan["E"].append({"text": f"{name} — zmergowana ({b['ms']}), ale to bieżąca gałąź: najpierw przełącz się na {default}",
                                  "cmd": command("switch", "--", default), "sha": sha})
            elif in_wt:
                cats.append("decide")
                plan["E"].append({"text": f"{name} — zmergowana ({b['ms']}), ale wystawiona w worktree {b['worktree']}: najpierw usuń worktree",
                                  "cmd": command("worktree", "remove", "--", b["worktree"]), "sha": sha})
            else:
                cats.append("safe")
                flag = "-d" if b["ms"] == "merged" else "-D"
                why = {"merged": "przodek bazy",
                       "rebased": "wszystkie patche już są w bazie (-D, bo git nie rozpozna rebase'u)",
                       "squashed": "cała treść jest w bazie jako squash (-D, bo git nie rozpozna squasha)"}[b["ms"]]
                if lo:
                    why += f"; {lo} commit(ów) nie ma na remote, ale ich treść jest w bazie"
                plan["A"].append({"cmd": command("branch", flag, "--", name), "sha": sha, "why": why})
        elif "abandoned" in cats and not ({"default", "protected", "current", "worktree"} & set(cats)):
            plan["E"].append({"text": f"{name} — porzucona: {age} dni bez commita, niezmergowana"
                                      + (f", {lo} commit(ów) TYLKO lokalnie" if lo else ""),
                              "cmd": command("branch", "-D", "--", name), "sha": b["sha"]})
        elif "gone" in cats and lo > 0:
            plan["E"].append({"text": f"{name} — upstream zniknął z serwera, a {lo} commit(ów) istnieje tylko u Ciebie "
                                      "(push wykonuje użytkownik)",
                              "cmd": command("push", "-u", "--", a["remote"] or "origin", name), "sha": b["sha"]})
        if not cats or cats == ["worktree"] or cats == ["current"] or cats == ["current", "worktree"]:
            cats.append("active")
        b["cats"] = list(dict.fromkeys(cats))
        notes_by_branch[name] = notes

    # Remote
    remote_name = a["remote"] or "origin"
    unchecked = 0
    for r in a["remote_rows"]:
        if r["ms"] == "UNCHECKED":
            unchecked += 1
        if r["name"] == default or prot.search(r["name"]):
            continue
        if r["ms"] in MERGED_LIKE + ("contained",) and a["net"] != "fresh":
            plan["E"].append({"text": f"{remote_name}/{r['name']} — przed usunięciem potrzebny świeży fetch",
                              "cmd": "# ponów audyt z dostępem do remote", "sha": r["sha"]})
            continue
        if r["ms"] == "contained":
            plan["E"].append({"text": f"{remote_name}/{r['name']} — czubek na głównej linii bazy (brak własnych commitów): "
                                      f"świeżo założona albo fast-forward; {r['age']} dni, {r['author']}",
                              "cmd": command("push", "--delete", "--", remote_name, r["name"]), "sha": r["sha"]})
        elif r["ms"] in MERGED_LIKE:
            plan["B"].append({"cmd": command("push", "--delete", "--", remote_name, r["name"]), "sha": r["sha"],
                              "why": f"{r['ms']}, {r['age']} dni, {r['author']}"})

    # Stash
    stash_eval = []
    for st in a["stash"]:
        nf = to_int(st["files"]); ut = to_int(st["untracked"])
        idx = to_int((re.search(r"\{(\d+)\}", st["ref"]) or [None, "0"])[1])
        in_base = nf > 0 and st["same_base"] == f"{nf}/{nf}"
        in_tree = st["rev_applies"] == "yes" and nf > 0
        unreachable = st["reach"] == "NIEOSIĄGALNY"
        index_safe = st.get("index_state") in ("base", "worktree")
        if not index_safe:
            verdict, kind = "indeks stasha zawiera osobną treść albo nie został sprawdzony — zachowaj", "rescue"
        elif (in_base or in_tree) and ut == 0:
            verdict, kind = ("treść już jest w bazie" if in_base else "treść już jest w drzewie roboczym"), "drop"
        elif nf == 0 and ut == 0:
            verdict, kind = "pusty", "drop"
        elif unreachable:
            verdict, kind = "gałąź źródłowa nie istnieje — prawdopodobnie jedyna kopia tej pracy", "rescue"
        else:
            verdict, kind = "istotny — treści nie ma w bazie", "rescue"
        ev = {**st, "idx": idx, "verdict": verdict, "kind": kind, "nf": nf, "ut": ut}
        stash_eval.append(ev)
    for ev in sorted(stash_eval, key=lambda e: -e["idx"]):
        if ev["kind"] == "drop":
            plan["C"].append({"cmd": command("stash", "drop", f"stash@{{{ev['idx']}}}"), "sha": ev["sha"], "why": ev["verdict"]})
    for ev in sorted(stash_eval, key=lambda e: e["idx"]):
        if ev["kind"] == "rescue":
            slug = re.sub(r"[^A-Za-z0-9._-]+", "-", ev["created_on"] or "stash").strip("-")[:40] or "stash"
            plan["E"].append({"text": f"stash@{{{ev['idx']}}} — {ev['verdict']} ({ev['nf']} plik(ów)"
                                      + (f" + {ev['ut']} nieśledzonych" if ev["ut"] else "")
                                      + f", {ev['age']} dni); `git stash branch` przełącza bieżący worktree na nową gałąź",
                              "cmd": command("stash", "branch", f"rescue/stash-{ev['idx']}-{slug}", f"stash@{{{ev['idx']}}}"),
                              "sha": ev["sha"]})

    # Śmieci techniczne
    if a["stale_refs"]:
        plan["D"].append({"cmd": command("remote", "prune", "--", remote_name), "sha": "",
                          "why": f"{len(a['stale_refs'])} gałęzi zdalnych usuniętych na serwerze"})
    if a["prunable"]:
        plan["D"].append({"cmd": command("worktree", "prune"), "sha": "", "why": f"{len(a['prunable'])} martwych wpisów worktree"})
    garbage = to_int(a["health"].get("garbage", "0"))
    loose = to_int(a["health"].get("count", "0"))
    if garbage > 0 or loose > 5000:
        plan["D"].append({"cmd": command("gc"), "sha": "", "why": f"garbage={garbage}, luźnych obiektów {loose}"})

    # Alerty
    alerts = []
    if a["net"] == "failed":
        alerts.append(("bad", f"Fetch nieudany — dane remote z ostatniego fetcha ({a['fetch_age_days'] or '?'} dni). Wnioski „gone” i „merged na remote” są warunkowe."))
    elif a["net"] == "skipped":
        alerts.append(("warn" if to_int(a["fetch_age_days"] or "1", 1) > 0 else "info", f"Fetch pominięty (--no-fetch) — dane remote sprzed {a['fetch_age_days'] or '?'} dni."))
    for op in a["in_progress"]:
        alerts.append(("bad", f"Operacja w toku: {op}"))
    wc = a["wt_counts"]
    if wc["conflicted"]:
        alerts.append(("bad", f"{wc['conflicted']} plik(ów) w konflikcie w drzewie roboczym"))
    if wc["staged"] or wc["modified_unstaged"]:
        alerts.append(("warn", f"Brudne drzewo robocze: {wc['staged']} w indeksie, {wc['modified_unstaged']} zmienionych"))
    m = re.match(r"ahead=(\d+) behind=(\d+)", a["local_default_vs_remote"])
    if m and int(m.group(1)) > 0:
        alerts.append(("warn", f"Lokalny {a['default']} ma {m.group(1)} commit(ów), których nie ma {a['base']}"))
    if len({t.split()[0] for t in a["trunk_like"]}) > 1:
        alerts.append(("warn", "Kilka gałęzi typu trunk: " + ", ".join(a["trunk_like"])))
    if a["tags_unpushed"]:
        alerts.append(("warn", f"Tagi niewypchnięte: {', '.join(a['tags_unpushed'][:10])}"))
    if unchecked:
        alerts.append(("info", f"{unchecked} starszych gałęzi remote poza limitem {a['remote_limit']} — sprawdzone tylko pod kątem zwykłego merge (UNCHECKED). Pełna detekcja: --remote-limit N."))

    return {"plan": plan, "stash": stash_eval, "alerts": alerts, "notes": notes_by_branch, "unchecked": unchecked}


# ---------------------------------------------------------------- historia
def snapshot(a: dict) -> dict:
    return {
        "generated_at": a["generated_at"],
        "local": {b["name"]: b["sha"] for b in a["local"]},
        "remote": {r["name"]: r["sha"] for r in a["remote_rows"]},
        "stash": {s["sha"]: s["message"] for s in a["stash"]},
        "worktrees": len(a["worktrees"]),
    }


def save_and_diff(outdir: Path, a: dict) -> dict | None:
    hist = outdir / "history"
    hist.mkdir(exist_ok=True)
    snap = snapshot(a)
    stamp = datetime.fromtimestamp(a["generated_at"] or datetime.now().timestamp()).strftime("%Y%m%d-%H%M%S")
    prev = None
    for f in sorted(hist.glob("*.json"), reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("generated_at", 0) < snap["generated_at"]:
            prev = data
            break
    (hist / f"{stamp}.json").write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    for old in sorted(hist.glob("*.json"))[:-HISTORY_KEEP]:
        old.unlink(missing_ok=True)
    if not prev:
        return None

    def same_sha(left, right):
        return (isinstance(left, str) and isinstance(right, str)
                and re.fullmatch(r'[0-9a-f]{7,64}', left) is not None
                and re.fullmatch(r'[0-9a-f]{7,64}', right) is not None
                and (left.startswith(right) or right.startswith(left)))

    # Older snapshots used abbreviated IDs. A switch to full IDs is not a ref update.
    old_stash = prev.get('stash', {})
    migrated_stash = {}
    for oid, message in old_stash.items():
        matches = [current for current in snap['stash'] if same_sha(oid, current)]
        migrated_stash[matches[0] if len(matches) == 1 else oid] = message
    prev['stash'] = migrated_stash

    def delta(key):
        p, c = prev.get(key, {}), snap[key]
        return {
            "removed": sorted(set(p) - set(c)),
            "added": sorted(set(c) - set(p)),
            "changed": sorted(k for k in set(p) & set(c)
                              if p[k] != c[k] and not (key in ('local', 'remote') and same_sha(p[k], c[k]))),
        }

    return {"since": prev["generated_at"], "local": delta("local"), "remote": delta("remote"),
            "stash": delta("stash"), "prev_stash": prev.get("stash", {}), "prev_local": prev.get("local", {})}


# ---------------------------------------------------------------- HTML
def e(x) -> str:
    return html.escape(str(x), quote=True)


def fmt_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "?"


def badge(text: str, kind: str = "") -> str:
    return f'<span class="bd {kind}">{e(text)}</span>'


MS_KIND = {"contained": "warn", "merged": "ok", "rebased": "ok", "squashed": "ok", "NOT_MERGED": "", "(default)": "acc", "UNCHECKED": "mut"}
CAT_KIND = {"safe": "ok", "gone": "warn", "abandoned": "warn", "diverged": "warn", "local_only": "bad",
            "decide": "warn", "default": "acc", "protected": "acc", "current": "acc", "worktree": "mut", "active": "mut"}
SYNC_KIND = {"UP_TO_DATE": "mut", "WOULD_FF": "ok", "WOULD_MERGE": "ok", "FF": "ok", "MERGED": "ok",
             "CONFLICT": "bad", "ERROR": "bad"}
SYNC_LABEL = {"UP_TO_DATE": "aktualna", "WOULD_FF": "fast-forward", "WOULD_MERGE": "czysty merge",
              "FF": "fast-forward ✓", "MERGED": "zmergowano ✓", "CONFLICT": "konflikt", "ERROR": "błąd",
              "SKIP_BLOCKED": "zablokowana", "SKIP_PROTECTED": "chroniona", "SKIP_ALREADY_IN_BASE": "już w bazie",
              "SKIP_DIVERGED": "rozjazd", "SKIP_WORKTREE": "inny worktree"}

PLAN_META = {
    "A": ("Lokalne gałęzie bezpieczne do usunięcia", "Treść jest już w bazie. Odzysk: git branch <nazwa> <sha>."),
    "B": ("Gałęzie na remote do usunięcia", "Zmiana współdzielona — osobne potwierdzenie. Odzysk: git push <remote> <sha>:refs/heads/<nazwa>."),
    "C": ("Stash do usunięcia", "Od najwyższego indeksu w dół. Odzysk: git stash store <sha>."),
    "D": ("Sprzątanie techniczne", "Nie usuwa żadnej pracy."),
    "E": ("Wymaga decyzji", "Każda pozycja osobno — nic z tej listy nie wykonuje się hurtem."),
}

CSS = """
:root{--bg:#f6f7f9;--surface:#fff;--surface2:#eef0f3;--text:#1c2128;--muted:#5b6570;--faint:#8a939d;
--border:#dde1e6;--ok:#1a6b35;--ok-bg:#e3f4e8;--warn:#7a4a00;--warn-bg:#fdf1db;--bad:#a11d1d;--bad-bg:#fde7e7;
--acc:#2350b8;--acc-bg:#e6edfc;--mut-bg:#eceef1;--code-bg:#f0f2f5;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#121518;--surface:#1b1f24;--surface2:#232830;
--text:#e4e8ec;--muted:#a1abb5;--faint:#6f7a85;--border:#30363e;--ok:#7fd29a;--ok-bg:#16301f;--warn:#f2c36b;--warn-bg:#352812;
--bad:#f39a9a;--bad-bg:#3a1a1a;--acc:#8fb0ff;--acc-bg:#1d2a48;--mut-bg:#262b32;--code-bg:#15191d;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#121518;--surface:#1b1f24;--surface2:#232830;--text:#e4e8ec;--muted:#a1abb5;--faint:#6f7a85;
--border:#30363e;--ok:#7fd29a;--ok-bg:#16301f;--warn:#f2c36b;--warn-bg:#352812;--bad:#f39a9a;--bad-bg:#3a1a1a;
--acc:#8fb0ff;--acc-bg:#1d2a48;--mut-bg:#262b32;--code-bg:#15191d;color-scheme:dark}
*{box-sizing:border-box}[hidden]{display:none!important}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1080px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;font-weight:600;margin:0}h2{font-size:16px;font-weight:600;margin:32px 0 10px}
.sub{color:var(--muted);font-size:13px;margin:4px 0 0}.sub code{font-size:12px}
header{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-start;justify-content:space-between;margin-bottom:18px}
code,pre{font-family:ui-monospace,"Cascadia Code",Consolas,monospace;font-size:12.5px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:8px}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:10px 12px}
.tile b{display:block;font-size:24px;font-weight:600;line-height:1.2}.tile span{font-size:12px;color:var(--muted)}
.tile.ok b{color:var(--ok)}.tile.warn b{color:var(--warn)}.tile.bad b{color:var(--bad)}
.alert{border-radius:8px;padding:8px 12px;margin:8px 0 0;font-size:13px;border:1px solid var(--border);background:var(--surface)}
.alert.bad{background:var(--bad-bg);color:var(--bad);border-color:transparent}
.alert.warn{background:var(--warn-bg);color:var(--warn);border-color:transparent}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 14px;margin:8px 0}
.card h3{font-size:14px;margin:0 0 6px;font-weight:600}
.scroll{overflow-x:auto;background:var(--surface);border:1px solid var(--border);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:6px 10px;border-bottom:1px solid var(--border);vertical-align:top}
tr:last-child td{border-bottom:0}
th{font-weight:600;font-size:12px;color:var(--muted);background:var(--surface2);white-space:nowrap;position:sticky;top:0}
table.sortable th{cursor:pointer;user-select:none}table.sortable th[data-dir=asc]::after{content:" ▲"}table.sortable th[data-dir=desc]::after{content:" ▼"}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
td.subj{color:var(--muted);max-width:320px}td.cats{min-width:170px}td.cats .mut{font-size:12px}
.path{word-break:break-all}
.bd{display:inline-block;font-size:11px;line-height:1.5;padding:0 7px;border-radius:999px;background:var(--mut-bg);color:var(--muted);margin:1px 3px 1px 0;white-space:nowrap}
.bd.ok{background:var(--ok-bg);color:var(--ok)}.bd.warn{background:var(--warn-bg);color:var(--warn)}
.bd.bad{background:var(--bad-bg);color:var(--bad)}.bd.acc{background:var(--acc-bg);color:var(--acc)}
.net{font-size:12px;padding:4px 10px;border-radius:999px;white-space:nowrap}
.net.ok{background:var(--ok-bg);color:var(--ok)}.net.warn{background:var(--warn-bg);color:var(--warn)}.net.bad{background:var(--bad-bg);color:var(--bad)}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 8px}
.chips button{font:inherit;font-size:12px;border:1px solid var(--border);background:var(--surface);color:var(--text);border-radius:999px;padding:2px 10px;cursor:pointer}
.chips button[aria-pressed=true]{background:var(--acc-bg);color:var(--acc);border-color:var(--acc)}
.block{background:var(--surface);border:1px solid var(--border);border-radius:10px;margin:10px 0;overflow:hidden}
.block .hd{display:flex;gap:10px;align-items:center;justify-content:space-between;padding:10px 14px;background:var(--surface2)}
.block .hd b{font-size:14px}.block .hd small{color:var(--muted);display:block;font-size:12px}
.letter{display:inline-grid;place-items:center;width:22px;height:22px;border-radius:6px;background:var(--acc-bg);color:var(--acc);font-weight:700;font-size:12px;margin-right:6px}
pre{margin:0;padding:10px 14px;background:var(--code-bg);overflow-x:auto;white-space:pre}
.c{color:var(--faint)}
button.copy{font:inherit;font-size:12px;border:1px solid var(--border);background:var(--surface);color:var(--text);border-radius:6px;padding:3px 10px;cursor:pointer;white-space:nowrap}
button.copy:hover{border-color:var(--acc);color:var(--acc)}
ul.dec{list-style:none;margin:0;padding:0}ul.dec li{padding:8px 14px;border-top:1px solid var(--border)}
ul.dec li:first-child{border-top:0}ul.dec .row{display:flex;gap:8px;align-items:center;margin-top:4px}
ul.dec code{background:var(--code-bg);padding:2px 6px;border-radius:4px;overflow-x:auto;white-space:nowrap;max-width:100%}
details{margin:8px 0}summary{cursor:pointer;color:var(--muted);font-size:13px}
.diff li{margin:2px 0}.mut{color:var(--muted)}
footer{margin-top:36px;color:var(--faint);font-size:12px}
"""

JS = """
function copyText(t,b){const done=()=>{const o=b.textContent;b.textContent='Skopiowano';setTimeout(()=>b.textContent=o,1200)};
const fb=()=>{const a=document.createElement('textarea');a.value=t;a.style.position='fixed';a.style.opacity='0';
document.body.appendChild(a);a.select();try{document.execCommand('copy');done()}catch(e){}a.remove()};
try{if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(t).then(done,fb)}else fb()}catch(e){fb()}}
document.querySelectorAll('button.copy').forEach(b=>b.addEventListener('click',()=>{
const src=b.dataset.text!==undefined?b.dataset.text:document.getElementById(b.dataset.copy).innerText;copyText(src,b)}));
document.querySelectorAll('.chips').forEach(g=>g.addEventListener('click',ev=>{const c=ev.target.closest('button');if(!c)return;
g.querySelectorAll('button').forEach(x=>x.setAttribute('aria-pressed',String(x===c)));const f=c.dataset.f;
document.getElementById(g.dataset.table).querySelectorAll('tbody tr').forEach(r=>{
r.hidden=f!=='all'&&!(' '+r.dataset.cats+' ').includes(' '+f+' ')})}));
document.querySelectorAll('table.sortable').forEach(t=>t.querySelectorAll('th').forEach((th,i)=>th.addEventListener('click',()=>{
const tb=t.tBodies[0],dir=th.dataset.dir==='asc'?'desc':'asc';t.querySelectorAll('th').forEach(x=>delete x.dataset.dir);th.dataset.dir=dir;
const key=r=>{const c=r.cells[i];const v=c.dataset.v!==undefined?c.dataset.v:c.textContent.trim();const n=Number(v);return v!==''&&!isNaN(n)?n:v.toLowerCase()};
[...tb.rows].sort((a,b)=>{const x=key(a),y=key(b);return (x>y?1:x<y?-1:0)*(dir==='asc'?1:-1)}).forEach(r=>tb.appendChild(r))})));
"""


def cmd_line(item: dict) -> str:
    c = item["cmd"]
    return f"{c}  # {item['sha']}" if item.get("sha") else c


def render(a: dict, cl: dict, sync: dict | None, diff: dict | None, sources: list[str], protected: str) -> str:
    repo_name = Path(a["root"]).name or "repo"
    plan = cl["plan"]
    P: list[str] = []
    w = P.append

    net_cls, net_txt = {
        "fresh": ("ok", "remote: świeże (fetch OK)"),
        "failed": ("bad", f"remote: NIEAKTUALNE — fetch nieudany, dane sprzed {a['fetch_age_days'] or '?'} dni"),
        "skipped": ("warn", f"remote: z ostatniego fetcha ({a['fetch_age_days'] or '?'} dni)"),
        "none": ("warn", "brak remote'ów"),
    }[a["net"]]

    w(f'<header><div><h1>git-clean · {e(repo_name)}</h1>'
      f'<p class="sub"><code class="path">{e(a["root"])}</code> · gałąź <b>{e(a["current"])}</b> · baza <b>{e(a["base"])}</b>'
      f' · audyt {e(fmt_ts(a["generated_at"]))}</p></div>'
      f'<span class="net {net_cls}">{e(net_txt)}</span></header>')

    # Kafelki
    conflicts = len(sync["conflicts"]) if sync and "rows" in sync else 0
    lo_branches = sum(1 for b in a["local"] if "local_only" in b["cats"])
    tiles = [
        (len(a["local"]), "gałęzi lokalnych", ""),
        (len(plan["A"]), "do usunięcia lokalnie (A)", "ok" if plan["A"] else ""),
        (len(plan["B"]), "do usunięcia na remote (B)", "ok" if plan["B"] else ""),
        (lo_branches, "z pracą tylko lokalnie", "warn" if lo_branches else ""),
        (conflicts, "konfliktów z bazą", "bad" if conflicts else ""),
        (len(a["stash"]), "wpisów w stashu", "warn" if any(s["kind"] == "rescue" for s in cl["stash"]) else ""),
        (len(a["worktrees"]), "worktree", ""),
    ]
    w('<div class="tiles">' + "".join(f'<div class="tile {k}"><b>{n}</b><span>{e(t)}</span></div>' for n, t, k in tiles) + "</div>")
    for kind, text in cl["alerts"]:
        w(f'<div class="alert {kind}">{e(text)}</div>')

    w(graph.render_graph(a))

    # Zmiany od poprzedniego raportu
    if diff:
        items = []
        for label, d, fmt in (("gałęzie lokalne", diff["local"], str), ("gałęzie remote", diff["remote"], str)):
            if d["removed"]:
                items.append(f"<li>usunięte {label}: " + ", ".join(f"<code>{e(x)}</code>" for x in d["removed"]) + "</li>")
            if d["added"]:
                items.append(f"<li>nowe {label}: " + ", ".join(f"<code>{e(x)}</code>" for x in d["added"]) + "</li>")
            if d["changed"]:
                items.append(f"<li>przesunięte {label}: " + ", ".join(f"<code>{e(x)}</code>" for x in d["changed"]) + "</li>")
        if diff["stash"]["removed"]:
            items.append("<li>usunięte ze stasha: " + ", ".join(
                f"<code>{e(diff['prev_stash'].get(x, x)[:60])}</code> <span class='mut'>({e(x)})</span>" for x in diff["stash"]["removed"]) + "</li>")
        if diff["stash"]["added"]:
            items.append(f"<li>nowe w stashu: {len(diff['stash']['added'])}</li>")
        body = "<ul class='diff'>" + "".join(items) + "</ul>" if items else "<p class='mut'>Bez zmian w gałęziach i stashu.</p>"
        w(f'<h2>Zmiany od poprzedniego raportu ({e(fmt_ts(diff["since"]))})</h2><div class="card">{body}</div>')

    # Synchronizacja
    if sync:
        w("<h2>Synchronizacja z bazą</h2>")
        if "error" in sync:
            w(f'<div class="alert warn">{e(sync["error"])}</div>')
        else:
            mode = "podgląd (dry-run) — nic nie zostało zmienione" if sync["mode"] == "dry-run" else "wykonano"
            w(f'<p class="sub">baza <code>{e(sync["base"])} @ {e(sync["base_sha"])}</code> · {e(mode)} · {e(fmt_ts(sync["mtime"]))}'
              f' · {e(sync["summary"].replace("podsumowanie: ", ""))}</p>')
            w('<div class="scroll"><table class="sortable"><thead><tr><th>gałąź</th><th>status</th><th>za bazą</th>'
              '<th>przed bazą</th><th>stare SHA</th><th>nowe SHA</th><th>uwaga</th></tr></thead><tbody>')
            for r in sync["rows"]:
                k = SYNC_KIND.get(r["status"], "warn" if r["status"].startswith("SKIP") else "")
                w(f'<tr><td><code>{e(r["branch"])}</code></td><td>{badge(SYNC_LABEL.get(r["status"], r["status"]), k)}</td>'
                  f'<td class="num">{e(r["behind"])}</td><td class="num">{e(r["ahead"])}</td>'
                  f'<td><code>{e(r["old_sha"])}</code></td><td><code>{e(r["new_sha"])}</code></td><td class="subj">{e(r["detail"])}</td></tr>')
            w("</tbody></table></div>")
            for c in sync["conflicts"]:
                w(f'<div class="card"><h3>{badge("konflikt", "bad")} <code>{e(c["branch"])}</code> — informacja dla ownera</h3>'
                  f'<div class="mut">autorzy: {e(c["owners"])}</div>'
                  f'<div>pliki ({e(c.get("nfiles", "?"))}): ' + ", ".join(f"<code>{e(f)}</code>" for f in c["files"].split(",") if f) + "</div>"
                  f'<ul class="dec"><li style="padding-left:0"><div class="row"><code>{e(c["cmd"])}</code>'
                  f'<button class="copy" data-text="{e(c["cmd"])}">Kopiuj</button></div></li></ul></div>')
            for k, v in sync["notes"].items():
                w(f'<div class="alert warn">{e(v)}</div>')
            if any(r["status"] in ("FF", "MERGED") for r in sync["rows"]):
                w('<div class="alert">Brak konfliktów tekstowych nie znaczy, że kod się zbuduje — przed push uruchom bramkę projektu na zaktualizowanych gałęziach.</div>')

    # Gałęzie lokalne
    w("<h2>Gałęzie lokalne</h2>")
    present = [c for c in CAT_LABEL if any(c in b["cats"] for b in a["local"])]
    w('<div class="chips" data-table="t-local"><button aria-pressed="true" data-f="all">wszystkie</button>'
      + "".join(f'<button aria-pressed="false" data-f="{c}">{e(CAT_LABEL[c])} ({sum(1 for b in a["local"] if c in b["cats"])})</button>' for c in present)
      + "</div>")
    w('<div class="scroll"><table id="t-local" class="sortable"><thead><tr><th>gałąź</th><th>kategorie</th><th>merge do bazy</th>'
      '<th>przed/za bazą</th><th>upstream</th><th>tylko lokalnie</th><th>wiek [dni]</th><th>autor</th><th>ostatni commit</th></tr></thead><tbody>')
    for b in sorted(a["local"], key=lambda x: x["age_int"]):
        cats = " ".join(badge(CAT_LABEL[c], CAT_KIND[c]) for c in b["cats"])
        notes = "".join(f"<div class='mut'>{e(n)}</div>" for n in cl["notes"].get(b["name"], []))
        up = "—" if b["upstream"] == "-" else f'<code>{e(b["upstream"])}</code> ' + (e(b["track"]) if b["track"] != "-" else "") \
             + (f' <span class="mut">{e(b["vs_upstream"])}</span>' if b["vs_upstream"] not in ("-", "0/0") else "")
        wt = (f"<div class='mut' title='{e(b['worktree'])}'>worktree: <code>…/{e('/'.join(b['worktree'].rstrip('/').split('/')[-2:]))}</code></div>"
              if b["worktree"] not in ("", "-") else "")
        w(f'<tr data-cats="{e(" ".join(b["cats"]))}"><td><code>{e(b["name"])}</code><div class="mut"><code>{e(b["sha"])}</code></div>{wt}</td>'
          f'<td class="cats">{cats}{notes}</td><td>{badge(b["ms"], MS_KIND.get(b["ms"], ""))}</td><td class="num">{e(b["vs_base"])}</td><td>{up}</td>'
          f'<td class="num" data-v="{b["lo_int"]}">{e(b["local_only"])}</td><td class="num">{e(b["age"])}</td>'
          f'<td>{e(b["author"])}</td><td class="subj">{e(b["subject"])}</td></tr>')
    w("</tbody></table></div>")

    # Stash
    if cl["stash"]:
        w("<h2>Stash</h2>")
        for s in cl["stash"]:
            k = "ok" if s["kind"] == "drop" else "warn"
            files = ", ".join(f"<code>{e(f)}</code>" for f in s["file_list"].split(",") if f and f != "-")
            more = f" <span class='mut'>(+{s['nf'] - 10})</span>" if s["nf"] > 10 else ""
            w(f'<div class="card"><h3><code>{e(s["ref"])}</code> {badge(s["verdict"], k)}</h3>'
              f'<div class="mut">{e(s["message"])} · {e(s["age"])} dni · {s["nf"]} plik(ów)'
              + (f" + {s['ut']} nieśledzonych" if s["ut"] else "")
              + f' · gałąź źródłowa: {e(s["reach"])} · sha <code>{e(s["sha"])}</code></div>'
              + (f"<div>{files}{more}</div>" if files else "") + "</div>")

    # Remote
    if a["remote_rows"]:
        w(f"<h2>Gałęzie na {e(a['remote'])}</h2>")
        w(f'<p class="sub">{len(a["remote_rows"])} gałęzi · {len(plan["B"])} do usunięcia (blok B)'
          + (f" · {cl['unchecked']} poza limitem pełnej detekcji" if cl["unchecked"] else "")
          + (f" · {len(a['stale_refs'])} usuniętych na serwerze, wiszących lokalnie" if a["stale_refs"] else "") + "</p>")
        w('<details><summary>Pokaż wszystkie gałęzie remote</summary><div class="scroll"><table class="sortable"><thead><tr>'
          '<th>gałąź</th><th>merge do bazy</th><th>przed/za bazą</th><th>wiek [dni]</th><th>autor</th><th>lokalnie</th><th>ostatni commit</th></tr></thead><tbody>')
        for r in a["remote_rows"]:
            w(f'<tr><td><code>{e(r["name"])}</code></td><td>{badge(r["ms"], MS_KIND.get(r["ms"], ""))}</td>'
              f'<td class="num">{e(r["vs_base"])}</td><td class="num">{e(r["age"])}</td><td>{e(r["author"])}</td>'
              f'<td>{e(r["has_local"])}</td><td class="subj">{e(r["subject"])}</td></tr>')
        w("</tbody></table></div></details>")

    # Worktree
    w("<h2>Worktree</h2><div class='card'>" + "".join(f"<div><code class='path'>{e(x)}</code></div>" for x in a["worktrees"])
      + "".join(f"<div class='mut'>martwy wpis: {e(x)}</div>" for x in a["prunable"]) + "</div>")

    # Plan
    w("<h2>Plan sprzątania</h2>")
    if not any(plan.values()):
        w('<div class="card">Nic do posprzątania.</div>')
    for key in "ABCD":
        if not plan[key]:
            continue
        title, desc = PLAN_META[key]
        shown = "\n".join(
            e(i["cmd"]) + (f'  <span class="c"># {e(i["sha"])}</span>' if i.get("sha") else "") for i in plan[key])
        why = "".join(f"<li><code>{e(i['cmd'].split()[-1])}</code> — {e(i['why'])}</li>" for i in plan[key] if i.get("why"))
        w(f'<div class="block"><div class="hd"><div><b><span class="letter">{key}</span>{e(title)} ({len(plan[key])})</b>'
          f'<small>{e(desc)}</small></div><button class="copy" data-copy="blk-{key}">Kopiuj blok</button></div>'
          f'<pre id="blk-{key}">{shown}</pre>'
          + (f'<details style="padding:0 14px 8px"><summary>dlaczego</summary><ul>{why}</ul></details>' if why else "") + "</div>")
    if plan["E"]:
        title, desc = PLAN_META["E"]
        w(f'<div class="block"><div class="hd"><div><b><span class="letter">E</span>{e(title)} ({len(plan["E"])})</b>'
          f'<small>{e(desc)}</small></div></div><ul class="dec">')
        for i in plan["E"]:
            w(f'<li>{e(i["text"])}' + (f' <span class="mut">· sha <code>{e(i["sha"])}</code></span>' if i.get("sha") else "")
              + f'<div class="row"><code>{e(i["cmd"])}</code><button class="copy" data-text="{e(i["cmd"])}">Kopiuj</button></div></li>')
        w("</ul></div>")

    # Push
    if sync and sync.get("mode") == "apply":
        w("<h2>Komendy push</h2>")
        cmds = [x for x in sync["push"] if not x.startswith("#")]
        blocked = [x for x in sync["push"] if x.startswith("#")]
        if cmds:
            w('<div class="block"><div class="hd"><div><b>Do wypchnięcia (gałęzie zaktualizowane w tym przebiegu)</b>'
              '<small>Nigdy --force. Wykonujesz sam.</small></div><button class="copy" data-copy="blk-push">Kopiuj blok</button></div>'
              f'<pre id="blk-push">{e(chr(10).join(cmds))}</pre></div>')
        else:
            w('<div class="card">Nic do wypchnięcia.</div>')
        for x in blocked:
            w(f'<div class="alert warn">{e(x.lstrip("# "))}</div>')
        upd = [r for r in sync["rows"] if r["status"] in ("FF", "MERGED")]
        if upd:
            wt_of = {b["name"]: b["worktree"] for b in a["local"]}
            w('<details open><summary>Jak cofnąć aktualizację (stare SHA)</summary><div class="scroll"><table><thead><tr>'
              '<th>gałąź</th><th>stare SHA</th><th>cofnięcie</th></tr></thead><tbody>')
            for r in upd:
                wt = wt_of.get(r["branch"], "-")
                undo = git_command('branch', '-f', '--', r['branch'], r['old_sha'], shell=a.get('shell', 'bash')) if wt in ('', '-') else git_command('-C', wt, 'reset', '--keep', r['old_sha'], shell=a.get('shell', 'bash'))
                w(f'<tr><td><code>{e(r["branch"])}</code></td><td><code>{e(r["old_sha"])}</code></td><td><code>{e(undo)}</code></td></tr>')
            w("</tbody></table></div></details>")

    w(f'<footer>Źródła: {", ".join(f"<code>{e(s)}</code>" for s in sources)} · próg porzucenia {a["stale_days"]} dni'
      f' · chronione <code>{e(protected)}</code> · wygenerowano {e(datetime.now().strftime("%Y-%m-%d %H:%M"))}</footer>')

    return ('<!doctype html><html lang="pl"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>git-clean · {e(repo_name)}</title><style>{CSS}{graph.CSS}</style></head>'
            f'<body><main>{"".join(P)}</main><script>{JS}{graph.JS}</script></body></html>')


# ---------------------------------------------------------------- tekst dla modelu
def text_summary(a: dict, cl: dict, sync: dict | None, diff: dict | None, out: Path) -> str:
    L: list[str] = []
    w = L.append
    plan = cl["plan"]
    net = {"fresh": "świeże", "failed": f"NIEAKTUALNE (fetch nieudany, dane sprzed {a['fetch_age_days'] or '?'} dni)",
           "skipped": f"z ostatniego fetcha ({a['fetch_age_days'] or '?'} dni)", "none": "brak remote'ów"}[a["net"]]
    w(f"RAPORT HTML: {out}")
    w(f"repo: {a['root']} | gałąź: {a['current']} | baza: {a['base']} | remote: {net}")
    lo = [b["name"] for b in a["local"] if "local_only" in b["cats"]]
    w(f"gałęzi lokalnych: {len(a['local'])} | do usunięcia A: {len(plan['A'])} | remote B: {len(plan['B'])} | "
      f"do usunięcia C: {len(plan['C'])} | stash do oceny E: {sum(s['kind'] == 'rescue' for s in cl['stash'])} | "
      f"stash łącznie: {len(a['stash'])} | worktree: {len(a['worktrees'])} | z pracą tylko lokalnie: {len(lo)}"
      + (f" ({', '.join(lo)})" if lo else ""))
    for kind, text in cl["alerts"]:
        w(f"ALERT[{kind}]: {text}")
    if diff:
        parts = []
        for label, key in (("lokalne", "local"), ("remote", "remote")):
            d = diff[key]
            if d["removed"]:
                parts.append(f"usunięte {label}: {', '.join(d['removed'])}")
            if d["changed"]:
                parts.append(f"przesunięte {label}: {', '.join(d['changed'])}")
            if d["added"]:
                parts.append(f"nowe {label}: {', '.join(d['added'])}")
        if diff["stash"]["removed"]:
            parts.append(f"usunięte ze stasha: {len(diff['stash']['removed'])}")
        w(f"ZMIANY od {fmt_ts(diff['since'])}: " + ("; ".join(parts) if parts else "brak"))
    if sync:
        if "error" in sync:
            w(f"SYNC: {sync['error']}")
        else:
            w(f"SYNC ({sync['mode']}, baza {sync['base']}): {sync['summary'].replace('podsumowanie: ', '')}")
            for r in sync["rows"]:
                if r["status"] not in ("UP_TO_DATE",):
                    w(f"  {r['branch']}: {r['status']} — {r['detail']}")
            for c in sync["conflicts"]:
                w(f"  KONFLIKT {c['branch']}: autorzy {c['owners']}; pliki ({c.get('nfiles', '?')}): {c['files']}")
            for v in sync["notes"].values():
                w(f"  UWAGA: {v}")
    rescue = [s for s in cl["stash"] if s["kind"] == "rescue"]
    if rescue:
        w("STASH DO OCENY (opisz sens zmian jednym zdaniem — `git stash show --stat`):")
        for s in rescue:
            w(f"  {s['ref']}: {s['verdict']}; {s['message']}; pliki: {s['file_list']}")
    w("")
    w("PLAN (polecenia gotowe do wykonania; komentarz # to SHA do odzysku):")
    if not any(plan.values()):
        w("  nic do posprzątania")
    for key in "ABCD":
        if plan[key]:
            w(f"[{key}] {PLAN_META[key][0]} ({len(plan[key])})")
            for i in plan[key]:
                w(cmd_line(i))
    if plan["E"]:
        w(f"[E] {PLAN_META['E'][0]} ({len(plan['E'])}) — każda pozycja wymaga osobnej decyzji")
        for i in plan["E"]:
            w(f"  - {i['text']}")
            w(f"    propozycja: {cmd_line(i)}")
    if sync and sync.get("mode") == "apply":
        w("")
        cmds = [x for x in sync["push"] if not x.startswith("#")]
        w("PUSH:" if cmds else "PUSH: nic do wypchnięcia")
        for x in sync["push"]:
            w(x)
        for r in sync["rows"]:
            if r["status"] in ("FF", "MERGED"):
                w(f"  stare SHA {r['branch']}: {r['old_sha']}")
    return "\n".join(L)


# ---------------------------------------------------------------- main
def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description="git-clean: raport HTML z wyjścia audit.sh/sync.sh")
    ap.add_argument("--sync", choices=["auto", "dryrun", "apply", "none"], default="auto")
    ap.add_argument("--protected", default=PROTECTED_DEFAULT)
    ap.add_argument("--open", action="store_true")
    ap.add_argument("--shell", choices=["bash", "powershell"], default="powershell" if os.name == "nt" else "bash")
    args = ap.parse_args()

    res = subprocess.run(["git", "rev-parse", "--git-common-dir"], capture_output=True, text=True)
    if res.returncode:
        print("BŁĄD: to nie jest repozytorium git", file=sys.stderr)
        return 2
    outdir = Path(res.stdout.strip()).resolve() / "git-clean"
    audit_f = outdir / "audit.txt"
    if not audit_f.exists():
        print(f"BŁĄD: brak {audit_f} — najpierw uruchom audit.sh", file=sys.stderr)
        return 2

    a = parse_audit(audit_f.read_text(encoding="utf-8", errors="replace"))
    sources = [audit_f.name]
    sync = None
    if args.sync != "none":
        cands = {"dryrun": outdir / "sync-dryrun.txt", "apply": outdir / "sync-apply.txt"}
        if args.sync == "auto":
            existing = [p for p in cands.values() if p.exists()]
            pick = max(existing, key=lambda p: p.stat().st_mtime) if existing else None
            if pick and pick.stat().st_mtime < audit_f.stat().st_mtime - SYNC_MAX_LAG_S:
                pick = None
        else:
            pick = cands[args.sync] if cands[args.sync].exists() else None
        if pick:
            sync = parse_sync(pick.read_text(encoding="utf-8", errors="replace"), pick.stat().st_mtime)
            sources.append(pick.name)

    a['shell'] = args.shell
    if sync and 'push' in sync:
        sync['push'] = [translate_command(c, args.shell) for c in sync['push']]
    cl = classify(a, args.protected, args.shell)
    diff = save_and_diff(outdir, a)
    out = outdir / "report.html"
    out.write_text(render(a, cl, sync, diff, sources, args.protected), encoding="utf-8")
    print(text_summary(a, cl, sync, diff, out))
    if args.open:
        webbrowser.open(out.as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
