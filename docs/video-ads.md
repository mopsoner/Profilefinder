# Video Ads

Page `/video-ads`, accessible depuis la navigation commune. Le format par défaut est vertical **1080 × 1920 (9:16)**. Formats supplémentaires : **1920 × 1080 (16:9)** et **1080 × 1080 (1:1)**.

## Parcours

1. Dans Ads, choisir un lead et préparer le script. Une voix générée est automatiquement enregistrée avec le texte exact envoyé au moteur vocal. Le mix final est lui aussi sauvegardé automatiquement avec ce message. Cliquer sur **Ouvrir cet audio et son message dans Video Ads** pour le retrouver dans le studio vidéo. Si une sauvegarde échoue, le bouton permet de la réessayer. Les fichiers téléchargés avant cette fonctionnalité peuvent être importés dans Video Ads avec leur texte de voix off.
2. Dans Sites IA, générer le site du même lead si nécessaire.
3. L’étape **Préparer mon message** peut générer un nouveau texte via OpenAI en utilisant le profil, les avis, les analyses et le site enregistrés. Le texte reste modifiable et peut être transféré dans Ads pour créer une nouvelle voix off. Cette génération utilise la clé et le modèle OpenAI existants et consomme les crédits du compte. Elle ne remplace jamais le texte associé à un audio existant.
4. Dans Video Ads, sélectionner le lead, un audio sauvegardé et le format. **Préparer mon slideshow** capture les pages du site enregistré en HD et répartit le script en slides.
5. Modifier les textes, choisir la page associée à chaque slide, réordonner, ajouter ou supprimer des slides et ajuster leurs durées.
6. **Générer ma vidéo MP4** produit une vidéo H.264 avec audio AAC, texte incrusté, captures des pages, coordonnées disponibles et fondus. Le fichier est lisible dans la page et téléchargeable.

Le champ **Message** reprend automatiquement le texte de l’audio sélectionné, y compris après rechargement ou changement d’audio. Le storyboard utilise toujours ce texte sauvegardé. Un brouillon modifié ne remplace pas le texte d’un audio existant : générer une nouvelle voix crée une nouvelle version, et le bouton **Reprendre le message de l’audio** restaure la source.

Le texte est découpé localement, sans requête IA supplémentaire. Les durées sont réparties sur la durée réelle de l’audio ; la synchronisation est indicative et ne constitue pas un alignement mot à mot. Les modifications du storyboard sont enregistrées au lancement du rendu. Les captures correspondent au site enregistré au moment de la préparation, même si le site est ensuite modifié.

## Retrouver les créations d’un prospect

La fiche `/leads/{id}` contient la rubrique **Sites, audios & Video Ads** : site enregistré, audios avec leur message et lecteur, et projets vidéo avec état, lecture et téléchargement des rendus terminés. **Ouvrir ce projet** restaure le storyboard exact ; **Ouvrir cet audio** recharge sa voix et son texte dans Ads ; **Créer sa vidéo** ouvre un nouveau slideshow à partir de cet audio.

Le studio dédié `/leads/{id}/video-ads` conserve le prospect dans l’URL, l’affiche dans l’en-tête et permet de revenir à sa fiche. Sans paramètre supplémentaire, il reprend le dernier projet du prospect ; `?new=1` ouvre un nouveau projet et `?audio_id=...` sélectionne l’audio source. Les liens de navigation vers les studios conservent ce contexte.

## Installation et exécution

Exécuter `bash scripts/install.sh` puis `bash scripts/start.sh` depuis la racine du dépôt. Le script installe Python, FFmpeg, les dépendances Python dont Playwright, et un Chromium Playwright si aucun Chromium système n’est disponible. Sur un environnement déjà préparé :

```sh
.venv/bin/pip install -r requirements.txt
# Seulement si aucun Chromium système n'est installé :
.venv/bin/playwright install --with-deps chromium
bash scripts/start.sh
```

Les nouvelles tables SQLite sont créées au démarrage, sans modifier les données existantes. Le modèle `AudioAd` conserve le texte et la durée ; `VideoAd` conserve le format, le storyboard, le contenu du site et l’état du rendu. Les fichiers se trouvent dans `data/ads/`, répertoire ignoré par Git. `ADS_MEDIA_ROOT` permet de déplacer ce stockage ; sauvegarder ce répertoire **avec la base SQLite**. Les captures et vidéos restent disponibles après redémarrage. Les traitements interrompus sont signalés comme échoués et peuvent être relancés depuis l’interface. Les médias ne doivent pas être supprimés si on souhaite conserver les projets.

## Limites et fonctionnement

- Audio : 20 Mo, durée de 1 à 300 secondes, texte de 4 096 caractères maximum.
- Site : jusqu’à huit pages capturées. Vidéo : de une à huit slides, 700 caractères maximum par slide. Les captures respectent le ratio du projet ; les images ne sont pas recadrées dans les slides.
- Les captures utilisent le template réel des sites, leur contenu et leurs images générées déjà stockées localement. Le navigateur est isolé du réseau et les scripts sont désactivés. Les images distantes et les photos Google non stockées localement ne sont pas téléchargées pendant la capture.
- Un seul travail vidéo à la fois par instance ; le rendu utilise deux threads FFmpeg. Utiliser un seul worker Uvicorn pour ce studio local. Une file distribuée et une authentification sont nécessaires avant d’en faire un service public multi-instance.
- Les anciens audios importés peuvent être dans un autre format que MP3 : le moteur analyse leur contenu, puis les encode en AAC pour la vidéo.
- Le téléchargement vidéo et les captures sont servis par des routes dédiées, sans exposer tout le répertoire de stockage.

## Validation

```sh
PYTHONPATH=. .venv/bin/pytest tests/test_voice.py tests/test_video_ads.py -q
```

Le parcours complet est aussi vérifié avec un audio synthétique et un site local : sauvegarde audio, préparation des captures, édition et rendu MP4, téléchargement et contrôle des dimensions et des codecs avec ffprobe. Aucun appel IA payant n’est nécessaire pour ce test.
