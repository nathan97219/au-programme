"""Au Programme : la commande principale.

    python -m auprogramme.pipeline verifier [--semaine AAAA-MM-JJ]   contrôle de neutralité des fiches
    python -m auprogramme.pipeline calendrier [--semaines 4]          qui passe quand (tirage au sort)
    python -m auprogramme.pipeline apercu [--semaine AAAA-MM-JJ]      les 7 vidéos d'une semaine, pour relecture
    python -m auprogramme.pipeline publier [--date …] [--essai]       la vidéo du jour (fiche validée uniquement)
    python -m auprogramme.pipeline preparer-semaine [--semaine …]    le robot de recherche (fiches vérifiées)
    python -m auprogramme.pipeline photos                              photos libres de droits des candidats
    python -m auprogramme.pipeline instagram compte|renouveler
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import fiches
from .calendrier import lundi, programme_du_jour
from .config import DATA_DIR, OUTPUT_DIR, load_candidats, load_settings, load_themes

HISTORIQUE = DATA_DIR / "publications.json"
JOURS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]


def aujourd_hui(settings: dict) -> date:
    return datetime.now(ZoneInfo(settings["calendrier"].get("fuseau", "Europe/Paris"))).date()


def historique() -> list[dict]:
    return json.loads(HISTORIQUE.read_text(encoding="utf-8")) if HISTORIQUE.exists() else []


def noter(entree: dict) -> None:
    h = historique()
    h.append(entree)
    HISTORIQUE.parent.mkdir(parents=True, exist_ok=True)
    HISTORIQUE.write_text(json.dumps(h, ensure_ascii=False, indent=1), encoding="utf-8")


def _alerter(texte: str) -> None:
    """Message Telegram (facultatif : sans les secrets, on écrit seulement dans le journal)."""
    print(texte)
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat:
        import requests
        try:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=20,
                          data={"chat_id": chat, "text": texte})
        except requests.RequestException:
            pass


def _jour(args, settings) -> date:
    return date.fromisoformat(args.date) if getattr(args, "date", None) else aujourd_hui(settings)


def preparer(jour: date, settings: dict, themes: list, candidats: list, avec_voix: bool = True,
             exiger_validation: bool = True) -> dict | None:
    """Fiche du jour → contrôle → vidéo → légende. Rien n'est publié ici."""
    from .legende import legende
    from .video import fabriquer, photo
    prog = programme_du_jour(jour, settings, themes, candidats)
    if prog is None:
        print(f"Pas de vidéo prévue le {jour} (avant le début, pause ou jour sans candidat).")
        return None
    t, c = prog["theme"], prog["candidat"]
    fiche = fiches.charger(t["id"], c["id"])
    pb = fiches.problemes(fiche, t["id"], c["id"], settings)
    if pb:
        raise RuntimeError(f"Fiche {t['id']}/{c['id']} non conforme : " + " ; ".join(pb))
    if exiger_validation and fiche["statut"] == "bloque":
        raise RuntimeError(f"La fiche {t['id']}/{c['id']} est bloquée (statut : bloque) : rien n'est publié.")
    relecture = (settings.get("publication") or {}).get("validation_humaine", True)
    if exiger_validation and relecture and fiche["statut"] != "valide":
        raise RuntimeError(f"La fiche {t['id']}/{c['id']} n'est pas validée (statut : {fiche['statut']}). "
                           "Passer « statut: valide » après vérification.")
    dossier = OUTPUT_DIR / jour.isoformat()
    dossier.mkdir(parents=True, exist_ok=True)
    v = fabriquer(prog, fiche, settings, dossier / f"{t['id']}-{c['id']}.mp4", avec_voix=avec_voix)
    _, credit_photo = photo(c["id"])
    texte = legende(prog, fiche, settings, credit_photo, v.get("musique"))
    (dossier / "legende.txt").write_text(texte, encoding="utf-8")
    return {"prog": prog, "video": v["chemin"], "legende": texte, "duree": v["duree"], "voix": v["voix"]}


def cmd_verifier(args, settings, themes, candidats) -> int:
    jours = [lundi(date.fromisoformat(args.semaine))] if args.semaine else None
    themes_vus = ({programme_du_jour(j, settings, themes, candidats)["theme"]["id"] for j in jours}
                  if jours else {p.name for p in (Path(fiches.CONTENU_DIR)).iterdir() if p.is_dir()})
    erreurs = 0
    for theme_id in sorted(themes_vus):
        for cid, pb in fiches.verifier_theme(theme_id, candidats, settings).items():
            f = fiches.charger(theme_id, cid)
            etat = "✅" if not pb else "❌"
            statut = f" ({f['statut']})" if f else ""
            print(f"{etat} {theme_id}/{cid}{statut}" + "".join(f"\n     - {p}" for p in pb))
            erreurs += bool(pb)
    return 1 if erreurs else 0


def cmd_calendrier(args, settings, themes, candidats) -> int:
    debut = lundi(date.fromisoformat(args.date) if args.date else aujourd_hui(settings))
    for k in range(args.semaines * 7):
        j = debut + timedelta(days=k)
        p = programme_du_jour(j, settings, themes, candidats)
        if j.weekday() == 0:
            print(f"\nSemaine du {j} : {p['theme']['nom'] if p else '—'}")
        if p:
            f = fiches.charger(p["theme"]["id"], p["candidat"]["id"])
            statut = f["statut"] if f else "fiche manquante"
            print(f"  {JOURS[j.weekday()]} {j:%d/%m}  {p['rang']}/{p['total']}  {p['candidat']['nom']:<22} [{statut}]")
    return 0


def cmd_apercu(args, settings, themes, candidats) -> int:
    """Les vidéos d'une semaine entière, AVANT validation : pour relire et regarder."""
    debut = lundi(date.fromisoformat(args.semaine) if args.semaine else aujourd_hui(settings) + timedelta(days=7))
    for k in range(7):
        r = preparer(debut + timedelta(days=k), settings, themes, candidats, exiger_validation=False)
        if r:
            print(f"🎬 {r['video']} ({r['duree']} s, voix : {'oui' if r['voix'] else 'non'})")
    return 0


def cmd_publier(args, settings, themes, candidats) -> int:
    jour = _jour(args, settings)
    if not settings["instagram"].get("actif") and not args.essai:
        print("Instagram désactivé (config/settings.yaml → instagram.actif).")
        return 0
    if not args.essai and any(h["date"] == jour.isoformat() for h in historique()):
        print(f"Déjà publié le {jour} : rien à faire.")
        return 0
    try:
        r = preparer(jour, settings, themes, candidats, exiger_validation=not args.essai)
    except RuntimeError as e:
        _alerter(f"⛔ Au Programme ({jour}) : {e}")
        return 1
    if r is None:
        return 0
    print(r["legende"])
    from .publier_instagram import publier_video
    res = publier_video(r["video"], r["legende"], settings, publier=not args.essai)
    if args.essai:
        print(f"✅ Répétition réussie : Instagram a accepté la vidéo (non publiée). {res}")
        return 0
    p = r["prog"]
    noter({"date": jour.isoformat(), "theme": p["theme"]["id"], "candidat": p["candidat"]["id"],
           "media_id": res.get("media_id"), "lien": res.get("permalink")})
    print(f"✅ Publié : {res.get('permalink')}")
    return 0


def cmd_preparer_semaine(args, settings, themes, candidats) -> int:
    """Le robot de recherche : les fiches de la semaine suivante (ou de --semaine), vérifiées, + ménage."""
    from .recherche import aujourdhui_paris, preparer_semaine, resume
    jour = aujourdhui_paris()
    cible = lundi(date.fromisoformat(args.semaine)) if args.semaine else lundi(jour) + timedelta(days=7)
    r = preparer_semaine(cible, jour, settings, themes, candidats, refaire=args.refaire)
    print("\n".join(r["journal"]))
    texte = resume(r, cible)
    _alerter(texte)
    return 0


def cmd_photos(args, settings, themes, candidats) -> int:
    from .photos import recuperer
    recuperer(candidats)
    return 0


def cmd_instagram(args, settings, themes, candidats) -> int:
    from .publier_instagram import compte, renouveler_jeton
    if args.action == "compte":
        print(compte(settings))
    else:
        print(renouveler_jeton())
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="auprogramme")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("verifier"); s.add_argument("--semaine")
    s = sub.add_parser("calendrier"); s.add_argument("--date"); s.add_argument("--semaines", type=int, default=2)
    s = sub.add_parser("apercu"); s.add_argument("--semaine")
    s = sub.add_parser("publier"); s.add_argument("--date"); s.add_argument("--essai", action="store_true")
    s = sub.add_parser("preparer-semaine"); s.add_argument("--semaine"); s.add_argument("--refaire", action="store_true")
    sub.add_parser("photos")
    s = sub.add_parser("instagram"); s.add_argument("action", choices=["compte", "renouveler"])
    args = ap.parse_args(argv)
    settings, themes, candidats = load_settings(), load_themes(), load_candidats()
    return {"verifier": cmd_verifier, "calendrier": cmd_calendrier, "apercu": cmd_apercu, "publier": cmd_publier,
            "photos": cmd_photos, "preparer-semaine": cmd_preparer_semaine, "instagram": cmd_instagram}[args.cmd](args, settings, themes, candidats)


if __name__ == "__main__":
    sys.exit(main())
