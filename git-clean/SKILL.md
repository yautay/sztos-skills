---
name: git-clean
description: Audyt higieny repozytorium git, z którego jest uruchomiony — lokalne vs remote (o ile jest sieć/VPN), gałęzie już wmergowane do main/master (też squash/rebase), porzucone, do usunięcia, rozjazdy z upstreamem, commity istniejące tylko lokalnie, stashe z istotną treścią, worktree, tagi. Dodatkowo wyrównuje lokalne gałęzie z origin/<default> (fast-forward gałęzi domyślnej, merge do pozostałych tylko gdy bez konfliktów; konflikty → info dla ownera) i na końcu podaje gotowe komendy push. Wynik to raport HTML do obejrzenia w przeglądarce plus krótkie podsumowanie. Najpierw raport, kasowanie wyłącznie po potwierdzeniu. Użyj, gdy użytkownik prosi o /git-clean, porządek w gałęziach, „co mogę usunąć", przegląd stasha, „zaktualizuj gałęzie o master".
argument-hint: "[--no-fetch] [--stale-days N] [--remote-limit N] [--no-sync] [--sync-worktrees]"
model: claude-haiku-4-5-20251001
---

# /git-clean — audyt i sprzątanie repozytorium

Zasada nadrzędna: **najpierw raport, potem pytanie, dopiero potem akcja.** Nic
nie kasujesz w tym samym kroku, w którym analizujesz.

**Podział pracy:** fakty zbierają `audit.sh` i `sync.sh`, a klasyfikację, plan
sprzątania (bloki A–E), komendy push i raport HTML robi `report.py`.
**Ty niczego nie klasyfikujesz ani nie przeliczasz** — bierzesz liczby, listy
i polecenia z wyjścia `report.py`, pokazujesz raport i pytasz o zgodę. Jedyna
rzecz z Twoim osądem: jedno zdanie o sensie każdego stasha „do oceny".

Wszystkie wyniki lądują w `.git/git-clean/` (`audit.txt`, `sync-*.txt`,
`report.html`, `history/`) — nigdy w drzewie roboczym.

## Polecenia

Używaj wariantu pasującego do powłoki, w której pracujesz. W PowerShellu
**nie wołaj `bash` wprost** (na PATH bywa bash z WSL) — `run.ps1` znajduje Git
Bash obok `git.exe` i ustawia UTF-8.

| Krok | Bash | PowerShell |
|---|---|---|
| audyt | `bash ~/.claude/skills/git-clean/audit.sh ARG` | `& "$env:USERPROFILE\.claude\skills\git-clean\run.ps1" audit ARG` |
| sync | `bash ~/.claude/skills/git-clean/sync.sh ARG` | `& "$env:USERPROFILE\.claude\skills\git-clean\run.ps1" sync ARG` |
| raport | `bash ~/.claude/skills/git-clean/report.sh` | `& "$env:USERPROFILE\.claude\skills\git-clean\run.ps1" report` |

Argumenty użytkownika: `--no-fetch`, `--stale-days N`, `--remote-limit N` →
do **audytu**; `--sync-worktrees` → do **sync**; `--no-sync` → pomijasz kroki
sync (1b i 5) i **każdy** raport uruchamiasz z `--sync none` (inaczej raport
pokaże wynik sync z wcześniejszego przebiegu).

## 1. Zbierz fakty

a) Audyt z argumentami użytkownika. Wynik tylko przewiń — czytać będziesz
raport. Robi `git fetch` (bez `--prune`, z timeoutem); fetcha **nie ponawiaj**,
gdy się nie uda (brak VPN) — raport sam to oznaczy.

b) Podgląd synchronizacji (tylko czyta): sync z `--dry-run`.

## 2. Raport i podsumowanie

Uruchom raport. Na stdout dostajesz streszczenie: ścieżkę `RAPORT HTML`,
liczniki, `ALERT`y, `SYNC`, `STASH DO OCENY`, `PLAN` z blokami A–E i (po
synchronizacji) `PUSH`.

1. **Pokaż raport:** wyślij plik z linii `RAPORT HTML` narzędziem `SendUserFile`
   z `display: "render"` (gdy narzędzia nie ma — pomiń). Zawsze podaj też
   komendę otwierającą go w zwykłej przeglądarce, gdzie działają filtry,
   sortowanie i przyciski „Kopiuj": `start "" "<ścieżka>"` (Windows) albo
   `open "<ścieżka>"` (macOS).
2. **Stash do oceny:** dla każdej pozycji z `STASH DO OCENY` uruchom
   `git stash show --stat 'stash@{n}'` i napisz jedno zdanie, czego dotyczy zmiana.
3. **Podsumowanie po polsku, 5–8 linii,** wyłącznie z liczb i list ze stdout:
   status sieci (jeśli `ALERT[bad]` o fetchu — powiedz wprost, że wnioski
   o remote są warunkowe), ile do usunięcia w A/B/C, praca tylko lokalnie,
   konflikty z bazą (gałąź + autorzy + pliki), gałęzie `SKIP_WORKTREE` i
   `SKIP_BLOCKED`, uwagi `UWAGA:` (pominięte hooki / niepodpisane merge).
   Tabel nie przepisuj — są w HTML.

## 3. Zapytaj

`AskUserQuestion` z `multiSelect: true`: opcja na każdy **niepusty** blok A–D
(etykieta = litera + tytuł + liczba pozycji; blok B opisz jako zmianę
współdzieloną na serwerze). Pozycje bloku E to osobne decyzje — jeśli są,
zadaj drugie pytanie z pozycjami E jako opcjami (gdy jest ich więcej niż 4,
wypisz je w czacie i poproś o odpowiedź tekstem). Brak zgody = nic nie robisz.

## 4. Wykonaj (tylko zatwierdzone)

- Wykonuj **dokładnie te linie** z `PLAN`, które należą do zatwierdzonych
  bloków/pozycji, jedna po drugiej, i raportuj wynik każdej. Komentarz `# <sha>`
  zostaw — to SHA do odzysku (`git branch <nazwa> <sha>`, `git stash store <sha>`,
  `git push <remote> <sha>:refs/heads/<nazwa>`).
- Stash: kolejność z planu (od najwyższego indeksu); `stash@{n}` zawsze
  w pojedynczych cudzysłowach — inaczej PowerShell psuje nawiasy klamrowe.
- Blok B wymaga sieci; jeśli fetch w kroku 1 się nie udał — pomiń blok i powiedz.
- Gdy polecenie się nie powiedzie — zatrzymaj się na nim, pokaż błąd, nie
  próbuj obejść (np. `-d` → `-D`) bez pytania.
- **Push robi użytkownik.** Jedyny push, który wykonujesz, to `git push <remote>
  --delete …` z zatwierdzonego bloku B. Pozycje E z `git push -u …` (upstream
  zniknął, a praca jest tylko lokalnie) **podajesz użytkownikowi** do
  samodzielnego wykonania — nawet gdy je zaznaczy.
- **„Praca tylko lokalnie"** = kategoria `tylko lokalnie` w raporcie, czyli
  gałąź `NOT_MERGED` z commitami, których nie ma na remote. Gałęzie
  `merged`/`rebased`/`squashed` z bloku A mogą mieć commity nieobecne na
  remote (typowe po squash-merge i usunięciu gałęzi na serwerze), ale ich treść
  jest w bazie — zgoda na blok A wystarcza.
- **Nigdy**: `push --force`, `reset --hard`, `clean -fd`, `stash clear`,
  kasowanie bieżącej gałęzi, domyślnej albo chronionej (`main`, `master`,
  `develop`, `trunk`, `release/*`, `hotfix/*`), kasowanie gałęzi z kategorii
  `tylko lokalnie` (np. porzuconej z bloku E) bez wyraźnego „tak, wyrzuć tę
  pracę".

## 5. Synchronizacja z bazą (automatyczna, bez konfliktów)

Pomiń przy `--no-sync`. Przed uruchomieniem sprawdź w `CLAUDE.md`/`AGENTS.md`
repo i w instrukcjach sesji, czego wymaga treść commita (znacznik w temacie,
stopka `Co-Authored-By`) i przekaż: `--msg-suffix " <znacznik>"`,
`--trailer "<stopka>"`. Uruchom sync **bez** `--dry-run` (z `--sync-worktrees`
tylko, jeśli użytkownik go podał).

Skrypt robi wyłącznie: fast-forward gałęzi domyślnej, merge `origin/<default>`
do gałęzi, gdzie `merge-tree` potwierdza brak konfliktów. Nie rusza gałęzi
chronionych, już wmergowanych, z brudnym drzewem, z konfliktem, z rozjechanym
lokalnym defaultem, ani — bez `--sync-worktrees` — wystawionych w **innym**
worktree (ktoś może tam pracować, np. równoległa sesja agenta).
**Konflikty nigdy nie są rozwiązywane automatycznie** — nie proponuj rebase'u
ani force-pusha.

## 6. Stan końcowy

Audyt z `--no-fetch`, potem raport (sam porówna z poprzednim — sekcja
`ZMIANY`). Pokaż HTML ponownie i napisz krótko „przed → po" z linii `ZMIANY`.
Raz dodaj zastrzeżenie: brak konfliktów tekstowych nie znaczy, że kod się
zbuduje — przed push uruchom bramkę projektu na zaktualizowanych gałęziach.

Na samym końcu odpowiedzi **jeden blok ```bash** z liniami z sekcji `PUSH`,
które nie zaczynają się od `#` — po jednej w linii, bez `$` (komendy są
identyczne w Bashu i PowerShellu). Linie z `#` to adnotacje (rozjazd z
upstreamem, upstream usunięty) — przytocz je poza blokiem. Jeśli `PUSH: nic do
wypchnięcia` — powiedz to zamiast pustego bloku. Pod blokiem: stare SHA
(`stare SHA …`) i jak cofnąć — `git branch -f <b> <old_sha>` albo, w worktree
gałęzi, `git reset --hard <old_sha>`; wykonuje to wyłącznie użytkownik.

## Ściąga: co znaczą statusy

- **merge do bazy** (`audit.txt`): `merged` (przodek bazy), `contained` (czubek
  leży na głównej linii bazy — świeżo założona albo fast-forward; zawsze blok E),
  `rebased`, `squashed`, `NOT_MERGED`, `UNCHECKED` (gałąź remote poza
  `--remote-limit`, sprawdzona tylko pod kątem zwykłego merge).
- **sync**: `UP_TO_DATE`, `WOULD_FF`/`FF`, `WOULD_MERGE`/`MERGED`, `CONFLICT`,
  `SKIP_BLOCKED` (brudny worktree / operacja w toku), `SKIP_WORKTREE` (inny
  worktree), `SKIP_PROTECTED`, `SKIP_ALREADY_IN_BASE`, `SKIP_DIVERGED`, `ERROR`.
- **bloki planu**: A lokalne bezpieczne · B remote · C stash do usunięcia ·
  D sprzątanie techniczne (`remote prune`, `worktree prune`, `gc`) ·
  E wymaga decyzji (porzucone, `contained`, upstream zniknął z lokalną pracą,
  zmergowane, ale bieżące lub w worktree, stash istotny → `git stash branch`).
