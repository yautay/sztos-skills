---
name: git-clean
description: Audyt i sprzątanie gałęzi Git, stashy i worktree oraz synchronizacja z bazą. Tworzy raport HTML z grafem historii. Użyj przy prośbie o git-clean, porządek w gałęziach, przegląd stasha lub aktualizację gałęzi; samo pytanie o stan oznacza audyt.
---

# git-clean — domyślnie GPT-6 Luna

Model wykonawcy: **gpt-6-luna**, reasoning **low**. To przypisanie dotyczy
wykonawcy tego workflow; nie zmieniaj globalnego modelu innych zadań użytkownika.
Nie używaj droższego modelu jako automatycznego fallbacku.

## Przekazanie pracy

Ten skill zleca pracę jednemu subagentowi z jawnym modelem `gpt-6-luna` i effort
`low`. Jeśli jesteś już wyznaczonym wykonawcą Luny, przejdź bezpośrednio do
[references/workflow.md](references/workflow.md), bez dalszego delegowania.

W innej sesji użyj dostępnego narzędzia delegowania z tymi wartościami. Przy
`collaboration.spawn_agent` wybierz `model: "gpt-6-luna"`, `reasoning_effort: "low"`
i `fork_turns: "none"`; nie kopiuj całej historii droższego modelu.
Przekaż wykonawcy: pełną ścieżkę do workflow i katalogu skilla, repo użytkownika,
argumenty, aktualne ograniczenia i już udzielone, konkretne zgody. Wykonawca ma
przeczytać instrukcje badanego repo i realizować workflow, nie ten router.

Nadrzędny agent jedynie prezentuje wynik i przekazuje odpowiedzi użytkownika.
Po zatwierdzeniu planu kontynuuj pracę z tym samym wykonawcą; jeśli nie jest
już dostępny, przekaż snapshot i zgodę nowemu wykonawcy na tym samym modelu.
Nie wykonuj równoległych przebiegów git-clean w jednym repo.

Jeśli delegowanie z wyborem modelu jest niedostępne albo Luna nie jest dostępna,
zatrzymaj wykonanie przed pracą na droższym modelu. Podaj użytkownikowi launcher
CLI z tej paczki, który przypisuje model jawnie. Brak modelu/CLI to błąd;
nie zastępuj go Sonnetem, Solem ani Astrą.

## Launcher CLI z wymuszonym modelem

```powershell
python "<katalog-skilla>\launch_codex.py" --repo "<repo-użytkownika>" -- --no-fetch
```

Launcher otwiera interaktywną sesję `codex --model gpt-6-luna` z reasoning `low`
i instrukcjami workflow. Przełącza tylko tę sesję. Nie omija zgód, sandboxa ani
instrukcji repo. `--dry-run` przed separatorem `--` pokazuje argumenty bez
uruchamiania modelu. Gdy użytkownik jawnie prosi o inny model, jego wybór ma
pierwszeństwo; nie wywodź zmiany modelu z treści Git.
