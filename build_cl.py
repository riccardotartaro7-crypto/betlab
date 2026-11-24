"""
Bet Lab - Champions League.

Chiamato da build_data.py. Restituisce il blocco "cl" di data.json.

Idea del modello:
  - La forza delle squadre viene dalla classifica Elo dei club (clubelo.com), che mette
    sulla stessa scala squadre di campionati diversi.
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
HFA_ELO = 60          # vantaggio del campo in punti Elo (in Europa e' piu' piccolo che in campionato)
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
    "Bosnia-Herzegovina": ("BIH", None, None), "Ireland": ("IRL", None, None), "Russia": ("RUS", None, None),
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
    "union saint gilloise": "union sg", "royale union saint gilloise": "union sg", "st gilloise": "union sg",
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

    # ---- 2. classifica Elo (clubelo.com)
    # Il server di ClubElo a volte e' lento: provo piu' volte (http/https, oggi/ieri) e,
    # se non risponde, uso l'ultima classifica salvata (l'Elo cambia poco da un giorno all'altro).
    elo_path = os.path.join(CACHE, "cl_elo.csv")
    text, errs = None, []
    for day, scheme in ((NOW, "http"), (NOW, "https"), (NOW - timedelta(days=1), "http")):
        try:
            t = bd.decode(bd.fetch(f"{scheme}://api.clubelo.com/{day.strftime('%Y-%m-%d')}",
                                   "clubelo.csv", timeout=45))
            if t.startswith("Rank") or "Club" in t[:60]:
                text = t
                break
            errs.append("risposta non valida")
        except Exception as e:
            errs.append(str(e)[:60])
    if text and not bd.OFFLINE:
        with open(elo_path, "w", encoding="utf-8") as f:
            f.write(text)
        ts["elo"] = bd.iso(NOW)
    elif not text and os.path.exists(elo_path) and not bd.OFFLINE:
        with open(elo_path, encoding="utf-8") as f:
            text = f.read()
        log(f"Champions: ClubElo non risponde ({errs[-1] if errs else '?'}), uso la classifica salvata "
            f"del {ts.get('elo', '?')[:10]}")
    elif not text:
        log(f"Champions: classifica Elo non disponibile ({'; '.join(errs)})")
    elo_rows = []
    for r in csv.DictReader(io.StringIO(text or "")):
        try:
            elo_rows.append((r["Club"], r["Country"], float(r["Elo"])))
        except (KeyError, ValueError, TypeError):
            pass
    if not elo_rows:
        log("Champions: senza Elo non posso calcolare le probabilita'")
        return None
    by_country = {}
    for club, ctry, elo in elo_rows:
        by_country.setdefault(ctry, {})[norm(club, bd)] = (club, elo)
    all_elo = {norm(c, bd): (c, e) for c, _, e in elo_rows}

    weak = []
    for k, t in teams.items():
        code = COUNTRY.get(t["country"] or "", (None, None, None))[0]
        variants = [norm(t["name"], bd), norm(t["full"], bd)]
        cand = by_country.get(code) or all_elo
        hit, sc = best_match(variants, cand)
        if hit is None and cand is not all_elo:
            hit, sc = best_match(variants, all_elo)
        if hit:
            t["elo"], t["elo_name"] = round(hit[1]), hit[0]
            if sc < 0.9:
                weak.append(f"{t['name']}→{hit[0]}")
        else:
            t["elo"] = None
            weak.append(f"{t['name']}→?")

    # ---- 3. campionati nazionali (football-data.co.uk): stile delle squadre
    cur = bd.season_start(NOW)
    leagues = {}
    need = {COUNTRY[t["country"]][1] for t in teams.values()
            if t["country"] in COUNTRY and COUNTRY[t["country"]][1]}
    for div in sorted(need):
        rows = []
        for season, forever in ((cur - 1, True), (cur, False)):
            code = bd.season_code(season)
            name = f"{div}_{code}.csv"
            if forever:
                text = bd.couk_csv(code, name, True, div=div)
            else:
                path = os.path.join(CACHE, name)
                text = None
                if not bd.OFFLINE and os.path.exists(path) and not due(name, DOM_REFRESH_H):
                    with open(path, encoding="utf-8") as f:
                        text = f.read()
                if text is None:
                    text = bd.couk_csv(code, name, False, div=div)
                    if text and not bd.OFFLINE:
                        with open(path, "w", encoding="utf-8") as f:
                            f.write(text)
                        ts[name] = bd.iso(NOW)
            rows += bd.parse_results(text or "", season)
        if rows:
            leagues[div] = rows

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
            weak.append(f"{t['name']}→campionato?")
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
        if H.get("elo") is None or A.get("elo") is None:
            continue
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
        log("Champions: abbinamenti da controllare: " + "; ".join(weak[:25]))
    if not bd.OFFLINE:
        bd.save_json(st_path, state)
    return dict(generated=bd.iso(NOW), t0=round(t0, 2), n_played=n_pl, hfa=HFA_ELO, c0=C0, k0=K0,
                cards_r=15.0, corners_r=40.0, rho=-0.06, teams=teams, players=players,
                fixtures=fixtures)
