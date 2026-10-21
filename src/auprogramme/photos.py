"""Photos des candidats, libres de droits, avec leur crédit (Wikipédia / Wikimedia Commons).

On prend l'image principale de la page Wikipédia du candidat, uniquement si elle est sous licence libre
(paramètre « pilicense=free »), puis on récupère sur Wikimedia Commons son auteur et sa licence.
Résultat : assets/candidats/<id>.jpg et assets/candidats/credits.yaml. Une photo sans crédit n'est jamais utilisée.
Lancé par le robot « Photos des candidats » (le réseau de GitHub y a accès) ; à relire avant de valider.
"""
from __future__ import annotations

import html
import io
import re

import requests
import yaml
from PIL import Image

from .config import ASSETS_DIR, load_candidats

ENTETES = {"User-Agent": "AuProgrammeBot/1.0 (compte Instagram @au.programme ; photos sous licence libre)"}
WP = "https://fr.wikipedia.org/w/api.php"
COMMONS = "https://commons.wikimedia.org/w/api.php"
LICENCES_OK = ("cc0", "cc by", "cc-by", "public domain", "domaine public", "pd", "attribution")


def _texte(valeur: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", valeur or ""))).strip()


def infos_photo(titre_wikipedia: str) -> dict | None:
    r = requests.get(WP, headers=ENTETES, timeout=30, params={
        "action": "query", "format": "json", "prop": "pageimages", "piprop": "name", "pilicense": "free",
        "titles": titre_wikipedia, "redirects": 1})
    r.raise_for_status()
    pages = r.json()["query"]["pages"]
    nom = next(iter(pages.values())).get("pageimage")
    if not nom:
        return None
    r = requests.get(COMMONS, headers=ENTETES, timeout=30, params={
        "action": "query", "format": "json", "titles": f"File:{nom}", "prop": "imageinfo",
        "iiprop": "url|extmetadata", "iiurlwidth": 1000})
    r.raise_for_status()
    info = next(iter(r.json()["query"]["pages"].values()))["imageinfo"][0]
    meta = info.get("extmetadata", {})
    auteur = _texte(meta.get("Artist", {}).get("value", ""))
    licence = _texte(meta.get("LicenseShortName", {}).get("value", ""))
    if not auteur or not any(l in licence.lower() for l in LICENCES_OK):
        return None
    return {"fichier": nom, "url": info.get("thumburl") or info["url"], "page": info.get("descriptionurl"),
            "auteur": auteur, "licence": licence,
            "credit": f"{auteur}, {licence}, via Wikimedia Commons"}


def recuperer(candidats: list[dict] | None = None) -> dict:
    dossier = ASSETS_DIR / "candidats"
    dossier.mkdir(parents=True, exist_ok=True)
    fichier_credits = dossier / "credits.yaml"
    credits = yaml.safe_load(fichier_credits.read_text(encoding="utf-8")) if fichier_credits.exists() else {}
    credits = credits or {}
    for c in candidats or load_candidats():
        if (credits.get(c["id"]) or {}).get("manuel"):          # photo choisie à la main : on n'y touche pas
            continue
        info = infos_photo(c["wikipedia"])
        if not info:
            print(f"⚠️ {c['nom']} : pas de photo libre trouvée (le monogramme sera affiché)")
            continue
        r = requests.get(info["url"], headers=ENTETES, timeout=60)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        img.thumbnail((1000, 1250))
        img.save(dossier / f"{c['id']}.jpg", "JPEG", quality=88)
        credits[c["id"]] = {k: info[k] for k in ("fichier", "page", "auteur", "licence", "credit")}
        print(f"✅ {c['nom']} : {info['fichier']} ({info['licence']})")
    fichier_credits.write_text("# Généré par photos.py. « manuel: true » pour figer une photo choisie à la main.\n"
                               + yaml.safe_dump(credits, allow_unicode=True, sort_keys=True), encoding="utf-8")
    return credits
