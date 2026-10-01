// Site behaviour: mobile menu, copy-to-clipboard, footer year and the contact form.
(() => {
  'use strict';

  /* ---------- Mobile menu ---------- */
  const header = document.querySelector('.site-header');
  const toggle = document.querySelector('.nav-toggle');
  const nav = document.getElementById('site-nav');

  const setMenu = (open) => {
    if (!header || !toggle) return;
    header.classList.toggle('nav-open', open);
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
  };

  if (toggle) {
    toggle.addEventListener('click', () => {
      setMenu(toggle.getAttribute('aria-expanded') !== 'true');
    });
  }
  if (nav) {
    nav.addEventListener('click', (event) => {
      if (event.target.closest('a')) setMenu(false);
    });
  }
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && header && header.classList.contains('nav-open')) {
      setMenu(false);
      toggle.focus();
    }
  });
  const wide = window.matchMedia('(min-width: 901px)');
  const onWide = (event) => { if (event.matches) setMenu(false); };
  if (wide.addEventListener) wide.addEventListener('change', onWide);

  /* ---------- Footer year ---------- */
  document.querySelectorAll('[data-year]').forEach((el) => {
    el.textContent = String(new Date().getFullYear());
  });

  /* ---------- Copy email ---------- */
  document.querySelectorAll('[data-copy]').forEach((button) => {
    const original = button.textContent;
    let timer;
    const flash = (label) => {
      button.textContent = label;
      clearTimeout(timer);
      timer = setTimeout(() => { button.textContent = original; }, 2200);
    };
    const selectFallback = () => {
      const target = document.getElementById(button.dataset.copyTarget || '');
      if (target) {
        const range = document.createRange();
        range.selectNodeContents(target);
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
      }
      flash('Selected');
    };
    button.addEventListener('click', () => {
      const text = button.dataset.copy;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => flash('Copied'), selectFallback);
      } else {
        selectFallback();
      }
    });
  });

  /* ---------- Contact form ---------- */
  const form = document.getElementById('contact-form');
  const status = document.getElementById('form-status');
  if (!form || !status) return;

  const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  const ownerEmail = form.dataset.email || '';

  const showStatus = (state, message, withEmail) => {
    status.hidden = false;
    status.dataset.state = state;
    status.textContent = message;
    if (withEmail && ownerEmail) {
      const link = document.createElement('a');
      link.href = `mailto:${ownerEmail}`;
      link.textContent = ownerEmail;
      status.append(' ', link, '.');
    }
  };

  const markField = (field, invalid) => {
    field.classList.toggle('is-invalid', invalid);
    if (invalid) field.setAttribute('aria-invalid', 'true');
    else field.removeAttribute('aria-invalid');
  };

  const validate = () => {
    const invalid = [];
    form.querySelectorAll('[required]').forEach((field) => {
      const value = field.value.trim();
      const bad = !value || (field.type === 'email' && !emailPattern.test(value));
      markField(field, bad);
      if (bad) invalid.push(field);
    });
    return invalid;
  };

  form.addEventListener('input', (event) => {
    if (event.target.classList && event.target.classList.contains('is-invalid')) {
      markField(event.target, false);
    }
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();

    const invalid = validate();
    if (invalid.length) {
      showStatus('error', 'Please add your name, a valid email address and a few words about your goals.');
      invalid[0].focus();
      return;
    }

    const data = new FormData(form);
    const name = String(data.get('name') || '').trim();
    const firstName = name.split(/\s+/)[0];

    if (form.dataset.preview === 'true') {
      showStatus('success', 'This is a preview, so nothing was sent. On the live site this form delivers the message to your inbox.');
      return;
    }

    const endpoint = (form.dataset.endpoint || '').trim();

    if (endpoint) {
      const button = form.querySelector('[type="submit"]');
      const label = button.textContent;
      button.disabled = true;
      button.textContent = 'Sending…';
      try {
        const response = await fetch(endpoint, {
          method: 'POST',
          body: data,
          headers: { Accept: 'application/json' },
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        form.reset();
        showStatus('success', `Thanks, ${firstName}. Your message is on its way and I will reply within one business day.`);
      } catch (error) {
        showStatus('error', 'Your message did not send. Check your connection and try again, or email me at', true);
      } finally {
        button.disabled = false;
        button.textContent = label;
      }
      return;
    }

    // No form service configured: open the visitor's email app with the message filled in.
    const services = data.getAll('services').join(', ') || 'Not specified';
    const body = [
      `Name: ${name}`,
      `Email: ${String(data.get('email') || '').trim()}`,
      `Website: ${String(data.get('website') || '').trim() || 'Not given'}`,
      `Monthly budget: ${data.get('budget') || 'Not specified'}`,
      `Help with: ${services}`,
      '',
      String(data.get('message') || '').trim(),
    ].join('\n');
    const subject = `New project enquiry from ${name}`;
    window.location.href = `mailto:${ownerEmail}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
    showStatus('success', 'Your email app should open with the message ready to send. If nothing opened, email me at', true);
  });
})();
