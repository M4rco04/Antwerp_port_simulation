# Strategie VTS: gra czasu przybycia (A) i dynamiczna polityka śluzowania (L)

## Strategia A: gra czasu przybycia

### Problem

Moment przybycia statku do stacji pilotowej jest decyzją, która kształtuje kolejki. Przy obsłudze według kolejności przybycia (FCFS) każdemu opłaca się dotrzeć wcześniej niż inni, żeby zająć lepsze miejsce w kolejce. Skutkiem jest **wyścig do stacji, a potem czekanie** (*hurry-up-and-wait*): statki płyną szybko, spalają paliwo, a po przybyciu stoją na kotwicy. Wszyscy tracą, a nikt indywidualnie nie ma powodu, by przestać.

Gdyby reguła obsługi nie premiowała wczesnego przybycia, statki mogłyby płynąć wolniej i docierać dokładnie wtedy, gdy zasoby są dostępne. To idea *Just-In-Time Arrival* (JIT) promowana przez IMO.

### Model wąskiego gardła Vickreya

Gracze wybierają czas przybycia do punktu o ograniczonej przepustowości. Koszt gracza:

**c(t) = α · W(t) + β · [t\* − (t + W(t))]⁺ + γ · [(t + W(t)) − t\*]⁺**

- **W(t)**: czas czekania w kolejce dla przybycia w chwili t,
- **t\***: pożądany moment przejścia (w porcie: okno nabrzeżowe),
- **α**: koszt godziny czekania,
- **β**: koszt godziny przybycia za wcześnie,
- **γ**: koszt godziny przybycia za późno,
- **[x]⁺**: część dodatnia, czyli max(x, 0).

Własności modelu:

- **Równowaga bez sterowania.** Powstaje kolejka, bo gracze wyrównują sobie koszty w różnych momentach. W podstawowym modelu z jednorodnymi graczami ok. połowa kosztu prywatnego to czas w kolejce, który nikomu nie służy (czysta strata społeczna).
- **Rozwiązanie z opłatą.** Opłata równa opóźnieniu z kolejki likwiduje kolejkę przy tym samym rozkładzie przybyć. Opłata jest transferem, więc strata znika.
- **Odpowiednik bez pieniędzy.** Opłatę można zastąpić regułą obsługi lub przydziałem okien, które pozbawiają wczesne przybycie przewagi.

### Gra w porcie

- **Gracze:** armatorzy i operatorzy kontenerowców, którzy mają harmonogramy i okna nabrzeżowe. Statki tła (masowce, barki, tankowce) nie mają okien i występują tylko jako szum zajmujący te same zasoby.
- **Strategia gracza:** zamierzony moment dotarcia do stacji pilotowej, czyli wyprzedzenie względem okna nabrzeżowego. To jedna liczba, a jej wybór oznacza jednocześnie wybór prędkości na morzu.
- **Koszt gracza:** (1) czekanie na kotwicowisku lub przy stacji, (2) spóźnienie lub przedwczesność względem okna nabrzeżowego (z wagą zależną od pilności statku), (3) paliwo. Zużycie paliwa na milę rośnie mniej więcej z kwadratem prędkości; badanie dotyczące przybyć JIT podaje oszczędność do ok. 14 % paliwa kontenerowców na rejs.
- **Lider i naśladowcy (Stackelberg):** VTS najpierw publicznie ogłasza regułę obsługi, a potem statki wybierają wyprzedzenie, znając regułę i oczekiwane natężenie ruchu.

### Reguły obsługi

| Reguła | Opis | Spodziewana reakcja statków |
|---|---|---|
| **A0: FCFS według przybycia** | kto wcześniej dotrze, ten wcześniej dostaje obsługę (stan obecny) | wyścig: maksymalne wyprzedzenie i czekanie na kotwicy |
| **A1: priorytet według planu** | kolejność wynika z planowanego czasu przy nabrzeżu, a nie z chwili przybycia | brak powodu do pośpiechu, statki dopasowują prędkość do planu |
| **A2: okna wejścia** | VTS przydziela okna czasowe na wejście do stacji z limitem pojemności; poza oknem czeka się dłużej | statki celują w swoje okno |
| **A3: A1 plus wymiana okien bez pieniędzy** | statki mogą zamieniać się oknami, np. za niezbywalne punkty | lepsze dopasowanie do prywatnej pilności |

Najciekawsza jest **A1**: nie wymaga opłaty ani limitu, tylko zmiany klucza, według którego ustawia się kolejkę. Ryzyko to manipulowanie deklarowanym planem, ale okno nabrzeżowe wydaje terminal, nie statek, więc pole do manipulacji jest ograniczone.

### Wyznaczanie równowagi

Równowagi nie da się wyprowadzić wzorem, więc stosuje się **empiryczną analizę gier**, w której symulator jest źródłem wypłat:

1. Opisz strategię statku jednym parametrem (wyprzedzenie), osobno dla kilku klas statków.
2. Dla danej reguły VTS i rozkładu strategii uruchom symulację i zmierz średni koszt każdej klasy.
3. Dla każdej klasy sprawdź, czy zmiana parametru obniży jej koszt (najlepsza odpowiedź). Jeśli tak, zaktualizuj strategię klasy.
4. Powtarzaj do ustabilizowania. Wynik jest przybliżoną równowagą Nasha.

Przyjazdy i pogoda nie zależą od stanu portu, więc wspólne liczby losowe obniżają szum. Jakość równowagi mierzy **największy zysk z jednostronnego odstępstwa (ε)**.

### Wymagania wobec modelu

- Obecnie obowiązuje stała reguła „wirtualnego przybycia”: kontenerowiec wchodzi nie wcześniej niż 8 godzin przed oknem i zwalnia na morzu, by przybić zgodnie z planem. To założona strategia statków, a nie ich wybór.
- VTS widzi statek dopiero na brzegu obszaru, a zapowiedzi przybycia (ETA) nie są modelowane.

Strategia wymaga więc parametru wyprzedzenia po stronie statku, który zastąpi stałą regułę, oraz opcjonalnego kanału ETA. Równowaga reguły A0 powinna odtworzyć zachowanie zaobserwowane w danych AIS (m.in. mniej więcej jeden statek na dziewięć wchodzi na kotwicowisko). Jeśli tego nie robi, wypłaty są źle ustawione.

### Ograniczenia

- **Mały efekt przy dzisiejszym ruchu:** na kotwicy jest średnio ok. 2 z ok. 28 kontenerowców w obszarze, więc potencjał skrócenia czekania jest niewielki. Potrzebny jest scenariusz obciążony, a oszczędność paliwa wymaga wskaźnika zastępczego.
- **Niepewność opóźnień:** gdy statki bywają spóźnione, wyprzedzenie działa jak ubezpieczenie, więc przy dużej zmienności A1 traci przewagę.
- **Statki tła:** bez okien nie mają planu, więc trzeba ustalić, jak A1 je traktuje (np. według kolejki przybycia, za kontenerowcami z oknem).

---

## Strategia L: dynamiczna polityka śluzowania

### Problem

Operator śluzy podejmuje jednocześnie kilka decyzji:

1. **Kiedy zamknąć komorę:** czekać na kolejny statek czy ruszać z tym, co jest w środku.
2. **Kogo wpuścić**, gdy chętnych jest więcej niż miejsca.
3. **Którą komorę wybrać**, gdy śluza ma ich kilka.
4. **Czy wykonać śluzowanie jednostronne lub puste**, aby obsłużyć statek po drugiej stronie.

Każde śluzowanie kosztuje czas pełnego cyklu (wejście, zamknięcie bram, napełnienie lub opróżnienie, otwarcie, wyjście), więc statki zebrane w jednym śluzowaniu dzielą ten koszt. Z drugiej strony czekanie na kolejny statek opóźnia tych, którzy już są w komorze.

### Punkt odniesienia: stałe zegary (L0)

- komora czeka na kolejną jednostkę śródlądową do 12 minut od wejścia pierwszej, a krótkie oczekiwanie na drugi statek wynosi 3 minuty (także wtedy, gdy żaden nie jest w zasięgu wzroku),
- komora, do której wezwano statek, nie rusza pusta, a na statek morski czeka do chwili jego wejścia,
- kolejka jest sortowana według klasy priorytetu i numeru kolejności (FCFS w obrębie klasy),
- statki są układane w komorze zachłannie (od największego), a wybór komory polega na zapełnianiu jednej, zanim zacznie się następną,
- losowe wstrzymania (średnio 35 minut) są kalibrowane, a nie obserwowane.

Luka: logiczną regułą byłoby czekać tylko na statek, który faktycznie nadpływa, bo operator go widzi, ale brakuje danych o tym, jak daleko naprzód operator patrzy.

### Idea

Stałe zegary zostają zastąpione **polityką zależną od stanu**: liczby statków w komorze i w kolejkach po obu stronach, ich rozmiarów i pilności oraz położenia statków nadpływających.

**Reguła krańcowa (przybliżenie jednokrokowe):**

- **U_in**: suma kosztów godzinowych statków w komorze i czekających po drugiej stronie,
- **λ̂**: oczekiwane tempo nadpływania kolejnych statków w zasięgu bramy,
- **ū**: ich średni koszt godzinowy,
- **T_c**: czas cyklu śluzowania.

Dodatkowa minuta czekania kosztuje U_in. Z prawdopodobieństwem λ̂ nowy statek dołączy do tego śluzowania zamiast czekać na następny cykl i oszczędzi ok. ū · T_c. Komora czeka dalej, dopóki:

**λ̂ · ū · T_c > U_in**

To przybliżenie, a nie rozwiązanie optymalne, ale pokazuje progową strukturę prawdziwej polityki: im więcej statków już czeka w komorze, tym krócej opłaca się czekać.

### Drabina polityk

| Polityka | Opis | Wymagana informacja |
|---|---|---|
| **L0** | stałe zegary (baza skalibrowana do danych AIS) | brak |
| **L1** | czekaj tylko na statek faktycznie nadpływający, w zasięgu horyzontu h | pozycja i prędkość statków (obserwowalne) |
| **L2** | reguła krańcowa z wagami pilności | jak wyżej plus waga pilności statku |
| **L3** | polityka optymalna ze stanu (proces decyzyjny Markowa, rozwiązywany osobno dla każdej śluzy) | stan komory, kolejek i statków nadpływających |
| **L4** | Oracle: zna przyszłe momenty dotarcia do bramy | pełna informacja, górna granica |

Horyzont h w L1 jest przeglądany w pewnym zakresie. Osobna oś to **dobór statków do komory**: kolejność przybycia (baza) kontra maksymalizacja ważonej liczby statków w śluzowaniu (heurystyki pakowania z literatury o śluzach Antwerpii).

### Warstwa teoriogrowa

1. **Koszt zewnętrzny wstrzymania.** Czekanie na spóźnialskiego nakłada koszt na wszystkich w komorze. Można go sprawiedliwie podzielić wartością Shapleya lub mechanizmem odpornym na strategiczne zachowanie. W wersji bez pieniędzy koszt wyraża się w niezbywalnych punktach (karma).
2. **Wiarygodność sygnałów.** Deklaracja „jestem pięć minut od bramy” to *cheap talk*: każdy zadeklaruje pięć minut. Dlatego polityki L1 i dalsze opierają się wyłącznie na **obserwowalnym położeniu i prędkości** (AIS).
3. **Reakcja statków na regułę.** Gdy śluza pracuje w przewidywalnym rytmie, statki dopasują do niego moment dotarcia. To łączy L ze strategią A.

### Ograniczenia

- **L0 nie jest słabym punktem odniesienia:** zegary są skalibrowane na czasach przejścia z AIS i pośrednio odzwierciedlają pracę prawdziwych operatorów. Zysk L1–L3 to potencjał ponad ten poziom.
- **Niepewność parametrów:** częstość i długość wstrzymań są skalibrowane, a nie obserwowane. Czasy przejścia na śluzach kanałowych są w modelu o ok. 12–24 % za długie w pobliżu bram, więc porównania względne między politykami są wiarygodniejsze niż liczby bezwzględne.
- **Priorytety i bezpieczeństwo:** polityka nie może wstrzymywać statków zależnych od pływu (priorytet 1), naruszać wyłącznego użycia komory przez największe kontenerowce (350 m i więcej) ani zmieniać kolejności w klasach 0 i 1.
- **Sprawiedliwość:** polityka maksymalizująca przepustowość może systematycznie wypychać na koniec duże i wolne statki morskie albo statki śródlądowe, więc wynik trzeba mierzyć według klas.

---

## Kluczowe artykuły

### Strategia A

- Vickrey, W. S. (1969). *Congestion theory and transport investment.* American Economic Review 59(2), 251–260. Praca założycielska modelu wąskiego gardła.
- Arnott, R., de Palma, A., Lindsey, R. (1990). *Economics of a bottleneck.* Journal of Urban Economics 27(1), 111–130. Pełna analiza równowagi bez opłaty i z opłatą.
- Small, K. A. (2015). *The bottleneck model: An assessment and interpretation.* Economics of Transportation. Przegląd i ocena modelu wraz z ograniczeniami.
- Wellman, M. P. (2006). *Methods for empirical game-theoretic analysis.* Proceedings of AAAI 2006. Wyznaczanie równowagi z symulatora jako źródła wypłat.
- GEF-UNDP-IMO GloMEEP i Low Carbon GIA (2020). *Just In Time Arrival Guide: Barriers and Potential Solutions.* IMO. Koncepcja JIT i bariery wdrożenia.
- Psaraftis, H. N., Kontovas, C. A. (2013). *Speed models for energy-efficient maritime transportation: A taxonomy and survey.* Transportation Research Part C 26, 331–351. Zależność zużycia paliwa od prędkości.
- Elokda, E. i in. (2025). *CARMA: Fair and efficient bottleneck congestion management via nontradable karma credits.* Transportation Science 59(2), 340–359. Odpowiednik opłaty za wąskie gardło bez pieniędzy, wzorzec dla reguły A3.

### Strategia L

- Passchyn, W., Coene, S., Briskorn, D., Hurink, J. L., Spieksma, F. C. R., Vanden Berghe, G. (2016). *The lockmaster's problem.* European Journal of Operational Research 251(2), 432–441. Moment startu śluzowania jako problem szeregowania wsadowego; podstawa dla L4.
- Verstichel, J., De Causmaecker, P., Spieksma, F. C. R., Vanden Berghe, G. (2014). *Exact and heuristic methods for placing ships in locks.* European Journal of Operational Research 235(2), 387–398. Układanie statków w komorze na danych ze śluz Antwerpii.
- Golak, J., Grigoriev, A., van Lent, F., van der Zanden, T. (2025). *Optimizing periodic operations for efficient inland waterway lock management.* arXiv:2506.17743. Okresowe harmonogramy śluz dopasowane do nieregularnych przybyć na podstawie AIS.
- Defryn, C., Golak, J., Grigoriev, A., Timmermans, V. (2019). *Inland waterway efficiency through skipper collaboration and joint speed optimization.* Springer, DOI 10.1007/978-3-030-22629-9_15. Optymalizacja prędkości przy śluzie i projektowanie mechanizmu; łączy strategie A i L.
- Puterman, M. L. (1994). *Markov decision processes.* Wiley. Podstawa metodologiczna dla L3.
- Moulin, H., Shenker, S. (2001). *Strategyproof sharing of submodular costs: Budget balance versus efficiency.* Economic Theory 18, 511–533. Podział kosztu odporny na strategiczne zachowanie.
