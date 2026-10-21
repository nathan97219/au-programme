"""Photos des candidats, libres de droits, avec leur crédit (Wikipédia / Wikimedia Commons).

On prend l'image principale de la page Wikipédia du candidat, uniquement si elle est sous licence libre
(paramètre « pilicense=free »), puis on récupère sur Wikimedia Commons son auteur et sa licence.
Résultat : assets/candidats/<id>.jpg et assets/candidats/credits.yaml. Une photo sans crédit n'est jamais utilisée.

Wikimedia exige qu'un robot s'identifie (nom + contact) et limite les requêtes : on fait UNE requête groupée
pour tous les candidats, on respecte les demandes d'attente (429, Retry-After), et un échec ne bloque pas les autres.
"""
from __future__ import annotations

import html
import io
import re
import time

import requests
import yaml
from PIL import Image

from .config import ASSETS_DIR, load_candidats

# Format demandé par la politique de Wikimedia : NomDuRobot/version (adresse de contact) bibliothèque/version
ENTETES = {"User-Agent": f"AuProgrammeBot/1.1 (https://www.instagram.com/au.programme/; photos sous licence libre) "
                         f"python-requests/{requests.__version__}"}
WP = "https://fr.wikipedia.org/w/api.php"
COMMONS = "https://commons.wikimedia.org/w/api.php"
LICENCES_OK = ("cc0", "cc by", "cc-by", "public domain", "domaine public", "pd", "attribution")


def _get(url: str, params: dict | None = None, essais: int = 5) -> requests.Response:
    """GET poli : on attend et on réessaie quand Wikimedia demande de patienter."""
    attente = 5.0
    for _ in range(essais):
        r = requests.get(url, params=params, headers=ENTETES, timeout=60)
        if r.status_code in (429, 503):
            pause = float(r.headers.get("Retry-After") or attente)
            print(f"… Wikimedia demande de patienter ({r.status_code}) : {pause:.0f} s")
            time.sleep(min(pause, 120))
            attente *= 2
            continue
        r.raise_for_status()
        return r
    r.raise_for_status()
    return r


def _texte(valeur: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", valeur or ""))).strip()


def noms_des_images(titres: list[str]) -> dict[str, str]:
    """{titre Wikipédia: nom du fichier image libre}, en une seule requête."""
    r = _get(WP, {"action": "query", "format": "json", "formatversion": 2, "prop": "pageimages", "piprop": "name",
                  "pilicense": "free", "titles": "|".join(titres), "redirects": 1})
    q = r.json()["query"]
    vers = {t: t for t in titres}
    for n in q.get("normalized", []) + q.get("redirects", []):      # « titre demandé » → « titre réel »
        for k, v in list(vers.items()):
            if v == n["from"]:
                vers[k] = n["to"]
    images = {p["title"]: p.get("pageimage") for p in q.get("pages", [])}
    return {t: images.get(vers[t]) for t in titres if images.get(vers[t])}


def infos_fichiers(fichiers: list[str]) -> dict[str, dict]:
    """Adresse, auteur et licence de chaque fichier Commons, en une seule requête."""
    r = _get(COMMONS, {"action": "query", "format": "json", "formatversion": 2, "prop": "imageinfo",
                       "iiprop": "url|extmetadata", "iiurlwidth": 1000,
                       "titles": "|".join(f"File:{f}" for f in fichiers)})
    out = {}
    for p in r.json()["query"].get("pages", []):
        if not p.get("imageinfo"):
            continue
        info = p["imageinfo"][0]
        meta = info.get("extmetadata", {})
        auteur = _texte(meta.get("Artist", {}).get("value", ""))
        licence = _texte(meta.get("LicenseShortName", {}).get("value", ""))
        if not auteur or not any(l in licence.lower() for l in LICENCES_OK):
            continue
        nom = p["title"].split(":", 1)[1]
        out[nom.replace(" ", "_")] = out[nom] = {
            "fichier": nom, "url": info.get("thumburl") or info["url"], "page": info.get("descriptionurl"),
            "auteur": auteur, "licence": licence, "credit": f"{auteur}, {licence}, via Wikimedia Commons"}
    return out


def recuperer(candidats: list[dict] | None = None) -> dict:
    candidats = candidats or load_candidats()
    dossier = ASSETS_DIR / "candidats"
    dossier.mkdir(parents=True, exist_ok=True)
    fichier_credits = dossier / "credits.yaml"
    credits = (yaml.safe_load(fichier_credits.read_text(encoding="utf-8")) if fichier_credits.exists() else {}) or {}
    a_faire = [c for c in candidats if not (credits.get(c["id"]) or {}).get("manuel")]   # « manuel » : on n'y touche pas
    images = noms_des_images([c["wikipedia"] for c in a_faire])
    infos = infos_fichiers(sorted(set(images.values()))) if images else {}
    echecs = []
    for c in a_faire:
        nom = images.get(c["wikipedia"])
        info = infos.get(nom) or infos.get((nom or "").replace(" ", "_")) if nom else None
        if not info:
            print(f"⚠️ {c['nom']} : pas de photo libre trouvée (le monogramme sera affiché)")
            echecs.append(c["nom"])
            continue
        try:
            time.sleep(2)                                            # une image toutes les 2 secondes : poli
            img = Image.open(io.BytesIO(_get(info["url"]).content)).convert("RGB")
        except (requests.RequestException, OSError) as e:
            print(f"⚠️ {c['nom']} : téléchargement impossible ({e})")
            echecs.append(c["nom"])
            continue
        img.thumbnail((1000, 1250))
        img.save(dossier / f"{c['id']}.jpg", "JPEG", quality=88)
        credits[c["id"]] = {k: info[k] for k in ("fichier", "page", "auteur", "licence", "credit")}
        print(f"✅ {c['nom']} : {info['fichier']} ({info['licence']})")
    fichier_credits.write_text("# Généré par photos.py. « manuel: true » pour figer une photo choisie à la main.\n"
                               + yaml.safe_dump(credits, allow_unicode=True, sort_keys=True), encoding="utf-8")
    print(f"\n{len(a_faire) - len(echecs)}/{len(a_faire)} photos récupérées."
          + (f" Sans photo : {', '.join(echecs)} (relancer plus tard)." if echecs else ""))
    return credits
