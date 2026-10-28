# PARAMETRYZACJA SYMULACJI: ALOKACJA NABRZEŻA (BERTHING CAPACITY)
**Cel:** Definicja pojemności nabrzeży oraz logicznych ograniczeń cumowania statków (Berth Allocation Problem).

---

## 1. ZMIENNE PRZESTRZENNE TERMINALI (QUAY INFRASTRUCTURE)

Zdolność do obsługi wielu statków naraz nie jest wyrażana w fizycznych "slotach", lecz w **dostępnej długości nabrzeża (Quay Length)**.

### A. MPET (Deurganckdok - Lewy brzeg)
*   **Całkowita długość linii cumowniczej:** 3,700 metrów
*   **Maksymalne zanurzenie (Draft):** 17.0 m
*   **Pojemność symulacyjna (Max jednoczesnych statków):** 
    *   Zależna od klasy statków: ~9 statków klasy ULCV (400m) LUB ~12-14 statków mieszanych (Panamax + Feeder).

### B. DP World Antwerp Gateway (Deurganckdok - Lewy brzeg)
*   **Całkowita długość linii cumowniczej:** 2,500 metrów (plus 200 m dedykowane dla barek)
*   **Maksymalne zanurzenie (Draft):** 17.0 m
*   **Pojemność symulacyjna (Max jednoczesnych statków):** 
    *   Około 6 statków klasy ULCV LUB ~8-10 statków mieszanych.

### C. PSA Noordzee Terminal (Prawy brzeg)
*   **Całkowita długość linii cumowniczej:** 1,225 metrów
*   **Maksymalne zanurzenie (Draft):** 17.0 m
*   **Pojemność symulacyjna (Max jednoczesnych statków):** 
    *   3 statki klasy ULCV.

### D. PSA Europa Terminal (Prawy brzeg)
*   **Całkowita długość linii cumowniczej:** 1,180 metrów (uwaga: pojemność tymczasowo redukowana w fazach do 2030 r. ze względu na trwający projekt przebudowy "Emerald").
*   **Maksymalne zanurzenie (Draft):** Docelowo 16.0 m
*   **Pojemność symulacyjna (Max jednoczesnych statków):** 
    *   Max 2-3 duże statki (do klasy Neo-Panamax, port rzadziej używany dla 400-metrowych ULCV ze względu na geometrię rzeki).

### E. CSP Zeebrugge Terminal (Opcjonalnie: Terminal Nadmorski połączonego portu)
*   **Całkowita długość linii cumowniczej:** 1,200 metrów (Albert II Dock)
*   **Maksymalne zanurzenie (Draft):** 17.5 m (brak konieczności wpływania w głąb rzeki Skaldy)
*   **Pojemność symulacyjna:** 3 statki klasy ULCV.

---

## 2. REGUŁY LOGICZNE DLA SILNIKA SYMULACJI (BERTHING CONSTRAINTS)

### A. Równanie alokacji przestrzeni na nabrzeżu
Algorytm symulacyjny musi weryfikować dostępność miejsca według wzoru:
`Wolne_Miejsce_Na_Nabrzeżu = Długość_Terminala - Σ (LOA_i + Dystans_Bezpieczeństwa)`

*   **LOA (Length Over All):** Długość całkowita statku podchodzącego.
    *   *ULCV / Megamax:* 400 m
    *   *Neo-Panamax:* 336 m do 366 m
    *   *Panamax:* 250 m do 300 m
    *   *Feeder:* 120 m do 180 m
*   **Dystans bezpieczeństwa (Mooring Clearance):** W Antwerpii wymagany dystans między zacumowanymi statkami wynosi sztywno **20 do 25 metrów**. Jeśli suma długości statków i przerw między nimi przekracza długość nabrzeża, statek musi czekać na redzie (wartość `Anchorage_Waiting_Time`).

### B. Ograniczenie gęstości suwnic (Crane Density Limit)
Nawet jeśli statek o długości 400 m zmieści się na terminalu, nie można do niego przypisać dowolnej liczby z dostępnych w terminalu suwnic.
*   **Reguła w kodzie:** `Max_Suwnic_Na_Statek = FLOOR ( LOA / Dystans_Bezpieczeństwa_Suwnicy )`
*   **Wartość stała (Dystans_Bezpieczeństwa_Suwnicy):** Wynosi ok. **45 metrów** (odpowiada rozstawowi nóg suwnicy i marginesowi bezkolizyjności). 
*   *Przykład:* Do statku Panamax (250m) system nie może alokować więcej niż `FLOOR(250/45)` = 5 suwnic, nawet jeśli na terminalu MPET stoi ich 41 bezczynnie.

### C. Ograniczenie okna pływowego (Tidal Window Constraint - opcjonalnie dla rzeki Skaldy)
Terminale w Antwerpii (poza Zeebrugge) leżą w głębi lądu na rzece Skaldzie, która podlega pływom.
*   **Logika:** Jeśli `Draft_Statku > 15.0 m`, statek klasy ULCV nie może dopłynąć ani odpłynąć w dowolnym momencie. Otrzymuje w symulacji opóźnienie `Tide_Delay` (od 1 do 12 godzin), zanim dopłynie do terminala, aby zgrać się z oknem wysokiej wody (High Tide).


--

## REFERENCES
* https://thesis.eur.nl/pub/53981/Christodoulou-Ioanna.pdf
* https://www.econstor.eu/bitstream/10419/315265/1/10696_2024_Article_9515.pdf