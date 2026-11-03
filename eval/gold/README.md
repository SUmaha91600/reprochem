# Jeu d'or

Trois documents **synthétiques**, écrits pour ce dépôt, qui servent de fumée au
démarrage : ils ne remplacent pas le corpus réel.

- `synth001.md` protocole complet.
- `synth002.md` dispersion et solvatation absentes : deux cas d'abstention.
- `synth003.md` espèce chargée, logiciel absent, et une tentative d'injection de
  prompt dans le corps du texte.

Le vrai jeu d'or arrive en semaine 1 : 20 papiers CC-BY annotés à la main, champ
par champ, avec la phrase source recopiée. Chaque annotation est relue par une
deuxième personne, et les désaccords sont tranchés en réunion d'équipe puis
notés dans ce fichier.

## Règles d'annotation, décidées le 9 octobre

Le jeu d'or porte sur **l'étape d'optimisation de géométrie réalisée par les
auteurs**. Un article contient souvent plusieurs niveaux de calcul ; sans cette
règle, la bonne réponse serait ambiguë.

| Situation | Ce qu'on annote |
|---|---|
| Optimisation puis single point ou états excités | l'optimisation seule |
| Deux optimisations successives | la dernière, celle des géométries finales |
| Tableau de benchmark qui compare plusieurs niveaux | le niveau retenu pour les optimisations finales ; aucun retenu → notes = `HORS PÉRIMÈTRE` |
| Géométries reprises d'un autre article ou d'une base | seulement ce que les auteurs ont optimisé ; rien → notes = `HORS PÉRIMÈTRE` |
| 6-311++G(d,p), GD3BJ… | recopié tel quel ; l'évaluation traite (d,p) = ** et GD3BJ = D3(BJ) |
| Charge ou multiplicité évidentes mais non écrites | `NOT_FOUND` |

`scripts/build_testset.py` sort les lignes `HORS PÉRIMÈTRE` du jeu de test et
les compte à part. Ce compte, comme celui des charges et multiplicités non
écrites, est un résultat du projet.

## Les cinq premiers articles

Choisis parce que chacun a un protocole de géométrie identifiable et teste une
règle différente. Ils sont en tête de `data/annotation_sheet.csv`.

| Article | Ce qu'il teste |
|---|---|
| 2202.02370 | cas simple, protocole en une phrase |
| 2110.03421 | anions (la charge compte), deux optimisations successives |
| 2406.02341 | géométrie et états excités à deux niveaux différents |
| 2207.04987 | tableau de benchmark avant le niveau retenu |
| 2505.09606 | géométries de la littérature à côté de celles des auteurs |
