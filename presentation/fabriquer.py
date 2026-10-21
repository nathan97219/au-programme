"""Vidéo de présentation d'Au Programme : texte animé calé sur le tempo de la musique (sans voix off).

    python presentation/fabriquer.py            → presentation/Au-Programme-presentation.mp4
    python presentation/fabriquer.py 3 12 25    → images de contrôle aux secondes indiquées
"""
import random
import subprocess
import sys
import tempfile
from pathlib import Path

import imageio_ffmpeg
from jinja2 import Environment, FileSystemLoader

ICI = Path(__file__).parent
RACINE = ICI.parent
IPS = 30
MUSIQUE = RACINE / "assets" / "musique" / "heroes-tonight-slowed.mp3"
CREDIT = "Johnning, Janji - Heroes Tonight (Slowed) [NCS Release] · Music provided by NoCopyrightSounds"
BPM, PREMIER_TEMPS = 117.5, 0.16
NB_TEMPS = 64

# Ordre alphabétique (nom de famille) : aucun candidat mis en avant.
CANDIDATS = ["Raphaël Glucksmann", "Marine Le Pen", "Jean-Luc Mélenchon", "Édouard Philippe",
             "Bruno Retailleau", "Marine Tondelier", "Éric Zemmour"]


def nom_court(c: str) -> str:
    return c.split(" ", 1)[1] if not c.startswith("Jean-Luc") else "Mélenchon"


def fabriquer(apercu=None):
    from playwright.sync_api import sync_playwright
    total = NB_TEMPS * 60 / BPM
    courts = [nom_court(c) for c in CANDIDATS]
    ordre = courts[:]
    random.Random(2027).shuffle(ordre)          # illustration du tirage (le vrai tirage est fait chaque semaine)
    html = Environment(loader=FileSystemLoader(str(ICI))).get_template("presentation.html").render(
        polices=(RACINE / "assets" / "fonts").resolve().as_uri(), candidats=CANDIDATS,
        donnees={"bpm": BPM, "total": total, "noms_courts": courts, "ordre": ordre})
    sortie = ICI / "Au-Programme-presentation.mp4"
    with tempfile.TemporaryDirectory() as tmp:
        page_f = Path(tmp) / "p.html"
        page_f.write_text(html, encoding="utf-8")
        with sync_playwright() as p:
            nav = p.chromium.launch()
            page = nav.new_page(viewport={"width": 1080, "height": 1920})
            page.goto(page_f.as_uri())
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(300)
            if apercu:
                for x in apercu:
                    page.evaluate(f"poser({x})")
                    page.screenshot(path=str(ICI / f"apercu_{x}.jpg"), type="jpeg", quality=80)
                nav.close()
                return
            cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
                   "-f", "image2pipe", "-framerate", str(IPS), "-c:v", "mjpeg", "-i", "-",
                   "-ss", f"{PREMIER_TEMPS:.3f}", "-i", str(MUSIQUE), "-filter_complex",
                   f"[1:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS,volume=0.9,afade=t=in:d=0.4,"
                   f"afade=t=out:st={total - 2.2:.3f}:d=2.2[a]",
                   "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high",
                   "-preset", "medium", "-crf", "19", "-r", str(IPS), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                   "-movflags", "+faststart", "-t", f"{total:.3f}", str(sortie)]
            enc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
            for n in range(int(total * IPS)):
                page.evaluate(f"poser({n / IPS:.4f})")
                enc.stdin.write(page.screenshot(type="jpeg", quality=92))
            enc.stdin.close()
            nav.close()
            if enc.wait():
                raise SystemExit("ffmpeg a échoué")
    print(sortie, f"{total:.1f} s")


if __name__ == "__main__":
    fabriquer([float(x) for x in sys.argv[1:]] or None)
