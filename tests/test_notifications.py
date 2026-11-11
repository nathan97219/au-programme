"""Messages du robot dans des tickets GitHub (API simulée, aucun accès réseau)."""
from auprogramme import notifications as notif


def test_sans_github_le_message_est_seulement_affiche(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert notif.signaler("coucou") is None
    assert "coucou" in capsys.readouterr().out


def test_un_ticket_par_sujet_puis_des_commentaires(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "moi/depot")
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setenv("GITHUB_REPOSITORY_OWNER", "moi")
    tickets, appels = [], []

    def appel(methode, chemin, **kw):
        appels.append((methode, chemin, kw.get("json")))
        if methode == "GET":
            return [{"number": n, "title": t} for n, t in tickets]
        if methode == "POST" and chemin == "/issues":
            tickets.append((len(tickets) + 1, kw["json"]["title"]))
            return {"number": len(tickets)}
        return {}

    monkeypatch.setattr(notif, "_appel", appel)
    assert notif.signaler("premier") == 1
    assert notif.signaler("second") == 1                     # même sujet : commentaire dans le même ticket
    assert appels[1][2]["body"].startswith("@moi premier")
    assert appels[-1][1] == "/issues/1/comments" and appels[-1][2]["body"] == "@moi second"


def test_une_panne_de_github_ne_bloque_jamais(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "moi/depot")
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setattr(notif, "_appel", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("500")))
    assert notif.signaler("alerte") is None
