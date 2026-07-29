#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Veille logement etudiant Nantes — collecte des annonces et generation de index.html.
Tourne sur GitHub Actions (voir .github/workflows/update.yml).
Sources collectees : PAP, ImmoJeune, ResidenceEtudiante.fr.
Chaque source est independante : si l'une echoue, les autres continuent et la page se genere quand meme.
"""

import re
import html
import datetime
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,image/apng,*/*;q=0.8"),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Referer": "https://www.google.com/",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-User": "?1",
    "Sec-CH-UA": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"Windows"',
}

PAP_URL = "https://www.pap.fr/annonce/locations-meuble-nantes-44-g43619-jusqu-a-650-euros-a-partir-de-20-m2"
IMMOJEUNE_URL = "https://www.immojeune.com/logement-etudiant/nantes-44.html"
RESIDENCE_URL = "https://www.residenceetudiante.fr/location-etudiant-nantes.html"
LOCATIONETU_URL = "https://www.location-etudiant.fr/residences-etudiantes-nantes.html"
MAX_PRICE = 650


def esc(s):
    return html.escape(str(s or ""), quote=True)


SESSION = requests.Session()


def fetch(url, tries=3):
    last = None
    for _ in range(tries):
        try:
            r = SESSION.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            return r.text
        except Exception as e:
            last = e
    raise last


def first_int(pattern, text):
    m = re.search(pattern, text)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------- PAP (particuliers)
def scrape_pap():
    out = []
    try:
        page = fetch(PAP_URL)
    except Exception as e:
        print("[PAP] echec:", e)
        return out
    soup = BeautifulSoup(page, "html.parser")
    seen = set()
    anchors = soup.find_all("a", href=re.compile(r"/annonces/[a-z]+-nantes[\w-]*-r\d+"))
    print(f"[PAP] {len(anchors)} liens d'annonces trouves")
    for a in anchors:
        href = a.get("href", "")
        rid_m = re.search(r"-r(\d+)", href)
        if not rid_m:
            continue
        rid = rid_m.group(1)
        if rid in seen:
            continue
        seen.add(rid)
        url = href if href.startswith("http") else "https://www.pap.fr" + href
        # remonter jusqu'a un conteneur qui porte le texte de l'annonce
        cont = a
        for _ in range(5):
            if cont.parent is not None:
                cont = cont.parent
            if cont.get_text(" ", strip=True).count("€") == 1:
                break
        txt = cont.get_text(" ", strip=True)
        price = first_int(r"([\d][\d\s ]{1,6})\s*€", txt)
        if price:
            price = int(re.sub(r"[\s ]", "", str(price)))
        surf = first_int(r"(\d{1,3})\s*m", txt)
        if not price or price > MAX_PRICE:
            continue
        coloc = "colocation" in href
        if coloc:
            kind = "coloc"
            title = "Chambre en colocation" + (f" · {surf} m²" if surf else "")
            dtype = f"chambre en colocation" + (f" ({surf} m²)" if surf else "")
        else:
            kind = "pap"
            if surf and surf < 24 or re.search(r"studio", txt, re.I):
                t = "Studio"
            elif re.search(r"2\s*pi", txt, re.I):
                t = "T2"
            else:
                t = "Logement"
            title = t + (f" · {surf} m²" if surf else "")
            dtype = t.lower() + (f" ({surf} m²)" if surf else "")
        out.append({
            "id": "pap-r" + rid, "kind": kind, "url": url,
            "price": f"{price} €", "title": title, "spot": "Nantes (44000)",
            "src": "PAP · particulier", "dtype": dtype, "dq": "Nantes", "dm": f"{price} € CC",
        })
    print(f"[PAP] {len(out)} annonces retenues (<= {MAX_PRICE} €)")
    return out[:24]


# ------------------------------------------------- Residences etudiantes (plusieurs sources)
def name_from_url(url):
    """Deduit un nom lisible depuis l'URL de la residence (fiable, pas de texte de lien foireux)."""
    seg = url.rstrip("/").split("/")[-1]
    seg = re.sub(r"\.html?$", "", seg)
    seg = re.sub(r"[_-]\d+$", "", seg)          # id de fin (_7428)
    words = [w for w in re.split(r"[-_]+", seg) if w]
    drop = {"residence", "residences", "etudiante", "etudiant", "etudiants",
            "location", "logement", "logements", "la", "le", "les", "de", "du",
            "des", "a", "nantes", "44"}
    kept = [w for w in words if w.lower() not in drop] or words
    name = " ".join(w.capitalize() for w in kept)
    return name[:46] or "Résidence étudiante"


def _scrape_res(url, src, href_pat, base):
    out = []
    try:
        soup = BeautifulSoup(fetch(url), "html.parser")
    except Exception as e:
        print(f"[{src}] echec:", e)
        return out
    seen = set()
    for a in soup.find_all("a", href=re.compile(href_pat)):
        href = a.get("href", "")
        full = href if href.startswith("http") else base + href
        if full in seen:
            continue
        # remonter jusqu'a trouver un prix dans le conteneur de la carte
        cont, price, surf = a, None, None
        for _ in range(5):
            if cont.parent is not None:
                cont = cont.parent
            txt = cont.get_text(" ", strip=True)
            pm = re.search(r"(\d{3,4})\s*€", txt)
            if pm:
                price = int(pm.group(1))
                sm = re.search(r"(\d{1,3})\s*m", txt)
                surf = int(sm.group(1)) if sm else None
                break
        if not price or price > MAX_PRICE:
            continue
        seen.add(full)
        nm = name_from_url(full)
        out.append({
            "id": "res-" + re.sub(r"\W+", "-", (src[:3] + nm).lower())[:36],
            "kind": "res", "url": full, "price": f"dès {price} €",
            "title": nm + (f" · {surf} m²" if surf else ""), "spot": "Nantes", "src": src,
            "dtype": (f"studio/T1 {surf} m²" if surf else "studio/T1"),
            "dq": "Nantes", "dm": f"dès {price} €",
        })
    print(f"[{src}] {len(out)} retenues")
    return out


def scrape_residences():
    raw = []
    raw += _scrape_res(RESIDENCE_URL, "ResidenceEtudiante.fr", r"/residence/", "https://www.residenceetudiante.fr")
    raw += _scrape_res(IMMOJEUNE_URL, "ImmoJeune", r"/residence-etudiante/", "https://www.immojeune.com")
    raw += _scrape_res(LOCATIONETU_URL, "Location-Etudiant.fr", r"residence-etudiante", "https://www.location-etudiant.fr")
    uniq = {}
    for d in raw:
        uniq.setdefault(d["title"].lower(), d)   # dedoublonnage par nom
    res = list(uniq.values())[:18]
    print(f"[Residences] total {len(res)}")
    return res


def card(d):
    cls = "ad" + (" res" if d["kind"] == "res" else " coloc" if d["kind"] == "coloc" else "")
    label = "Voir la résidence ↗" if d["kind"] == "res" else "Voir ↗"
    return (
        f'<div class="{cls}" data-id="{esc(d["id"])}" data-kind="{esc(d["kind"])}" '
        f'data-type="{esc(d["dtype"])}" data-quartier="{esc(d["dq"])}" data-montant="{esc(d["dm"])}">'
        f'<span class="stbadge"></span>'
        f'<div class="price">{esc(d["price"])}<small> CC</small></div>'
        f'<div class="type">{esc(d["title"])}</div>'
        f'<div class="spot">{esc(d["spot"])}</div>'
        f'<span class="src">{esc(d["src"])}</span>'
        f'<div class="actions">'
        f'<a class="go" href="{esc(d["url"])}" target="_blank" rel="noopener">{label}</a>'
        f'<button class="act msg" onclick="copyMsg(this)">Message</button>'
        f'<button class="act" data-s="lu" onclick="setStatus(this)">Lu</button>'
        f'<button class="act" data-s="envoye" onclick="setStatus(this)">Envoyé</button>'
        f'<button class="act" data-s="non" onclick="setStatus(this)">Non</button>'
        f'</div></div>'
    )


def section(cards_html, count):
    if not cards_html:
        return ('<div class="empty">Aucune annonce collectée sur cette source pour le moment '
                '(la source peut bloquer temporairement). Voir la section « Chercher plus & alertes ».</div>')
    return f'<div class="cards">{cards_html}</div>'


def build():
    pap = scrape_pap()
    studios = [d for d in pap if d["kind"] == "pap"]
    colocs = [d for d in pap if d["kind"] == "coloc"]
    residences = scrape_residences()

    now = datetime.datetime.now(ZoneInfo("Europe/Paris")).strftime("%d/%m/%Y à %Hh%M")

    studios_html = section("".join(card(d) for d in studios), len(studios))
    residences_html = section("".join(card(d) for d in residences), len(residences))
    colocs_html = section("".join(card(d) for d in colocs), len(colocs))

    html_out = TEMPLATE.format(
        updated=now,
        n_studios=len(studios), n_res=len(residences), n_coloc=len(colocs),
        studios=studios_html, residences=residences_html, colocs=colocs_html,
    )
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html_out)
    print(f"index.html genere — {len(studios)} studios/appts, {len(residences)} residences, {len(colocs)} colocs.")


# ------------------------------------------------------------------------ GABARIT HTML
TEMPLATE = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>Logement étudiant à Nantes — annonces & guide</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,500;0,600;0,700;1,600&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root{{--bg:#0e1613;--bg2:#0a100d;--card:#15201b;--card-soft:#121b17;--ink:#ece5d5;--muted:#9d947f;--line:rgba(198,168,108,.16);--gold:#c6a86c;--gold-dim:#a98f56;--gold-soft:rgba(198,168,108,.10);--sage:#93a074;--sage-soft:rgba(147,160,116,.14);--wine:#b06a5c;--wine-soft:rgba(176,106,92,.14);--shadow:0 24px 50px rgba(0,0,0,.45);--shadow-sm:0 8px 22px rgba(0,0,0,.30);--serif:"Cormorant Garamond",Georgia,serif;--sans:"Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;}}
  *{{box-sizing:border-box}} html{{scroll-behavior:smooth}}
  body{{margin:0;font-family:var(--sans);background:radial-gradient(1000px 560px at 82% -12%,rgba(198,168,108,.08) 0,rgba(198,168,108,0) 58%),radial-gradient(760px 480px at 4% 2%,rgba(147,160,116,.07) 0,rgba(147,160,116,0) 55%),linear-gradient(180deg,var(--bg) 0,var(--bg2) 100%);background-attachment:fixed;color:var(--ink);line-height:1.6;-webkit-font-smoothing:antialiased}}
  a{{color:var(--gold);text-decoration:none;border-bottom:1px solid rgba(198,168,108,.32)}} a:hover{{border-bottom-color:var(--gold)}}
  a.go,.watch a,.tabnav a{{border-bottom:none}}
  .wrap{{max-width:980px;margin:0 auto;padding-left:max(22px,env(safe-area-inset-left));padding-right:max(22px,env(safe-area-inset-right))}}
  header.hero{{padding:calc(56px + env(safe-area-inset-top)) 0 18px;text-align:center}}
  .badge{{display:inline-flex;gap:8px;color:var(--gold);border:1px solid var(--line);padding:8px 18px;border-radius:2px;font-size:11.5px;font-weight:600;letter-spacing:2.4px;text-transform:uppercase}}
  h1{{font-family:var(--serif);font-weight:600;font-size:clamp(36px,5.6vw,56px);line-height:1.04;margin:20px 0 10px}} h1 .hl{{color:var(--gold);font-style:italic}}
  .sub{{color:var(--muted);font-size:16px;max-width:540px;margin:0 auto}}
  .facts{{display:flex;flex-wrap:wrap;gap:12px;justify-content:center;margin-top:26px}}
  .fact{{background:var(--card);border:1px solid var(--line);border-radius:4px;padding:13px 18px;min-width:150px}}
  .fact .k{{font-size:10.5px;color:var(--muted);text-transform:uppercase;letter-spacing:1.4px;font-weight:600}}
  .fact .v{{font-family:var(--serif);font-size:21px;font-weight:600;margin-top:2px;color:var(--ink)}}
  .updated{{margin-top:22px;font-size:12.5px;color:var(--gold-dim)}} .updated b{{color:var(--gold)}}
  .tabnav{{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin:22px auto 0;max-width:640px}}
  .tabnav a{{font-size:12px;font-weight:600;letter-spacing:.5px;text-transform:uppercase;color:var(--muted);border:1px solid var(--line);padding:8px 14px;border-radius:2px}}
  .tabnav a:hover{{border-color:var(--gold);color:var(--gold)}}
  .howto{{max-width:760px;margin:24px auto 0;background:var(--card-soft);border:1px solid var(--line);border-left:2px solid var(--gold);border-radius:8px;padding:14px 18px;font-size:13px;color:var(--muted);line-height:1.55;text-align:left}} .howto b{{color:var(--ink)}}
  section{{margin:30px 0}}
  .banner{{font-family:var(--serif);font-weight:600;font-size:15px;letter-spacing:2px;text-transform:uppercase;color:var(--gold);text-align:center;margin:44px 0 6px}}
  .sec-head{{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin:0 4px 14px;border-bottom:1px solid var(--line);padding-bottom:10px}}
  .sec-head h2{{font-family:var(--serif);font-weight:600;font-size:26px;margin:0}}
  .sec-head .count{{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:1.2px}}
  .empty{{color:var(--muted);font-size:14px;background:var(--card-soft);border:1px solid var(--line);border-radius:8px;padding:16px 18px}}
  .step{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:32px 32px 26px;box-shadow:var(--shadow)}}
  .step-head{{display:flex;align-items:center;gap:16px;margin-bottom:6px}}
  .num{{flex:0 0 auto;width:44px;height:44px;border-radius:50%;border:1.4px solid var(--gold);color:var(--gold);display:grid;place-items:center;font-family:var(--serif);font-weight:600;font-size:21px}}
  .step h2{{font-family:var(--serif);font-weight:600;font-size:28px;margin:0}} .step .lead{{color:var(--muted);margin:6px 0 20px;font-size:15px}}
  .hiddenbar{{display:flex;align-items:center;justify-content:flex-end;gap:12px;margin:0 4px 8px;font-size:12.5px;color:var(--muted)}}
  .hiddenbar button{{background:transparent;border:1px solid var(--line);color:var(--muted);padding:6px 12px;border-radius:3px;font-size:11px;font-weight:600;letter-spacing:.6px;text-transform:uppercase;cursor:pointer;font-family:var(--sans)}}
  .hiddenbar button:hover{{border-color:var(--gold);color:var(--gold)}}
  .cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:14px}}
  .ad{{position:relative;display:flex;flex-direction:column;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;transition:opacity .2s ease,border-color .15s ease}}
  .ad .price{{font-family:var(--serif);font-weight:600;font-size:30px;color:var(--gold);line-height:1}} .ad .price small{{font-size:13px;color:var(--muted);font-family:var(--sans);font-weight:400}}
  .ad .type{{margin-top:8px;font-weight:600;font-size:15px;color:var(--ink)}} .ad .spot{{margin-top:2px;font-size:12.5px;color:var(--muted)}}
  .ad .src{{margin-top:10px;font-size:10.5px;letter-spacing:1px;text-transform:uppercase;color:var(--gold-dim);border:1px solid var(--line);padding:3px 8px;border-radius:2px;align-self:flex-start}}
  .ad.res .price{{color:var(--sage)}} .ad.coloc .price{{color:var(--wine)}}
  .stbadge{{position:absolute;top:12px;right:12px;font-size:9.5px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;padding:3px 8px;border-radius:2px;display:none}}
  .ad[data-status="lu"] .stbadge{{display:inline-block;background:var(--gold-soft);color:var(--gold-dim);border:1px solid var(--line)}}
  .ad[data-status="envoye"] .stbadge{{display:inline-block;background:var(--sage-soft);color:var(--sage);border:1px solid rgba(147,160,116,.4)}}
  .ad[data-status="non"]{{display:none}} body.show-hidden .ad[data-status="non"]{{display:flex;opacity:.45}}
  .ad[data-status="non"] .stbadge{{display:inline-block;background:var(--wine-soft);color:var(--wine);border:1px solid rgba(176,106,92,.4)}}
  .actions{{display:flex;flex-wrap:wrap;gap:6px;margin-top:14px;align-items:center}}
  .go,.act{{font-family:var(--sans);font-size:10.5px;font-weight:600;letter-spacing:.6px;text-transform:uppercase;border-radius:3px;cursor:pointer;transition:all .12s ease}}
  .go{{border:1px solid var(--gold);color:var(--gold);padding:6px 11px;background:transparent}} .go:hover{{background:var(--gold);color:var(--bg)}}
  .act{{background:transparent;border:1px solid var(--line);color:var(--muted);padding:6px 10px}} .act:hover{{border-color:var(--gold);color:var(--gold)}}
  .act.msg{{border-color:var(--gold);color:var(--gold)}} .act.msg:hover{{background:var(--gold);color:var(--bg)}}
  .act.on[data-s="lu"]{{background:var(--gold);color:var(--bg);border-color:var(--gold)}}
  .act.on[data-s="envoye"]{{background:var(--sage);color:var(--bg);border-color:var(--sage)}}
  .act.on[data-s="non"]{{background:var(--wine);color:var(--bg);border-color:var(--wine)}}
  .callout{{border-radius:8px;padding:18px 22px;font-size:14.5px;line-height:1.55;background:var(--card-soft);border:1px solid var(--line);border-left:2px solid var(--gold)}} .callout.sage{{border-left-color:var(--sage)}} .callout b{{color:var(--ink)}}
  .callout ul{{margin:11px 0 0;padding-left:18px}} .callout li{{margin:6px 0;color:var(--muted)}} .callout li b{{color:var(--ink)}} .callout li::marker{{color:var(--gold)}}
  .grp-title{{font-size:11.5px;font-weight:700;text-transform:uppercase;letter-spacing:1.6px;color:var(--gold-dim);margin:26px 0 12px;padding-bottom:9px;border-bottom:1px solid var(--line)}}
  .hoods{{display:grid;grid-template-columns:repeat(auto-fill,minmax(232px,1fr));gap:12px;margin-top:16px}}
  .hood{{background:var(--card-soft);border:1px solid var(--line);border-radius:8px;padding:18px}}
  .hood h3{{font-family:var(--serif);font-weight:600;margin:0 0 6px;font-size:20px}}
  .hood .tag{{font-size:10px;font-weight:700;padding:3px 10px;border-radius:2px;display:inline-block;margin-bottom:10px;letter-spacing:1px;text-transform:uppercase}}
  .tag.top{{background:var(--sage-soft);color:var(--sage);border:1px solid rgba(147,160,116,.3)}} .tag.mid{{background:var(--gold-soft);color:var(--gold);border:1px solid var(--line)}} .tag.bud{{background:var(--wine-soft);color:var(--wine);border:1px solid rgba(176,106,92,.3)}}
  .hood p{{margin:0;font-size:13px;color:var(--muted)}} .hood .price{{margin-top:10px;font-size:13px;font-weight:600;color:var(--ink)}}
  .safety{{background:var(--gold-soft);border:1px solid var(--line);border-radius:8px;padding:20px 22px;margin-top:18px;font-size:14px}}
  .safety > b{{color:var(--gold);font-family:var(--serif);font-size:18px;font-weight:600}}
  .safety ul{{margin:13px 0 0;padding-left:20px}} .safety li{{margin:8px 0;color:var(--muted)}} .safety li b{{color:var(--ink)}} .safety li::marker{{color:var(--gold)}}
  .tablewrap{{margin-top:22px;border:1px solid var(--line);border-radius:8px;overflow:hidden}}
  table{{width:100%;border-collapse:collapse;font-size:15px}} th,td{{text-align:left;padding:14px 18px;border-bottom:1px solid var(--line)}}
  th{{background:var(--card-soft);color:var(--gold-dim);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:1.2px}} td .who{{color:var(--muted);font-size:13.5px}} td.p{{font-family:var(--serif);font-weight:600;color:var(--gold);white-space:nowrap;font-size:17px}} tr:last-child td{{border-bottom:none}}
  .hint{{font-size:12.5px;color:var(--muted);margin:14px 0 0}}
  ul.check{{list-style:none;padding:0;margin:0;display:grid;grid-template-columns:1fr 1fr;gap:10px}}
  ul.check li{{background:var(--card-soft);border:1px solid var(--line);border-radius:6px;padding:13px 15px;font-size:14px;display:flex;gap:11px;align-items:flex-start}} ul.check li::before{{content:"\2726";color:var(--gold);font-size:12px;flex:0 0 auto;margin-top:2px}}
  .aides{{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px}}
  .aide{{background:var(--card-soft);border:1px solid var(--line);border-left:2px solid var(--gold);border-radius:6px;padding:16px 18px}} .aide h4{{font-family:var(--serif);font-weight:600;margin:0 0 5px;font-size:19px}} .aide p{{margin:0;font-size:13px;color:var(--muted)}}
  .msgwrap{{position:relative}} .msg{{background:var(--bg2);border:1px solid var(--line);border-radius:8px;padding:24px;font-size:14.5px;white-space:pre-wrap;line-height:1.7;color:var(--ink)}}
  .copybtn{{position:absolute;top:16px;right:16px;background:transparent;color:var(--gold);border:1px solid var(--gold);padding:9px 16px;border-radius:3px;font-weight:600;cursor:pointer;font-size:12px;font-family:var(--sans);letter-spacing:1px;text-transform:uppercase;transition:all .15s ease}} .copybtn:hover{{background:var(--gold);color:var(--bg)}}
  .note{{background:var(--card-soft);border:1px solid var(--line);border-left:2px solid var(--gold);border-radius:8px;padding:16px 20px;font-size:14px;color:var(--muted);line-height:1.6}} .note b{{color:var(--ink)}}
  .watch{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;margin-top:14px}}
  .watch a{{display:block;background:var(--card-soft);border:1px solid var(--line);border-radius:8px;padding:14px 16px;color:var(--ink)}} .watch a:hover{{border-color:var(--gold)}}
  .watch .t{{font-weight:600;font-size:15px;display:flex;justify-content:space-between}} .watch .t .arw{{color:var(--gold)}} .watch .d{{font-size:12px;color:var(--muted);margin-top:5px}}
  .alert{{background:var(--wine-soft);border:1px solid rgba(176,106,92,.32);border-radius:8px;padding:20px 22px;font-size:14px;line-height:1.55}} .alert b{{color:var(--wine)}}
  footer{{text-align:center;color:var(--muted);font-size:12.5px;padding:44px 0 calc(60px + env(safe-area-inset-bottom));line-height:1.6}}
  #toast{{position:fixed;left:50%;bottom:26px;transform:translateX(-50%) translateY(30px);background:var(--gold);color:var(--bg);padding:11px 20px;border-radius:4px;font-size:13px;font-weight:600;opacity:0;transition:all .25s ease;pointer-events:none;z-index:50;box-shadow:var(--shadow)}} #toast.show{{opacity:1;transform:translateX(-50%) translateY(0)}}
  @media(max-width:560px){{ul.check{{grid-template-columns:1fr}}.facts{{gap:8px}}.fact{{min-width:calc(50% - 8px)}}.step{{padding:24px 20px}}table,tbody,tr,td{{display:block;width:100%}}tr:first-child{{display:none}}tr{{border-bottom:1px solid var(--line);padding:10px 0}}tr:last-child{{border-bottom:none}}td{{border-bottom:none;padding:2px 16px}}td:first-child{{font-family:var(--serif);font-size:19px;color:var(--ink);padding-top:12px}}td.p{{font-size:16px}}td:last-child{{padding-bottom:12px}}header.hero{{padding-top:calc(44px + env(safe-area-inset-top))}}}}
</style>
</head>
<body>

<header class="hero"><div class="wrap">
  <span class="badge">Logement étudiant · Nantes</span>
  <h1>Les annonces <span class="hl">& le guide</span></h1>
  <p class="sub">Studios / T1 / T2 meublés · ≤ 650 € CC · campus du Tertre · pour le 1<sup>er</sup> septembre.</p>
  <div class="facts">
    <div class="fact"><div class="k">Budget</div><div class="v">600–650 € <span style="font-size:13px;color:var(--muted);font-family:var(--sans)">CC</span></div></div>
    <div class="fact"><div class="k">Priorité</div><div class="v">Studio · T1 · T2</div></div>
    <div class="fact"><div class="k">Zone</div><div class="v">Campus Tertre</div></div>
    <div class="fact"><div class="k">Échéance</div><div class="v">1<sup>er</sup> septembre</div></div>
  </div>
  <div class="updated">Annonces au <b>{updated}</b> · sources : PAP · ImmoJeune · ResidenceEtudiante.fr · <b>actualisé automatiquement</b></div>
  <nav class="tabnav"><a href="#annonces">Annonces</a><a href="#alertes">Alertes</a><a href="#quartiers">Quartiers</a><a href="#dossier">Dossier</a><a href="#message">Message</a></nav>
  <div class="howto"><b>Mode d'emploi.</b> En haut : les <b>annonces réelles du moment</b> (mises à jour toutes les 3 h). Sur chaque carte, <b>Message</b> copie une candidature déjà adaptée ; marquez ensuite <b>Lu</b>, <b>Envoyé</b> ou <b>Non</b> (les « Non » sont mis de côté). En bas : le <b>guide</b> — quartiers, dossier, message type, pièges à éviter.</div>
</div></header>

<div class="wrap">

  <div class="banner" id="annonces">— Les annonces du moment —</div>
  <div id="hiddenbar" class="hiddenbar" style="display:none"><span id="hiddencount"></span><button id="hiddenbtn" onclick="toggleHidden()">Afficher</button></div>

  <section>
    <div class="sec-head"><h2>Studios &amp; appartements</h2><span class="count">particuliers · {n_studios}</span></div>
    {studios}
  </section>

  <section>
    <div class="sec-head"><h2>Résidences étudiantes</h2><span class="count">meublé + services · {n_res}</span></div>
    {residences}
  </section>

  <section>
    <div class="sec-head"><h2>Colocations</h2><span class="count">dernier recours · {n_coloc}</span></div>
    {colocs}
  </section>

  <section id="alertes">
    <div class="sec-head"><h2>Chercher plus & alertes</h2></div>
    <div class="note"><b>Leboncoin, Bien'ici et SeLoger bloquent la collecte automatique.</b> Pour eux : ouvrir le lien filtré et activer leur <b>alerte</b> (mail / notification instantanée).
      <div class="watch">
        <a href="https://www.leboncoin.fr/recherche?category=10&locations=Nantes_44000&real_estate_type=2&furnished=1&price=min-650&square=20-max&rooms=1-2" target="_blank" rel="noopener"><div class="t">Leboncoin <span class="arw">↗</span></div><div class="d">Plus gros volume · alerte</div></a>
        <a href="https://www.bienici.com/recherche/location/nantes-44000/appartement?prix-max=650&surface-min=20&meuble=oui" target="_blank" rel="noopener"><div class="t">Bien'ici <span class="arw">↗</span></div><div class="d">Carte · alerte</div></a>
        <a href="https://www.seloger.com/immobilier/locations/immo-nantes-44/" target="_blank" rel="noopener"><div class="t">SeLoger <span class="arw">↗</span></div><div class="d">Agences + particuliers · alerte</div></a>
        <a href="https://www.studapart.com/fr/logement-etudiant-nantes" target="_blank" rel="noopener"><div class="t">Studapart <span class="arw">↗</span></div><div class="d">Résidences + particuliers · dossier</div></a>
      </div>
    </div>
  </section>

  <div class="banner">— Le guide —</div>

  <section id="quartiers"><div class="step">
    <div class="step-head"><div class="num">1</div><h2>Quartiers &amp; sécurité</h2></div>
    <p class="lead">Studio/T1 : 500–700 €. Cible : 600–650 € CC, proche du Tertre, quartier calme.</p>
    <div class="callout sage" style="margin-bottom:18px"><b>Campus du Tertre.</b> Tram ligne 2 (arrêts Facultés, Michelet-Sciences) + busway. Déplacements en transports en commun : viser ≤ 10 min à pied d'un arrêt tram/bus (<a href="https://www.tan.fr/" target="_blank" rel="noopener">réseau TAN</a>). Parking inutile.</div>
    <div class="hoods">
      <div class="hood"><span class="tag top">Priorité</span><h3>Petit Port / Universités</h3><p>Contigu au Tertre. Étudiant, animé, bien fréquenté.</p><div class="price">≈ 550–680 €</div></div>
      <div class="hood"><span class="tag top">Sûr</span><h3>Hauts-Pavés / Saint-Félix</h3><p>Résidentiel, calme. Tram/bus vers le campus.</p><div class="price">≈ 550–680 €</div></div>
      <div class="hood"><span class="tag mid">Sûr</span><h3>Graslin / Canclaux / Zola</h3><p>Résidentiel, tram direct. Plus éloigné du Tertre.</p><div class="price">≈ 600–720 €</div></div>
      <div class="hood"><span class="tag mid">Central</span><h3>Bouffay / Commerce</h3><p>Centre, tout à pied. Animé, bruyant le week-end.</p><div class="price">≈ 600–720 €</div></div>
      <div class="hood"><span class="tag mid">Récent</span><h3>Île de Nantes</h3><p>Neuf, éclairé, tram direct. Vérifier de nuit.</p><div class="price">≈ 580–700 €</div></div>
      <div class="hood"><span class="tag bud">À vérifier</span><h3>Nantes Nord / Bellevue</h3><p>Abordable, proche fac. Variable selon la rue. Visiter jour et nuit.</p><div class="price">≈ 480–600 €</div></div>
    </div>
    <div class="safety"><b>Contrôle sécurité du quartier</b>
      <ul>
        <li>Reconnaître le secteur <b>de jour et de nuit</b> : éclairage, fréquentation, commerces.</li>
        <li>Trajet arrêt de tram → porte : court, éclairé, passant.</li>
        <li>Avis sur <a href="https://www.bien-dans-ma-ville.fr/nantes-44109/" target="_blank" rel="noopener">Bien dans ma ville</a>.</li>
        <li>Immeuble : entrée sécurisée, hall propre, voisinage étudiant/familial.</li>
        <li>Doute au moment de la visite : écarter le logement.</li>
      </ul>
    </div>
    <div class="tablewrap"><table>
      <tr><th>Type</th><th>Loyer (CC)</th><th>Notes</th></tr>
      <tr><td>Résidence étudiante</td><td class="p">450 – 650 €</td><td class="who">Meublé, services compris. Dossier simple.</td></tr>
      <tr><td>Studio / T1 privé</td><td class="p">550 – 700 €</td><td class="who">Logement indépendant. Priorité 1.</td></tr>
      <tr><td>T2 (chambre séparée)</td><td class="p">650 – 850 €</td><td class="who">Plus d'espace. Tenable en quartier abordable ou à deux.</td></tr>
      <tr><td>Chambre en coloc</td><td class="p">380 – 500 €</td><td class="who">Repli. Exiger propreté et sécurité.</td></tr>
    </table></div>
    <p class="hint">Charges (eau, élec, internet) : + 30 à 90 €/mois si « hors charges ». Souvent incluses en résidence.</p>
    <p class="hint">Surface minimale : 20 m². Meublé : bail 1 an (ou 9 mois étudiant), préavis 1 mois.</p>
  </div></section>

  <section id="dossier"><div class="step">
    <div class="step-head"><div class="num">2</div><h2>Le dossier</h2></div>
    <p class="lead">Dossier complet en PDF, dans un dossier partagé. Envoi en 2 minutes.</p>
    <div class="callout sage" style="margin-bottom:18px"><b>Garanties : Visale + GarantMe + 2 garants familiaux</b> (mère, frère). Présenter l'option exigée par le propriétaire. Mentionner dès le premier message.</div>
    <ul class="check">
      <li>Pièce d'identité (recto-verso)</li><li>Certificat de scolarité ou carte étudiante</li>
      <li>Visa Visale (à générer avant les visites)</li><li>Dossier GarantMe (en alternative)</li>
      <li>Garants (mère et frère) : pièce d'identité, 3 bulletins de salaire, avis d'imposition</li><li>RIB à son nom</li>
      <li>Justificatif de ressources</li><li>Assurance habitation (à la signature)</li>
    </ul>
    <div class="grp-title" style="margin-top:26px">Aides</div>
    <div class="aides">
      <div class="aide"><h4>Garanties</h4><p>En place. Générer le visa Visale sur <a href="https://www.visale.fr/" target="_blank" rel="noopener">visale.fr</a>. Tenir chaque option prête.</p></div>
      <div class="aide"><h4>APL / CAF</h4><p>Aide mensuelle. Simulation sur <a href="https://www.caf.fr/allocataires/aides-et-demarches/mes-demarches/faire-une-simulation" target="_blank" rel="noopener">caf.fr</a>. Gain fréquent : 100–200 €/mois.</p></div>
      <div class="aide"><h4>LocaPass</h4><p>Avance du dépôt de garantie (Action Logement). Gratuit.</p></div>
    </div>
  </div></section>

  <section id="message"><div class="step">
    <div class="step-head"><div class="num">3</div><h2>Message type</h2></div>
    <p class="lead">Pour les annonces des autres sites. Sur les annonces ci-dessus, le bouton « Message » fait déjà ça, adapté au logement.</p>
    <div class="msgwrap"><div class="msg" id="tmpl">Bonjour,

Je me permets de vous contacter au sujet de votre annonce pour le [studio / T1] meublé à [quartier], au loyer de [montant] € charges comprises.

Étudiante en L1 Histoire à Nantes Université (campus du Tertre), je recherche un logement meublé pour le 1er septembre au plus tard.

Mes garanties sont en place : Visale, GarantMe, et deux garants familiaux. Dossier complet et prêt à envoyer : pièce d'identité, certificat de scolarité, attestation de garantie, RIB.

Je suis disponible pour une visite [en semaine / ce week-end / en visio], selon vos disponibilités.

Merci pour votre retour,
Mélissandre Joly
+33 6 07 17 43 11 · melijoly85@gmail.com</div>
    <button class="copybtn" onclick="copyTemplate()">Copier</button></div>
  </div></section>

  <section><div class="alert"><b>Règle absolue.</b> Aucun paiement (ni « réservation ») avant visite et bail signé. Signaux d'arnaque : loyer anormalement bas, propriétaire « à l'étranger », clés par la poste, virement / coupon PCS / crypto. Visiter — ou faire visiter par un proche — avant de signer.</div></section>

</div>

<footer><div class="wrap">Page actualisée automatiquement (toutes les 3 h). Dernière collecte : {updated}. Sources : PAP · ImmoJeune · ResidenceEtudiante.fr. Guide indicatif — prix et disponibilités évolutifs. Statuts mémorisés sur cet appareil. Site non officiel.</div></footer>

<div id="toast"></div>

<script>
var KEY='annonces-nantes-status-v1';
function loadMap(){{try{{return JSON.parse(localStorage.getItem(KEY)||'{{}}')}}catch(e){{return window.__st||{{}}}}}}
function saveMap(m){{window.__st=m;try{{localStorage.setItem(KEY,JSON.stringify(m))}}catch(e){{}}}}
function toast(t){{var e=document.getElementById('toast');e.textContent=t;e.classList.add('show');clearTimeout(window.__tt);window.__tt=setTimeout(function(){{e.classList.remove('show')}},1900)}}
function paint(card){{var s=card.getAttribute('data-status')||'';var b=card.querySelector('.stbadge');b.textContent=s==='lu'?'Lu':s==='envoye'?'Demande envoyée':s==='non'?'Pas pour moi':'';card.querySelectorAll('.act[data-s]').forEach(function(btn){{btn.classList.toggle('on',btn.getAttribute('data-s')===s)}})}}
function setStatus(btn){{var card=btn.closest('.ad'),s=btn.getAttribute('data-s');var cur=card.getAttribute('data-status')||'';var next=cur===s?'':s;if(next)card.setAttribute('data-status',next);else card.removeAttribute('data-status');var m=loadMap(),id=card.getAttribute('data-id');if(next)m[id]=next;else delete m[id];saveMap(m);paint(card);updateHiddenBar()}}
function updateHiddenBar(){{var n=document.querySelectorAll('.ad[data-status="non"]').length;var bar=document.getElementById('hiddenbar'),c=document.getElementById('hiddencount'),btn=document.getElementById('hiddenbtn');if(n>0){{bar.style.display='flex';c.textContent=n+(n>1?' annonces écartées':' annonce écartée')}}else{{bar.style.display='none';document.body.classList.remove('show-hidden');if(btn)btn.textContent='Afficher'}}}}
function toggleHidden(){{var on=document.body.classList.toggle('show-hidden');document.getElementById('hiddenbtn').textContent=on?'Masquer':'Afficher'}}
function buildMsg(card){{var kind=card.getAttribute('data-kind'),type=card.getAttribute('data-type'),q=card.getAttribute('data-quartier'),m=card.getAttribute('data-montant');var objet;if(kind==='res')objet='un logement meublé (type '+type+') dans votre résidence à '+q;else if(kind==='coloc')objet='votre annonce de '+type+' à '+q+' ('+m+')';else objet='votre annonce : '+type+' meublé à '+q+' ('+m+')';return 'Bonjour,\n\nJe me permets de vous contacter au sujet de '+objet+'.\n\nÉtudiante en L1 Histoire à Nantes Université (campus du Tertre), je recherche un logement meublé pour le 1er septembre au plus tard. Il correspond parfaitement à ce que je cherche.\n\nMes garanties sont en place : Visale, GarantMe, et deux garants familiaux. Dossier complet et prêt à envoyer : pièce d identité, certificat de scolarité, attestation de garantie, RIB.\n\nJe suis disponible pour une visite en semaine, le week-end ou en visio, selon vos disponibilités.\n\nMerci pour votre retour,\nMélissandre Joly\n+33 6 07 17 43 11 · melijoly85@gmail.com'}}
function doCopy(txt,msg){{function ok(){{toast(msg)}}if(navigator.clipboard&&navigator.clipboard.writeText){{navigator.clipboard.writeText(txt).then(ok).catch(function(){{fallback(txt);ok()}})}}else{{fallback(txt);ok()}}}}
function copyMsg(btn){{doCopy(buildMsg(btn.closest('.ad')),'Message copié ✓ — plus qu à le coller')}}
function copyTemplate(){{doCopy(document.getElementById('tmpl').innerText,'Message copié ✓')}}
function fallback(txt){{var ta=document.createElement('textarea');ta.value=txt;ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.select();try{{document.execCommand('copy')}}catch(e){{}}document.body.removeChild(ta)}}
(function init(){{var m=loadMap();document.querySelectorAll('.ad').forEach(function(card){{var id=card.getAttribute('data-id');if(m[id])card.setAttribute('data-status',m[id]);paint(card)}});updateHiddenBar()}})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    build()
