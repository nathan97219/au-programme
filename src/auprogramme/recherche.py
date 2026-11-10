"""Le robot de recherche : prépare les fiches de la semaine suivante, tout seul.

L'IA (Gemini + recherche Google) PROPOSE des mesures. Le code ne garde que ce qu'il a VÉRIFIÉ.

Vérification complète (la page source s'ouvre) :
  1. le site est dans la liste des sources reconnues (config/settings.yaml) ;
  2. le candidat (ou son parti) est cité dans la page ;
  3. la date de publication vient de la page (métadonnées, adresse ou mention « publié le ») et a moins d'un an ;
  4. chaque nombre du TITRE figure dans la page ; une phrase d'explication au chiffre introuvable est retirée ;
  5. la citation figure MOT POUR MOT dans la page, sinon elle est retirée ;
  6. une relecture indépendante (l'IA lit la page, sans recherche) confirme la mesure ;
  7. le contrôle de neutralité (fiches.py) passe.

Vérification par Google (la page est bloquée aux robots ou réservée aux abonnés) : la mesure est gardée seulement si
Google lui-même rattache la mesure à cette page d'un site reconnu, que le candidat ou son parti y est nommé, et qu'une
date récente est connue. La citation est alors retirée (impossible de la vérifier mot pour mot) et la fiche le note.
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


MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
           "novembre", "décembre"]


def date_de_la_page(page_html: str) -> date | None:
    """Date de publication lue dans la page elle-même (jamais devinée) : métadonnées, sinon « publié le … »."""
    motifs = [r'article:published_time["\'][^>]+content=["\'](\d{4}-\d{2}-\d{2})',
              r'content=["\'](\d{4}-\d{2}-\d{2})[^"\']*["\'][^>]+article:published_time',
              r'"datePublished"\s*:\s*"(\d{4}-\d{2}-\d{2})',
              r'"dateCreated"\s*:\s*"(\d{4}-\d{2}-\d{2})',
              r'<time[^>]+datetime=["\'](\d{4}-\d{2}-\d{2})',
              r'name=["\'](?:date|pubdate|publish-date|DC\.date\.issued|dcterms\.date|parsely-pub-date)["\'][^>]+content=["\'](\d{4}-\d{2}-\d{2})',
              r'itemprop=["\']datePublished["\'][^>]+content=["\'](\d{4}-\d{2}-\d{2})']
    for motif in motifs:
        m = re.search(motif, page_html, re.I)
        if m:
            try:
                return date.fromisoformat(m.group(1))
            except ValueError:
                continue
    return date_dans_le_texte(texte_de_la_page(page_html)[:6000])


def date_dans_le_texte(texte: str) -> date | None:
    """« Publié le 12 octobre 2026 », « mis à jour le 3/11/2026 »… (seulement avec un mot qui annonce la date)."""
    t = normaliser(texte)
    m = re.search(r"(?:publi[ée]+|mis en ligne|mis à jour|modifi[ée]+)\s+le\s+(\d{1,2})(?:er)?\s+(" + "|".join(MOIS_FR)
                  + r")\s+(\d{4})", t)
    try:
        if m:
            return date(int(m.group(3)), MOIS_FR.index(m.group(2)) + 1, int(m.group(1)))
        m = re.search(r"(?:publi[ée]+|mis en ligne|mis à jour|modifi[ée]+)\s+le\s+(\d{1,2})/(\d{1,2})/(\d{4})", t)
        if m:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None
    return None


def date_dans_l_adresse(url: str) -> date | None:
    """Beaucoup de médias mettent la date dans l'adresse : /2026/10/15/ ou -20261015-."""
    for motif in (r"/(20\d{2})/(\d{1,2})/(\d{1,2})/", r"[/_-](20\d{2})(\d{2})(\d{2})(?:[/_.-]|$)", r"/(20\d{2})-(\d{2})-(\d{2})"):
        m = re.search(motif, url)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
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


def nom_present(nom: str, page: str, parti: str | None = None) -> bool:
    """Le nom de famille du candidat (ou le nom de son parti) figure dans le texte."""
    famille = nom.split(" ", 1)[1] if " " in nom else nom
    t = normaliser(page)
    return normaliser(famille) in t or bool(parti and len(parti) > 8 and normaliser(parti) in t)


def retirer_chiffres_non_sources(explication: str, page: str) -> str:
    """Retire de l'explication les phrases dont un chiffre ne figure pas dans la source (au lieu de tout rejeter)."""
    phrases = re.split(r"(?<=[.!?])\s+", explication.strip())
    gardees = [p for p in phrases if not nombres_presents(p, page)]
    return " ".join(gardees).strip()


TEXTE_TRONQUE = 1800          # une page plus courte que ça est presque toujours réservée aux abonnés ou bloquée


def extrait_autour(nom: str, texte: str, taille: int = MAX_TEXTE_RELECTURE) -> str:
    """Le passage de la page centré sur le candidat (pour la relecture)."""
    famille = nom.split(" ", 1)[1] if " " in nom else nom
    i = normaliser(texte).find(normaliser(famille))
    debut = max(0, i - taille // 3) if i >= 0 else 0
    return texte[debut: debut + taille]


# ---------- Le travail de l'IA ----------

def consigne_recherche(c: dict, theme: dict, jour: date, domaines: list[str], deja: list[str]) -> str:
    return f"""Tu aides un média neutre et pédagogique qui présente les propositions des candidats à l'élection présidentielle française de 2027.

Cherche sur le web les propositions RÉCENTES (publiées dans les 12 derniers mois avant le {jour.isoformat()}) de {c['nom']} ({c['parti']}) sur le thème : « {theme['nom']} ».
Les programmes officiels ne sont pas encore tous publiés : une proposition annoncée dans une interview, un discours, un
document du parti ou une proposition de loi déposée par ses élus compte, tant qu'elle est clairement défendue par {c['nom']} ou {c['parti']}.

Où chercher, dans cet ordre :
1. le site officiel de {c['parti']} ou du candidat (pages propositions, programme, communiqués) ;
2. les propositions de loi déposées par ses élus (assemblee-nationale.fr, senat.fr) ;
3. les médias en accès libre (franceinfo, AFP, Public Sénat, LCP, Ouest-France, 20 Minutes, BFMTV, TF1 Info, Europe 1, RTL…) ;
4. en dernier, les articles réservés aux abonnés.
Uniquement des pages de CES sites : {", ".join(domaines)}.

Règles :
- Une proposition = une mesure concrète défendue pour la France (pas une critique d'un adversaire).
- 3 propositions au maximum, les plus importantes. Si tu n'en trouves aucune de fiable, renvoie une liste vide.
- « titre » : la mesure en 70 caractères maximum, à l'infinitif, factuelle, sans adjectif de jugement ni étiquette politique (gauche, droite, extrême…).
- « explication » : 170 caractères maximum, des faits tirés de la page (chiffres compris), neutres.
- « citation » : facultative ; uniquement une phrase de {c['nom']} recopiée MOT POUR MOT de la page (170 caractères maximum), sinon null.
- « source » : l'adresse EXACTE de la page (url), le nom du média ou du site, le titre, et la date de publication (AAAA-MM-JJ).
{"- Déjà écarté (ne pas reproposer) : " + "; ".join(deja) if deja else ""}

Réponds UNIQUEMENT avec ce JSON :
{{"mesures": [{{"titre": "...", "explication": "...", "citation": null, "source": {{"media": "...", "titre": "...", "url": "https://...", "date": "AAAA-MM-JJ"}}}}]}}"""


def consigne_relecture(c: dict, m: dict, extrait: str) -> str:
    return f"""Voici un extrait d'une page web. Réponds en lisant UNIQUEMENT ce texte, sans aucune autre connaissance.

Question : ce texte indique-t-il clairement que {c['nom']} propose (ou défend) la mesure suivante ?
Mesure : « {m['titre']} ». Précision : « {m['explication']} ».
Réponds « true » seulement si le texte le dit explicitement et que tous les détails de la précision y figurent. Sinon « false ».

Texte :
\"\"\"{extrait}\"\"\"

Réponds UNIQUEMENT avec ce JSON : {{"confirme": true, "raison": "..."}}"""


# ---------- La fiche d'un candidat ----------

def _date_proposee(m: dict) -> date | None:
    try:
        return date.fromisoformat(str((m.get("source") or {}).get("date") or "")[:10])
    except ValueError:
        return None


def _mots(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-zàâçéèêëîïôûùüÿœ0-9]{4,}", normaliser(t))}


def appuyee_par_google(m: dict, appuis: list[str]) -> bool:
    """Google rattache-t-il la mesure à cette source ? (un passage appuyé qui reprend l'essentiel de la mesure)"""
    mesure = _mots(f"{m.get('titre', '')} {m.get('explication', '')}")
    if not mesure:
        return False
    return any(len(mesure & _mots(seg)) >= max(3, len(mesure) // 2) for seg in appuis)


def verifier_mesure(m: dict, c: dict, jour: date, settings: dict, adresses_google: list[str],
                    relire, appuis: dict[str, list[str]] | None = None) -> tuple[dict | None, str]:
    """Vérifie une mesure proposée. Renvoie (mesure corrigée, '') ou (None, raison du rejet).
    Essaie d'abord une vérification complète dans la page ; sinon, la vérification par Google (voir en tête)."""
    domaines = fiches.domaines_reconnus(settings)
    max_jours = (settings.get("recherche") or {}).get("anciennete_max_jours", 365)
    appuis = appuis or {}
    proposee = str((m.get("source") or {}).get("url") or "")
    essais = [proposee] + [a for a in adresses_google if a != proposee]
    raison = "aucune source vérifiable"
    recente = lambda d: d is not None and d <= jour and (jour - d).days <= max_jours     # noqa: E731
    secours = None                                                  # page bloquée mais appuyée par Google
    for url in essais:
        if not url.startswith("https://") or not fiches.source_reconnue(url, domaines):
            raison = f"source non reconnue ({urlparse(url).hostname})"
            continue
        page = ouvrir(url)
        texte = texte_de_la_page(page[1]) if page else ""
        if not page or (len(texte) < TEXTE_TRONQUE and not nom_present(c["nom"], texte, c.get("parti"))):
            raison = f"page inaccessible ou réservée aux abonnés ({urlparse(url).hostname})"
            if secours is None and appuyee_par_google(m, appuis.get(url, [])):
                secours = url
            continue
        finale, brut = page
        if not fiches.source_reconnue(finale, domaines):
            raison = "redirection vers un site non reconnu"
            continue
        if not nom_present(c["nom"], texte, c.get("parti")):
            raison = "ni le candidat ni son parti ne sont cités dans la page"
            continue
        d = date_de_la_page(brut) or date_dans_l_adresse(finale) or date_dans_l_adresse(url)
        if not recente(d):
            raison = "date de publication introuvable ou trop ancienne"
            continue
        manquants = nombres_presents(str(m.get("titre", "")), texte)
        if manquants:
            raison = f"chiffres du titre absents de la page : {', '.join(manquants)}"
            continue
        explication = retirer_chiffres_non_sources(str(m.get("explication") or ""), texte)
        citation = m.get("citation")
        if citation and not citation_presente(citation, texte):
            citation = None                                         # citation non retrouvée : retirée, jamais inventée
        if not relire(consigne_relecture(c, {**m, "explication": explication}, extrait_autour(c["nom"], texte))):
            raison = "la relecture de la page ne confirme pas la mesure"
            continue
        src = m.get("source") or {}
        return {"titre": str(m["titre"]).strip(), "explication": explication or str(m["titre"]).strip() + ".",
                "citation": citation.strip() if citation else None,
                "source": {"media": str(src.get("media") or urlparse(finale).hostname).strip(),
                           "titre": titre_de_la_page(brut) or str(src.get("titre") or "").strip(),
                           "url": finale, "date": d, "verification": "page"}}, ""
    if secours:
        appui = " ".join(appuis.get(secours, []))
        d = date_dans_l_adresse(secours) or _date_proposee(m)
        if not nom_present(c["nom"], f"{appui} {m.get('titre', '')} {(m.get('source') or {}).get('titre', '')}", c.get("parti")):
            return None, "page bloquée, et le candidat n'apparaît pas dans ce que Google en rapporte"
        if not recente(d):
            return None, "page bloquée, et pas de date récente connue"
        src = m.get("source") or {}
        explication = retirer_chiffres_non_sources(str(m.get("explication") or ""), f"{appui} {src.get('titre', '')}")
        if nombres_presents(str(m.get("titre", "")), f"{appui} {src.get('titre', '')}"):
            return None, "page bloquée, et les chiffres du titre ne sont pas dans ce que Google en rapporte"
        return {"titre": str(m["titre"]).strip(), "explication": explication or str(m["titre"]).strip() + ".",
                "citation": None,
                "source": {"media": str(src.get("media") or urlparse(secours).hostname).strip(),
                           "titre": str(src.get("titre") or urlparse(secours).hostname).strip(),
                           "url": secours, "date": d, "verification": "google"}}, ""
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
        google, appuis = [], {}
        for src in sources:
            a = adresse_reelle(src["uri"])
            if a and fiches.source_reconnue(a, domaines):
                google.append(a)
                appuis.setdefault(a, []).extend(src.get("appuis") or [])
        for m in (reponse.get("mesures") or [])[:5]:
            if len(gardees) >= fiches.MAX_MESURES or not isinstance(m, dict) or not m.get("titre"):
                continue
            if any(normaliser(m["titre"]) == normaliser(g["titre"]) for g in gardees):
                continue
            ok, raison = verifier_mesure(m, c, jour, settings, google, relire, appuis)
            if ok:
                essai = {"theme": theme["id"], "candidat": c["id"], "statut": "valide", "consulte_le": jour,
                         "mesures": gardees + [ok]}
                pb = fiches.problemes(essai, theme["id"], c["id"], settings)
                if pb:
                    raison, ok = "; ".join(pb), None
            if ok:
                gardees.append(ok)
                par = " · vérifiée via Google, page réservée" if ok["source"].get("verification") == "google" else ""
                journal.append(f"✅ {c['nom']} : {ok['titre']} ({ok['source']['media']}, {ok['source']['date']}{par})")
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
              "# vérifiée dans sa page source (verification: page) ou, si la page est réservée, par Google (verification: google).\n"
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
    rejets = compter_rejets(r["journal"])
    if rejets:
        lignes.append("✖️ Écartées : " + ", ".join(f"{n} {raison}" for raison, n in rejets))
    if r["supprimes"]:
        lignes.append(f"🧹 Anciennes fiches supprimées : {', '.join(r['supprimes'])}")
    return "\n".join(lignes)


def compter_rejets(journal: list[str]) -> list[tuple[str, int]]:
    """Combien de mesures écartées, et pourquoi (pour voir d'un coup d'œil quel contrôle bloque)."""
    from collections import Counter
    familles = Counter()
    for ligne in journal:
        if "écartée : " not in ligne:
            continue
        raison = ligne.split("écartée : ", 1)[1]
        cle = ("page bloquée" if "inaccessible" in raison or "bloquée" in raison else
               "source non reconnue" if "non reconnu" in raison else
               "date" if "date" in raison else "chiffres" if "chiffres" in raison else
               "candidat absent" if "cité" in raison else "relecture" if "relecture" in raison else "neutralité")
        familles[cle] += 1
    return familles.most_common()


def journal_json(r: dict) -> str:
    return json.dumps(r["journal"], ensure_ascii=False, indent=1)


def aujourdhui_paris() -> date:
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Europe/Paris")).date()
