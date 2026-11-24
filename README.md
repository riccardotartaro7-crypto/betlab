# Bet Lab · Serie A

App personale per il telefono che stima le probabilità degli eventi nelle partite di Serie A:

- esito 1X2, doppia chance, over/under, goal/no goal, risultati esatti
- cartellini, tenendo conto dell'arbitro designato e del clima della partita
- calci d'angolo
- marcatori, con le formazioni ufficiali quando escono
- forma recente e stile di gioco delle squadre
- confronto con le quote dei bookmaker, con il "valore" evidenziato
- pulsante che copia l'analisi da incollare in Claude, così puoi aggiungere le notizie dell'ultima ora

Costo: **0 €**.

---

## Come funziona

**1. Ogni ora GitHub (gratis) esegue `scripts/build_data.py`**

Lo script scarica i dati dalle fonti gratuite e calcola gli indici delle squadre. Poi salva tutto in `docs/data.json`.

**2. L'app (`docs/index.html`) è pubblicata gratis su GitHub Pages**

Sul telefono la installi come un'app normale. Legge `data.json` e calcola le probabilità direttamente sul telefono.

In questo modo puoi cambiare arbitro, clima della partita e giocatori assenti, e i numeri si aggiornano subito.

**Fonti dei dati**

| Fonte | Cosa dà | Chiave |
|---|---|---|
| football-data.co.uk | risultati, tiri, falli, corner, cartellini, quote (2 stagioni) | nessuna |
| football-data.org | calendario, arbitri, classifica marcatori | gratuita, obbligatoria |
| API-Football | arbitro designato, formazioni ufficiali, indisponibili | gratuita, facoltativa |

---

## Il modello, in breve

**Gol**

Usa la distribuzione di Poisson con la correzione di Dixon-Coles per i pareggi.

I gol attesi di una squadra si calcolano così:

gol attesi casa = media gol in casa della Serie A × attacco squadra di casa × difesa squadra ospite

L'attacco e la difesa misurano quanto una squadra segna e subisce rispetto alla media del campionato (1.00 = nella media).

Per calcolarli usa una "misura gol": 60% gol veri + 40% tiri in porta. In questo modo si riduce il peso della fortuna, come fanno gli xG.

Le partite recenti contano di più: una partita di 150 giorni fa pesa la metà di una di oggi. I valori sono anche corretti in base alla forza degli avversari affrontati.

**Cartellini**

cartellini attesi = media Serie A × quanti ne prende la squadra × quanti ne fa prendere l'avversario × effetto arbitro × clima della partita

Per la probabilità usa la binomiale negativa. Serve perché i cartellini variano più di quanto preveda la Poisson.

**Arbitro**

L'effetto arbitro confronta la sua media di cartellini a partita con la media della Serie A.

Se ha arbitrato poche partite, il suo valore viene avvicinato alla media del campionato, per non fidarsi troppo di pochi dati.

**Marcatori**

probabilità che segni = 1 − e^(−λ)

λ = gol a partita del giocatore × (gol attesi oggi dalla squadra / gol che la squadra segna di solito) × minuti previsti

I minuti previsti dipendono da cosa scegli: titolare, probabile, panchina o fuori.

Se segni fuori un giocatore importante, si abbassano anche i gol attesi della sua squadra.

**Valore**

valore = probabilità del modello × quota − 1

Se il risultato supera +3%, l'app lo evidenzia.

> Le probabilità sono stime: i bookmaker usano modelli più sofisticati e in più ci mettono il loro margine.
> Usa l'app per ragionare, non come una garanzia.

---

## Installazione (circa 20 minuti, una volta sola)

### 1. Prendi le chiavi gratuite

- **football-data.org**: vai su https://www.football-data.org/client/register e registrati. Il token ti arriva per email.
- **API-Football** (facoltativa): vai su https://dashboard.api-football.com e registrati. Non serve la carta di credito. La chiave è nella dashboard.

### 2. Crea il repository su GitHub

1. Registrati su https://github.com
2. In alto a destra premi **+** e poi **New repository**
3. Come nome scrivi `betlab`, scegli **Public** e premi **Create repository**

Il repository deve essere pubblico: GitHub Pages gratis funziona solo così. Le tue chiavi invece restano segrete.

### 3. Carica i file

1. Nel repository premi **uploading an existing file**
2. Trascina le cartelle `docs`, `scripts` e `cache` e il file `README.md`
3. Premi **Commit changes**

La cartella `.github` di solito è nascosta, quindi va creata a mano:

1. Premi **Add file** e poi **Create new file**
2. Come nome scrivi esattamente `.github/workflows/aggiorna.yml`
3. Incolla dentro il contenuto del file `aggiorna.yml`
4. Premi **Commit changes**

### 4. Inserisci le chiavi

1. Vai su **Settings**, poi **Secrets and variables**, poi **Actions**
2. Premi **New repository secret**
3. Aggiungi questi due segreti:
   - nome `FOOTBALL_DATA_TOKEN`, come valore il token di football-data.org
   - nome `API_FOOTBALL_KEY`, come valore la chiave di API-Football (se ce l'hai)

### 5. Attiva la pubblicazione dell'app

1. Vai su **Settings** e poi **Pages**
2. In **Source** scegli **Deploy from a branch**
3. Come branch scegli `main`, come cartella `/docs`, poi premi **Save**

### 6. Primo aggiornamento dei dati

1. Apri la scheda **Actions** e, se te lo chiede, abilita i workflow
2. A sinistra apri **Aggiorna dati**
3. Premi **Run workflow** e poi di nuovo **Run workflow**
4. Dopo circa un minuto deve comparire la spunta verde

Da quel momento i dati si aggiornano da soli ogni ora.

Se il passaggio "Salva" fallisce:

1. Vai su **Settings**, poi **Actions**, poi **General**
2. In **Workflow permissions** scegli **Read and write permissions**

### 7. Installa l'app sul telefono

Apri questo indirizzo: `https://TUO-NOME-UTENTE.github.io/betlab/`

- **iPhone (Safari)**: tasto Condividi, poi **Aggiungi alla schermata Home**
- **Android (Chrome)**: menu ⋮, poi **Installa app**

---

## Limiti noti

- **Piano gratuito di API-Football**: potrebbe non coprire la stagione in corso.

  Se succede, lo vedi nel "Registro aggiornamento" in fondo all'app.

  In quel caso formazioni e indisponibili li segni a mano con i pulsanti Tit / Prob / Pan / Out, per esempio guardando SOS Fanta. Il resto funziona lo stesso.

- **Marcatori**: compaiono solo i giocatori che hanno già segnato in campionato.

- **football-data.co.uk**: aggiorna i risultati un paio di volte a settimana. I gol delle partite più recenti arrivano comunque da football-data.org.

- **Arbitri**: i numeri sono affidabili solo per gli arbitri che hanno diretto abbastanza partite. Con pochi dati l'effetto viene ridotto in automatico.

## Test in locale (facoltativo)

```
python3 test/make_fake_data.py /tmp/fake
OFFLINE_DIR=/tmp/fake AF_TEST=1 NOW_ISO=2026-11-14T10:45:00+00:00 python3 scripts/build_data.py
cd docs && python3 -m http.server 8000     # poi apri http://localhost:8000
```
