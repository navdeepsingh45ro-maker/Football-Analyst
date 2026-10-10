// Settings: where your data lives, backups, export, import, and the reference lists.

import { api, ApiError } from '../api.js';
import { clear, h } from '../dom.js';
import { formatMoment, plural } from '../format.js';
import { errorNote, load, mountPage } from '../layout.js';
import { confirmDialog, emptyState, formDialog, toast } from '../ui.js';

const page = mountPage({
  active: 'settings.html', title: 'Settings',
  lede: 'Your data stays in one folder on this computer. This page is for keeping it safe and moving it in and out.',
});

function section(title, ...body) {
  return h('section', { class: 'section' }, h('div', { class: 'section-head' }, h('h2', {}, title)), body);
}

const megabytes = (bytes) => (bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`);

// ── Where the data is ────────────────────────────────────────────────────────
async function aboutSection() {
  const about = await api.get('/api/about');
  return section('Where your data is',
    h('dl', { class: 'facts' },
      h('dt', {}, 'Data folder'), h('dd', {}, h('code', {}, about.data_folder)),
      h('dt', {}, 'Database'), h('dd', {}, `${plural(about.players, 'player')}, ${plural(about.observations, 'observation')}, ${plural(about.diagrams, 'diagram')}`),
      h('dt', {}, 'Frame pictures'), h('dd', {}, `${about.frame_pictures} saved in the media/frames folder`),
      h('dt', {}, 'Database version'), h('dd', {}, about.schema_revision)),
    h('p', { class: 'small muted' }, 'Nothing is sent anywhere unless you switch on the optional AI assistance. Videos are never copied; only their location is stored.'));
}

// ── Backups ──────────────────────────────────────────────────────────────────
function backupsSection() {
  const list = h('div', {});
  const result = h('div', {});

  const refresh = () => load(list, async () => {
    const backups = await api.get('/api/backups');
    if (!backups.length) return emptyState('No backups yet.');
    return h('ul', { class: 'list' }, backups.map((backup) => h('li', { class: 'row spread' },
      h('div', {}, h('strong', {}, backup.name), h('div', { class: 'small muted' }, `${megabytes(backup.size_bytes)}, made ${formatMoment(backup.modified_at)}`)),
      h('a', { class: 'button small', href: `/api/backups/${backup.name}` }, 'Download a copy'))));
  });

  const make = h('button', { type: 'button', class: 'button primary', onclick: async () => {
    make.disabled = true;
    try {
      const backup = await api.post('/api/backups');
      const check = backup.check;
      clear(result).append(h('div', { class: check.ok ? 'note' : 'note error' }, check.ok
        ? `Backup made and checked: it opens, its database passes SQLite's integrity check, and it holds ${check.rows} rows and ${plural(check.frame_pictures, 'frame picture')}. Saved as ${backup.name} (${megabytes(backup.size_bytes)}).`
        : `The backup was written but FAILED its check: ${check.problem}. Do not rely on it.`));
      refresh();
    } catch (error) {
      clear(result).append(errorNote(error));
    } finally {
      make.disabled = false;
    }
  } }, 'Make a backup now');

  refresh();
  return section('Backups',
    h('p', { class: 'prose' }, 'A backup is one zip file with the database and every frame picture. Each backup is opened and checked the moment it is made. '
      + 'Keep copies somewhere other than this computer (an external drive, cloud storage).'),
    h('div', { class: 'row' }, make), result, list,
    h('details', {}, h('summary', {}, 'How to put a backup back'),
      h('ol', {},
        h('li', {}, 'Stop the server (Ctrl+C in its terminal).'),
        h('li', {}, 'In the backend folder run: ', h('code', {}, 'python scripts/restore_backup.py data/backups/NAME-OF-BACKUP.zip')),
        h('li', {}, 'Start the server again.')),
      h('p', { class: 'small muted' }, 'The data being replaced is moved into a dated folder next to it, not deleted, so a mistaken restore can be undone.')));
}

// ── Export ───────────────────────────────────────────────────────────────────
function exportSection() {
  const file = (entity, text) => h('li', {}, h('a', { href: `/api/export/csv/${entity}` }, text));
  return section('Export',
    h('div', { class: 'columns' },
      h('div', { class: 'stack' }, h('h3', {}, 'Everything, as one file'),
        h('p', {}, 'Every record with its identifiers and links, in an open text format (JSON). It can be loaded into a fresh, empty copy of this app. Frame pictures are not inside it; a backup has those.'),
        h('p', {}, h('a', { class: 'button', href: '/api/export/json' }, 'Download everything (JSON)'))),
      h('div', { class: 'stack' }, h('h3', {}, 'One kind of record, for a spreadsheet'),
        h('ul', {}, file('players', 'Players (CSV)'), file('matches', 'Matches (CSV)'), file('statistics', 'Statistics (CSV)'), file('observations', 'Observations (CSV)')),
        h('p', { class: 'small muted' }, 'A filtered set of observations can be downloaded from the Observations page. A diagram can be saved as a picture or as data from where it is shown.'))));
}

// ── Import ───────────────────────────────────────────────────────────────────
function importReport(report) {
  if (report.errors && report.errors.length) {
    return h('div', { class: 'note error stack' },
      h('strong', {}, `Nothing was imported: ${plural(report.errors.length, 'problem')} in ${plural(report.rows, 'row')}.`),
      h('div', { class: 'table-wrap' }, h('table', {},
        h('thead', {}, h('tr', {}, ['Line in the file', 'Column', 'Problem'].map((label) => h('th', { scope: 'col' }, label)))),
        h('tbody', {}, report.errors.map((error) => h('tr', {}, h('td', { class: 'numeric' }, error.row ?? 'whole file'),
          h('td', {}, error.column ?? ''), h('td', {}, error.message)))))),
      h('p', { class: 'small' }, 'Fix those lines in the file and try again. An import is all or nothing, so nothing was half-saved.'));
  }
  const ignored = report.ignored_columns && report.ignored_columns.length
    ? ` Columns not read (they are export-only): ${report.ignored_columns.join(', ')}.` : '';
  if (report.dry_run) {
    const count = report.would_create ?? report.total;
    return h('div', { class: 'note' }, `The file is fine: ${plural(count, 'row')} would be added. Nothing has been saved yet.${ignored}`);
  }
  return h('div', { class: 'note' }, `Imported ${plural(report.created ?? report.total, 'row')}.${ignored}`);
}

function importSection() {
  const kind = h('select', { id: 'import-kind' },
    [['players', 'Players (CSV)'], ['matches', 'Matches (CSV)'], ['statistics', 'Statistics (CSV)'],
      ['observations', 'Observations (CSV)'], ['json', 'Everything (JSON export, into an empty database)']]
      .map(([value, label]) => h('option', { value }, label)));
  const picker = h('input', { type: 'file', id: 'import-file', accept: '.csv,.json,text/csv,application/json' });
  const result = h('div', {});

  async function run(dryRun) {
    const chosen = picker.files[0];
    if (!chosen) {
      clear(result).append(h('div', { class: 'note caution' }, 'Choose a file first.'));
      return;
    }
    try {
      const text = await chosen.text();
      const report = kind.value === 'json'
        ? await api.post('/api/import/json', JSON.parse(text), { dry_run: dryRun })
        : await api.postText(`/api/import/csv/${kind.value}`, text, { dry_run: dryRun });
      clear(result).append(importReport(report));
      if (report.saved) toast('Import finished');
    } catch (error) {
      const message = error instanceof SyntaxError ? 'That file is not valid JSON.' : (error instanceof ApiError ? error.message : null);
      clear(result).append(message ? h('div', { class: 'note error', role: 'alert' }, message) : errorNote(error));
    }
  }

  return section('Import',
    h('p', { class: 'prose' }, 'Bring in records from a spreadsheet. Every row is checked with the same rules as the forms. '
      + 'If any row is wrong, nothing is saved and you are told which line and why. A CSV import only adds records; it never changes or deletes existing ones.'),
    h('div', { class: 'filters' },
      h('div', { class: 'field' }, h('label', { for: 'import-kind' }, 'What the file contains'), kind),
      h('div', { class: 'field' }, h('label', { for: 'import-file' }, 'File'), picker)),
    h('div', { class: 'row' },
      h('button', { type: 'button', class: 'button', onclick: () => run(true) }, 'Check the file'),
      h('button', { type: 'button', class: 'button primary', onclick: () => run(false) }, 'Import')),
    result,
    h('p', { class: 'small muted' }, 'The easiest way to get the right columns: export the same kind of record above, and use that file as the template. Times can be written as 32:14.'));
}

// ── Teams, competitions, seasons ─────────────────────────────────────────────
function referenceSection() {
  const kinds = [['teams', 'team', 'Teams'], ['competitions', 'competition', 'Competitions'], ['seasons', 'season', 'Seasons']];
  const boxes = kinds.map(([plural_, singular, title]) => {
    const box = h('div', {});
    const refresh = () => load(box, async () => {
      const rows = await api.get(`/api/${plural_}`);
      if (!rows.length) return h('p', { class: 'muted small' }, 'None yet. They are created as you type them in a player or match form.');
      return h('ul', { class: 'list' }, rows.map((row) => h('li', { class: 'row spread' },
        h('span', {}, row.name),
        h('span', { class: 'row' },
          h('button', { type: 'button', class: 'button small quiet', onclick: async () => {
            const saved = await formDialog({
              title: `Rename ${row.name}`, intro: 'The new name appears everywhere this is used.',
              fields: [{ name: 'name', label: 'Name', required: true }], values: row, submitLabel: 'Save name',
              onSubmit: (values) => api.put(`/api/${plural_}/${row.id}`, singular === 'team' ? { ...values, team_type: row.team_type, country: row.country }
                : (singular === 'competition' ? { ...values, country: row.country } : values)),
            });
            if (saved) { toast('Renamed'); refresh(); }
          } }, 'Rename'),
          h('button', { type: 'button', class: 'button small quiet', onclick: async () => {
            if (!await confirmDialog({ title: `Delete ${row.name}?`, message: `Only possible while no player, match or stat line uses this ${singular}.`, confirmLabel: 'Delete', danger: true })) return;
            try {
              await api.delete(`/api/${plural_}/${row.id}`);
              toast('Deleted');
              refresh();
            } catch (error) {
              toast(error.message, 'error');
            }
          } }, 'Delete')))));
    });
    refresh();
    return h('div', {}, h('h3', {}, title), box);
  });
  return section('Teams, competitions and seasons',
    h('p', { class: 'muted' }, 'Fix a spelling here and it changes everywhere. One that is still in use cannot be deleted.'),
    h('div', { class: 'columns' }, boxes));
}

// ── The page ─────────────────────────────────────────────────────────────────
async function aiSection() {
  const status = await api.get('/api/ai/status');
  return section('AI coach (optional)',
    h('div', { class: status.enabled ? 'note' : 'note caution' }, status.message),
    h('p', { class: 'small muted' }, 'It is switched on or off in the file backend/.env, not here, so that a key is never typed into a web page. The README explains how.'));
}

load(page.content, async () => [
  await aboutSection(), backupsSection(), exportSection(), importSection(), referenceSection(), await aiSection(),
]);
