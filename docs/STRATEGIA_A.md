# Strategia A: A0, A1, A2 i eksperymenty równowagi

Ten dokument opisuje implementację modelową, nie gotową kalibrację portu.
Polecenia poniżej są dla PowerShella w katalogu głównym repozytorium. Zakładają
działające środowisko projektu; na Windowsie zamiast `py` można użyć
`.\venv\Scripts\python.exe`.

## 1. Co zostało zaimplementowane

`src\strategies\arrival_game.py` udostępnia:

- **A0**: bazową kolejność odpraw FCFS w ramach klasy bezpieczeństwa.
- **A1**: w klasie zwykłej przychodzące statki z planowanym czasem nabrzeża
  są odprawiane według tego czasu, przed statkami bez planu. Odjazdy i statki
  bez planu są rozpatrywane według kolejności zgłoszenia.
- **A2**: okna odprawy przy stacji pilotowej dla zwykłych kontenerowców z
  terminalem i planem nabrzeża. Pojemność okna liczy się osobno dla każdej
  stacji. Pozostałe statki, w tym rozpoczynające podróż na kotwicowisku, nie
  zajmują tych rezerwacji i są obsługiwane według bazowej kolejności.

We wszystkich wariantach statki w niebezpieczeństwie i zależne od pływu
zachowują pierwszeństwo i kolejność bazową; A2 nie ogranicza ich oknami.
Kontrole trasy, pogody, pływu, pilotów i nabrzeża pozostają w modelu.
Okno nie gwarantuje odprawy: jeśli statek zgłosi się w oknie, a kontrola
nie pozwoli na wypłynięcie, zachowuje prawo do odprawy po końcu okna. Jeśli
zgłosi się po końcu okna, dostaje najbliższe wolne następne okno.

**Ograniczenia A2:** rezerwacja dotyczy obsługi przy stacji, nie fizycznego
wejścia do obszaru. Dotyczy tylko wspomnianej grupy, a inne statki mogą
zużyć wspólne zasoby w czasie okna. Brak zapowiedzi ETA przed granicą
obszaru: okno przydzielane jest, gdy generator przekazuje statek strategii.
To nie jest pełny system przydziałów znany z rzeczywistego portu. A3
(wymiana okien) nie jest implementowana.

## 2. Czas dojścia do stacji

Nie podaje się już jednej liczby dla wszystkich. `Simulation.approach_estimate`
wybiera w modelu źródło wejścia, właściwą stację i trasę podejścia, po czym
liczy czas z prędkością planistyczną i ograniczeniami na trasie. Jeśli dla
północnego wejścia model zmienia stację ze względu na dostępność trasy,
prognoza uwzględnia tę decyzję. Wynik to **prognoza**, nie rzeczywisty czas:
ruch, prądy, losowa prędkość, krok symulacji i inne ograniczenia mogą go
zmienić. Stan statku przed wejściem jest używany do prognozy; jeżeli model
zmieni jego zanurzenie przy wejściu, faktyczna trasa może być inna.

`approach_buffer_min` (domyślnie 0 minut) jest dodatkowym zapasem dodawanym
do prognozy przy wyznaczaniu okna. To **jeden wspólny** parametr — nie
oszacowanie czasu dojścia i nie osobny zapas dla każdej trasy.

### Jak sprawdzić prognozę i dobrać zapas

1. Wykonaj przebieg A0 z zapisywaniem prognoz:

```powershell
py src\sim\pipeline.py --days 14 --warmup 2 --seed 1 --containers weeks --vts arrival_game --vts-option service_rule=A0 --vts-option record_approach_estimates=true --label a0-prognoza
```

2. Sprawdź identyfikator utworzonego przebiegu w `results\runs\index.html`.
   W poniższym przykładzie `0001` **zastąp faktycznym ID**:

```powershell
py src\sim\arrival_approach_analysis.py results\runs\0001\events.csv --warmup-days 2 --output results\podejscia.csv --summary results\podejscia-podsumowanie.json
```

CSV zawiera `estimated_min`, `actual_min` i `error_min = actual - estimated`
dla każdego ukończonego podejścia. JSON podaje liczebność, mediany i 90.
percentyl błędu osobno według źródła i stacji. `incomplete` to liczba
nieukończonych albo niezaobserwowanych podejść; nie są traktowane jak zero.
Powtórz analizę na kilku ziarnach i z odpowiednio długą symulacją. Przy małej
liczbie obserwacji nie traktuj percentyli jako stabilnych.

3. Roboczy kandydat to nieujemny 90. percentyl błędu prognozy
(`candidate_buffer_p90_min`). Sprawdź też np. brak zapasu oraz mniejszy i
większy zapas na **innych ziarnach**, a następnie porównaj spóźnienia do
okien i czas oczekiwania. Nie wybieraj wartości tylko dlatego, że daje
najlepszy wynik na danych, na których ją wyliczono.

Ta procedura porównuje prognozę z **wynikiem symulacji**, nie z rzeczywistymi
danymi AIS. Nie jest dowodem poprawnej kalibracji do portu.

## 3. Uruchomienie strategii i dobór parametrów

Przykłady:

```powershell
py src\sim\pipeline.py --days 14 --warmup 2 --seed 1 --containers weeks --vts arrival_game --vts-option service_rule=A0 --label a0
py src\sim\pipeline.py --days 14 --warmup 2 --seed 1 --containers weeks --vts arrival_game --vts-option service_rule=A1 --label a1
py src\sim\pipeline.py --days 14 --warmup 2 --seed 1 --containers weeks --vts arrival_game --vts-option service_rule=A2 --vts-option window_min=60 --vts-option window_capacity=1 --vts-option approach_buffer_min=15 --label a2
```

`approach_buffer_min=15` jest przykładem, **nie wartością skalibrowaną**.
Porównuj warianty na tych samych ziarnach i z tymi samymi ustawieniami
generatora, czasu, pogody i rozgrzewki. Same wspólne ziarna nie gwarantują
identycznych wszystkich późniejszych zdarzeń: działania statków wpływają na
stan portu. Wyniki wariantów A0 i A1 przy domyślnym wyprzedzeniu nie są
automatycznie wynikami w równowadze.

| Parametr strategii | Znaczenie i dobór |
|---|---|
| `service_rule` | `A0`, `A1` albo `A2`. |
| `early_arrival_hours` | Skrócenie domyślnego oczekiwania na morzu dla wszystkich odpowiednich kontenerowców; domyślnie 0, zakres 0–48 h. Testuj kilka wartości. |
| `ship_arrival_hours` | Słownik ID statku → wyprzedzenie w godzinach. Nadpisuje wartość wspólną; używa go narzędzie równowagi. |
| `window_min` | Długość okna A2; domyślnie 60 min, dodatnia wielokrotność rundy VTS (15 min). Porównuj np. 30, 60 i 120 minut. |
| `window_capacity` | Rezerwacje zwykłych statków na stację i okno; domyślnie 1. Porównuj scenariusze, np. 1 i 2, i sprawdź obciążenie pilotów. To nie jest pomiar rzeczywistej przepustowości. |
| `approach_buffer_min` | Dodatni lub zerowy zapas prognozy A2; domyślnie 0. Dobieraj jak w sekcji 2. |
| `record_approach_estimates` | `true` zapisuje prognozy także dla A0/A1; A2 zapisuje je zawsze. |

Wyprzedzenie **tylko skraca domyślny czas utrzymywania na morzu**, maksymalnie
do zera. Statek nie może pojawić się przed chwilą, w której generator go
utworzy. Zatem np. wyprzedzenie 4 h i 8 h może dać dokładnie ten sam czas
wejścia. Nie jest to fizyczna optymalizacja prędkości.

## 4. Przybliżona równowaga

`src\sim\arrival_equilibrium.py` uruchamia symulację dla danego zestawu
decyzji. Następnie dla każdego wybranego statku porównuje jego koszt po
jednostronnej zmianie wyprzedzenia; aktualizuje decyzje i ponownie liczy
korzyść z odstępstwa. Inne statki mają wyprzedzenie 0. Wynik jest
przybliżeniem **dla wybranych graczy, podanych decyzji i ziaren**, nie
równowagą wszystkich statków w porcie.

### Wybór statków i uruchomienie

1. Uruchom zwykłą symulację z tym samym `--start`, `--days`, `--warmup`,
   `--containers` i ziarnem. Otwórz `results\runs\<ID>\ships.csv`. Wybierz
   identyfikatory kontenerowców z terminalem, które weszły po rozgrzewce i
   zdążyły dobić do nabrzeża; upewnij się, że dotrą także w badanych wariantach.
   Pole `moored_min` oznacza zaobserwowany moment dojścia do nabrzeża.
2. Wstaw wybrane ID zamiast `C0001` i `C0002`:

```powershell
py src\sim\arrival_equilibrium.py --players C0001 C0002 --rule A2 --start "2026-10-21 00:00" --days 14 --warmup 2 --containers weeks --seeds 1 --actions 0 2 4 6 8 --window-min 60 --window-capacity 1 --approach-buffer-min 0 --waiting 1 --early 0.5 --late 2 --iterations 10 --tolerance 0.01 --output results\rownowaga-a2.json
```

Każdy nowy zestaw decyzji wymaga osobnego pełnego przebiegu **na każde
ziarno**. Zacznij od jednego lub dwóch statków i kilku decyzji. Jeśli statek
nie dotrze do nabrzeża w choć jednym badanym przebiegu, program zgłosi błąd:
wydłuż okres obserwacji lub wybierz inne statki, nie interpretuj braków jako
zerowego kosztu. Domyślne opcje ruchu, pogody i opóźnień są takie jak w
`Simulation`; flagi `--no-delays` i `--no-background` muszą odpowiadać
przebiegowi, z którego wybrano ID.

Można podać `--seeds 1 2 3`: koszt to średnia po tych ziarnach, a każda
decyzja jest sprawdzana na tym samym zestawie ziaren. Ale w trybach `weeks`
i `nhpp` identyfikator może oznaczać inny statek przy innym ziarnie.
Program sprawdza nazwę i terminal i w razie różnicy przerwie. Zbieżność nazwy
i terminala nie gwarantuje identycznego zawinięcia. Dla analizy wielu ziaren
użyj porównywalnych, ręcznie zweryfikowanych zawinięć, np. w `--containers
replay` przy odpowiednich datach harmonogramu. To ograniczenie generatora, nie
gwarancja stabilności ID.

### Koszty i interpretacja wyniku

Koszt jednego statku:

```text
waiting × godziny oczekiwania + early × godziny przedwczesności
                               + late × godziny spóźnienia
```

Oczekiwanie to czas stanów `anchored` i `wait_clearance` **przed pierwszym
dobiciem**; nie obejmuje wszystkich rodzajów opóźnień, np. kolejek do śluz.
Przedwczesność i spóźnienie liczone są względem `berth_min` — planu modelu
po uwzględnieniu jego losowego opóźnienia i planowania nabrzeża, nie zawsze
oryginalnego czasu z rozkładu.

`--waiting 1 --early 0.5 --late 2` to **niekalibrowane wagi eksperymentalne**.
Jeśli masz dane o kosztach (np. koszt godziny kotwiczenia, kara kontraktowa),
wyraź je w tych samych jednostkach na godzinę. Bez danych porównaj różne
zestawy wag i sprawdź, czy wnioski się zmieniają. Paliwo **nie jest liczone**:
model nie udostępnia tutaj dość informacji o całym rejsie i rzeczywistej
prędkości, by wiarygodnie wycenić zmianę zużycia. Równowaga pomija więc ważny
składnik i nie stanowi kompletnej oceny ekonomicznej strategii A.

`--actions` to siatka wyprzedzeń w godzinach, np. `0 2 4 6 8`; porównaj
wynik z gęstszą siatką. `--iterations` ogranicza kolejne iteracje, a
`--tolerance` to akceptowalna korzyść z odstępstwa **w jednostkach
zdefiniowanego kosztu**, np. 0,01.

W JSON:

- `profile`: wyprzedzenie każdego wybranego statku;
- `costs`: jego średni koszt na podanych ziarnach;
- `regrets`: najlepsza korzyść z jednostronnej zmiany na wartość z siatki;
- `epsilon`: największa z tych korzyści; `converged` oznacza jedynie
  `epsilon <= tolerance` w tym skończonym eksperymencie;
- `stop_reason`: osiągnięcie tolerancji, cykl albo limit iteracji;
- `history`, `settings`, `profiles_simulated`: przebieg i konfiguracja.

Brak zbieżności lub cykl to możliwy wynik, nie dowód braku dowolnej
równowagi. Wyniki zależą od punktu startowego, siatki, wybranych statków,
wag i ziaren. Nie mają przedziałów ufności i nie powinny być jeszcze podstawą
wniosków o rzeczywistej Cenie Anarchii.
