/* =========================================================
   TS Impact — script du site
   ========================================================= */

/*
 * Clé d'accès Web3Forms (https://web3forms.com).
 * Ce n'est pas un mot de passe : elle est faite pour être visible dans le site
 * et sert seulement à indiquer à Web3Forms à quelle adresse envoyer les messages.
 * Tant qu'elle est vide, les formulaires affichent un message invitant à appeler.
 */
var WEB3FORMS_ACCESS_KEY = '';

(function () {
  'use strict';

  var TELEPHONE = '06 13 02 60 45';
  var TELEPHONE_LIEN = 'tel:+33613026045';
  var URL_ENVOI = 'https://api.web3forms.com/submit';

  /* ---------------------------------------------------------
     Fenêtre « Choisir cette offre »
     --------------------------------------------------------- */
  var modal = document.getElementById('modal');
  var etatForm = modal.querySelector('[data-etat="formulaire"]');
  var etatMerci = modal.querySelector('[data-etat="envoye"]');
  var champOffre = modal.querySelector('.js-offre-champ');
  var dernierBouton = null;

  function ouvrir(offre, bouton) {
    dernierBouton = bouton;
    document.querySelectorAll('.js-offre').forEach(function (el) { el.textContent = offre; });
    champOffre.value = offre;
    etatForm.hidden = false;
    etatMerci.hidden = true;
    effacerErreur(etatForm.querySelector('form'));
    modal.setAttribute('aria-labelledby', 'modal-titre');
    document.body.classList.add('modal-ouverte');

    if (typeof modal.showModal === 'function') {
      modal.showModal();
    } else {
      modal.setAttribute('open', '');
    }
    var champ = modal.querySelector('input:not([type="hidden"]):not(.piege)');
    if (champ) champ.focus();
  }

  function fermer() {
    if (!modal.open) return;
    if (typeof modal.close === 'function') {
      modal.close();
    } else {
      modal.removeAttribute('open');
      apresFermeture();
    }
  }

  function apresFermeture() {
    document.body.classList.remove('modal-ouverte');
    if (dernierBouton) dernierBouton.focus();
  }

  // Événement natif « close » : déclenché par fermer() et par la touche Échap.
  modal.addEventListener('close', apresFermeture);

  document.querySelectorAll('[data-offre]').forEach(function (b) {
    b.addEventListener('click', function () { ouvrir(b.getAttribute('data-offre'), b); });
  });
  modal.querySelectorAll('[data-action="fermer"]').forEach(function (b) {
    b.addEventListener('click', fermer);
  });
  // Clic sur le fond sombre (en dehors de la boîte blanche).
  modal.addEventListener('click', function (e) {
    if (e.target === modal) fermer();
  });
  document.addEventListener('keydown', function (e) {
    if (!modal.open) return;
    // Touche Échap (filet de sécurité pour les navigateurs sans showModal).
    if (e.key === 'Escape') {
      e.preventDefault();
      fermer();
      return;
    }
    // Touche Tab : le focus tourne en boucle à l'intérieur de la fenêtre.
    if (e.key === 'Tab') {
      var focusables = Array.prototype.filter.call(
        modal.querySelectorAll('button, input:not([type="hidden"]):not(.piege), textarea, a[href]'),
        function (el) { return !el.disabled && el.offsetParent !== null; }
      );
      if (!focusables.length) return;
      var premier = focusables[0];
      var dernier = focusables[focusables.length - 1];
      var actif = document.activeElement;
      if (e.shiftKey && (actif === premier || !modal.contains(actif))) {
        e.preventDefault();
        dernier.focus();
      } else if (!e.shiftKey && (actif === dernier || !modal.contains(actif))) {
        e.preventDefault();
        premier.focus();
      }
    }
  });

  /* ---------------------------------------------------------
     Envoi des formulaires (Web3Forms)
     --------------------------------------------------------- */
  function zoneErreur(form) { return form.querySelector('.form-erreur'); }

  function effacerErreur(form) {
    var zone = zoneErreur(form);
    if (zone) zone.textContent = '';
  }

  function afficherErreur(form, texte) {
    var zone = zoneErreur(form);
    zone.textContent = '';
    zone.appendChild(document.createTextNode(texte + ' '));
    var lien = document.createElement('a');
    lien.href = TELEPHONE_LIEN;
    lien.textContent = 'Appelez-nous au ' + TELEPHONE + '.';
    zone.appendChild(lien);
  }

  function valeur(form, nom) {
    var champ = form.elements[nom];
    return champ && champ.value ? champ.value.trim() : '';
  }

  function donnees(form) {
    var resultat = {};
    var interets = [];
    Array.prototype.forEach.call(form.elements, function (champ) {
      if (!champ.name || champ.name === 'botcheck' || champ.disabled) return;
      if (champ.type === 'checkbox') {
        if (champ.checked && champ.name === 'interets') interets.push(champ.value);
        return;
      }
      if (champ.value.trim() !== '') resultat[champ.name] = champ.value.trim();
    });
    if (interets.length) resultat.interets = interets.join(', ');
    return resultat;
  }

  function montrerMerci(form) {
    var cible = form.getAttribute('data-merci');
    var titre;
    if (cible === 'modal') {
      etatForm.hidden = true;
      etatMerci.hidden = false;
      modal.setAttribute('aria-labelledby', 'modal-merci');
      titre = etatMerci.querySelector('.merci__titre');
    } else {
      form.parentNode.hidden = true;
      var merci = document.getElementById(cible);
      merci.hidden = false;
      titre = merci.querySelector('.merci__titre');
    }
    if (titre) titre.focus();
  }

  function envoyer(form) {
    effacerErreur(form);

    // Champ piège : un robot l'a coché, on fait semblant d'avoir envoyé.
    if (form.elements.botcheck && form.elements.botcheck.checked) {
      form.reset();
      montrerMerci(form);
      return;
    }

    var tel = valeur(form, 'telephone');
    var email = valeur(form, 'email');
    if (!tel && !email) {
      afficherErreur(form, form.elements.email
        ? 'Indiquez au moins un téléphone ou un e-mail pour qu\'on puisse vous recontacter.'
        : 'Indiquez votre téléphone pour qu\'on puisse vous rappeler.');
      var champ = form.elements.telephone;
      if (champ) champ.focus();
      return;
    }
    if (email && form.elements.email && !form.elements.email.checkValidity()) {
      afficherErreur(form, 'L\'adresse e-mail semble incomplète.');
      form.elements.email.focus();
      return;
    }

    if (!WEB3FORMS_ACCESS_KEY) {
      afficherErreur(form, 'Le formulaire n\'est pas encore activé.');
      return;
    }

    var contenu = donnees(form);
    var origine = contenu.offre ? 'Offre : ' + contenu.offre : contenu.formulaire;
    contenu.access_key = WEB3FORMS_ACCESS_KEY;
    contenu.subject = 'Site TS Impact – ' + origine;
    contenu.from_name = 'Site TS Impact';
    contenu.botcheck = false;

    var bouton = form.querySelector('[type="submit"]');
    var texteBouton = bouton.textContent;
    bouton.disabled = true;
    bouton.textContent = 'Envoi en cours…';

    fetch(URL_ENVOI, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify(contenu)
    })
      .then(function (reponse) {
        return reponse.json().then(function (json) {
          if (!reponse.ok || !json.success) throw new Error(json.message || 'Envoi refusé');
        });
      })
      .then(function () {
        form.reset();
        montrerMerci(form);
      })
      .catch(function () {
        afficherErreur(form, 'L\'envoi n\'a pas fonctionné. Réessayez dans un instant.');
      })
      .then(function () {
        bouton.disabled = false;
        bouton.textContent = texteBouton;
      });
  }

  document.querySelectorAll('.js-formulaire').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      envoyer(form);
    });
  });
})();
