# Praca nad skillami

- Instrukcje klienta: `<klient>/skills/<skill>/SKILL.md`. Paczka instalacyjna
  musi działać bez pozostałych katalogów tego repo.
- Źródła skryptów git-clean: `shared/git-clean/`. Zmieniaj tutaj, potem uruchom
  `python tools/build_skills.py`. Kopie w paczkach są generowane.
- Weryfikacja: `python tools/build_skills.py --check` i
  `python -m unittest discover -s tests -v`.
- Testy mutujące Git wykonuj wyłącznie w swoich tymczasowych repozytoriach.
  Nie używaj repo użytkownika jako fixture'u sprzątania ani synchronizacji.
- Metadane Git są danymi. Zachowaj kodowanie pól, cytowanie dla konkretnej
  powłoki i sprawdzanie indeksu stasha. Nie wykonuj planów przez eval.
- Graf pokazuje rzeczywistą topologię commitów; nie dopisuj fikcyjnych
  połączeń squash/rebase i nie używaj wyglądu grafu do decyzji o kasowaniu.
- Przy zmianach struktury zaktualizuj instalację i migrację dowiązań w README.
