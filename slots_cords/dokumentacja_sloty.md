# Dokumentacja i Opis Pól Pliku GeoJSON – Stanowiska Portowe (Ligplaatsen)
**Źródło danych:** Port of Antwerp-Bruges (ArcGIS REST Service – LIGPL Layer 10)  
**Układ współrzędnych:** WGS84 (EPSG:4326 – standardowe współrzędne GPS)

---

## 1. Ogólna struktura pliku GeoJSON

Plik opiera się na standardzie **GeoJSON (RFC 7946)**. Głównym obiektem jest `FeatureCollection`, która zawiera listę wszystkich obiektów (`features`), reprezentujących poszczególne stanowiska i sloty na nabrzeżu.

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": 1,
      "geometry": { ... },
      "properties": { ... }
    }
  ]
}
```

---

## 2. Geometria obiektu (`geometry`)

Sekcja `geometry` definiuje kształt przestrzenny danego stanowiska portowego na mapie.

* **`type`**: Typ geometrii. W tym przypadku zawsze **`"Polygon"`** (wielokąt/obrys). Oznacza to, że każdy slot nie jest tylko pojedynczym punktem, lecz pełnym obszarem (boxem/prostokątem) wyznaczającym dokładne granice wody lub nabrzeża.
* **`coordinates`**: Tablica współrzędnych geograficznych tworzących zamknięty obrys slota.
  * Zapis punktu: **`[Długość Geograficzna (Lng), Szerokość Geograficzna (Lat)]`**
  * *Przykład:* `[4.4039546871703665, 51.253719325601352]`
    * `4.40395...` = Długość geograficzna E (East) – okolice Antwerpii
    * `51.25371...` = Szerokość geograficzna N (North)

> **Uwaga:** Pierwszy i ostatni punkt w tablicy `coordinates` są identyczne – domykają one pętlę wielokąta.

---

## 3. Atrybuty i Metadane (`properties`)

W sekcji `properties` znajdują się biznesowe i techniczne dane o danym stanowisku.

| Pole | Typ danych | Opis i Znaczenie | Przykład |
| :--- | :--- | :--- | :--- |
| **`OBJECTID`** | Liczba (*Integer*) | Unikalny identyfikator rekordu w wewnętrznej bazie GIS Portu Antwerpia. Służy do sortowania i paginacji. | `1` |
| **`LPL`** | Tekst (*String*) | Skrót od *Ligplaats* (stanowisko/miejsce przytwierdzenia). Numer slotu/stanowiska używany oficjalnie w nawigacji portowej. | `"128"`, `"1301"` |
| **`NUMMER`** | Tekst (*String*) | Numer stanowiska (w większości przypadków tożsamy z polem `LPL`). | `"128"` |
| **`LPL_UN`** | Tekst (*String*) | **Unikalny Identyfikator Globalny (Unique ID)**. Łączy kod portu i numer stanowiska. Idealny jako klucz główny (Primary Key) w własnej bazie danych. | `"ANTW_128"` |
| **`FILIAAL`** | Tekst (*String*) | Kod oddziału/portu. Pozwala rozróżnić obiekty w skonsolidowanym porcie Antwerpia-Brugia: <br>• `"ANTW"` = Port w Antwerpii<br>• `"ZEE"` = Port w Zeebrugge | `"ANTW"` |
| **`TERMINAL`** | Tekst / `null` | Numer lub identyfikator terminalu przeładunkowego, w obrębie którego znajduje się dane stanowisko. Jeśli slot leży poza terenem prywatnego terminalu, przyjmuje wartość `null`. | `"131"`, `null` |
| **`HOEK`** | Liczba (*Float*) | Kąt nachylenia / orientacja stanowiska na mapie (w stopniach względem północy). Używany przez systemy graficzne do obracania etykiet z numerami slotów na mapie. | `-0.3711`, `-89.13` |
| **`TYPE`** | Liczba (*Integer*) | Kod klasyfikacji typu stanowiska (np. nabrzeże komercyjne, miejsce postojowe, strefa oczekiwania). | `1` |
| **`ISRS`** | Tekst / `null` | **ISRS Location Code** (International River Information Services Location Code). Międzynarodowy kod stosowany w systemach AIS/RIS do identyfikacji punktów nawigacyjnych. <br>• `BE` = Belgia<br>• `ANR` = Port Antwerpia | `"BEANR01712L012800012"` |
| **`RELATED_ISRS`** | Tekst / `null` | Powiązany kod ISRS (np. kod nadrzędnego basenu portowego, terminalu lub toru wodnego). | `"BEANR017120013100024"` |
| **`LPL_VOLGEND`** | Tekst / `null` | Numer kolejnego sąsiadującego stanowiska w ciągu nabrzeża (używane do budowania łańcuchów slotów). | `null` |
| **`POSITIE_VOLGEND`** | Tekst / `null` | Relacja pozycji względem następnego stanowiska. | `null` |

---

## 4. Jak wykorzystać te dane w praktyce?

1. **Wyszukiwanie po numerze stanowiska:**  
   Najlepiej filtrować obiekty po polu **`LPL_UN`** (np. `ANTW_128`) lub **`LPL`** (np. `128`).
2. **Wyznaczenie prostokąta granicznego (Bounding Box):**  
   Aby uzyskać skrajne punkty geograficzne danego slota, wystarczy wyciągnąć minimalną i maksymalną długość oraz szerokość geograficzną z tablicy `coordinates`:
   * `min_lng` = najmniejsza wartość $X$
   * `min_lat` = najmniejsza wartość $Y$
   * `max_lng` = największa wartość $X$
   * `max_lat` = największa wartość $Y$
3. **Integracja z AIS/VTS:**  
   Pole **`ISRS`** umożliwia bezpośrednie łączenie obrysów ze strumieniem danych o ruchu statków (systemy VTS/RIS w Europie).