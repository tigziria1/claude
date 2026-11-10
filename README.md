# Site de TS Impact, agence web à Caen

Le site se trouve dans le dossier **`site/`**. C'est le seul dossier à mettre en ligne.
Les autres fichiers (`CLAUDE.md`, la maquette d'origine) servent au travail et ne sont pas publiés.

## Ouvrir le site sur votre ordinateur

1. Téléchargez le projet (sur GitHub : bouton vert **Code**, puis **Download ZIP**) et décompressez-le.
2. Ouvrez le dossier `site`.
3. Double-cliquez sur `index.html` : le site s'ouvre dans votre navigateur.

La page 404 ne s'affiche correctement qu'une fois le site en ligne (c'est normal).

## Contenu du dossier `site/`

| Fichier | Rôle |
|---|---|
| `index.html` | Page d'accueil (la maquette) |
| `mentions-legales.html`, `confidentialite.html` | Pages légales |
| `404.html` | Page affichée quand une adresse n'existe pas |
| `styles.css` | Toute la mise en forme (couleur principale : `--accent: #FFC727`) |
| `script.js` | Fenêtre « Choisir cette offre » et envoi des formulaires |
| `fonts/` | Polices Bricolage Grotesque et Inter, hébergées sur le site |
| `_headers` | Règles de sécurité appliquées par Cloudflare |
| `sitemap.xml`, `robots.txt` | Pour Google |
| `favicon.*`, `apple-touch-icon.png`, `og-image.png` | Icônes et image de partage |

## Activer les formulaires

Ouvrez `site/script.js` et collez votre clé Web3Forms entre les guillemets, tout en haut :

```js
var WEB3FORMS_ACCESS_KEY = 'votre-clé-ici';
```

Tant que la clé est vide, les formulaires affichent : « Le formulaire n'est pas encore activé. Appelez-nous au 06 13 02 60 45. »

## Informations encore à compléter

- Mentions légales : statut juridique, SIRET, directeur de la publication, téléphone de Cloudflare (à vérifier).
- Confidentialité : durée de conservation des données, garanties des transferts hors Union européenne.
- Domaine `https://tsimpact.fr` à confirmer (il figure dans `index.html`, `sitemap.xml`, `robots.txt` et les pages légales).
