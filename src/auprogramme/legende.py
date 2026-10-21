"""La légende de la publication : les mesures, les sources (liens complets), les crédits. Rien n'est rédigé par une IA."""
from __future__ import annotations

from .video import date_courte, date_longue

LIMITE = 2200                         # limite d'Instagram


def legende(prog: dict, fiche: dict, settings: dict, credit_photo: str | None, credit_musique: str | None) -> str:
    c, theme = prog["candidat"], prog["theme"]
    lignes = [f"{theme['nom']} · {prog['rang']}/{prog['total']} — {c['nom']} ({c['parti']})", ""]
    sources = []
    if fiche.get("aucune_proposition"):
        lignes += ["Pas de proposition vérifiable trouvée sur ce point à ce jour.",
                   f"(Recherche du {date_longue(fiche['consulte_le'])} : presse nationale, sites officiels, sites du "
                   "candidat et de son parti. Une proposition nous a échappé ? Écrivez-nous avec la source.)", ""]
    else:
        for i, m in enumerate(fiche["mesures"], 1):
            lignes.append(f"{i}. {m['titre']}")
            lignes.append(m["explication"])
            if m.get("citation"):
                lignes.append(f"« {m['citation']} »")
            s = m["source"]
            lignes.append(f"Source : {s['media']}, {date_courte(s['date'])}")
            lignes.append("")
            if s["url"] not in sources:
                sources.append(s["url"])
    suiv = prog["suivant"]
    if suiv["meme_theme"]:
        lignes.append(f"Demain : {suiv['candidat']['nom']}, sur le même thème.")
    else:
        lignes.append(f"Lundi, nouveau thème : {suiv['theme']['nom']}.")
    lignes += ["Ordre de passage tiré au sort chaque semaine. Nous résumons, sans commenter.",
               settings["marque"]["mention"], ""]
    if sources:
        lignes.append("📚 Sources :")
        lignes += sources
        lignes.append("")
    if credit_photo:
        lignes.append(f"📷 Photo : {credit_photo}")
    if credit_musique:
        lignes.append(f"🎵 Musique : {credit_musique}")
    tags = [*settings["instagram"].get("hashtags", []), theme.get("hashtag", "")]
    lignes += ["", " ".join(t for t in dict.fromkeys(tags) if t)]
    texte = "\n".join(lignes).strip()
    if len(texte) > LIMITE:
        raise ValueError(f"légende trop longue ({len(texte)} caractères, {LIMITE} maximum) : raccourcir la fiche")
    return texte
