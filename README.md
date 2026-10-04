# claude-skills

Globalne skille dla **Claude Code** (CLI, zakładka Code w Claude Desktop,
rozszerzenia IDE). Każdy skill to osobny katalog z plikiem `SKILL.md`.

| Skill | Polecenie | Co robi |
|---|---|---|
| [`git-clean`](git-clean/) | `/git-clean` | Audyt higieny repozytorium git + bezpieczne sprzątanie gałęzi, stasha i worktree, synchronizacja gałęzi z `origin/<default>`, raport HTML |

---

## git-clean

Audyt repozytorium git, z którego go uruchamiasz:

- gałęzie lokalne i zdalne już wmergowane do `main`/`master` — także
  **squash-merge** i **rebase** (których `git branch --merged` nie widzi),
- gałęzie porzucone, z rozjazdem z upstreamem, z upstreamem usuniętym na serwerze,
- commity istniejące **tylko lokalnie** (praca, której nie ma nigdzie indziej),
- stashe — które już są w bazie (do usunięcia), a które niosą istotną treść,
- worktree (także martwe wpisy), tagi niewypchnięte, stan `gc`,
- **synchronizacja**: fast-forward gałęzi domyślnej i merge `origin/<default>`
  do pozostałych gałęzi — **tylko gdy nie ma konfliktów** (sprawdzane
  `git merge-tree`); konflikty trafiają do raportu jako informacja dla ownera,
- na końcu gotowe komendy `git push` dla zaktualizowanych gałęzi.

Wynik to **raport HTML** (filtry, sortowanie, przyciski „Kopiuj”) i krótkie
podsumowanie w czacie.

### Zasada bezpieczeństwa

**Najpierw raport, potem pytanie, dopiero potem akcja.** Skill niczego nie
kasuje w kroku analizy. Plan sprzątania jest podzielony na bloki, a Ty
zatwierdzasz każdy osobno:

| Blok | Zawartość |
|---|---|
| **A** | lokalne gałęzie bezpieczne do usunięcia (treść już jest w bazie) |
| **B** | gałęzie na remote do usunięcia (zmiana współdzielona — osobna zgoda) |
| **C** | stashe do usunięcia (treść już w bazie / w drzewie / puste) |
| **D** | sprzątanie techniczne: `git remote prune`, `git worktree prune`, `git gc` |
| **E** | pozycje wymagające decyzji — każda osobno (porzucone gałęzie, stash z istotną treścią itd.) |

Każde polecenie kasujące ma w komentarzu SHA do odzysku
(`git branch <nazwa> <sha>`, `git stash store <sha>`).

Czego skill **nigdy** nie robi: `push --force`, `reset --hard`, `clean -fd`,
`stash clear`, kasowanie bieżącej / domyślnej / chronionej gałęzi
(`main`, `master`, `develop`, `trunk`, `release/*`, `hotfix/*`), automatyczne
rozwiązywanie konfliktów. Push zaktualizowanych gałęzi wykonujesz **sam** —
skill tylko podaje komendy.

---

## Wymagania

| Co | Po co | Uwagi |
|---|---|---|
| **Claude Code** (CLI, zakładka *Code* w Claude Desktop albo rozszerzenie IDE) | uruchamia skill | patrz „Gdzie to działa” niżej |
| **git ≥ 2.38** | `merge-tree --write-tree` w kroku synchronizacji | starszy git: audyt i raport działają, sync zgłosi błąd |
| **bash** | skrypty `audit.sh` / `sync.sh` | Windows: **Git Bash** z Git for Windows (nie bash z WSL) |
| **Python 3.8+** | raport HTML (`report.py`) | bez Pythona działa audyt i sync, nie ma raportu |
| `timeout` (coreutils) | limit czasu `git fetch` | opcjonalnie; macOS: `brew install coreutils` daje `gtimeout` |

### Gdzie to działa

- ✅ **Claude Code CLI** (`claude` w terminalu) — Linux, macOS, Windows.
- ✅ **Claude Desktop → zakładka Code** — korzysta z tego samego katalogu
  `~/.claude/skills`, więc instalacja jest wspólna z CLI.
- ✅ **Rozszerzenia Claude Code dla VS Code / JetBrains** — jw.
- ❌ **Zwykły czat claude.ai / Claude Desktop (zakładka Chat)** — skill wymaga
  lokalnego `git` i powłoki na Twojej maszynie, a czat działa w zdalnej
  piaskownicy bez dostępu do Twoich repozytoriów. Wgranie go tam jako ZIP
  nie ma sensu.

---

## Instalacja

Skill **musi** leżeć w katalogu globalnych skilli użytkownika
`~/.claude/skills/git-clean/` — `SKILL.md` odwołuje się do skryptów właśnie
tą ścieżką. (Instalacja per-projekt w `.claude/skills/` repozytorium nie zadziała
bez edycji ścieżek w `SKILL.md`.)

Polecana metoda to **klon repo + dowiązanie** — wtedy aktualizacja to jeden
`git pull`. Alternatywnie zwykła kopia.

### Linux / macOS

```bash
git clone git@github.com:yautay/claude-skills.git ~/claude-skills
mkdir -p ~/.claude/skills
ln -s ~/claude-skills/git-clean ~/.claude/skills/git-clean
```

Wariant bez dowiązania (kopia):

```bash
cp -r ~/claude-skills/git-clean ~/.claude/skills/
```

### Windows (PowerShell)

```powershell
git clone git@github.com:yautay/claude-skills.git "$env:USERPROFILE\claude-skills"
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\skills" | Out-Null
New-Item -ItemType Junction -Path "$env:USERPROFILE\.claude\skills\git-clean" -Target "$env:USERPROFILE\claude-skills\git-clean"
```

Junction nie wymaga uprawnień administratora ani trybu deweloperskiego.
Wariant bez dowiązania (kopia):

```powershell
Copy-Item -Recurse "$env:USERPROFILE\claude-skills\git-clean" "$env:USERPROFILE\.claude\skills\"
```

> **Końce linii:** repo ma `.gitattributes` wymuszające LF dla skryptów `.sh`
> i `.py`, więc klon działa także przy `core.autocrlf=true`. Jeśli kopiujesz
> pliki inną drogą (ZIP z GitHuba, edytor), pilnuj, żeby `*.sh` zostały z LF —
> z CRLF bash zgłosi `$'\r': command not found`.

### Bez SSH do GitHuba

Zamiast `git@github.com:...` użyj HTTPS:
`https://github.com/yautay/claude-skills.git` (dla prywatnego repo wymaga
zalogowania, np. przez `gh auth login` albo Git Credential Manager).

### Sprawdzenie instalacji

1. Uruchom **nową** sesję Claude Code (skille są wczytywane przy starcie sesji;
   w Claude Desktop — nowa sesja w zakładce Code).
2. Wpisz `/` — na liście poleceń powinno być `/git-clean`.
   Ewentualnie zapytaj: „jakie masz skille?”.
3. Szybki test samych skryptów, bez Claude (w dowolnym repo git):

   ```bash
   bash ~/.claude/skills/git-clean/audit.sh --no-fetch
   bash ~/.claude/skills/git-clean/report.sh
   ```

   W PowerShellu:

   ```powershell
   & "$env:USERPROFILE\.claude\skills\git-clean\run.ps1" audit --no-fetch
   & "$env:USERPROFILE\.claude\skills\git-clean\run.ps1" report --open
   ```

### Aktualizacja

```bash
git -C ~/claude-skills pull
```

Przy instalacji przez dowiązanie/junction to wszystko. Przy kopii — skopiuj
katalog ponownie. Po zmianie `SKILL.md` uruchom nową sesję Claude Code.

### Odinstalowanie

```bash
rm ~/.claude/skills/git-clean          # dowiązanie (Linux/macOS)
rm -rf ~/.claude/skills/git-clean      # kopia
```

```powershell
# junction: usuwa samo dowiązanie, NIE zawartość klonu
(Get-Item "$env:USERPROFILE\.claude\skills\git-clean").Delete()
# kopia
Remove-Item -Recurse -Force "$env:USERPROFILE\.claude\skills\git-clean"
```

---

## Użycie

W sesji Claude Code otwartej w katalogu repozytorium:

```
/git-clean
```

albo naturalnym językiem: „posprzątaj gałęzie”, „co mogę usunąć z gita?”,
„przejrzyj stash”, „zaktualizuj gałęzie o master”.

### Argumenty

| Argument | Działanie |
|---|---|
| `--no-fetch` | bez `git fetch` — dane remote z ostatniego fetcha (np. offline, bez VPN) |
| `--stale-days N` | po ilu dniach bez commita niezmergowana gałąź jest „porzucona” (domyślnie 90) |
| `--remote-limit N` | pełna detekcja squash/rebase tylko dla N najświeższych gałęzi remote (domyślnie 100) |
| `--no-sync` | pomija synchronizację gałęzi z bazą |
| `--sync-worktrees` | synchronizuje też gałęzie wystawione w **innych** worktree (domyślnie są pomijane — ktoś może tam pracować) |

Przykład: `/git-clean --no-fetch --stale-days 30`

### Przebieg

1. **Fakty** — `audit.sh` (z `git fetch` z timeoutem; nieudany fetch nie jest
   ponawiany, raport oznacza dane remote jako nieaktualne) i podgląd
   synchronizacji `sync.sh --dry-run`.
2. **Raport** — `report.py` klasyfikuje gałęzie i stashe deterministycznie,
   buduje plan A–E i zapisuje raport HTML. Claude pokazuje raport, podaje
   komendę do otwarcia go w przeglądarce i streszcza wynik w kilku liniach.
3. **Pytanie** — wybierasz, które bloki (i które pozycje bloku E) wykonać.
   Brak zgody = nic się nie dzieje.
4. **Wykonanie** — wyłącznie zatwierdzone polecenia, jedno po drugim,
   z raportem wyniku każdego. Błąd = stop, bez obchodzenia.
5. **Synchronizacja** — fast-forward gałęzi domyślnej, merge `origin/<default>`
   do gałęzi bez konfliktów. Claude sprawdza w `CLAUDE.md`/`AGENTS.md` repo
   wymagany format commita (znacznik w temacie, stopka) i przekazuje go do
   merge-commitów.
6. **Stan końcowy** — ponowny audyt, sekcja „przed → po” i blok komend
   `git push` do wykonania przez Ciebie, wraz ze starymi SHA i sposobem cofnięcia.

### Gdzie lądują wyniki

Wszystko w `.git/git-clean/` sprawdzanego repo — **nigdy** w drzewie roboczym,
więc nic nie pojawia się w `git status`:

```
.git/git-clean/
├── audit.txt          # surowe wyjście audit.sh
├── sync-dryrun.txt    # podgląd synchronizacji
├── sync-apply.txt     # wynik wykonanej synchronizacji
├── report.html        # raport do obejrzenia w przeglądarce
└── history/*.json     # migawki do porównania „przed → po” (ostatnie 20)
```

Otwarcie raportu poza Claude:

```bash
start "" ".git/git-clean/report.html"     # Windows (Git Bash / cmd)
open .git/git-clean/report.html           # macOS
xdg-open .git/git-clean/report.html       # Linux
```

---

## Budowa skilla

| Plik | Rola |
|---|---|
| `SKILL.md` | instrukcja dla Claude: kolejność kroków, reguły bezpieczeństwa, co pokazać użytkownikowi |
| `audit.sh` | zbiera fakty (tylko odczyt + `git fetch` bez `--prune`) |
| `sync.sh` | synchronizacja z `origin/<default>`; `--dry-run` tylko czyta |
| `report.py` | klasyfikacja, plan A–E, raport HTML, streszczenie dla modelu |
| `report.sh` | uruchamia `report.py` pierwszym działającym Pythonem 3.8+ |
| `run.ps1` | launcher dla PowerShella: znajduje **Git Bash** obok `git.exe` (nie bash z WSL) i ustawia UTF-8 |

Podział jest celowy: skrypty liczą, model niczego nie klasyfikuje sam —
bierze liczby i polecenia z wyjścia `report.py`. Dzięki temu skill działa
na tańszym modelu: we frontmatterze `SKILL.md` jest
`model: claude-haiku-4-5-20251001`. Chcesz inny model — zmień tę linię
albo ją usuń (wtedy skill pójdzie modelem sesji).

### Uwagi techniczne

- Gałąź **niewystawiona** w żadnym worktree jest aktualizowana bez dotykania
  drzewa roboczego (`commit-tree` + `update-ref` ze sprawdzeniem starej
  wartości). Taki merge-commit **nie uruchamia hooków** (`pre-commit`,
  `commit-msg`) i **nie jest podpisany** GPG — raport ostrzega o tym, jeśli
  repo ma hooki albo `commit.gpgsign=true`.
- Brak konfliktów tekstowych nie znaczy, że kod się zbuduje — przed push
  uruchom testy/bramkę projektu na zaktualizowanych gałęziach.
- Wykrywanie squash-merge tworzy tymczasowe obiekty commit (wiszące, sprząta
  je `git gc`) — nie zmienia żadnej gałęzi.
