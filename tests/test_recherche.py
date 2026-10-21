"""Le robot de recherche : l'IA propose, le code vérifie. Pages et IA simulées (aucun accès réseau)."""
from datetime import date

import pytest

from auprogramme import fiches, recherche
from auprogramme.config import load_candidats, load_settings, load_themes

S, T, C = load_settings(), load_themes(), load_candidats()
JOUR = date(2026, 10, 28)
CAND = next(c for c in C if c["id"] == "retailleau")
THEME = {"id": "securite", "nom": "Sécurité"}
URL = "https://www.europe1.fr/politique/article-securite-123"

PAGE = """<html><head><title>Sécurité : les propositions de Bruno Retailleau</title>
<meta property="article:published_time" content="2026-10-10T08:00:00+02:00"></head>
<body><script>var x = 99999;</script><p>Bruno Retailleau propose de créer 10 000 places de prison supplémentaires.
« Nous construirons 10 000 places de prison d’ici 2032 », a-t-il déclaré.</p></body></html>"""

BONNE = {"titre": "Créer 10 000 places de prison supplémentaires", "explication": "D'ici 2032, selon sa proposition.",
         "citation": "Nous construirons 10 000 places de prison d'ici 2032",
         "source": {"media": "Europe 1", "titre": "x", "url": URL}}


@pytest.fixture(autouse=True)
def pages(monkeypatch):
    toile = {URL: PAGE}
    monkeypatch.setattr(recherche, "ouvrir", lambda u: (u, toile[u]) if u in toile else None)
    monkeypatch.setattr(recherche, "adresse_reelle", lambda u: u)
    monkeypatch.setattr(recherche.time, "sleep", lambda s: None)
    return toile


def verifier(m, relire=lambda p: True, jour=JOUR):
    return recherche.verifier_mesure(m, CAND, jour, S, [], relire)


def test_une_mesure_verifiee_est_gardee_avec_la_date_et_le_titre_de_la_page():
    m, raison = verifier(BONNE)
    assert raison == "" and m["source"]["date"] == date(2026, 10, 10)
    assert m["source"]["titre"] == "Sécurité : les propositions de Bruno Retailleau"
    assert m["citation"] == BONNE["citation"]                      # apostrophe droite/courbe : même phrase


def test_chiffre_invente_rejete():
    m, raison = verifier({**BONNE, "titre": "Créer 15 000 places de prison"})
    assert m is None and "15000" in raison


def test_citation_non_retrouvee_retiree_mais_mesure_gardee():
    m, _ = verifier({**BONNE, "citation": "Nous raserons gratis"})
    assert m is not None and m["citation"] is None


def test_site_non_reconnu_page_absente_date_ancienne_et_relecture_negative_rejetes():
    assert "non reconnue" in verifier({**BONNE, "source": {**BONNE["source"], "url": "https://www.elyseescope.com/x"}})[1]
    assert "inaccessible" in verifier({**BONNE, "source": {**BONNE["source"], "url": "https://www.europe1.fr/autre"}})[1]
    assert "trop ancienne" in verifier(BONNE, jour=date(2028, 1, 1))[1]
    assert "relecture" in verifier(BONNE, relire=lambda p: False)[1]


def test_candidat_absent_de_la_page_rejete(pages):
    pages[URL] = PAGE.replace("Bruno Retailleau", "Le ministre")
    assert "pas cité" in verifier(BONNE)[1]


def test_fiche_complete_et_jugement_rejete():
    mauvaise = {**BONNE, "titre": "Une mesure démagogique : 10 000 places de prison"}
    journal = []
    f = recherche.fiche_candidat(CAND, THEME, JOUR, S, lambda p: ({"mesures": [mauvaise, BONNE]}, []),
                                 lambda p: True, journal)
    assert [m["titre"] for m in f["mesures"]] == [BONNE["titre"]]
    assert any("démagog" in l for l in journal)
    assert not fiches.problemes(f, "securite", "retailleau", S)


def test_rien_de_verifiable_donne_aucune_proposition_jamais_une_invention():
    f = recherche.fiche_candidat(CAND, THEME, JOUR, S, lambda p: ({"mesures": [{**BONNE, "titre": "Créer 99 prisons"}]}, []),
                                 lambda p: True, [])
    assert f["aucune_proposition"] is True and f["mesures"] == []


def test_la_recherche_peut_utiliser_une_source_trouvee_par_google():
    """L'adresse donnée par l'IA est fausse, mais Google a bien consulté la bonne page : on la vérifie."""
    fausse = {**BONNE, "source": {**BONNE["source"], "url": "https://www.europe1.fr/inexistante"}}
    m, _ = recherche.verifier_mesure(fausse, CAND, JOUR, S, [URL], lambda p: True)
    assert m and m["source"]["url"] == URL


def test_preparer_semaine_ecrit_les_7_fiches_et_fait_le_menage(tmp_path, monkeypatch):
    monkeypatch.setattr(fiches, "CONTENU_DIR", tmp_path)
    monkeypatch.setattr(recherche, "CONTENU_DIR", tmp_path)
    (tmp_path / "vieux-theme").mkdir()
    (tmp_path / "vieux-theme" / "x.yaml").write_text("a: 1")
    lundi = S["calendrier"]["debut"]
    from datetime import timedelta
    r = recherche.preparer_semaine(lundi + timedelta(days=7), JOUR, S, T, C,
                                   chercher=lambda p: ({"mesures": []}, []), relire=lambda p: True)
    assert len(r["faites"]) == 7 and "vieux-theme" in r["supprimes"]
    theme = r["theme"]["id"]
    for c in C:
        f = fiches.charger(theme, c["id"])
        assert f["aucune_proposition"] is True and not fiches.problemes(f, theme, c["id"], S)
    assert "aucune proposition vérifiable" in recherche.resume(r, lundi)


def test_nombres():
    assert recherche.nombres("1 000 euros, 5,5 % et 200 000 €") == ["1000", "5,5", "200000"]
    assert recherche.nombres_presents("dès le 1er enfant", "dès le premier enfant") == []
