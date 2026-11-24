"""
Bet Lab - Champions League.

Chiamato da build_data.py. Restituisce il blocco "cl" di data.json.

Idea del modello:
  - La forza delle squadre e' un Elo calcolato qui, partita per partita, dai risultati dei
    campionati europei (dal 2022/23) e delle coppe europee: le coppe collegano i campionati
    tra loro, cosi' squadre di paesi diversi stanno sulla stessa scala.
  - Elo -> "punti attesi" della squadra di casa -> differenza reti attesa.
  - Il totale gol atteso parte dalla media della Champions di quest'anno, corretto con
    quanto sono "da gol" le due squadre nei loro campionati.
  - Cartellini e corner: tendenze delle squadre nei loro campionati (football-data.co.uk).
  - Marcatori: quota dei gol della squadra segnata da ogni giocatore (campionato + Champions).
"""
import csv
import difflib
import io
import json
import math
import os
import re
from datetime import timedelta

# ---- parametri --------------------------------------------------------------
HFA_ELO = 60          # vantaggio del campo in punti Elo nelle partite di Champions
ELO_FIRST = 2022      # l'Elo viene calcolato dai risultati a partire dalla stagione 2022/23
ELO_K_DOM, ELO_K_EU = 20, 30
ELO_HFA_DOM, ELO_HFA_EU = 65, 50
# punto di partenza dell'Elo per paese (poi si corregge da solo con i risultati, coppe comprese)
ELO_PRIOR = {"ENG": 1700, "ESP": 1660, "ITA": 1640, "GER": 1640, "FRA": 1600, "POR": 1570, "NED": 1560,
             "BEL": 1520, "TUR": 1490, "AUT": 1490, "SCO": 1480, "SUI": 1480, "DEN": 1480, "GRE": 1480,
             "CZE": 1480, "CRO": 1470, "UKR": 1470, "NOR": 1460, "SRB": 1460, "POL": 1450, "SWE": 1440,
             "ISR": 1440, "CYP": 1440, "ROM": 1430}
MAIN_DIVS = {"E0": "ENG", "SP1": "ESP", "D1": "GER", "I1": "ITA", "F1": "FRA", "N1": "NED", "P1": "POR",
             "B1": "BEL", "SC0": "SCO", "T1": "TUR", "G1": "GRE"}
EXTRA = {"AUT": "AUT", "DNK": "DEN", "NOR": "NOR", "POL": "POL", "ROU": "ROM", "SWE": "SWE", "SWZ": "SUI"}
AF_CUPS = {2: "Champions League", 3: "Europa League", 848: "Conference League"}
T_PRIOR = 3.0         # gol a partita tipici della Champions
C0 = 4.0              # cartellini a partita tipici della Champions (stima)
K0 = 10.0             # corner a partita tipici della Champions (stima)
DAYS_AHEAD = 14
DOM_REFRESH_H = 12    # dati dei campionati nazionali: aggiorno ogni 12 ore

# paese (nome football-data.org) -> (codice ClubElo, file football-data.co.uk, campionato football-data.org)
COUNTRY = {
    "England": ("ENG", "E0", "PL"), "Spain": ("ESP", "SP1", "PD"), "Germany": ("GER", "D1", "BL1"),
    "Italy": ("ITA", "I1", "SA"), "France": ("FRA", "F1", "FL1"), "Netherlands": ("NED", "N1", "DED"),
    "Portugal": ("POR", "P1", "PPL"), "Belgium": ("BEL", "B1", None), "Scotland": ("SCO", "SC0", None),
    "Turkey": ("TUR", "T1", None), "Türkiye": ("TUR", "T1", None), "Greece": ("GRE", "G1", None),
    "Austria": ("AUT", None, None), "Switzerland": ("SUI", None, None), "Czech Republic": ("CZE", None, None),
    "Czechia": ("CZE", None, None), "Denmark": ("DEN", None, None), "Norway": ("NOR", None, None),
    "Croatia": ("CRO", None, None), "Serbia": ("SRB", None, None), "Ukraine": ("UKR", None, None),
    "Cyprus": ("CYP", None, None), "Kazakhstan": ("KAZ", None, None), "Azerbaijan": ("AZE", None, None),
    "Slovakia": ("SVK", None, None), "Hungary": ("HUN", None, None), "Poland": ("POL", None, None),
    "Sweden": ("SWE", None, None), "Israel": ("ISR", None, None), "Bulgaria": ("BUL", None, None),
    "Romania": ("ROM", None, None), "Slovenia": ("SVN", None, None), "Moldova": ("MDA", None, None),
    "Bosnia-Herzegovina": ("BIH", None, None), "Czech-Republic": ("CZE", None, None), "Ireland": ("IRL", None, None), "Russia": ("RUS", None, None),
    "Finland": ("FIN", None, None), "Iceland": ("ISL", None, None), "Georgia": ("GEO", None, None),
}
LEAGUE_NAME = {"E0": "Premier League", "SP1": "Liga", "D1": "Bundesliga", "I1": "Serie A",
               "F1": "Ligue 1", "N1": "Eredivisie", "P1": "Primeira Liga", "B1": "Pro League (BEL)",
               "SC0": "Premiership (SCO)", "T1": "Süper Lig", "G1": "Super League (GRE)"}

STOP = {"fc", "cf", "sc", "ac", "as", "ss", "ssc", "afc", "sv", "fk", "sk", "bk", "if", "ff", "club",
        "de", "del", "la", "le", "les", "futbol", "football", "calcio", "the", "cd", "ud", "sd", "rc",
        "rcd", "ca", "sl", "cp", "gnk", "hnk", "nk", "pfc", "kv", "krc", "rsc", "rb", "vfb", "vfl",
        "tsg", "fsv", "osc", "ogc", "aj", "sco", "royal", "kaa", "ksc", "kfc", "bv", "sad", "jk", "ks",
        "us", "acf", "bc", "cfc", "e", "y", "and", "of", "do", "da", "clube", "sporting clube"}
ALIAS = {
    "manchester city": "man city", "manchester united": "man united", "man utd": "man united",
    "paris saint germain": "paris sg", "psg": "paris sg", "paris": "paris sg",
    "atletico madrid": "atletico", "atletico": "atletico", "ath madrid": "atletico",
    "athletic": "bilbao", "athletic bilbao": "bilbao", "ath bilbao": "bilbao",
    "bayern munchen": "bayern", "bayern munich": "bayern", "bayern": "bayern",
    "internazionale milano": "inter", "internazionale": "inter", "inter milan": "inter",
    "milan": "milan", "borussia dortmund": "dortmund", "bayer leverkusen": "leverkusen",
    "bayer 04 leverkusen": "leverkusen", "borussia monchengladbach": "gladbach", "mgladbach": "gladbach",
    "eintracht frankfurt": "frankfurt", "ein frankfurt": "frankfurt",
    "tottenham hotspur": "tottenham", "newcastle united": "newcastle", "aston villa": "aston villa",
    "sporting": "sporting", "sporting lisbon": "sporting", "sp lisbon": "sporting", "sporting portugal": "sporting",
    "club brugge": "brugge", "brugge": "brugge", "psv eindhoven": "psv", "psv": "psv",
    "olympique marseille": "marseille", "olympique lyonnais": "lyon", "monaco": "monaco",
    "lille": "lille", "stade brestois 29": "brest", "brestois": "brest",
    "red bull salzburg": "salzburg", "fc salzburg": "salzburg",
    "feyenoord rotterdam": "feyenoord", "benfica": "benfica", "porto": "porto", "sp braga": "braga",
    "sporting braga": "braga", "olympiacos": "olympiakos", "olympiakos piraeus": "olympiakos",
    "olympiacos piraeus": "olympiakos", "kobenhavn": "kobenhavn", "copenhagen": "kobenhavn",
    "bodo glimt": "bodoe glimt", "bodoglimt": "bodoe glimt", "crvena zvezda": "crvena zvezda",
    "red star belgrade": "crvena zvezda", "shakhtar donetsk": "shakhtar", "dinamo zagreb": "dinamo zagreb",
    "union saint gilloise": "union sg", "union st gilloise": "union sg", "royale union saint gilloise": "union sg", "st gilloise": "union sg",
    "qarabag agdam": "qarabag", "kairat almaty": "kairat", "slavia praha": "slavia praha",
    "sparta praha": "sparta praha", "galatasaray": "galatasaray", "fenerbahce": "fenerbahce",
}


def norm(name, bd):
    s = re.sub(r"[^a-z0-9 ]", " ", bd.strip_accents(name or "").lower().replace("ø", "o"))
    toks = [t for t in s.split() if t not in STOP and not t.isdigit()]
    k = " ".join(toks)
    return ALIAS.get(k, k)


def best_match(names, candidates):
    """names: varianti normalizzate del nome; candidates: {nome_normalizzato: valore}."""
    best, score = None, 0.0
    for n in names:
        if not n:
            continue
        for c in candidates:
            if n == c:
                sc = 1.0
            else:
                tn, tc = set(n.split()), set(c.split())
                if tn and tc and (tn <= tc or tc <= tn):
                    sc = 0.9
                else:
                    sc = difflib.SequenceMatcher(None, n, c).ratio()
            if sc > score:
                best, score = c, sc
    return (candidates[best], score) if best is not None and score >= 0.72 else (None, score)


def poisson(l, n=10):
    out = [math.exp(-l)]
    for k in range(1, n + 1):
        out.append(out[-1] * l / k)
    return out


def exp_points(lh, la, rho=-0.06):
    ph, pa = poisson(lh), poisson(la)
    h = d = tot = 0.0
    for i in range(11):
        for j in range(11):
            tau = 1.0
            if i == 0 and j == 0:
                tau = 1 - lh * la * rho
            elif i == 0 and j == 1:
                tau = 1 + lh * rho
            elif i == 1 and j == 0:
                tau = 1 + la * rho
            elif i == 1 and j == 1:
                tau = 1 - rho
            p = max(0.0, ph[i] * pa[j] * tau)
            tot += p
            if i > j:
                h += p
            elif i == j:
                d += p
    return (h + 0.5 * d) / tot


def lambdas_from_elo(we, total):
    """Trova i gol attesi (casa, ospite) con totale 'total' e punti attesi 'we' per la casa."""
    lo, hi = -total + 0.1, total - 0.1
    for _ in range(50):
        s = (lo + hi) / 2
        if exp_points((total + s) / 2, (total - s) / 2) < we:
            lo = s
        else:
            hi = s
    s = (lo + hi) / 2
    return (total + s) / 2, (total - s) / 2


def build(bd):
    log = bd.log
    NOW = bd.NOW
    CACHE = bd.CACHE
    st_path = os.path.join(CACHE, "cl_state.json")
    state = bd.load_json(st_path, {}) if not bd.OFFLINE else {}
    ts = state.setdefault("ts", {})

    def due(name, hours):
        t = ts.get(name)
        return t is None or (NOW - bd.parse_iso(t)) > timedelta(hours=hours)

    def cached(name, hours, getter):
        """Legge dalla cache se recente, altrimenti scarica e salva."""
        path = os.path.join(CACHE, "cl_" + name)
        data = None if bd.OFFLINE else bd.load_json(path, None)
        if data is None or due(name, hours):
            got = getter()
            if got is not None:
                data = got
                ts[name] = bd.iso(NOW)
                if not bd.OFFLINE:
                    bd.save_json(path, data)
        return data

    # ---- 1. partite e squadre della Champions (football-data.org)
    fd = bd.fd_get("/competitions/CL/matches", "fd_cl_matches.json")
    if not fd:
        log("Champions: calendario non disponibile (football-data.org)")
        return None
    teams_fd = cached("teams.json", 24, lambda: bd.fd_get("/competitions/CL/teams", "fd_cl_teams.json"))
    area = {}
    for t in (teams_fd or {}).get("teams", []):
        area[t["id"]] = (t.get("area") or {}).get("name")

    teams = {}

    def team_of(tj):
        k = f"t{tj['id']}"
        if k not in teams:
            teams[k] = dict(id=tj["id"], name=tj.get("shortName") or tj.get("name") or "?",
                            full=tj.get("name") or "", tla=tj.get("tla"),
                            country=area.get(tj["id"]))
        return k

    played, upcoming = [], []
    for m in fd.get("matches", []):
        if not m["homeTeam"].get("id") or not m["awayTeam"].get("id"):
            continue      # turni a eliminazione con squadre non ancora note
        h, a = team_of(m["homeTeam"]), team_of(m["awayTeam"])
        dt = bd.parse_iso(m["utcDate"])
        ft = (m.get("score") or {}).get("fullTime") or {}
        if m.get("status") == "FINISHED" and ft.get("home") is not None:
            played.append(dict(date=dt, home=h, away=a, hg=ft["home"], ag=ft["away"]))
        elif m.get("status") in ("SCHEDULED", "TIMED", "IN_PLAY", "PAUSED") and \
                NOW - timedelta(hours=3) <= dt <= NOW + timedelta(days=DAYS_AHEAD):
            upcoming.append(dict(id=f"cl{m['id']}", date=dt, home=h, away=a,
                                 stage=m.get("stage"), md=m.get("matchday"),
                                 ref=bd.ref_from_fd(m)))

    # ---- 2. risultati: campionati (football-data.co.uk) + coppe europee -> Elo calcolato qui
    cur = bd.season_start(NOW)

    def ccode(country):
        c = (country or "").replace("-", " ").strip()
        hit = COUNTRY.get(c) or COUNTRY.get((country or "").strip())
        return hit[0] if hit else c.upper()[:3]

    # 2a. campionati principali: stagioni passate salvate per sempre, quella in corso riscaricata
    leagues = {}          # div -> partite con statistiche (stagione scorsa + in corso)
    elo_matches = []      # (data, paese, nome casa, nome ospite, gol casa, gol ospite, "dom"/"eu", div)
    for div, code in MAIN_DIVS.items():
        rows_style = []
        for season in range(ELO_FIRST, cur + 1):
            sc = bd.season_code(season)
            text = bd.couk_csv(sc, f"{div}_{sc}.csv", season < cur, div=div)
            rows = bd.parse_results(text or "", season)
            for m in rows:
                elo_matches.append((m["date"], code, m["home_name"], m["away_name"], m["hg"], m["ag"], "dom", div))
            if season >= cur - 1:
                rows_style += rows
        if rows_style:
            leagues[div] = rows_style

    # 2b. altri campionati (Austria, Svizzera, Danimarca...): solo risultati, file unico per paese
    for fname, code in EXTRA.items():
        def get_extra(f=fname):
            try:
                text = bd.decode(bd.fetch(f"https://www.football-data.co.uk/new/{f}.csv", f"{f}.csv"))
            except Exception as e:
                log(f"Champions: campionato {f} non scaricato ({str(e)[:50]})")
                return None
            out = []
            for r in csv.DictReader(io.StringIO(text)):
                try:
                    y = int((r.get("Season") or "")[:4])
                except ValueError:
                    continue
                hg, ag = bd.num(r.get("HG") or r.get("FTHG")), bd.num(r.get("AG") or r.get("FTAG"))
                dt = bd.parse_uk_dt(r.get("Date"), r.get("Time"))
                if y < ELO_FIRST or hg is None or ag is None or dt is None:
                    continue
                out.append([bd.iso(dt), r.get("Home") or r.get("HomeTeam"), r.get("Away") or r.get("AwayTeam"),
                            int(hg), int(ag)])
            return out
        for d, h, a, hg, ag in (cached(f"extra_{fname}.json", 24, get_extra) or []):
            elo_matches.append((bd.parse_iso(d), code, h, a, hg, ag, "dom", fname))

    # 2c. coppe europee 2022-2024 (piano gratuito di API-Football): collegano i campionati tra loro
    af = bd.ApiFootball()
    n_cup = 0
    if af.enabled:
        for lg in AF_CUPS:
            for season in range(ELO_FIRST, ELO_FIRST + 3):
                def get_teams(lg=lg, season=season):
                    got = af.get(f"/teams?league={lg}&season={season}", f"af_teams_{lg}_{season}.json")
                    return None if got is None else {str(x["team"]["id"]): [x["team"]["name"], x["team"].get("country")]
                                                     for x in got}
                def get_fx(lg=lg, season=season):
                    got = af.get(f"/fixtures?league={lg}&season={season}", f"af_cup_{lg}_{season}.json")
                    if got is None:
                        return None
                    out = []
                    for fx in got:
                        if (fx["fixture"].get("status") or {}).get("short") not in ("FT", "AET", "PEN"):
                            continue
                        ft = (fx.get("score") or {}).get("fulltime") or {}
                        hg = ft.get("home") if ft.get("home") is not None else (fx.get("goals") or {}).get("home")
                        ag = ft.get("away") if ft.get("away") is not None else (fx.get("goals") or {}).get("away")
                        if hg is None or ag is None:
                            continue
                        out.append([fx["fixture"]["date"], str(fx["teams"]["home"]["id"]),
                                    str(fx["teams"]["away"]["id"]), hg, ag])
                    return out
                tmap = cached(f"af_teams_{lg}_{season}.json", 24 * 3650, get_teams) or {}
                fxs = cached(f"af_cup_{lg}_{season}.json", 24 * 3650, get_fx) or []
                for d, h, a, hg, ag in fxs:
                    if h in tmap and a in tmap:
                        elo_matches.append((bd.parse_iso(d), (ccode(tmap[h][1]), ccode(tmap[a][1])),
                                            tmap[h][0], tmap[a][0], hg, ag, "eu", lg))
                        n_cup += 1
        af.save()
    # 2d. Champions in corso (football-data.org)
    for m in played:
        H, A = teams[m["home"]], teams[m["away"]]
        elo_matches.append((m["date"], (ccode(H["country"]), ccode(A["country"])),
                            (H["name"], H["full"]), (A["name"], A["full"]), m["hg"], m["ag"], "eu", "CL"))

    # 2e. identita' delle squadre: stesso paese + nome simile = stessa squadra
    reg = {}

    def ident(code, names):
        names = names if isinstance(names, tuple) else (names,)
        r = reg.setdefault(code, {})
        variants = [norm(n, bd) for n in names if n]
        for v in variants:
            if v in r:
                return r[v]
        hit, sc = best_match(variants, r)
        if hit and sc >= 0.8:
            for v in variants:
                r[v] = hit
            return hit
        new_id = f"{code}:{variants[0] if variants else '?'}"
        for v in variants:
            r[v] = new_id
        return new_id

    # prima i campionati (nomi "di casa"), poi le coppe
    elo_matches.sort(key=lambda x: (x[6] != "dom", x[0]))
    resolved = []
    for d, code, h, a, hg, ag, kind, comp in elo_matches:
        ch, ca = (code if isinstance(code, tuple) else (code, code))
        resolved.append((d, ident(ch, h), ident(ca, a), hg, ag, kind, comp, ch, ca))
    resolved.sort(key=lambda x: x[0])

    # 2f. calcolo dell'Elo, partita per partita in ordine di data
    rating, n_games, league_teams = {}, {}, {}
    for d, h, a, hg, ag, kind, comp, ch, ca in resolved:
        for tid, code in ((h, ch), (a, ca)):
            if tid not in rating:
                mates = [rating[x] for x in league_teams.get(comp, ()) if x in rating] if kind == "dom" else []
                if len(mates) >= 8:
                    rating[tid] = sum(mates) / len(mates) - 75        # neopromossa
                else:
                    rating[tid] = ELO_PRIOR.get(code, 1400) - (0 if kind == "dom" else 50)
                n_games[tid] = 0
            if kind == "dom":
                league_teams.setdefault(comp, set()).add(tid)
        hfa = ELO_HFA_DOM if kind == "dom" else ELO_HFA_EU
        k = ELO_K_DOM if kind == "dom" else ELO_K_EU
        we = 1 / (1 + 10 ** (-(rating[h] + hfa - rating[a]) / 400))
        w = 1.0 if hg > ag else (0.5 if hg == ag else 0.0)
        gd = abs(hg - ag)
        g = 1.0 if gd <= 1 else (1.5 if gd == 2 else (11 + gd) / 8)
        delta = k * g * (w - we)
        rating[h] += delta
        rating[a] -= delta
        n_games[h] += 1
        n_games[a] += 1

    weak = []
    for k, t in teams.items():
        tid = ident(ccode(t["country"]), (t["name"], t["full"]))
        t["elo_n"] = n_games.get(tid, 0)
        if tid in rating and n_games[tid] >= 3:
            t["elo"] = round(rating[tid])
        else:
            t["elo"] = round(rating.get(tid, ELO_PRIOR.get(ccode(t["country"]), 1400) - 50))
            weak.append(f"{t['name']} (Elo stimato: poche partite)")
    log(f"Champions: Elo calcolato su {len(resolved)} partite ({n_cup} di coppe europee 2022-24)")

    # ---- 3. stile delle squadre nei loro campionati (cartellini, corner, gol)
    def rel(ms, key, hcol, acol):
        """Medie della squadra 'key' rispetto alla media del campionato (1 = nella media)."""
        ms2 = [m for m in ms if m[hcol] is not None]
        if not ms2:
            return None
        avg = sum(m[hcol] + m[acol] for m in ms2) / (2 * len(ms2))
        f = a = w = 0.0
        for m in ms2:
            ww = 0.5 ** (max(0.0, (NOW - m["date"]).days) / 150)
            if m["home"] == key:
                f += ww * m[hcol]; a += ww * m[acol]; w += ww
            elif m["away"] == key:
                f += ww * m[acol]; a += ww * m[hcol]; w += ww
        if not w or not avg:
            return None
        k = 4.0
        return ((f + k * avg) / (w + k) / avg, (a + k * avg) / (w + k) / avg, w)

    for k, t in teams.items():
        c = COUNTRY.get(t["country"] or "")
        t["league"] = LEAGUE_NAME.get(c[1]) if c and c[1] else None
        t.update(gf=1.0, cf=1.0, ca=1.0, kf=1.0, ka=1.0, st=None, form=[], dom=False)
        if not c or c[1] not in leagues:
            continue
        ms = leagues[c[1]]
        names = {}
        for m in ms:
            names[norm(m["home_name"], bd)] = m["home"]
            names[norm(m["away_name"], bd)] = m["away"]
        key, sc = best_match([norm(t["name"], bd), norm(t["full"], bd)], names)
        if not key:
            weak.append(f"{t['name']} (campionato non trovato)")
            continue
        for m in ms:
            if m["hy"] is not None:
                m["hcard"] = m["hy"] + (m["hr"] or 0)
                m["acard"] = m["ay"] + (m["ar"] or 0)
            else:
                m["hcard"] = m["acard"] = None
        g = rel(ms, key, "hg", "ag")
        cards = rel(ms, key, "hcard", "acard")
        corners = rel(ms, key, "hc", "ac")
        if g:
            t["gf"] = round((g[0] + g[1]) / 2, 3)   # quanto sono "da gol" le sue partite
        if cards:
            t["cf"], t["ca"] = round(cards[0], 3), round(cards[1], 3)
        if corners:
            t["kf"], t["ka"] = round(corners[0], 3), round(corners[1], 3)
        cur_ms = [m for m in ms if m["season"] == cur]
        st, form = bd.team_season_stats(cur_ms or ms, key)
        t["st"], t["form"], t["dom"] = st, form, True

    # forma in Champions
    for k, t in teams.items():
        f = []
        for m in sorted(played, key=lambda x: x["date"]):
            if k in (m["home"], m["away"]):
                home = m["home"] == k
                gf, ga = (m["hg"], m["ag"]) if home else (m["ag"], m["hg"])
                opp = teams[m["away"] if home else m["home"]]["name"]
                f.append(dict(r="V" if gf > ga else ("N" if gf == ga else "P"), s=f"{gf}-{ga}",
                              o=opp, h=home, d=m["date"].strftime("%d/%m")))
        t["cl_form"] = f[-6:][::-1]

    # ---- 4. marcatori: campionato (football-data.org) + Champions
    dom_codes = {COUNTRY[t["country"]][2] for t in teams.values()
                 if t["country"] in COUNTRY and COUNTRY[t["country"]][2]}
    team_goals = {k: 0.0 for k in teams}
    pgoals = {}

    def add_player(tk, pname, goals, pens):
        key = bd.surname_key(pname)
        p = pgoals.setdefault((tk, key), dict(name=pname, key=key, g=0, pen=0, gd=0, gc=0))
        p["g"] += goals
        p["pen"] += pens
        if len(pname) > len(p["name"]):
            p["name"] = pname
        return p

    fd_ids = {t["id"]: k for k, t in teams.items()}
    for code in sorted(dom_codes):
        table = cached(f"{code}_standings.json", DOM_REFRESH_H,
                       lambda c=code: bd.fd_get(f"/competitions/{c}/standings", f"fd_{c}_standings.json"))
        for grp in (table or {}).get("standings", []):
            if grp.get("type") != "TOTAL":
                continue
            for row in grp.get("table", []):
                tk = fd_ids.get(row["team"]["id"])
                if tk:
                    team_goals[tk] += row.get("goalsFor") or 0
        sc = cached(f"{code}_scorers.json", DOM_REFRESH_H,
                    lambda c=code: bd.fd_get(f"/competitions/{c}/scorers?limit=100", f"fd_{c}_scorers.json"))
        for s in (sc or {}).get("scorers", []):
            tk = fd_ids.get(s["team"]["id"])
            if tk:
                p = add_player(tk, s["player"]["name"], s.get("goals") or 0, s.get("penalties") or 0)
                p["gd"] += s.get("goals") or 0
    for m in played:
        team_goals[m["home"]] += m["hg"]
        team_goals[m["away"]] += m["ag"]
    clsc = cached("scorers.json", 6, lambda: bd.fd_get("/competitions/CL/scorers?limit=100",
                                                         "fd_cl_scorers.json"))
    for s in (clsc or {}).get("scorers", []):
        tk = fd_ids.get(s["team"]["id"])
        if tk:
            p = add_player(tk, s["player"]["name"], s.get("goals") or 0, s.get("penalties") or 0)
            p["gc"] += s.get("goals") or 0
    players = {}
    for (tk, _), p in pgoals.items():
        tg = team_goals.get(tk) or 0
        share = (p["g"] + 3 * 0.05) / (tg + 3) if tg else 0.05
        players.setdefault(tk, []).append(dict(name=p["name"], key=p["key"], g=p["g"], gd=p["gd"],
                                               gc=p["gc"], pen=p["pen"], share=round(min(share, 0.6), 4)))
    for tk in players:
        players[tk].sort(key=lambda x: -x["share"])
        players[tk] = players[tk][:12]

    # ---- 5. modello per ogni partita
    n_pl = len(played)
    avg_goals = sum(m["hg"] + m["ag"] for m in played) / n_pl if n_pl else T_PRIOR
    t0 = (avg_goals * n_pl + T_PRIOR * 30) / (n_pl + 30)
    fixtures = []
    for u in sorted(upcoming, key=lambda x: x["date"]):
        H, A = teams[u["home"]], teams[u["away"]]
        hfa = 0 if (u["stage"] or "").upper() == "FINAL" else HFA_ELO
        we = 1 / (1 + 10 ** (-(H["elo"] + hfa - A["elo"]) / 400))
        total = t0 * max(0.8, min(1.25, math.sqrt(H["gf"] * A["gf"])))
        lh, la = lambdas_from_elo(we, total)
        fixtures.append(dict(
            id=u["id"], comp="CL", date=bd.iso(u["date"]), home=u["home"], away=u["away"],
            stage=u["stage"], md=u["md"], ref_name=(u["ref"] or "").split(",")[0].strip() or None,
            model=dict(lh=round(lh, 3), la=round(la, 3),
                       ch=round(C0 * 0.47 * H["cf"] * A["ca"], 3), ca=round(C0 * 0.53 * A["cf"] * H["ca"], 3),
                       kh=round(K0 * 0.54 * H["kf"] * A["ka"], 3), ka=round(K0 * 0.46 * A["kf"] * H["ka"], 3),
                       we=round(we, 3)),
            odds=None, lineups=None, injuries=None))

    if weak:
        log("Champions: da controllare: " + "; ".join(weak[:25]))
    if not bd.OFFLINE:
        bd.save_json(st_path, state)
    return dict(generated=bd.iso(NOW), t0=round(t0, 2), n_played=n_pl, hfa=HFA_ELO, c0=C0, k0=K0,
                cards_r=15.0, corners_r=40.0, rho=-0.06, teams=teams, players=players,
                fixtures=fixtures)
