# Projet : site de TS Impact, agence web à Caen

Tu construis le site vitrine de TS Impact, une agence web de Caen (site internet, fiche Google, réseaux sociaux, Google Ads). Le propriétaire n'est pas développeur : explique simplement ce que tu fais, en français.

## Source de vérité : la maquette

Le fichier `maquette-ts-impact.html` est la maquette validée. Elle s'ouvre déjà dans un navigateur, mais tout est écrit en styles inline dans un seul fichier. Transforme-la en site propre :

- Les styles `style="…"` passent dans `styles.css`, avec des classes lisibles et une variable CSS `--accent: #FFC727`.
- Le script en bas de page passe dans `script.js`. Il gère déjà :
  - les boutons « Choisir cette offre », qui ouvrent la fenêtre de contact avec le nom de l'offre ;
  - la fermeture par la croix, le bouton Fermer, un clic sur le fond et la touche Échap ;
  - les messages de remerciement après envoi.
- Garde à l'identique les textes, les prix, les couleurs, les typographies (Bricolage Grotesque et Inter) et la mise en page.

## Pages à créer

- `index.html` : la maquette.
- `mentions-legales.html` : éditeur TS Impact, [statut juridique : À COMPLÉTER], 14 avenue de Thiès, 14000 Caen, 06 13 02 60 45, SIRET [À COMPLÉTER], directeur de la publication [À COMPLÉTER], hébergeur (nom, adresse, téléphone de Cloudflare, à vérifier sur leur site).
- `confidentialite.html` : données collectées par les formulaires (nom, métier, téléphone, e-mail, message), finalité (recontacter la personne), durée de conservation [À COMPLÉTER], droits RGPD, exercice des droits par téléphone ou courrier.
- `404.html` aux couleurs du site.
- Les liens « Mentions légales » et « Confidentialité » du pied de page pointent vers ces pages.

## Coordonnées, identiques partout

TS Impact · 14 avenue de Thiès, 14000 Caen · 06 13 02 60 45 (lien `tel:+33613026045`). Aucune adresse e-mail affichée sur le site.

## Formulaires

Le site est statique : les 3 formulaires (fenêtre « Choisir cette offre », audit gratuit, contact en bas de page) sont envoyés par Web3Forms.

- La clé d'accès Web3Forms va dans une constante en haut de `script.js` ; je te la donnerai.
- Un champ caché indique l'offre choisie ou le formulaire d'origine.
- Protection anti-spam par champ piège (honeypot).
- Messages de succès et d'erreur ; chaque champ garde son `<label>`.

## Référencement local

- `lang="fr"`, un seul `<h1>`, une hiérarchie `h2` / `h3` propre.
- `<title>` et meta description centrés sur « agence web à Caen ».
- Données structurées JSON-LD `ProfessionalService` : nom, adresse, téléphone, zone desservie (les communes de la section Zone d'intervention), URL.
- Balises Open Graph, favicon (carré jaune avec « TS »), `sitemap.xml`, `robots.txt`.
- Domaine prévu : `https://tsimpact.fr` [À CONFIRMER].

## Qualité

- Responsive, vérifié à 375 px, 768 px et 1440 px de large.
- Accessible : contrastes suffisants, focus visible, fenêtre modale utilisable au clavier.
- Rapide : objectif Lighthouse 90 ou plus partout.
- Polices hébergées dans le site (fichiers woff2), pas chargées depuis Google, pour le RGPD.
- Aucun cookie ni traceur, donc pas besoin de bannière cookies.

## Sécurité

- Fichier `_headers` (Cloudflare) avec : `Strict-Transport-Security`, une `Content-Security-Policy` stricte (le site lui-même et `api.web3forms.com`), `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy`, `X-Frame-Options: DENY`.
- Aucune clé secrète ni mot de passe dans le code.
- Git dans ce dossier, un commit à chaque étape importante.

## Mise en ligne

Hébergement prévu : Cloudflare Pages (gratuit). Explique chaque étape avant de la faire. Ne publie rien et n'achète rien sans mon accord.

## Règles

- Demande-moi avant de remplir une information marquée [À COMPLÉTER] ou [À CONFIRMER].
- N'invente ni avis clients, ni chiffres, ni références.
