"""Le calendrier : un thème par semaine, un candidat par jour, dans un ordre tiré au sort.

Le tirage est reproductible et vérifiable par tous : le mélange est fait par le générateur aléatoire de Python
initialisé avec « <thème>|<date du lundi> ». Personne ne choisit l'ordre, et on peut le refaire à l'identique.
"""
from __future__ import annotations

import random
from datetime import date, timedelta


def lundi(jour: date) -> date:
    return jour - timedelta(days=jour.weekday())


def numero_semaine(jour: date, settings: dict) -> int:
    """0 pour la semaine qui commence au lundi `calendrier.debut`."""
    return (lundi(jour) - settings["calendrier"]["debut"]).days // 7


def theme_de_la_semaine(jour: date, settings: dict, themes: list[dict]) -> dict | None:
    n = numero_semaine(jour, settings)
    if n < 0:
        return None
    return themes[n % len(themes)]


def _melange(theme_id: str, debut_semaine: date, candidats: list[dict], essai: int) -> list[dict]:
    ordre = sorted(candidats, key=lambda c: c["id"])
    graine = f"{theme_id}|{debut_semaine.isoformat()}" + (f"|{essai}" if essai else "")
    random.Random(graine).shuffle(ordre)
    return ordre


def tirage(theme_id: str, debut_semaine: date, candidats: list[dict], dernier_avant: str | None = None) -> list[dict]:
    """L'ordre de passage de la semaine (tirage au sort reproductible).
    Si le premier tiré est passé la veille (dernier de la semaine précédente), on retire : « |1 », « |2 »…"""
    for essai in range(50):
        ordre = _melange(theme_id, debut_semaine, candidats, essai)
        if len(ordre) < 2 or ordre[0]["id"] != dernier_avant:
            return ordre
    return ordre


def en_pause(jour: date, settings: dict) -> bool:
    return any(p["du"] <= jour <= p["au"] for p in settings["calendrier"].get("pauses") or [])


def ordre_de_la_semaine(lundi_: date, settings: dict, themes: list[dict], candidats: list[dict]) -> list[dict]:
    """Ordre de la semaine, en tenant compte du dernier candidat de la semaine précédente."""
    debut = settings["calendrier"]["debut"]
    dernier = None
    semaine = debut
    while True:
        theme = theme_de_la_semaine(semaine, settings, themes)
        ordre = tirage(theme["id"], semaine, candidats, dernier)
        if semaine >= lundi_:
            return ordre
        dernier = ordre[-1]["id"]
        semaine += timedelta(days=7)


def programme_du_jour(jour: date, settings: dict, themes: list[dict], candidats: list[dict]) -> dict | None:
    """Ce qui est prévu ce jour-là : thème, candidat, rang, et le candidat suivant (pour « Demain : … »)."""
    theme = theme_de_la_semaine(jour, settings, themes)
    if theme is None or en_pause(jour, settings):
        return None
    debut = lundi(jour)
    ordre = ordre_de_la_semaine(debut, settings, themes, candidats)
    rang = jour.weekday()
    if rang >= len(ordre):                     # moins de candidats que de jours (ex. second tour) : pas de vidéo
        return None
    if rang + 1 < len(ordre):
        suivant = {"candidat": ordre[rang + 1], "theme": theme, "meme_theme": True}
    else:
        prochain = theme_de_la_semaine(debut + timedelta(days=7), settings, themes)
        suivant = {"candidat": ordre_de_la_semaine(debut + timedelta(days=7), settings, themes, candidats)[0],
                   "theme": prochain, "meme_theme": False}
    return {"date": jour, "theme": theme, "candidat": ordre[rang], "rang": rang + 1, "total": len(ordre),
            "ordre": ordre, "suivant": suivant}
