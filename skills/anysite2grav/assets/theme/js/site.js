// Navigation dropdowns, mobile menu and <dialog> modals. No dependencies.
// Semicolons are deliberate: scripts appended to this file must not merge into the IIFE.
;(() => {
  const fitDropdown = (dropdown) => {
    const menu = dropdown.querySelector('.site-nav__dropdown');
    if (!menu || !window.matchMedia('(min-width: 992px)').matches) return;
    menu.classList.remove('is-aligned-end');
    if (menu.getBoundingClientRect().right > window.innerWidth - 16) menu.classList.add('is-aligned-end');
  };
  const closeAll = (except) => {
    document.querySelectorAll('[data-dropdown].is-open').forEach((dropdown) => {
      if (dropdown === except) return;
      dropdown.classList.remove('is-open');
      dropdown.querySelector('[data-dropdown-toggle]')?.setAttribute('aria-expanded', 'false');
    });
  };

  document.addEventListener('click', (event) => {
    const toggle = event.target.closest('[data-dropdown-toggle]');
    if (toggle) {
      const dropdown = toggle.closest('[data-dropdown]');
      const open = !dropdown.classList.contains('is-open');
      closeAll(dropdown);
      dropdown.classList.toggle('is-open', open);
      toggle.setAttribute('aria-expanded', String(open));
      if (open) fitDropdown(dropdown);
      return;
    }
    if (!event.target.closest('[data-dropdown]')) closeAll();

    const navToggle = event.target.closest('[data-nav-toggle]');
    if (navToggle) {
      const nav = document.querySelector('[data-nav]');
      const open = !nav.classList.contains('is-open');
      nav.classList.toggle('is-open', open);
      navToggle.setAttribute('aria-expanded', String(open));
    }

    // Header search: the icon opens (focuses) its field.
    const searchToggle = event.target.closest('[data-search-toggle]');
    if (searchToggle) {
      const field = searchToggle.closest('form')?.querySelector('input[type=search]');
      if (field) field.focus();
    }

    const opener = event.target.closest('[data-modal-open]');
    if (opener) {
      event.preventDefault();
      document.getElementById(`modal-${opener.dataset.modalOpen}`)?.showModal();
    }
  });

  // Desktop: open dropdowns on hover for pointer devices; click/keyboard work everywhere.
  if (window.matchMedia('(hover: hover) and (min-width: 992px)').matches) {
    document.querySelectorAll('.site-nav [data-dropdown]').forEach((dropdown) => {
      dropdown.addEventListener('mouseenter', () => {
        closeAll(dropdown);
        dropdown.classList.add('is-open');
        fitDropdown(dropdown);
        dropdown.querySelector('[data-dropdown-toggle]')?.setAttribute('aria-expanded', 'true');
      });
      dropdown.addEventListener('mouseleave', () => closeAll());
    });
  }

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    const activeDropdown = document.activeElement?.closest('[data-dropdown].is-open');
    closeAll();
    activeDropdown?.querySelector('[data-dropdown-toggle]')?.focus();
  });

  const fitOpenDropdowns = () => document.querySelectorAll('[data-dropdown].is-open').forEach(fitDropdown);
  window.addEventListener('resize', fitOpenDropdowns);
  document.fonts?.ready.then(fitOpenDropdowns);

  // Close a modal when its backdrop is clicked.
  document.querySelectorAll('dialog.modal').forEach((dialog) => {
    dialog.addEventListener('click', (event) => {
      if (event.target === dialog) dialog.close();
    });
  });

  // Reopen the modal that contains a submitted (non-XHR) form so its message is visible.
  const status = document.querySelector('dialog.modal .form-messages, dialog.modal .notices');
  status?.closest('dialog')?.showModal();

  // Links pointing at #modal-<name> open that dialog too (mirrors source "#" CTA triggers).
  document.querySelectorAll('a[href^="#modal-"]').forEach((link) => {
    link.addEventListener('click', (event) => {
      const dialog = document.querySelector(link.getAttribute('href'));
      if (dialog?.showModal) {
        event.preventDefault();
        dialog.showModal();
      }
    });
  });
})();
