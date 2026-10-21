# Fiches du thème « Pouvoir d'achat »

Une fiche par candidat. Publication automatique si toutes les sources sont reconnues (`config/settings.yaml`).
`statut: bloque` empêche la publication d'une fiche.

Règles (vérifiées automatiquement par `python -m auprogramme.pipeline verifier`) :
- 1 ou 2 mesures par candidat (même temps de parole pour tous) ;
- `titre` et `explication` : des faits, sans adjectif de jugement ni étiquette politique ;
- `citation` : facultative, recopiée **mot pour mot** depuis la source ;
- chaque mesure a sa source : média, titre, lien, date, sur un site reconnu (média professionnel, site officiel, site du candidat ou du parti) ;
- aucune proposition trouvée : `aucune_proposition: true` (la vidéo l'indique, le candidat garde son jour).
