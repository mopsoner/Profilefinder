# Ads Studio

Page Ads de ProfileFinder, intégrée à la navigation et au thème commun de l’application.

## Démarrage

Depuis `/workspace/Profilefinder` :

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
bash scripts/start.sh
```

La page est servie sur le port 8000, route `/ads`, avec le dashboard, les prospects et Sites IA. `APP_PORT` et `APP_HOST` permettent de modifier l’écoute. Le serveur autonome historique `ads/server.py` reste disponible pour tester Ads seul ; utiliser l’application complète pour naviguer entre les modules. Ajouter authentification, quotas et limites de concurrence avant toute exposition publique.

Python 3.10+, FFmpeg et ffprobe sont nécessaires. Le mixage utilise la durée de la voix, répète la musique si nécessaire, applique des fondus à la musique, un ducking optionnel et un limiteur avant export MP3 192 kb/s. Fichiers limités à 20 Mo chacun ; voix de 5 minutes maximum. Les fichiers de travail sont temporaires et supprimés après traitement.

## Génération vocale : OpenAI par défaut

Ads réutilise `OPENAI_API_KEY` via la configuration existante de ProfileFinder (`.env` ou variable du serveur). Aucune seconde clé OpenAI n’est nécessaire. Le moteur par défaut est `gpt-4o-mini-tts`, configurable avec `OPENAI_TTS_MODEL` ; il est distinct du modèle de génération de sites. La page propose un choix de voix, des consignes de ton et un téléchargement MP3 après mixage. La synthèse utilise `api.openai.com/v1/audio/speech`.

ElevenLabs reste une option explicitement sélectionnable : définir `ELEVENLABS_API_KEY`, redémarrer et fournir un Voice ID accessible au compte. La configuration est lue depuis `.env` ou les variables du serveur. Autoriser `api.elevenlabs.io` si cette option est utilisée.

Les clés restent côté serveur. Les appels consomment les crédits du fournisseur sélectionné ; aucune bascule automatique vers un autre fournisseur n’est effectuée en cas d’erreur. Le texte vocal est limité à 4 096 caractères. L’import audio reste disponible sans clé. Le serveur autonome utilise aussi la configuration de ProfileFinder et se lance avec `.venv/bin/python ads/server.py`.

## Périmètre

- Interface française responsive, profil d’entreprise modifiable, génération de script OpenAI à partir du dossier du prospect, copie et estimation de durée.
- Génération vocale OpenAI par défaut et ElevenLabs en option, si configurés, import et écoute de voix, import de musique, volumes, ducking et export MP3 réel avec FFmpeg.
- Le formulaire Ads permet de sélectionner un lead réel ou un profil libre. La voix générée et le mix sont automatiquement sauvegardés avec leur texte exact pour le lead sélectionné. **Ouvrir cet audio et son message dans Video Ads** ouvre le studio vidéo sans créer de doublon. Le message y est automatiquement chargé pour l’audio sélectionné. La génération du message utilise OpenAI avec le profil, les avis, les analyses et le site du prospect ; le résultat reste éditable.
- Les réglages et brouillons non enregistrés restent en mémoire dans la page. Les voix générées et mixes liés à un lead sont sauvegardés sur le serveur avec leur message ; les profils libres sans lead ne sont pas sauvegardés automatiquement. Un échec de sauvegarde est signalé et peut être réessayé avec le mix.
- Les polices Google sont facultatives ; des polices système prennent le relais sans accès réseau.

Ne pas créer de worktree pour utiliser ce dépôt : chaque tâche cloud dispose déjà de son environnement isolé.

## Design partagé

`shared/theme.css` contient le thème Ads commun, `shared/layout.js` la navigation, l’en-tête et le pied de page. Les pages métier héritent de `app/templates/base.html` et leurs composants sont dans `app/static/style.css`, sous `.site-page` pour préserver le studio audio. Les sites vitrines générés pour les clients conservent leur identité propre.
