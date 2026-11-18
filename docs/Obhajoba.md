# Hovorená obhajoba: Motor Rent

## 0:00 - 0:35  /  Cieľ

Spravil som lokálneho asistenta pre fiktívnu autopožičovňu Motor Rent. Odpovedá na otázky o podmienkach, cenách a konkrétnych prenájmoch. Znalostnú bázu tvorí desať textových PDF a pôvodná ontológia autopožičovne z prvého zadania. Po stiahnutí modelov beží celé spracovanie na jednom počítači.

## 0:35 - 1:15  /  Ako funguje RAG

Podľa článku Databricks som oddelil prípravu zdrojov od odpovedania. Najprv načítam stránky PDF a prevediem OWL na výňatky so zachovanými identifikátormi. Každý výňatok uložím s metadátami a vektorom. Pri otázke spojím vyhľadávanie podľa slov BM25 s kosínusovou podobnosťou vektorov. Prvé tri nájdené úryvky pridám k otázke. Model následne odpovie z kontextu a ku tvrdeniam priradí citácie.

## 1:15 - 1:55  /  Načo je ontológia

Ontológiu používam ako zdroj faktov. Napríklad Prenajom_002 má hodnotu pocetDni desať a väzby na auto aj pobočky. Z intervalu v ekvivalentnej definícii sa dá odvodiť, že ide o strednodobý prenájom. Pôvodný súbor ostal nezmenený. Aplikácia používa vybranú časť pravidiel tohto modelu; úplné logické usudzovanie by robil OWL reasoner.

## 1:55 - 3:25  /  Ukážka na obrazovke

Otvorím web a ukážem zoznam zdrojov. Spýtam sa na balík Plus, potom na Prenajom_002. Nakoniec spojím dennú cenu BMW z ontológie so zálohou z cenníka. Pri odpovedi otvorím citáciu a ukážem presnú stranu alebo identifikátor. Pri otázke bez zdroja ukážem, ako vyzerá odmietnutie odpovede.

## 3:25 - 4:10  /  Vyhodnotenie

Pripravil som osemnásť otázok. Pri pätnástich som vopred označil potrebné stránky alebo jedincov. Zvlášť som zmeral, či ich vyhľadávač našiel, a zvlášť, či model uviedol potrebné údaje aj citácie. Pri troch otázkach bez podkladu som sledoval, či systém odpoveď odmietne. Skóre platí pre tento korpus. Výhodou je možnosť skontrolovať zdroj, lebo ani lokálny model nemusí vždy odpovedať správne.

**Výsledok:** 14/15 doložených otázok prešlo automatickou kontrolou údajov a citácií. Pri otázkach bez podkladu prešli 2/3.
