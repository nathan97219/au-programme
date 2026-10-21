"""Tests d'Au Programme : calendrier équitable, fiches conformes, textes, légende."""
from datetime import date, timedelta
from pathlib import Path

import pytest

from auprogramme import fiches
from auprogramme.calendrier import programme_du_jour, tirage
from auprogramme.config import CONTENU_DIR, load_candidats, load_settings, load_themes
from auprogramme.legende import legende
from auprogramme.video import chronologie, phrases, pour_la_voix

S, T, C = load_settings(), load_themes(), load_candidats()
DEBUT = S["calendrier"]["debut"]
EXEMPLES = Path(__file__).parent / "donnees"        # fiches d'exemple figées (le vrai contenu, lui, est renouvelé)


@pytest.fixture
def exemples(monkeypatch):
    """Les tests du circuit utilisent des fiches d'exemple, indépendantes de contenu/ (qui est nettoyé chaque semaine)."""
    monkeypatch.setattr(fiches, "CONTENU_DIR", EXEMPLES)


def test_le_calendrier_commence_un_lundi_et_chaque_candidat_passe_une_fois_par_semaine():
    assert DEBUT.weekday() == 0
    for semaine in range(20):
        lundi = DEBUT + timedelta(weeks=semaine)
        vus = [programme_du_jour(lundi + timedelta(days=k), S, T, C)["candidat"]["id"] for k in range(7)]
        assert sorted(vus) == sorted(c["id"] for c in C)
        themes = {programme_du_jour(lundi + timedelta(days=k), S, T, C)["theme"]["id"] for k in range(7)}
        assert len(themes) == 1


def test_jamais_le_meme_candidat_deux_jours_de_suite():
    jours = [DEBUT + timedelta(days=k) for k in range(7 * 40)]
    ids = [programme_du_jour(j, S, T, C)["candidat"]["id"] for j in jours]
    assert all(a != b for a, b in zip(ids, ids[1:]))


def test_le_tirage_est_reproductible_et_change_chaque_semaine():
    a = [c["id"] for c in tirage("pouvoir-d-achat", DEBUT, C)]
    assert a == [c["id"] for c in tirage("pouvoir-d-achat", DEBUT, list(reversed(C)))]   # l'ordre du fichier ne compte pas
    assert a != [c["id"] for c in tirage("securite", DEBUT + timedelta(weeks=1), C)]


def test_personne_n_est_toujours_premier():
    """Sur un an, chaque candidat ouvre la semaine au moins une fois, et personne plus de 2 fois sur 3 la moyenne × 2."""
    premiers = [programme_du_jour(DEBUT + timedelta(weeks=k), S, T, C)["candidat"]["id"] for k in range(52)]
    compte = {c["id"]: premiers.count(c["id"]) for c in C}
    assert min(compte.values()) >= 1 and max(compte.values()) <= 2 * 52 / len(C)


def test_rien_avant_le_debut_ni_pendant_une_pause():
    assert programme_du_jour(DEBUT - timedelta(days=1), S, T, C) is None
    avec_pause = {**S, "calendrier": {**S["calendrier"], "pauses": [{"du": DEBUT, "au": DEBUT + timedelta(days=1)}]}}
    assert programme_du_jour(DEBUT + timedelta(days=1), avec_pause, T, C) is None
    assert programme_du_jour(DEBUT + timedelta(days=2), avec_pause, T, C) is not None


def test_le_dimanche_annonce_le_theme_suivant():
    p = programme_du_jour(DEBUT + timedelta(days=6), S, T, C)
    assert not p["suivant"]["meme_theme"] and p["suivant"]["theme"]["id"] == T[1]["id"]


@pytest.mark.parametrize("theme", sorted(p.name for p in CONTENU_DIR.iterdir() if p.is_dir()) or ["(aucun)"])
def test_toutes_les_fiches_sont_conformes(theme):
    if theme == "(aucun)":
        pytest.skip("pas encore de fiches")
    pbs = fiches.verifier_theme(theme, C, S)
    assert all(not pb for pb in pbs.values()), pbs


def test_le_controle_attrape_jugements_etiquettes_et_sources_manquantes():
    f = {"theme": "t", "candidat": "x", "statut": "valide", "consulte_le": date(2026, 10, 21), "mesures": [
        {"titre": "Une mesure démagogique de la droite", "explication": "Malheureusement irréaliste.",
         "source": {"media": "M", "titre": "T", "url": "http://pas-securise", "date": date(2026, 11, 1)}}]}
    pb = " | ".join(fiches.problemes(f, "t", "x"))
    for attendu in ("démagog", "droite", "malheureusement", "irréaliste", "https", "après la vérification"):
        assert attendu in pb
    assert fiches.problemes(None, "t", "x")[0].startswith("fiche manquante")
    trop = {**f, "mesures": [f["mesures"][0]] * 3}
    assert any("entre 1 et 2" in p for p in fiches.problemes(trop, "t", "x"))


def test_publication_sans_relecture_mais_jamais_une_fiche_bloquee_ou_mal_sourcee(tmp_path, monkeypatch, exemples):
    from auprogramme import pipeline
    monkeypatch.setattr(pipeline, "HISTORIQUE", tmp_path / "h.json")
    envoyes = []
    monkeypatch.setattr(pipeline, "_alerter", envoyes.append)
    fabriques = []
    import auprogramme.video as video
    monkeypatch.setattr(video, "fabriquer", lambda *a, **k: fabriques.append(1) or {"chemin": tmp_path / "v.mp4", "duree": 30,
                                                                                    "voix": True, "musique": None})
    publies = []
    import auprogramme.publier_instagram as pi
    monkeypatch.setattr(pi, "publier_video", lambda v, l, s, publier=True: publies.append(l) or {"media_id": "1"})
    monkeypatch.setattr(pipeline, "OUTPUT_DIR", tmp_path)

    class Args:
        date, essai = DEBUT.isoformat(), False
    vraie = fiches.charger
    assert S["publication"]["validation_humaine"] is False
    # 1) fiche « a_valider » mais bien sourcée : publiée directement
    monkeypatch.setattr(fiches, "charger", lambda t, c: {**vraie(t, c), "statut": "a_valider"})
    assert pipeline.cmd_publier(Args, S, T, C) == 0 and len(publies) == 1
    # 2) fiche bloquée : jamais publiée
    (tmp_path / "h.json").unlink()
    monkeypatch.setattr(fiches, "charger", lambda t, c: {**vraie(t, c), "statut": "bloque"})
    assert pipeline.cmd_publier(Args, S, T, C) == 1 and "bloquée" in envoyes[-1] and len(publies) == 1
    # 3) une source hors de la liste (agrégateur) : jamais publiée
    def mal_sourcee(t, c):
        f = vraie(t, c)
        m = [{**x, "source": {**x["source"], "url": "https://www.elyseescope.com/page"}} for x in f.get("mesures") or []]
        return {**f, "mesures": m}
    monkeypatch.setattr(fiches, "charger", mal_sourcee)
    p = programme_du_jour(DEBUT, S, T, C)
    if vraie(p["theme"]["id"], p["candidat"]["id"]).get("mesures"):
        assert pipeline.cmd_publier(Args, S, T, C) == 1 and "source non reconnue" in envoyes[-1] and len(publies) == 1


def test_sources_reconnues():
    d = fiches.domaines_reconnus(S)
    assert fiches.source_reconnue("https://www.publicsenat.fr/x", d)
    assert fiches.source_reconnue("https://fr.euronews.com/x", d)
    assert not fiches.source_reconnue("https://www.elyseescope.com/x", d)
    assert not fiches.source_reconnue("https://publicsenat.fr.pirate.com/x", d)


def test_voix_et_scenes(exemples):
    assert pour_la_voix("De 20 % à 5,5 % · 350 € dès le 1er enfant") == "De 20 pour cent à 5,5 pour cent · 350 euros dès le premier enfant"
    p = programme_du_jour(DEBUT, S, T, C)
    f = fiches.charger(p["theme"]["id"], p["candidat"]["id"])
    sc = phrases(p, f)
    assert sc[0]["type"] == "intro" and sc[-1]["type"] == "fin" and p["candidat"]["nom"] in sc[0]["voix"]
    temps = chronologie(sc, None)
    assert all(b["debut"] == a["fin"] for a, b in zip(temps, temps[1:])) and 15 < temps[-1]["fin"] < 60


def test_legende_complete_et_sous_la_limite(exemples):
    for k in range(7):
        p = programme_du_jour(DEBUT + timedelta(days=k), S, T, C)
        f = fiches.charger(p["theme"]["id"], p["candidat"]["id"])
        t = legende(p, f, S, "Auteur, CC BY-SA 4.0, via Wikimedia Commons", "Morceau [NCS Release]")
        assert p["candidat"]["nom"] in t and p["candidat"]["parti"] in t and S["marque"]["mention"] in t
        for m in f.get("mesures") or []:
            assert m["source"]["url"] in t and m["titre"] in t
        assert len(t) <= 2200


def test_aucune_etiquette_politique_dans_les_textes_affiches():
    """Ni la maquette ni les textes fixes n'affichent « gauche », « droite », « extrême »…"""
    gabarit = (Path(__file__).parents[1] / "src" / "auprogramme" / "templates" / "video.html").read_text(encoding="utf-8")
    import re
    visible = re.sub(r"<style>.*?</style>|<script>.*?</script>", "", gabarit, flags=re.S).lower()
    for mot in ("gauche", "droite", "extrême", "centre"):
        assert mot not in visible


def test_les_fiches_d_exemple_sont_conformes(exemples):
    for k in range(7):
        p = programme_du_jour(DEBUT + timedelta(days=k), S, T, C)
        f = fiches.charger(p["theme"]["id"], p["candidat"]["id"])
        assert f["statut"] != "bloque" and not fiches.problemes(f, p["theme"]["id"], p["candidat"]["id"], S)
