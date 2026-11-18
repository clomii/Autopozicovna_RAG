# Motor Rent — lokálny RAG

Zadanie 3: vyhľadávanie a generovanie odpovedí nad 10 PDF a pôvodnou ontológiou
autopožičovne. Motor Rent je fiktívna požičovňa. Všetky ceny, pravidlá, osoby a
záznamy sú výučbové.

## Spustenie

1. Rozbaľ celý ZIP do zapisovateľného priečinka. Nainštaluj
   [Python 3.11 alebo novší](https://www.python.org/downloads/) a
   [Ollamu](https://ollama.com/download). Odporúčaná verzia Pythonu je 3.12.
2. Spusti Ollamu. Vo Windows/macOS beží po otvorení aplikácie na pozadí; na
   Linuxe môžeš použiť službu Ollama alebo spustiť `ollama serve` v samostatnom
   termináli, ak služba ešte nebeží.
3. V termináli raz stiahni oba modely:

       ollama pull qwen3:4b-instruct-2507-q4_K_M
       ollama pull qwen3-embedding:0.6b

   Modely spolu zaberajú približne 3,1 GB. Na ich prvé stiahnutie treba internet.
4. **Windows:** dvojklik na **Spustit_Windows.bat**. **Linux/macOS:**
   v priečinku projektu spusti `bash spustit.sh`. Vytvorí sa .venv a potrebná
   knižnica na čítanie PDF sa nainštaluje z pribaleného balíka, bez PyPI.
   Aplikácia sa otvorí na **http://127.0.0.1:8000/**. Konzolu nechaj otvorenú.
5. Pri prvom spustení sa vypočítajú vektory. Po uložení indexu ich netreba
   opakovať, kým sa nezmení korpus alebo model. Na ukončenie stlač Ctrl+C.

Na odpovedanie sa používa iba lokálny model. Aplikácia posiela otázky a výňatky
na loopback adresu Ollamy. Nepotrebuje cloudový účet ani API kľúč. Ollamu možno
spustiť s OLLAMA_NO_CLOUD=1 podľa jej dokumentácie. Samotná Ollama a váhy
modelov nie sú pribalené.

## Ukážka na obhajobu

- „Koľko stojí balík Plus na deň a aká je s ním spoluúčasť pri oprávnenom poškodení?“
  → 12 EUR/deň a 200 EUR; PDF 05, strana 1.
- „Koľko dní trvá Prenajom_002 a do akej triedy podľa dĺžky patrí?“
  → 10 dní, strednodobý; jedinec v OWL.
- „Akú dennú cenu má Auto_BMW3_01 a aká záloha sa blokuje pre jeho cenovú triedu?“
  → 95 EUR/deň podľa OWL a 700 EUR podľa PDF 03, strana 1.
- „Akú farbu má Auto_Golf_01?“ → Farba nie je v korpuse; skontroluj, či asistent
  nevymýšľa údaj. Pri obhajobe ukáž aj karty so zdrojmi.

V **Nastaveniach** sa dá prepnúť hybridné vyhľadávanie/BM25, obmedziť vyhľadávanie
na PDF alebo OWL a vypnúť formulovanie odpovede. Každá otázka sa vyhodnocuje
samostatne. Pri nedostupnom generátore sa ukážu výňatky s jasným označením.

## Súbory a testy

- **data/pdfs/**: 10 pôvodných fiktívnych dokumentov, každý má 2 strany.
- **data/ontology/**: neupravovaná ontológia z prvého zadania, verzia 1.4 (OWL/XML).
- **rag/**: extrakcia, obmedzené odvodenie z OWL, BM25, vektory, spojenie výsledkov
  a volanie lokálneho modelu.
- **web/** a **app.py**: webové rozhranie a lokálne HTTP API.
- **evaluation/questions.json**: 18 otázok s očakávanými zdrojmi a odpoveďami.
- **evaluation/results.json**: namerané výsledky na lokálnych modeloch.
- **docs/**: dokumentácia, obhajoba a manifest korpusu.
- **vendor/**: oficiálny balík pypdf 6.21.4 pre offline inštaláciu (licencia je vo wheel súbore).

Po prvom spustení spusti z koreňa projektu v termináli:

    # Windows:
    .venv\Scripts\python.exe evaluate.py --generate --output evaluation/moj_test.json
    # Linux/macOS:
    .venv/bin/python evaluate.py --generate --output evaluation/moj_test.json

Bez parametra --generate sa vyhodnotí iba vyhľadávanie. Možno pridať
--id K01 pre jednu otázku a --lexical pre vyhľadávanie bez embedding modelu.
Výsledky generovania a čas sa môžu líšiť podľa zariadenia a verzií modelov.

## Obnova indexu a riešenie problémov

- **Pridať PDF:** vlož PDF s textovou vrstvou do data/pdfs a v aplikácii otvor
  **Zdroje → Preindexovať zdroje**. Pri skene je najprv potrebné OCR.
- **Len vyhľadávanie:** skontroluj v termináli `ollama list`, či máš stiahnuté
  oba uvedené modely. Potom preindexuj zdroje.
- **Málo RAM:** po stiahnutí qwen3:1.7b môžeš pred spustením nastaviť
  RAG_CHAT_MODEL=qwen3:1.7b. Výsledky v dokumentácii platia pre qwen3:4b-instruct-2507-q4_K_M.
- **Obsadený port:** spusti `python start.py --port 8001` (na Linuxe python3).
- **Modely už pripravené a chceš režim bez internetu:** po inštalácii Ollamy
  a stiahnutí oboch modelov spusti aplikáciu bez pripojenia; pypdf je v balíku.
- **Chýba venv na Linuxe:** doinštaluj modul python3-venv podľa distribúcie.
- Predvolené API Ollamy je http://127.0.0.1:11434. Voliteľné RAG_OLLAMA_URL
  podporuje iba HTTP na loopback adrese.

Postup vychádza z [Databricks: End-to-End RAG Workflow](https://www.databricks.com/blog/rag-workflow).
Databricks je metodický zdroj, nie služba potrebná na spustenie.
