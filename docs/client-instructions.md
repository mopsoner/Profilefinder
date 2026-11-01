# Instructions du client

Un champ facultatif de 3 000 caractères permet de conserver les attentes du client sans changer le parcours existant. Exemples : style clair et chaleureux, tons beiges, titres plus grands, services à mettre en avant, rythme calme, éléments à éviter. Décrire les références et attentes précisément ; les liens ne sont pas consultés automatiquement.

## Sites IA

Ouvrir **Instructions du client** dans le formulaire de génération ou de régénération de Sites IA. Le champ est aussi disponible lors de la première création depuis la fiche du prospect. Les instructions sont transmises à OpenAI pour orienter le style, le ton, les pages, les contenus et les prompts des images.

Le brief est conservé dans le job et avec le site généré. Il est prérempli lors d’une régénération et reste visible dans le détail du job, y compris après un échec. Relancer un job de site conserve ses instructions. La colonne SQLite `jobs.client_instructions` est ajoutée automatiquement au démarrage, avec une valeur vide pour les anciens jobs ; aucun contenu existant n’est supprimé.

## Video Ads

Remplir **Instructions du client** avant **Préparer mon slideshow**, **Actualiser les scènes** ou **Générer ma vidéo MP4**. Le brief est conservé avec le projet et rechargé à sa réouverture.

Quand il est renseigné ou modifié, OpenAI le traduit en réglages compatibles avec le moteur : palette, couleur d’accent, typographie, taille de texte, composition, mouvement, transition et affichage du téléphone. Cette interprétation utilise la clé et le modèle OpenAI de ProfileFinder et consomme les crédits du compte. Le résultat est réutilisé tant que le brief ne change pas. Un champ vide conserve le fonctionnement automatique, sans cet appel supplémentaire.

Les instructions vidéo ne modifient pas le site source, le message de la voix off, l’audio, sa durée ni le format choisi. Les réglages sont appliqués aux scènes et au MP4. Les attentes non prises en charge peuvent être signalées dans le studio : par exemple filmer un acteur, produire de la 3D ou changer la narration nécessite un autre travail. Les compositions restent modifiables manuellement après interprétation du brief.

Les briefs et les réglages ne sont pas publiés dans les sites vitrines ; ils servent à guider la création.
