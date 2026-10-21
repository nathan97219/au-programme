"""Le robot de recherche : prépare les fiches de la semaine suivante, tout seul.

L'IA (Gemini + recherche Google) PROPOSE des mesures. Le code ne garde que ce qu'il a VÉRIFIÉ dans la page source :
  1. le site est dans la liste des sources reconnues (config/settings.yaml) ;
  2. la page s'ouvre réellement, et le nom du candidat y figure ;
  3. la date de publication est lue dans la page elle-même (pas celle donnée par l'IA), et elle est récente ;
  4. chaque nombre du titre et de l'explication figure dans la page ;
  5. la citation, s'il y en a une, figure MOT POUR MOT dans la page (sinon elle est retirée) ;
  6. une relecture indépendante (l'IA lit la page, sans recherche) confirme que le candidat propose bien cela ;
  7. le contrôle de neutralité (fiches.py) passe.
Ce qui échoue est écarté. Sans mesure vérifiée : « aucune proposition vérifiable trouvée », jamais d'invention.
"""
from __future__ import annotations

import html as html_lib
import json
import re
import time
import unicodedata
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

import requests
import yaml

from . import fiches
from .config import CONTENU_DIR

ENTETES = {"User-Agent": "Mozilla/5.0 (compatible; AuProgrammeBot/1.0; +https://www.instagram.com/au.programme)",
           "Accept-Language": "fr-FR,fr;q=0.9"}
MAX_TEXTE_RELECTURE = 14000


# ---------- Lecture d'une page ----------

def normaliser(t: str) -> str:
    """Pour comparer : minuscules, apostrophes et guillemets unifiés, espaces simples, sans accents superflus."""
    t = unicodedata.normalize("NFKC", t or "").lower()
    t = t.replace("’", "'").replace("‘", "'").replace("`", "'").replace("«", '"').replace("»", '"')
    t = t.replace("“", '"').replace("”", '"').replace(" ", " ").replace(" ", " ").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", t).strip()


def texte_de_la_page(page_html: str) -> str:
    t = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", page_html)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html_lib.unescape(t)).strip()


def titre_de_la_page(page_html: str) -> str | None:
    for motif in (r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
                  r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title', r"(?is)<title[^>]*>(.*?)</title>"):
        m = re.search(motif, page_html)
        if m:
            return html_lib.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
    return None


def date_de_la_page(page_html: str) -> date | None:
    """Date de publication lue dans les métadonnées de la page (jamais devinée)."""
    motifs = [r'article:published_time["\'][^>]+content=["\'](\d{4}-\d{2}-\d{2})',
              r'content=["\'](\d{4}-\d{2}-\d{2})[^"\']*["\'][^>]+article:published_time',
              r'"datePublished"\s*:\s*"(\d{4}-\d{2}-\d{2})',
              r'<time[^>]+datetime=["\'](\d{4}-\d{2}-\d{2})',
              r'name=["\'](?:date|pubdate|publish-date|DC\.date\.issued)["\'][^>]+content=["\'](\d{4}-\d{2}-\d{2})']
    for motif in motifs:
        m = re.search(motif, page_html, re.I)
        if m:
            try:
                return date.fromisoformat(m.group(1))
            except ValueError:
                continue
    return None


def ouvrir(url: str) -> tuple[str, str] | None:
    """(adresse finale, html) ou None si la page ne s'ouvre pas."""
    try:
        r = requests.get(url, headers=ENTETES, timeout=25, allow_redirects=True)
    except requests.RequestException:
        return None
    if r.status_code != 200 or "html" not in r.headers.get("Content-Type", "html"):
        return None
    r.encoding = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else r.apparent_encoding
    return r.url, r.text


# ---------- Les vérifications ----------

def nombres(texte: str) -> list[str]:
    """Les nombres d'un texte, sans séparateurs de milliers (« 1 000 » → « 1000 », « 5,5 » reste « 5,5 »)."""
    t = re.sub(r"(?<=\d)[\s  .](?=\d{3}\b)", "", texte or "")
    return re.findall(r"\d+(?:,\d+)?", t)


def nombres_presents(ecrit: str, page: str) -> list[str]:
    """Les nombres du texte écrit qui sont ABSENTS de la page (liste vide = tout est sourcé)."""
    dans_la_page = set(nombres(page))
    # « 1er » s'écrit souvent « premier » : on l'accepte sous les deux formes
    dans_la_page |= {"1"} if re.search(r"\bpremier\b", page, re.I) else set()
    return [n for n in nombres(ecrit) if n not in dans_la_page]


def citation_presente(citation: str, page: str) -> bool:
    return normaliser(citation).strip(' ".') in normaliser(page)


def nom_present(nom: str, page: str) -> bool:
    famille = nom.split(" ", 1)[1] if " " in nom else nom
    return normaliser(famille) in normaliser(page)


def extrait_autour(nom: str, texte: str, taille: int = MAX_TEXTE_RELECTURE) -> str:
    """Le passage de la page centré sur le candidat (pour la relecture)."""
    famille = nom.split(" ", 1)[1] if " " in nom else nom
    i = normaliser(texte).find(normaliser(famille))
    debut = max(0, i - taille // 3) if i >= 0 else 0
    return texte[debut: debut + taille]


# ---------- Le travail de l'IA ----------

def consigne_recherche(c: dict, theme: dict, jour: date, domaines: list[str], deja: list[str]) -> str:
    return f"""Tu aides un média neutre et pédagogique qui présente les programmes des candidats à l'élection présidentielle française de 2027.

Cherche sur le web les propositions RÉCENTES (publiées dans les 12 derniers mois avant le {jour.isoformat()}) de {c['nom']} ({c['parti']}) sur le thème : « {theme['nom']} ».

Règles :
- Uniquement des articles ou pages de CES sites : {", ".join(domaines)}.
- Une proposition = une mesure concrète que {c['nom']} défend pour 2027 (pas une critique d'un adversaire, pas une mesure d'une autre élection).
- 2 propositions au maximum, les plus importantes. Si tu n'en trouves aucune de fiable, renvoie une liste vide.
- « titre » : la mesure en 70 caractères maximum, à l'infinitif, factuelle, sans adjectif de jugement ni étiquette politique (gauche, droite, extrême…).
- « explication » : 170 caractères maximum, des faits tirés de l'article (chiffres compris), neutres.
- « citation » : facultative ; uniquement une phrase de {c['nom']} recopiée MOT POUR MOT de l'article sur cette mesure (170 caractères maximum), sinon null.
- « source » : l'adresse EXACTE de l'article (url), le nom du média, le titre de l'article.
{"- Déjà écarté (ne pas reproposer) : " + "; ".join(deja) if deja else ""}

Réponds UNIQUEMENT avec ce JSON :
{{"mesures": [{{"titre": "...", "explication": "...", "citation": null, "source": {{"media": "...", "titre": "...", "url": "https://..."}}}}]}}"""


def consigne_relecture(c: dict, m: dict, extrait: str) -> str:
    return f"""Voici un extrait d'une page web. Réponds en lisant UNIQUEMENT ce texte, sans aucune autre connaissance.

Question : ce texte indique-t-il clairement que {c['nom']} propose (ou défend) la mesure suivante ?
Mesure : « {m['titre']} ». Précision : « {m['explication']} ».
Réponds « true » seulement si le texte le dit explicitement et que tous les détails de la précision y figurent. Sinon « false ».

Texte :
\"\"\"{extrait}\"\"\"

Réponds UNIQUEMENT avec ce JSON : {{"confirme": true, "raison": "..."}}"""


# ---------- La fiche d'un candidat ----------

def verifier_mesure(m: dict, c: dict, jour: date, settings: dict, adresses_google: list[str],
                    relire) -> tuple[dict | None, str]:
    """Vérifie une mesure proposée. Renvoie (mesure corrigée, '') ou (None, raison du rejet)."""
    domaines = fiches.domaines_reconnus(settings)
    max_jours = (settings.get("recherche") or {}).get("anciennete_max_jours", 365)
    proposee = str((m.get("source") or {}).get("url") or "")
    essais = [proposee] + [a for a in adresses_google if a != proposee]
    raison = "aucune source vérifiable"
    for url in essais:
        if not url.startswith("https://") or not fiches.source_reconnue(url, domaines):
            raison = f"source non reconnue ({urlparse(url).hostname})"
            continue
        page = ouvrir(url)
        if not page:
            raison = f"page inaccessible ({urlparse(url).hostname})"
            continue
        finale, brut = page
        if not fiches.source_reconnue(finale, domaines):
            raison = "redirection vers un site non reconnu"
            continue
        texte = texte_de_la_page(brut)
        if not nom_present(c["nom"], texte):
            raison = "le candidat n'est pas cité dans la page"
            continue
        d = date_de_la_page(brut)
        if d is None or d > jour or (jour - d).days > max_jours:
            raison = "date de publication absente ou trop ancienne"
            continue
        manquants = nombres_presents(f"{m.get('titre', '')} {m.get('explication', '')}", texte)
        if manquants:
            raison = f"chiffres absents de la page : {', '.join(manquants)}"
            continue
        citation = m.get("citation")
        if citation and not citation_presente(citation, texte):
            citation = None                                         # citation non retrouvée : retirée, jamais inventée
        if not relire(consigne_relecture(c, m, extrait_autour(c["nom"], texte))):
            raison = "la relecture de la page ne confirme pas la mesure"
            continue
        src = m.get("source") or {}
        return {"titre": str(m["titre"]).strip(), "explication": str(m["explication"]).strip(),
                "citation": citation.strip() if citation else None,
                "source": {"media": str(src.get("media") or urlparse(finale).hostname).strip(),
                           "titre": titre_de_la_page(brut) or str(src.get("titre") or "").strip(),
                           "url": finale, "date": d}}, ""
    return None, raison


def adresse_reelle(uri: str) -> str | None:
    """Les liens de Google sont des redirections : on récupère l'adresse finale (sans télécharger la page)."""
    try:
        r = requests.head(uri, headers=ENTETES, timeout=15, allow_redirects=False)
        loc = r.headers.get("Location")
        if loc:
            return loc
        r = requests.get(uri, headers=ENTETES, timeout=20, allow_redirects=True, stream=True)
        r.close()
        return r.url
    except requests.RequestException:
        return None


def fiche_candidat(c: dict, theme: dict, jour: date, settings: dict, chercher, relire, journal: list[str]) -> dict:
    """La fiche complète d'un candidat : uniquement des mesures vérifiées, sinon « aucune proposition vérifiable »."""
    domaines = fiches.domaines_reconnus(settings)
    pause = (settings.get("recherche") or {}).get("pause_entre_appels", 4)
    gardees, ecartees = [], []
    for tour in range(2):                                           # 2 tours de recherche au maximum
        try:
            reponse, sources = chercher(consigne_recherche(c, theme, jour, domaines, [e for e in ecartees]))
        except RuntimeError as e:
            journal.append(f"{c['nom']} : recherche impossible ({e})")
            break
        google = [a for a in (adresse_reelle(s["uri"]) for s in sources) if a]
        google = [a for a in google if fiches.source_reconnue(a, domaines)]
        for m in (reponse.get("mesures") or [])[:4]:
            if len(gardees) >= fiches.MAX_MESURES or not isinstance(m, dict) or not m.get("titre"):
                continue
            if any(normaliser(m["titre"]) == normaliser(g["titre"]) for g in gardees):
                continue
            ok, raison = verifier_mesure(m, c, jour, settings, google, relire)
            if ok:
                essai = {"theme": theme["id"], "candidat": c["id"], "statut": "valide", "consulte_le": jour,
                         "mesures": gardees + [ok]}
                pb = fiches.problemes(essai, theme["id"], c["id"], settings)
                if pb:
                    raison, ok = "; ".join(pb), None
            if ok:
                gardees.append(ok)
                journal.append(f"✅ {c['nom']} : {ok['titre']} ({ok['source']['media']}, {ok['source']['date']})")
            else:
                ecartees.append(str(m["titre"])[:80])
                journal.append(f"✖️ {c['nom']} : « {str(m['titre'])[:60]} » écartée : {raison}")
        if gardees:
            break
        time.sleep(pause)
    fiche = {"theme": theme["id"], "candidat": c["id"], "statut": "valide", "consulte_le": jour}
    if gardees:
        fiche["mesures"] = gardees
    else:
        fiche.update({"aucune_proposition": True, "mesures": []})
        journal.append(f"ℹ️ {c['nom']} : aucune proposition vérifiable trouvée")
    return fiche


def ecrire(fiche: dict) -> None:
    p = fiches.chemin(fiche["theme"], fiche["candidat"])
    p.parent.mkdir(parents=True, exist_ok=True)
    entete = (f"# Fiche préparée automatiquement par le robot le {fiche['consulte_le'].isoformat()} : chaque mesure a été\n"
              "# vérifiée dans sa page source (site reconnu, date, chiffres, citation mot pour mot, relecture).\n"
              "# Pour corriger : modifier ce fichier. Pour empêcher sa publication : « statut: bloque ».\n")
    p.write_text(entete + yaml.safe_dump(fiche, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")


def menage(themes_a_garder: set[str]) -> list[str]:
    """Supprime les fiches des thèmes passés (elles restent dans l'historique Git)."""
    import shutil
    supprimes = []
    for d in sorted(p for p in CONTENU_DIR.iterdir() if p.is_dir()):
        if d.name not in themes_a_garder:
            shutil.rmtree(d)
            supprimes.append(d.name)
    return supprimes


def preparer_semaine(lundi_: date, aujourd_hui: date, settings: dict, themes: list, candidats: list,
                     chercher=None, relire=None, refaire: bool = False) -> dict:
    from .calendrier import ordre_de_la_semaine, theme_de_la_semaine
    from .llm import generate_json, rechercher
    chercher = chercher or (lambda p: rechercher(p, settings))
    relire = relire or (lambda p: bool(generate_json(p, settings).get("confirme") is True))
    theme = theme_de_la_semaine(lundi_, settings, themes)
    ordre = ordre_de_la_semaine(lundi_, settings, themes, candidats)
    journal, faites = [], []
    for c in ordre:
        existante = fiches.charger(theme["id"], c["id"])
        if existante and not refaire:
            journal.append(f"= {c['nom']} : fiche déjà prête, conservée")
            continue
        f = fiche_candidat(c, theme, aujourd_hui, settings, chercher, relire, journal)
        ecrire(f)
        faites.append(c["id"])
    en_cours = theme_de_la_semaine(lundi_ - timedelta(days=7), settings, themes)
    supprimes = menage({theme["id"]} | ({en_cours["id"]} if en_cours else set()))
    return {"theme": theme, "ordre": ordre, "faites": faites, "journal": journal, "supprimes": supprimes}


def resume(r: dict, lundi_: date) -> str:
    lignes = [f"🗳️ Au Programme : fiches « {r['theme']['nom']} » pour la semaine du {lundi_:%d/%m}"]
    jours = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
    for i, c in enumerate(r["ordre"]):
        f = fiches.charger(r["theme"]["id"], c["id"]) or {}
        n = len(f.get("mesures") or [])
        etat = f"{n} mesure{'s' if n > 1 else ''}" if n else "aucune proposition vérifiable"
        lignes.append(f"{jours[i]} {c['nom']} : {etat}")
    if r["supprimes"]:
        lignes.append(f"🧹 Anciennes fiches supprimées : {', '.join(r['supprimes'])}")
    return "\n".join(lignes)


def journal_json(r: dict) -> str:
    return json.dumps(r["journal"], ensure_ascii=False, indent=1)


def aujourdhui_paris() -> date:
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Europe/Paris")).date()
