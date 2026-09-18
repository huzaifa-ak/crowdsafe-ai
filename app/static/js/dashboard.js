/**
 * The venue list.
 *
 * Only job so far is deleting, which is why it is so small. Everything else on
 * this page is a link.
 */

import { api } from './api.js';

class Dashboard {
  constructor(table) {
    this.table = table;
    table.addEventListener('click', (event) => {
      const button = event.target.closest('[data-delete]');
      if (button) this.#remove(button);
    });
  }

  async #remove(button) {
    const row = button.closest('tr');
    const id = Number(button.dataset.delete);
    const name = button.dataset.name || 'this venue';

    // A browser confirm rather than a nicer dialog, because deleting a venue
    // cannot be undone and a plain unmissable prompt is the right shape for
    // that. Runs already made against it survive: each one stored the plan as
    // it was at the time.
    if (!window.confirm(`Delete ${name}? This cannot be undone.`)) return;

    button.disabled = true;
    button.textContent = 'Deleting…';

    try {
      await api.deleteVenue(id);
      row.remove();
      if (!this.table.querySelector('tbody tr')) window.location.reload();
    } catch (error) {
      button.disabled = false;
      button.textContent = 'Delete';
      window.alert(error.message);
    }
  }
}

const table = document.querySelector('#venues');
if (table) new Dashboard(table);
