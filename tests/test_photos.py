"""Photos : une requête groupée, patience face aux limites de Wikimedia, un échec ne bloque pas les autres."""
import io

import pytest
from PIL import Image

from auprogramme import photos


class Rep:
    def __init__(self, code=200, data=None, content=b"", headers=None):
        self.status_code, self._data, self.content, self.headers = code, data, content, headers or {}

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise photos.requests.HTTPError(str(self.status_code))


def test_photos_groupees_avec_patience_et_echec_isole(tmp_path, monkeypatch):
    monkeypatch.setattr(photos, "ASSETS_DIR", tmp_path)
    monkeypatch.setattr(photos.time, "sleep", lambda s: None)
    jpeg = io.BytesIO(); Image.new("RGB", (40, 50), "grey").save(jpeg, "JPEG")
    appels = []

    def faux_get(url, params=None, headers=None, timeout=None):
        appels.append(url)
        assert "AuProgrammeBot" in headers["User-Agent"] and "(" in headers["User-Agent"]   # robot identifié
        if url == photos.WP:
            if appels.count(photos.WP) == 1:
                return Rep(429, headers={"Retry-After": "1"})                               # « patientez »
            return Rep(data={"query": {"normalized": [{"from": "Bruno_Retailleau", "to": "Bruno Retailleau"}],
                                       "pages": [{"title": "Bruno Retailleau", "pageimage": "Retailleau_2024.jpg"},
                                                 {"title": "Éric Zemmour"}]}})
        if url == photos.COMMONS:
            return Rep(data={"query": {"pages": [{"title": "File:Retailleau 2024.jpg", "imageinfo": [{
                "url": "https://upload.wikimedia.org/r.jpg", "descriptionurl": "https://commons.wikimedia.org/x",
                "extmetadata": {"Artist": {"value": "<a>Jean Dupont</a>"}, "LicenseShortName": {"value": "CC BY-SA 4.0"}}}]}]}})
        return Rep(content=jpeg.getvalue())
    monkeypatch.setattr(photos.requests, "get", faux_get)
    c = [{"id": "retailleau", "nom": "Bruno Retailleau", "wikipedia": "Bruno_Retailleau"},
         {"id": "zemmour", "nom": "Éric Zemmour", "wikipedia": "Éric Zemmour"}]
    credits = photos.recuperer(c)
    assert appels.count(photos.WP) == 2 and appels.count(photos.COMMONS) == 1         # requêtes groupées
    assert credits["retailleau"]["credit"] == "Jean Dupont, CC BY-SA 4.0, via Wikimedia Commons"
    assert (tmp_path / "candidats" / "retailleau.jpg").exists() and "zemmour" not in credits
