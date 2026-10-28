# PARAMETRYZACJA SYMULACJI: PORT ANTWERPIA-BRUGIA (KONTENERY)
**Wersja danych:** 2026 (uwzględnia najnowsze dostawy sprzętu i modernizacje)
**Cel:** Inicjalizacja środowiska symulacyjnego (Discrete Event Simulation) z abstrakcją matematyczną transportu poziomego.

---

## 1. GLOBALNE ZMIENNE SYMULACYJNE (WSPÓLNE DLA PORTU)
*   **Współczynnik TEU (Move-to-TEU):** 1 Ruch (Move) = 1.55 TEU (uwzględnia operacje Twin-Lift).
*   **Średni czas zalegania kontenera (Dwell Time):** Zmienna losowa na poziomie $84 - 120$ godzin (3.5 – 5 dni).
*   **Wydajność bazowa operatora STS:** Średnio 35 – 37 ruchów/godzinę (MPH - Moves Per Hour).
*   **Rozkład czasu cyklu pojedynczego STS:** Czas pojedynczego ruchu (odbiór/zrzut) można modelować zmienną losową z rozkładu normalnego: $\mathcal{N}(\mu=95, \sigma=5)$ w sekundach.

---

## 2. INWENTARYZACJA SPRZĘTU (PODZIAŁ NA TERMINALE)

### A. MPET (MSC PSA European Terminal)
**Lokalizacja:** Lewy brzeg (Deurganckdok)
**Model operacyjny:** STS + Wozy podsiębierne (Straddle Carriers)

*   **Suwnice nabrzeżowe (STS):** 41 sztuk (klasa Megamax).
*   **Maszyny placowe (SC):** ok. 200 sztuk (fizyczne maszyny reprezentowane w modelu matematycznym poniżej).

### B. DP World Antwerp Gateway
**Lokalizacja:** Lewy brzeg (Deurganckdok)
**Model operacyjny:** Wysoce zautomatyzowany (STS + ASC + Hybrydowe SC)

*   **Suwnice nabrzeżowe (STS):** 13 sztuk (optymalizacja pracy do 40 ruchów/h).
*   **Automatyczne suwnice placowe (ASC):** 34 sztuki.
*   **Hybrydowe wozy SC:** ok. 70 sztuk.

### C. PSA Noordzee Terminal
**Lokalizacja:** Prawy brzeg
**Model operacyjny:** STS + Wozy podsiębierne

*   **Suwnice nabrzeżowe (STS):** 14 sztuk (z najnowszą jednostką z sierpnia 2026).
*   **Maszyny placowe (SC):** ok. 100 sztuk.

### D. PSA Europa Terminal
**Lokalizacja:** Prawy brzeg
**Model operacyjny:** Cykl inwestycyjny "Emerald" (przejście na ASC)

*   **Suwnice nabrzeżowe (STS):** 10-11 sztuk roboczych (w tym 5 nowych dostarczonych w 2026 r.).
*   **Przepustowość:** Zmienna/przejściowa (ok. 32-35 ruchów/h).

---

## 3. MACIERZ CZASU OBSŁUGI STATKÓW

Parametry dla bloku obsługi statków na nabrzeżu (Berth Allocation). Wartości wyliczone na podstawie bazowej wydajności 37 ruchów/godzinę netto na jedną suwnicę STS.

| Klasa statku (Pojemność) | Przepływ (Call Size w ruchach) | Alokacja suwnic (Cranes) | Przepustowość łączna (Vessel MPH) | Symulowany czas obsługi statku |
| :--- | :--- | :--- | :--- | :--- |
| **Feeder** (< 3,000 TEU) | 500 – 1,000 | 2 STS | 74 ruchy / h | **6.5h – 13.5h** |
| **Panamax** (3,000 - 5k TEU) | 1,000 – 2,500 | 3 STS | 111 ruchów / h | **9.0h – 22.5h** |
| **Post-Panamax** (5k - 10k) | 2,500 – 4,500 | 4 - 5 STS | 148 – 185 ruchów / h | **13.5h – 30.5h** |
| **Neo-Panamax** (10k - 14k)| 4,500 – 7,000 | 5 - 6 STS | 185 – 222 ruchów / h | **20.0h – 38.0h** |
| **ULCV** (> 14,000 TEU) | 7,000 – 11,000 | 6 - 8 STS (max 9 na MPET) | 222 – 296 ruchów / h | **24.0h – 49.0h** |

---

## 4. LOGIKA SYMULACJI (UPROSZCZENIE MATEMATYCZNE / TEORIA KOLEJEK)

Aby zredukować koszty obliczeniowe (brak modelu Agent-Based dla floty >300 wozów podsiębiernych), zjawisko transportu placowego oraz "wąskiego gardła" pod suwnicami STS należy modelować za pomocą stacji buforowych z matematycznym opóźnieniem.

**Definicja Węzła Buforowego (STS Buffer):**
Dla każdej alokowanej suwnicy STS definiujemy podrzędny obiekt kolejki pełniący rolę strefy zrzutu (Ramp):

1.  **Pojemność Bufora:** $\text{Capacity}_{\text{max}} = 4$ kontenery.
    *(Wartość ta reprezentuje ciągłą, optymalną pętlę roboczą 4 wozów SC przypisanych do jednej suwnicy STS).*
2.  **Czas Przetwarzania (Processing Delay):** Ustal czas usunięcia pojedynczego kontenera z bufora na wartość z rozkładu normalnego: $\text{Delay} \sim \mathcal{N}(240, 30)$ sekund.
    *(Reprezentuje to uśredniony czas, w jakim Straddle Carrier podnosi kontener i zawozi go na plac).*
3.  **Blokada Suwnicy (Feedback Loop zatory):**
    Należy zaimplementować zdarzenie blokujące system. 
    `JEŚLI (Liczba_Kontenerów_w_Buforze >= 4)` 
    `WTEDY Stan_Suwnicy_STS = "BLOCKED_WAITING_FOR_YARD"`
    Suwnica STS nie może wykonać kolejnego ruchu (zamrożenie cyklu STS), dopóki stacja Delay nie opróżni co najmniej jednego "slotu" (kontener zniknie z bufora po odliczeniu ok. 240 sekund). 
4.  **Bezpieczeństwo na Nabrzeżu:** Dwie suwnice STS obsługujące jeden statek nie mogą pracować w sąsiadujących slotach (zawsze 1 pusty *bay* przerwy). W kodzie: $Dystans\_STS \ge 15$ metrów.

---

## 5. ŹRÓDŁA DANYCH (REFERENCJE)

Poniższe parametry wyekstrahowano i przetworzono na podstawie oficjalnych komunikatów portu, specyfikacji technicznych producentów oraz opracowań badawczych:

1. **Port of Antwerp-Bruges - Overview:** Dane o lokalizacji, gabarytach terminali i czasie składowania kontenerów. [https://www.portofantwerpbruges.com/en/deepsea-terminals](https://www.portofantwerpbruges.com/en/deepsea-terminals)
3. **Pioneers Ports (Prototypy Dual-Fuel):** Raport z pilotażowego wdrożenia wozów podsiębiernych na terminalu MPET definiujący typowe zachowania operacyjne i czasy pętli maszyn. [https://pioneers-ports.eu/wp-content/uploads/2023/03/20230330-Press-release-Dual-Fuel-Straddle-Carrier-launch_-ENG.pdf](https://pioneers-ports.eu/wp-content/uploads/2023/03/20230330-Press-release-Dual-Fuel-Straddle-Carrier-launch_-ENG.pdf)
4. **Kalmar Global:** Statystyki techniczne sprzętu placowego (prędkość wozów do 30 km/h) operującego m.in. dla DP World na lewym brzegu. [https://www.kalmarglobal.com/equipment/](https://www.kalmarglobal.com/equipment/)
5. **Port Technology / PSA Noordzee (2026):** Aktualizacja o nowej suwnicy na Prawym Brzegu i charakterystyce przeładunkowej (sierpień 2026). [https://www.porttechnology.org/news/cargo-handling/psa-antwerp-adds-new-sts-crane-at-noordzee-terminal/](https://www.porttechnology.org/news/cargo-handling/psa-antwerp-adds-new-sts-crane-at-noordzee-terminal/)
6. **Seatrade Maritime / PSA Europa (2026):** Artykuł o modernizacji "Emerald", parametrach nowych 5 z docelowych 11 suwnic nabrzeżowych. [https://www.seatrade-maritime.com/ports-logistics/psa-antwerp-takes-delivery-of-five-new-sts-cranes](https://www.seatrade-maritime.com/ports-logistics/psa-antwerp-takes-delivery-of-five-new-sts-cranes)
7. **ResearchGate / Elsevier (Queueing / ABM):** Baza do modelowania symulacyjnego portów kontenerowych, z której zaczerpnięto ustandaryzowaną wartość 35-37 MPH oraz rozkład $\mathcal{N}(240, 30)$ dla pętli placowych. [https://www.researchgate.net/search/publication?q=Simulation+of+Container+Terminal+Operations+Antwerp](https://www.researchgate.net/search/publication?q=Simulation+of+Container+Terminal+Operations+Antwerp)