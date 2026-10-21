"""Les fiches (contenu/<thème>/<candidat>.yaml) et le contrôle de neutralité.

Le robot ne rédige RIEN : tout le texte vient des fiches, écrites et relues par un humain.
Ce module vérifie que chaque fiche respecte les règles communes, pour que tous les candidats soient traités pareil.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import yaml

from .config import CONTENU_DIR

MAX_MESURES = 2                 # même temps de parole pour tous
LIMITES = {"titre": 70, "explication": 170, "citation": 170}
STATUTS = ("a_valider", "valide", "bloque")

# Mots interdits dans le texte écrit par nous (titre, explication) : étiquettes politiques et jugements.
# Les citations, elles, sont les mots du candidat : on ne les touche pas.
INTERDITS = [
    "gauche", "droite", "extrême", "extreme", "centriste", "populiste", "radical", "radicale",
    "démagog", "irréaliste", "irrealiste", "absurde", "dangereu", "courageu", "ambitieu", "audacieu",
    "utopi", "farfelu", "scandaleu", "honteu", "excellent", "mauvais", "bonne idée", "mauvaise idée",
    "malheureusement", "heureusement", "enfin", "seulement", "évidemment", "bien sûr", "hélas",
    "promet", "prétend", "affirme",
]


def domaines_reconnus(settings: dict | None) -> list[str]:
    if not settings:
        return []
    groupes = (settings.get("publication") or {}).get("sources_reconnues") or {}
    return [d.lower().strip() for liste in groupes.values() for d in liste or []]


def source_reconnue(url: str, domaines: list[str]) -> bool:
    from urllib.parse import urlparse
    hote = (urlparse(url).hostname or "").lower()
    return any(hote == d or hote.endswith("." + d) for d in domaines)


def chemin(theme_id: str, candidat_id: str) -> Path:
    return CONTENU_DIR / theme_id / f"{candidat_id}.yaml"


def charger(theme_id: str, candidat_id: str) -> dict | None:
    p = chemin(theme_id, candidat_id)
    if not p.exists():
        return None
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def _texte(v) -> str:
    return "" if v is None else str(v).strip()


def problemes(fiche: dict | None, theme_id: str, candidat_id: str, settings: dict | None = None) -> list[str]:
    """La liste des problèmes d'une fiche (vide = conforme). Avec `settings` : chaque source doit être reconnue."""
    domaines = domaines_reconnus(settings)
    if fiche is None:
        return [f"fiche manquante : {chemin(theme_id, candidat_id).relative_to(CONTENU_DIR.parent)}"]
    out = []
    if fiche.get("theme") != theme_id or fiche.get("candidat") != candidat_id:
        out.append("« theme » ou « candidat » ne correspond pas au nom du fichier")
    if fiche.get("statut") not in STATUTS:
        out.append(f"statut inconnu (attendu : {' ou '.join(STATUTS)})")
    consulte = fiche.get("consulte_le")
    if not isinstance(consulte, date):
        out.append("« consulte_le » manquant (date à laquelle les sources ont été vérifiées)")
    mesures = fiche.get("mesures") or []
    if fiche.get("aucune_proposition"):
        if mesures:
            out.append("« aucune_proposition » et des mesures en même temps")
        return out
    if not 1 <= len(mesures) <= MAX_MESURES:
        out.append(f"il faut entre 1 et {MAX_MESURES} mesures (ou « aucune_proposition: true »)")
    for i, m in enumerate(mesures, 1):
        nom = f"mesure {i}"
        for champ, limite in LIMITES.items():
            t = _texte(m.get(champ))
            if champ != "citation" and not t:
                out.append(f"{nom} : « {champ} » vide")
            if len(t) > limite:
                out.append(f"{nom} : « {champ} » trop long ({len(t)} caractères, {limite} maximum)")
        ecrit = f"{_texte(m.get('titre'))} {_texte(m.get('explication'))}".lower()
        for mot in INTERDITS:
            if re.search(rf"(?<![a-zà-ÿ]){re.escape(mot)}", ecrit):
                out.append(f"{nom} : mot à éviter « {mot} » (étiquette ou jugement) dans le titre ou l'explication")
        s = m.get("source") or {}
        if not _texte(s.get("media")) or not _texte(s.get("titre")):
            out.append(f"{nom} : source incomplète (média et titre)")
        if not str(s.get("url", "")).startswith("https://"):
            out.append(f"{nom} : lien de la source manquant ou non sécurisé (https)")
        elif domaines and not source_reconnue(s["url"], domaines):
            out.append(f"{nom} : source non reconnue ({s['url'].split('/')[2]}) : uniquement médias professionnels, "
                       "sites officiels, ou sites des candidats et partis (config/settings.yaml)")
        d = s.get("date")
        if not isinstance(d, date):
            out.append(f"{nom} : date de la source manquante")
        elif isinstance(consulte, date) and d > consulte:
            out.append(f"{nom} : source datée après la vérification")
    return out


def verifier_theme(theme_id: str, candidats: list[dict], settings: dict | None = None) -> dict[str, list[str]]:
    """Problèmes par candidat pour tout un thème (chaque candidat doit avoir sa fiche)."""
    return {c["id"]: problemes(charger(theme_id, c["id"]), theme_id, c["id"], settings) for c in candidats}
