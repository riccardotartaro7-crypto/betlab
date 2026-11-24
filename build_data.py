#!/usr/bin/env python3
"""
Bet Lab Serie A - raccolta dati.

Scarica i dati di Serie A da fonti GRATUITE e crea data.json,
che l'app sul telefono legge per calcolare le probabilita'.

Fonti:
  - football-data.co.uk  CSV gratuiti: risultati, tiri, falli, corner,
                         cartellini e quote dei bookmaker. Nessuna chiave.
  - football-data.org    Partite in programma, arbitri, classifica marcatori.
                         Chiave gratuita -> variabile FOOTBALL_DATA_TOKEN
  - API-Football         FACOLTATIVA: arbitro designato, formazioni ufficiali,
                         indisponibili. Chiave gratuita -> API_FOOTBALL_KEY

Usa solo la libreria standard di Python (niente pip install).
"""
import csv
import io
import json
import math
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.abspath(__file__))   # tutti i file stanno nella cartella principale
OUT = os.path.join(ROOT, "data.json")
CACHE = os.path.join(ROOT, "cache")

FD_TOKEN = os.environ.get("FOOTBALL_DATA_TOKEN", "").strip()
AF_KEY = os.environ.get("API_FOOTBALL_KEY", "").strip()
OFFLINE = os.environ.get("OFFLINE_DIR")          # solo per i test
NOW = (datetime.fromisoformat(os.environ["NOW_ISO"]) if os.environ.get("NOW_ISO")
       else datetime.now(timezone.utc))

# ---- parametri del modello -------------------------------------------------
HALF_LIFE_DAYS = 150   # una partita di 150 giorni fa pesa la meta' di una di oggi
K_TEAM = 3.0           # "partite fittizie nella media" per non esagerare con pochi dati
K_REF = 6.0            # idem per gli arbitri (in "partite di peso pieno")
REF_HALF_LIFE_DAYS = 730  # per gli arbitri lo storico vecchio conta di piu': stile stabile
K_PLAYER = 2.0         # idem per i marcatori
PLAYER_PRIOR_GPM = 0.04
AF_DAILY_LIMIT = 90    # il piano gratuito di API-Football ne da' 100 al giorno
AF_LEAGUE = 135        # Serie A su API-Football
DAYS_AHEAD = 10        # quanti giorni di partite in programma mostrare

UK = ZoneInfo("Europe/London")
status = []            # messaggi mostrati nell'app (in fondo alla pagina)


def log(msg):
    print(msg, file=sys.stderr)
    status.append(msg)


# ---- utilita' --------------------------------------------------------------
def fetch(url, name, headers=None, timeout=40):
    """Scarica un URL. Nei test (OFFLINE_DIR) legge invece OFFLINE_DIR/name."""
    if OFFLINE:
        path = os.path.join(OFFLINE, name)
        if not os.path.exists(path):
            raise FileNotFoundError(name)
        with open(path, "rb") as f:
            return f.read()
    h = {"User-Agent": "Mozilla/5.0 (BetLab uso personale)"}
    h.update(headers or {})
    with urlopen(Request(url, headers=h), timeout=timeout) as r:
        return r.read()


def decode(b):
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            pass
    return b.decode("utf-8", "ignore")


def strip_accents(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()


TEAM_STOP = {"fc", "ac", "as", "ss", "ssc", "us", "acf", "bc", "cfc", "calcio",
             "club", "sc", "fbc", "uc", "hellas", "ssd", "srl", "spa"}
TEAM_ALIAS = {
    "internazionale milano": "inter", "internazionale": "inter",
    "inter milan": "inter", "inter milano": "inter",
    "milan ac": "milan", "roma as": "roma",
}


def team_key(name):
    n = re.sub(r"[^a-z0-9 ]", " ", strip_accents(name).lower())
    toks = [t for t in n.split() if t not in TEAM_STOP and not t.isdigit()]
    k = " ".join(toks)
    return TEAM_ALIAS.get(k, k)


def surname_key(name):
    """'D. Doveri, Italy' -> 'doveri'; 'Lautaro Martínez' -> 'martinez'."""
    name = (name or "").split(",")[0]
    toks = re.sub(r"[^a-z ]", " ", strip_accents(name).lower()).split()
    return toks[-1] if toks else ""


def num(v):
    try:
        return float(v) if v not in ("", None) else None
    except ValueError:
        return None


def season_start(d):
    return d.year if d.month >= 7 else d.year - 1


def season_code(start):
    return f"{start % 100:02d}{(start + 1) % 100:02d}"


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def parse_uk_dt(date_s, time_s):
    d = None
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            d = datetime.strptime((date_s or "").strip(), fmt)
            break
        except ValueError:
            pass
    if d is None:
        return None
    hh, mm = 15, 0
    if time_s and ":" in time_s:
        hh, mm = [int(x) for x in time_s.split(":")[:2]]
    return d.replace(hour=hh, minute=mm, tzinfo=UK).astimezone(timezone.utc)


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


# ---- 1. football-data.co.uk ------------------------------------------------
def couk_csv(code, name, cache_forever=False):
    cache_path = os.path.join(CACHE, name)
    if cache_forever and os.path.exists(cache_path) and not OFFLINE:
        with open(cache_path, encoding="utf-8") as f:
            return f.read()
    try:
        url = (f"https://www.football-data.co.uk/mmz4281/{code}/I1.csv" if code
               else "https://www.football-data.co.uk/fixtures.csv")
        text = decode(fetch(url, name))
        if cache_forever and not OFFLINE:
            os.makedirs(CACHE, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(text)
        return text
    except (HTTPError, URLError, OSError, TimeoutError) as e:
        log(f"football-data.co.uk: impossibile scaricare {name} ({e})")
        return ""


def parse_results(text, season):
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        if not r.get("HomeTeam") or num(r.get("FTHG")) is None:
            continue
        dt = parse_uk_dt(r.get("Date"), r.get("Time"))
        if dt is None:
            continue
        g = lambda c: num(r.get(c))
        rows.append(dict(
            season=season, date=dt,
            home=team_key(r["HomeTeam"]), away=team_key(r["AwayTeam"]),
            home_name=r["HomeTeam"].strip(), away_name=r["AwayTeam"].strip(),
            hg=int(g("FTHG")), ag=int(g("FTAG")),
            hs=g("HS"), as_=g("AS"), hst=g("HST"), ast=g("AST"),
            hf=g("HF"), af=g("AF"), hc=g("HC"), ac=g("AC"),
            hy=g("HY"), ay=g("AY"), hr=g("HR"), ar=g("AR"), ref=None))
    return rows


def first(r, cols):
    for c in cols:
        v = num(r.get(c))
        if v and v > 1:
            return v
    return None


def parse_odds(text):
    """Quote delle prossime partite di Serie A (fixtures.csv)."""
    odds = {}
    for r in csv.DictReader(io.StringIO(text)):
        if (r.get("Div") or "").strip() != "I1" or not r.get("HomeTeam"):
            continue
        key = (team_key(r["HomeTeam"]), team_key(r["AwayTeam"]))
        odds[key] = dict(
            h=first(r, ["AvgH", "B365H", "PSH", "MaxH"]),
            d=first(r, ["AvgD", "B365D", "PSD", "MaxD"]),
            a=first(r, ["AvgA", "B365A", "PSA", "MaxA"]),
            o25=first(r, ["Avg>2.5", "B365>2.5", "P>2.5", "Max>2.5"]),
            u25=first(r, ["Avg<2.5", "B365<2.5", "P<2.5", "Max<2.5"]),
            date=parse_uk_dt(r.get("Date"), r.get("Time")),
            home_name=r["HomeTeam"].strip(), away_name=r["AwayTeam"].strip())
    return odds


# ---- 2. football-data.org --------------------------------------------------
def fd_get(path, name):
    if not FD_TOKEN and not OFFLINE:
        return None
    try:
        b = fetch("https://api.football-data.org/v4" + path, name,
                  {"X-Auth-Token": FD_TOKEN})
        return json.loads(b)
    except (HTTPError, URLError, OSError, ValueError, TimeoutError) as e:
        log(f"football-data.org: errore su {path} ({e})")
        return None


def ref_from_fd(m):
    for r in m.get("referees") or []:
        if (r.get("type") or "REFEREE") == "REFEREE" and r.get("name"):
            return r["name"]
    return None


# ---- 3. API-Football (facoltativa) -----------------------------------------
class ApiFootball:
    """Usa al massimo AF_DAILY_LIMIT richieste al giorno, salvando tutto in cache/."""

    def __init__(self):
        self.state_path = os.path.join(CACHE, "af_state.json")
        self.st = load_json(self.state_path, {})
        today = NOW.strftime("%Y-%m-%d")
        if self.st.get("day") != today:
            self.st["day"], self.st["used"] = today, 0
        self.st.setdefault("ts", {})
        self.st.setdefault("lineups", {})
        self.st.setdefault("injuries", {})
        self.st.setdefault("bad_seasons", {})
        self.enabled = bool(AF_KEY) or bool(OFFLINE and os.environ.get("AF_TEST"))
        self.last_error = None

    def due(self, name, hours):
        t = self.st["ts"].get(name)
        return t is None or (NOW - parse_iso(t)) > timedelta(hours=hours)

    def get(self, path, name):
        self.last_error = None
        if not self.enabled:
            return None
        if self.st["used"] >= AF_DAILY_LIMIT:
            log("API-Football: limite giornaliero raggiunto, riprovo domani")
            return None
        self.st["used"] += 1
        try:
            b = fetch("https://v3.football.api-sports.io" + path, name,
                      {"x-apisports-key": AF_KEY})
            data = json.loads(b)
        except (HTTPError, URLError, OSError, ValueError, TimeoutError) as e:
            self.last_error = str(e)
            log(f"API-Football: errore su {path} ({e})")
            return None
        errs = data.get("errors")
        if errs:
            msg = "; ".join(f"{v}" for v in (errs.values() if isinstance(errs, dict) else errs))
            self.last_error = msg
            if not self.season_error():
                log(f"API-Football: {msg}")
            return None
        return data.get("response") or []

    def season_error(self):
        e = (self.last_error or "").lower()
        return "season" in e or "plan" in e

    def save(self):
        if not OFFLINE:
            save_json(self.state_path, self.st)


# ---- 4. modello: forza squadre, cartellini, corner, arbitri ----------------
def weight(dt):
    age = max(0.0, (NOW - dt).total_seconds() / 86400)
    return 0.5 ** (age / HALF_LIFE_DAYS)


def wmean(pairs):
    sw = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / sw if sw else None


def build_ratings(matches, teams):
    """
    Forza d'attacco e di difesa di ogni squadra (1.00 = media della Serie A).
    Si usa una "misura gol" = 60% gol veri + 40% tiri in porta x conversione media:
    riduce la fortuna (e' un sostituto gratuito degli xG).
    Le medie sono corrette per la forza degli avversari (10 iterazioni).
    """
    tot_g = sum(m["hg"] + m["ag"] for m in matches if m["hst"] is not None)
    tot_sot = sum(m["hst"] + m["ast"] for m in matches if m["hst"] is not None)
    conv = tot_g / tot_sot if tot_sot else None

    def gm(goals, sot):
        if conv is None or sot is None:
            return goals
        return 0.6 * goals + 0.4 * sot * conv

    for m in matches:
        m["w"] = weight(m["date"])
        m["gm_h"] = gm(m["hg"], m["hst"])
        m["gm_a"] = gm(m["ag"], m["ast"])
    mu_h = wmean([(m["gm_h"], m["w"]) for m in matches]) or 1.45
    mu_a = wmean([(m["gm_a"], m["w"]) for m in matches]) or 1.15

    att = {t: 1.0 for t in teams}
    de = {t: 1.0 for t in teams}
    for _ in range(10):
        n_att = {t: [0.0, 0.0] for t in teams}
        n_def = {t: [0.0, 0.0] for t in teams}
        for m in matches:
            h, a, w = m["home"], m["away"], m["w"]
            if h in teams:
                n_att[h][0] += w * m["gm_h"] / (mu_h * de.get(a, 1.0))
                n_att[h][1] += w
                n_def[h][0] += w * m["gm_a"] / (mu_a * att.get(a, 1.0))
                n_def[h][1] += w
            if a in teams:
                n_att[a][0] += w * m["gm_a"] / (mu_a * de.get(h, 1.0))
                n_att[a][1] += w
                n_def[a][0] += w * m["gm_h"] / (mu_h * att.get(h, 1.0))
                n_def[a][1] += w
        att = {t: (s + K_TEAM) / (n + K_TEAM) for t, (s, n) in n_att.items()}
        de = {t: (s + K_TEAM) / (n + K_TEAM) for t, (s, n) in n_def.items()}
        ma, md = sum(att.values()) / len(att), sum(de.values()) / len(de)
        att = {t: v / ma for t, v in att.items()}
        de = {t: v / md for t, v in de.items()}

    # pareggi: correzione di Dixon-Coles fissa (valore tipico per la Serie A)
    return dict(mu_h=mu_h, mu_a=mu_a, att=att, de=de, conv=conv, rho=-0.08)


def ratio_rates(matches, teams, hcol, acol):
    """
    Per una statistica (es. cartellini): quanto una squadra ne PRENDE rispetto alla
    media ('for') e quanto ne fa prendere agli avversari ('against').
    """
    ms = [m for m in matches if m[hcol] is not None and m[acol] is not None]
    if not ms:
        return None
    bh = wmean([(m[hcol], m["w"]) for m in ms])
    ba = wmean([(m[acol], m["w"]) for m in ms])
    acc = {t: {"f": [0.0, 0.0], "a": [0.0, 0.0]} for t in teams}
    for m in ms:
        h, a, w = m["home"], m["away"], m["w"]
        if h in acc:
            acc[h]["f"][0] += w * (m[hcol] / bh if bh else 1)
            acc[h]["a"][0] += w * (m[acol] / ba if ba else 1)
            acc[h]["f"][1] += w
            acc[h]["a"][1] += w
        if a in acc:
            acc[a]["f"][0] += w * (m[acol] / ba if ba else 1)
            acc[a]["a"][0] += w * (m[hcol] / bh if bh else 1)
            acc[a]["f"][1] += w
            acc[a]["a"][1] += w
    out = {t: dict(f=(v["f"][0] + K_TEAM) / (v["f"][1] + K_TEAM),
                   a=(v["a"][0] + K_TEAM) / (v["a"][1] + K_TEAM)) for t, v in acc.items()}
    return dict(base_h=bh, base_a=ba, teams=out)


def nb_dispersion(values):
    """Parametro r della binomiale negativa (i cartellini sono 'piu' variabili' di Poisson)."""
    n = len(values)
    if n < 20:
        return 15.0
    m = sum(values) / n
    v = sum((x - m) ** 2 for x in values) / (n - 1)
    if v <= m * 1.02:
        return 60.0
    return max(3.0, min(60.0, m * m / (v - m)))


def build_referees(by_season, cur):
    """
    Per ogni arbitro: cartellini a gara divisi per la media della Serie A in quella stagione
    (cosi' stagioni con piu' o meno cartellini sono confrontabili). Le stagioni recenti pesano
    di piu'. Con poche partite il valore viene avvicinato a 1 (= arbitro nella media).
    """
    refs = {}
    for season, ms in by_season.items():
        tot = [m["hy"] + m["ay"] + (m["hr"] or 0) + (m["ar"] or 0) for m in ms if m["hy"] is not None]
        if not tot:
            continue
        savg = sum(tot) / len(tot)
        for m in ms:
            if not m.get("ref") or m["hy"] is None:
                continue
            c = m["hy"] + m["ay"] + (m["hr"] or 0) + (m["ar"] or 0)
            w = 0.5 ** (max(0.0, (NOW - m["date"]).total_seconds() / 86400) / REF_HALF_LIFE_DAYS)
            k = surname_key(m["ref"])
            nm = m["ref"].split(",")[0].strip()
            r = refs.setdefault(k, dict(name=nm, n=0, n_cur=0, cards=0.0, cards_cur=0.0, yel=0.0,
                                        red=0.0, fouls=0.0, nf=0, hw=0, sw=0.0, rel=0.0, last=None))
            if len(nm) > len(r["name"]):
                r["name"] = nm
            r["n"] += 1
            r["cards"] += c
            r["yel"] += m["hy"] + m["ay"]
            r["red"] += (m["hr"] or 0) + (m["ar"] or 0)
            r["sw"] += w
            r["rel"] += w * c / savg if savg else w
            if season == cur:
                r["n_cur"] += 1
                r["cards_cur"] += c
            if m["hf"] is not None:
                r["fouls"] += m["hf"] + m["af"]
                r["nf"] += 1
            r["hw"] += 1 if m["hg"] > m["ag"] else 0
            d = m["date"].strftime("%Y-%m-%d")
            r["last"] = max(r["last"] or d, d)
    out = {}
    for k, r in refs.items():
        n = r["n"]
        out[k] = dict(name=r["name"], n=n, n_cur=r["n_cur"],
                      cards=round(r["cards"] / n, 2),
                      cards_cur=round(r["cards_cur"] / r["n_cur"], 2) if r["n_cur"] else None,
                      yel=round(r["yel"] / n, 2), red=round(r["red"] / n, 2),
                      fouls=round(r["fouls"] / r["nf"], 1) if r["nf"] else None,
                      home_win=round(r["hw"] / n, 2),
                      factor=round((r["rel"] + K_REF) / (r["sw"] + K_REF), 3),
                      last=r["last"])
    return out


def team_season_stats(matches, t):
    ms = sorted([m for m in matches if t in (m["home"], m["away"])], key=lambda m: m["date"])
    if not ms:
        return None, []
    agg = dict(gf=0, ga=0, s=0.0, sa=0.0, sot=0.0, sota=0.0, f=0.0, c=0.0, ca=0.0, cards=0.0,
               ns=0, pts=0)
    form = []
    for m in ms:
        home = m["home"] == t
        gf, ga = (m["hg"], m["ag"]) if home else (m["ag"], m["hg"])
        agg["gf"] += gf
        agg["ga"] += ga
        res = "V" if gf > ga else ("N" if gf == ga else "P")
        agg["pts"] += 3 if res == "V" else (1 if res == "N" else 0)
        opp = m["away_name"] if home else m["home_name"]
        form.append(dict(r=res, s=f"{gf}-{ga}", o=opp, h=home, d=m["date"].strftime("%d/%m")))
        if m["hs"] is not None and m["hy"] is not None:
            agg["ns"] += 1
            agg["s"] += m["hs"] if home else m["as_"]
            agg["sa"] += m["as_"] if home else m["hs"]
            agg["sot"] += m["hst"] if home else m["ast"]
            agg["sota"] += m["ast"] if home else m["hst"]
            agg["f"] += m["hf"] if home else m["af"]
            agg["c"] += m["hc"] if home else m["ac"]
            agg["ca"] += m["ac"] if home else m["hc"]
            agg["cards"] += ((m["hy"] + (m["hr"] or 0)) if home else (m["ay"] + (m["ar"] or 0)))
    n, ns = len(ms), agg["ns"]
    r1 = lambda x: round(x, 2)
    st = dict(pj=n, pts=agg["pts"], gf=agg["gf"], ga=agg["ga"],
              gfpm=r1(agg["gf"] / n), gapm=r1(agg["ga"] / n))
    if ns:
        st.update(spm=r1(agg["s"] / ns), sapm=r1(agg["sa"] / ns), sotpm=r1(agg["sot"] / ns),
                  sotapm=r1(agg["sota"] / ns), fpm=r1(agg["f"] / ns), cpm=r1(agg["c"] / ns),
                  capm=r1(agg["ca"] / ns), cardpm=r1(agg["cards"] / ns))
    return st, form[-5:][::-1]


# ---- main -------------------------------------------------------------------
def main():
    cur = season_start(NOW)
    prev = cur - 1
    log_start = f"Aggiornamento {iso(NOW)} - stagione {cur}/{cur + 1}"
    print(log_start, file=sys.stderr)

    # --- risultati e statistiche (football-data.co.uk)
    m_prev = parse_results(couk_csv(season_code(prev), f"I1_{season_code(prev)}.csv", True), prev)
    m_cur = parse_results(couk_csv(season_code(cur), f"I1_{season_code(cur)}.csv"), cur)
    odds = parse_odds(couk_csv(None, "fixtures.csv"))
    names = {}
    for m in m_prev + m_cur:
        names.setdefault(m["home"], m["home_name"])
        names.setdefault(m["away"], m["away_name"])

    # --- partite, arbitri e marcatori (football-data.org)
    fd = fd_get("/competitions/SA/matches", "fd_matches.json")
    upcoming = []
    fd_ref = {}
    cur_keys = {(m["home"], m["away"]) for m in m_cur}
    if fd:
        for m in fd.get("matches", []):
            hn = m["homeTeam"].get("shortName") or m["homeTeam"].get("name") or ""
            an = m["awayTeam"].get("shortName") or m["awayTeam"].get("name") or ""
            h, a = team_key(hn), team_key(an)
            names.setdefault(h, hn)
            names.setdefault(a, an)
            dt = parse_iso(m["utcDate"])
            ref = ref_from_fd(m)
            if ref:
                fd_ref[(h, a)] = ref
            ft = (m.get("score") or {}).get("fullTime") or {}
            if m.get("status") == "FINISHED" and ft.get("home") is not None:
                if (h, a) not in cur_keys:   # risultato non ancora nel CSV: aggiungo solo i gol
                    m_cur.append(dict(season=cur, date=dt, home=h, away=a, home_name=hn,
                                      away_name=an, hg=ft["home"], ag=ft["away"],
                                      hs=None, as_=None, hst=None, ast=None, hf=None, af=None,
                                      hc=None, ac=None, hy=None, ay=None, hr=None, ar=None,
                                      ref=ref))
            elif m.get("status") in ("SCHEDULED", "TIMED", "POSTPONED") and \
                    NOW - timedelta(hours=3) <= dt <= NOW + timedelta(days=DAYS_AHEAD):
                upcoming.append(dict(id=f"fd{m['id']}", date=dt, home=h, away=a,
                                     matchday=m.get("matchday"), ref=ref,
                                     postponed=m.get("status") == "POSTPONED"))
    else:
        log("football-data.org non disponibile: uso il calendario di football-data.co.uk")

    if not upcoming:
        for (h, a), o in odds.items():
            if o["date"] and NOW - timedelta(hours=3) <= o["date"] <= NOW + timedelta(days=DAYS_AHEAD):
                names.setdefault(h, o["home_name"])
                names.setdefault(a, o["away_name"])
                upcoming.append(dict(id=f"uk{h}-{a}", date=o["date"], home=h, away=a,
                                     matchday=None, ref=None, postponed=False))

    for m in m_cur:
        if not m.get("ref"):
            m["ref"] = fd_ref.get((m["home"], m["away"]))

    # --- API-Football (facoltativa)
    # Piano gratuito: di solito NON copre la stagione in corso, ma copre alcune stagioni
    # passate. Da quelle prendo l'arbitro di ogni partita -> storico arbitri di piu' anni.
    af = ApiFootball()
    af_fx = {}            # (home, away) stagione in corso -> {id, ref}
    lineups, injuries = {}, {}
    hist = {}             # stagione -> partite (con cartellini) usate solo per gli arbitri
    af_cur_ok = False
    if af.enabled:
        bad = af.st["bad_seasons"]
        for season in range(cur, cur - 5, -1):
            name = f"af_fixtures_{season}.json"
            cpath = os.path.join(CACHE, name)
            b = bad.get(str(season))
            if b and NOW - parse_iso(b) < timedelta(days=7):
                continue          # stagione non coperta dal piano: riprovo tra una settimana
            data = None if OFFLINE else load_json(cpath, None)
            hours = 24 if season == cur else (24 * 30 if season == prev else 24 * 3650)
            if data is None or af.due(name, hours):
                got = af.get(f"/fixtures?league={AF_LEAGUE}&season={season}", name)
                if got is not None:
                    data = [dict(id=fx["fixture"]["id"],
                                 h=team_key(fx["teams"]["home"]["name"]),
                                 a=team_key(fx["teams"]["away"]["name"]),
                                 ref=(fx["fixture"].get("referee") or "").strip() or None)
                            for fx in got]
                    af.st["ts"][name] = iso(NOW)
                    bad.pop(str(season), None)
                    if not OFFLINE:
                        save_json(cpath, data)
                elif af.season_error():
                    bad[str(season)] = iso(NOW)
            if not data:
                continue
            refmap = {(f["h"], f["a"]): f["ref"] for f in data if f.get("ref")}
            if season == cur:
                af_cur_ok = True
                af_fx = {(f["h"], f["a"]): f for f in data}
                target = m_cur
            elif season == prev:
                target = m_prev
            else:
                code = season_code(season)
                target = parse_results(couk_csv(code, f"I1_{code}.csv", True), season)
                hist[season] = target
            for m in target:
                if not m.get("ref") and (m["home"], m["away"]) in refmap:
                    m["ref"] = refmap[(m["home"], m["away"])]

        if af_cur_ok:
            # formazioni (da 90 minuti prima del calcio d'inizio) e indisponibili (ogni 6 ore)
            for u in upcoming:
                fx = af_fx.get((u["home"], u["away"]))
                if not fx:
                    continue
                fid = str(fx["id"])
                u["af_id"] = fid
                if not u.get("ref") and fx.get("ref"):
                    u["ref"] = fx["ref"]
                mins = (u["date"] - NOW).total_seconds() / 60
                if -150 < mins < 90 and not af.st["lineups"].get(fid):
                    got = af.get(f"/fixtures/lineups?fixture={fid}", f"af_lineups_{fid}.json")
                    if got:
                        af.st["lineups"][fid] = got
                if 0 < mins < 72 * 60 and af.due(f"inj{fid}", 6):
                    got = af.get(f"/injuries?fixture={fid}", f"af_injuries_{fid}.json")
                    if got is not None:
                        af.st["injuries"][fid] = [
                            dict(t=team_key(i["team"]["name"]), p=i["player"]["name"],
                                 why=i["player"].get("reason") or "", ty=i["player"].get("type") or "")
                            for i in got]
                        af.st["ts"][f"inj{fid}"] = iso(NOW)
                if af.st["lineups"].get(fid):
                    lu = {}
                    for side in af.st["lineups"][fid]:
                        tk = team_key(side["team"]["name"])
                        lu[tk] = dict(
                            formation=side.get("formation"),
                            xi=[surname_key(p["player"]["name"]) for p in side.get("startXI", [])],
                            bench=[surname_key(p["player"]["name"]) for p in side.get("substitutes", [])],
                            xi_names=[p["player"]["name"] for p in side.get("startXI", [])])
                    lineups[u["id"]] = lu
                if af.st["injuries"].get(fid):
                    injuries[u["id"]] = af.st["injuries"][fid]
            keep = {u.get("af_id") for u in upcoming}
            af.st["lineups"] = {k: v for k, v in af.st["lineups"].items() if k in keep}
            af.st["injuries"] = {k: v for k, v in af.st["injuries"].items() if k in keep}
        else:
            log("API-Football: il piano gratuito non copre la stagione in corso -> "
                "formazioni e indisponibili vanno segnati a mano nell'app")
        af.save()
    n_hist = sum(1 for ms in hist.values() for m in ms if m.get("ref"))
    if n_hist:
        log(f"Storico arbitri: aggiunte {n_hist} partite delle stagioni "
            + ", ".join(f"{s}/{str(s + 1)[-2:]}" for s in sorted(hist)))

    # --- calcoli
    matches = m_prev + m_cur
    if not matches:
        log("Nessun risultato disponibile: impossibile calcolare il modello")
    teams = {m["home"] for m in m_cur} | {m["away"] for m in m_cur}
    teams |= {u["home"] for u in upcoming} | {u["away"] for u in upcoming}
    if not teams:
        teams = {m["home"] for m in m_prev} | {m["away"] for m in m_prev}
    rt = build_ratings(matches, teams)

    for m in matches:
        if m["hy"] is not None:
            m["hcard"] = m["hy"] + (m["hr"] or 0)
            m["acard"] = m["ay"] + (m["ar"] or 0)
        else:
            m["hcard"] = m["acard"] = None
    cards = ratio_rates(matches, teams, "hcard", "acard")
    corners = ratio_rates(matches, teams, "hc", "ac")
    card_totals = [m["hcard"] + m["acard"] for m in matches if m["hcard"] is not None]
    corner_totals = [m["hc"] + m["ac"] for m in matches if m["hc"] is not None]
    league_cards = (sum(card_totals) / len(card_totals)) if card_totals else 4.5
    by_season = {prev: m_prev, cur: m_cur}
    by_season.update(hist)
    referees = build_referees(by_season, cur)

    # --- marcatori
    players = {}
    sc = fd_get("/competitions/SA/scorers?limit=150", "fd_scorers.json")
    for s in (sc or {}).get("scorers", []):
        tn = s["team"].get("shortName") or s["team"].get("name") or ""
        tk = team_key(tn)
        played = s.get("playedMatches") or 0
        goals = s.get("goals") or 0
        if played <= 0:
            continue
        gpm = (goals + K_PLAYER * PLAYER_PRIOR_GPM) / (played + K_PLAYER)
        players.setdefault(tk, []).append(dict(
            name=s["player"]["name"], key=surname_key(s["player"]["name"]),
            g=goals, pen=s.get("penalties") or 0, a=s.get("assists") or 0,
            pj=played, gpm=round(gpm, 4)))
    for tk in players:
        players[tk].sort(key=lambda p: -p["gpm"])
    if not players:
        log("Classifica marcatori non disponibile (serve FOOTBALL_DATA_TOKEN)")

    # --- squadre
    out_teams = {}
    for t in sorted(teams):
        st, form = team_season_stats(m_cur, t)
        if st is None:   # neopromossa a inizio stagione: uso la stagione scorsa se c'e'
            st, form = team_season_stats(m_prev, t)
        out_teams[t] = dict(
            name=names.get(t, t.title()),
            att=round(rt["att"].get(t, 1.0), 3), de=round(rt["de"].get(t, 1.0), 3),
            cf=round(cards["teams"][t]["f"], 3) if cards else 1.0,
            ca=round(cards["teams"][t]["a"], 3) if cards else 1.0,
            kf=round(corners["teams"][t]["f"], 3) if corners else 1.0,
            ka=round(corners["teams"][t]["a"], 3) if corners else 1.0,
            st=st, form=form)

    fixtures = []
    for u in sorted(upcoming, key=lambda x: x["date"]):
        o = odds.get((u["home"], u["away"])) or {}
        rk = surname_key(u["ref"]) if u.get("ref") else None
        fixtures.append(dict(
            id=u["id"], date=iso(u["date"]), home=u["home"], away=u["away"],
            md=u.get("matchday"), postponed=u.get("postponed", False),
            ref=rk, ref_name=(u["ref"] or "").split(",")[0].strip() or None,
            odds={k: o.get(k) for k in ("h", "d", "a", "o25", "u25")} if o else None,
            lineups=lineups.get(u["id"]), injuries=injuries.get(u["id"])))

    data = dict(
        generated=iso(NOW), season=f"{cur}/{str(cur + 1)[-2:]}",
        league=dict(
            mu_h=round(rt["mu_h"], 3), mu_a=round(rt["mu_a"], 3), rho=rt["rho"],
            cards_h=round(cards["base_h"], 3) if cards else 2.2,
            cards_a=round(cards["base_a"], 3) if cards else 2.4,
            cards_total=round(league_cards, 3),
            cards_r=round(nb_dispersion(card_totals), 2),
            corners_h=round(corners["base_h"], 3) if corners else 5.3,
            corners_a=round(corners["base_a"], 3) if corners else 4.3,
            corners_r=round(nb_dispersion(corner_totals), 2),
            n_matches=len(matches), n_cur=len(m_cur)),
        teams=out_teams, referees=referees, fixtures=fixtures, players=players,
        sources=dict(couk=bool(m_cur or m_prev), fd=bool(fd), scorers=bool(players),
                     af=af_cur_ok, ref_hist=sorted(hist), odds=bool(odds)),
        status=status)
    save_json(OUT, data)
    print(f"OK: {len(fixtures)} partite, {len(out_teams)} squadre, {len(referees)} arbitri, "
          f"{sum(len(v) for v in players.values())} marcatori -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
