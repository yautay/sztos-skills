# Skills dla Claude i Codexa

Repo przechowuje oddzielne instrukcje dla każdego klienta i samodzielne paczki:

```text
claude/skills/git-clean/   # /git-clean w Claude Code
codex/skills/git-clean/    # $git-clean w Codexie
shared/git-clean/          # źródła wspólnych skryptów
tools/build_skills.py     # pakowanie do katalogów dostawców
tests/                    # testy na tymczasowych repozytoriach
```

Nowy klient może dostać `<klient>/skills/git-clean/SKILL.md`. Skrypt pakujący
odnajduje takie katalogi automatycznie. Każda paczka zawiera wszystkie skrypty;
po instalacji nie zależy od katalogu `shared/` ani API drugiego dostawcy.

## git-clean

Audyt gałęzi, stashy i worktree, plan sprzątania oraz synchronizacja z gałęzią
domyślną. Rozpoznaje merge, patche po rebase i squash. Pokazuje pracę tylko
lokalną, rozjazdy upstreamu i konflikty z bazą.

Raport HTML zawiera graf DAG z etykietami gałęzi lokalnych, remote, tagów i HEAD,
wybór historii gałęzi, powiększanie, kolorowe oznaczenia kandydatów do usunięcia
i pracy tylko lokalnej, filtrowane tabele, plan A–E oraz migawki „przed → po”.
Graf pokazuje rzeczywistych rodziców commitów: squash/rebase nie tworzy fikcyjnego
połączenia z dawną gałęzią. Równoważność treści jest sprawdzana osobno w tabelach.
Domyślnie pokazuje 120 commitów, maksymalnie 1000. Raport działa offline, bez CDN.

## Bezpieczeństwo

Najpierw raport i podgląd, potem konkretny wybór użytkownika. Sama prośba o audyt
nie oznacza zgody na synchronizację ani kasowanie.

| Blok | Zakres |
|---|---|
| A | lokalne gałęzie z treścią już w bazie |
| B | gałęzie remote — osobna zgoda i świeże dane |
| C | stashe bez osobnej, potrzebnej treści |
| D | prune i gc |
| E | indywidualne decyzje i ratowanie pracy |

Indeks stasha jest sprawdzany osobno od jego drzewa roboczego i plików
nieśledzonych. Jeśli zawiera osobną treść albo nie został sprawdzony w starym
audycie, stash zostaje do oceny. Metadane są kodowane w audycie, komendy cytowane
dla konkretnej powłoki (`--shell bash` / `--shell powershell`). Instrukcje wymagają
ponownej weryfikacji SHA przed mutacją. Nieświeże dane wyłączają blok B.

Nie usuwa się gałęzi bieżącej, domyślnej, chronionej ani wystawionej w worktree.
Chronione: main, master, develop, trunk, release/*, hotfix/*. Sync pomija brudne
worktree (także pliki nieśledzone), konflikty i inne worktree bez wyraźnego wyboru
`--sync-worktrees`. Błąd przerywa wykonanie z niezerowym kodem. Nieznany argument
również kończy skrypt błędem — literówka w `--dry-run` nie uruchomi synchronizacji.

Merge gałęzi poza worktree używa `commit-tree` i `update-ref` ze sprawdzeniem
starego SHA, pomijając hooki i podpisy. Raport ostrzega, jeśli repo ich wymaga.
Brak konfliktów tekstowych nie zastępuje bramki projektu przed pushem.
Audyt zapisuje pliki i tymczasowe obiekty Git; nie zmienia lokalnych gałęzi i nic
nie kasuje. Fetch odświeża refs bez prune. Podgląd sync zapisuje obiekty merge-tree
bez aktualizacji gałęzi.

## Wymagania

Git 2.38+ do synchronizacji, Bash (Windows: Git Bash), Python 3.8+ do raportu,
lokalna sesja klienta z dostępem do repo i powłoki. Bez zależności Pythona.

## Instalacja

Klon zostaje w `C:\dev\claude-skills`. Można zainstalować obie wersje jednocześnie.
Instrukcje używają ścieżki załadowanego skilla; działają również jako kopia albo
w katalogu skilli konkretnego projektu.

Windows — Claude Code:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\skills" | Out-Null
New-Item -ItemType Junction -Path "$env:USERPROFILE\.claude\skills\git-clean" -Target 'C:\dev\claude-skills\claude\skills\git-clean'
```

Windows — Codex:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.agents\skills" | Out-Null
New-Item -ItemType Junction -Path "$env:USERPROFILE\.agents\skills\git-clean" -Target 'C:\dev\claude-skills\codex\skills\git-clean'
```

Repozytoryjna instalacja Codexa: skopiuj paczkę do `.agents/skills/git-clean/`.
[Dokumentacja skilli Codexa](https://learn.chatgpt.com/docs/build-skills).

Linux/macOS, z korzenia klonu:

```bash
mkdir -p ~/.claude/skills ~/.agents/skills
ln -s "$PWD/claude/skills/git-clean" ~/.claude/skills/git-clean
ln -s "$PWD/codex/skills/git-clean" ~/.agents/skills/git-clean
```

Zamiast dowiązania można skopiować cały katalog skilla. Przy kopii aktualizacja
wymaga ponownego skopiowania. Przy dowiązaniu wystarcza `git pull`.

**Migracja starej instalacji:** `git-clean/` w korzeniu zostało zastąpione przez
`claude/skills/git-clean/`. Stare dowiązanie trzeba utworzyć ponownie do nowej
ścieżki. Usuwaj samo dowiązanie, nie jego cel; kopia wymaga innego postępowania.
Jeśli klient nie widzi skilla po aktualizacji, rozpocznij nową sesję.

## Użycie

Claude: `/git-clean`. Codex: `$git-clean`. Można też poprosić o audyt gałęzi/stashy.

| Argument | Działanie |
|---|---|
| --no-fetch | dane remote z ostatniego fetcha |
| --stale-days N | próg porzuconej gałęzi; domyślnie 90 |
| --remote-limit N | limit pełnej detekcji squash/rebase remote; domyślnie 100 |
| --graph-limit N | zakres grafu: domyślnie 120, maksymalnie 1000 |
| --no-sync | pomija sync; raport musi dostać --sync none |
| --sync-worktrees | obejmuje inne worktree, po wyraźnym wyborze |

Test bez klienta, z katalogu sprawdzanego repo:

```powershell
& 'C:\dev\claude-skills\codex\skills\git-clean\run.ps1' audit --no-fetch
& 'C:\dev\claude-skills\codex\skills\git-clean\run.ps1' sync --dry-run
& 'C:\dev\claude-skills\codex\skills\git-clean\run.ps1' report --sync dryrun --shell powershell --open
```

Wyniki: `<git-common-dir>/git-clean/` — audit.txt, sync-dryrun.txt, sync-apply.txt,
report.html i history/*.json. W zwykłym repo to `.git/git-clean/`; w worktree
raport leży we wspólnym katalogu Git.

## Rozwój

Zmieniaj skrypty w `shared/git-clean/`, instrukcje w katalogu konkretnego klienta.

```bash
python tools/build_skills.py
python tools/build_skills.py --check
python -m unittest discover -s tests -v
```

`.gitattributes` wymusza LF dla Bash/Pythona i CRLF dla PowerShella. Launcher ma
BOM dla UTF-8 w Windows PowerShell 5.1. Testy tworzą własne repozytoria i nie
sprzątają repo użytkownika.


## Domyślny koszt modelu

- Claude Code: `model: haiku` i `effort: low` w frontmatterze skilla. Model
  sesji wraca po zakończeniu wywołania zgodnie z mechanizmem Claude Code.
- Codex: wykonawca `gpt-6-luna`, reasoning `low`. Entrypoint `$git-clean`
  zleca workflow jednemu subagentowi z jawnym wyborem modelu i minimalnym
  kontekstem. Nadrzędny agent prezentuje wynik i przekazuje decyzje użytkownika.

Codex nie ma udokumentowanego pola `model` we frontmatterze `SKILL.md`.
Dlatego w paczce jest także `launch_codex.py`, który uruchamia interaktywną
sesję CLI na Lunie, bez zmiany globalnego modelu i bez obchodzenia zgód/sandboxa:

```powershell
python 'C:\dev\claude-skills\codex\skills\git-clean\launch_codex.py' --repo 'C:\dev\wybrane-repo' -- --no-fetch
```

Podgląd argumentów bez uruchamiania ani opłaty za model:

```powershell
python 'C:\dev\claude-skills\codex\skills\git-clean\launch_codex.py' --repo 'C:\dev\wybrane-repo' --dry-run -- --no-fetch
```

Sam import skilla nie przełącza modelu nadrzędnego chatu Codexa. Wymagane jest
narzędzie delegowania z wyborem modelu albo launcher CLI. Brak Luny nie oznacza
zgody na droższy model: wykonanie ma się zatrzymać. Jawny wybór użytkownika
może zmienić model. Skrypty liczą klasyfikację i budują graf bez używania LLM.

Wybór Luny sprawdzono 2026-10-06 w
[dokumentacji modeli OpenAI](https://learn.chatgpt.com/docs/model-selection) i
[cenniku Codexa](https://learn.chatgpt.com/docs/pricing).
Wybór modelu subagenta:
[dokumentacja OpenAI](https://learn.chatgpt.com/docs/agent-configuration/subagents).
Frontmatter Claude:
[dokumentacja Claude Code](https://code.claude.com/docs/en/skills).
