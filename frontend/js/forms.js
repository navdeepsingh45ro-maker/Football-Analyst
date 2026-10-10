// Forms described as data.
//
// Instead of hand-writing every <label> and <input>, a page lists its fields:
//
//   const form = buildForm([
//     { name: 'full_name', label: 'Full name', required: true },
//     { name: 'height_cm', label: 'Height (cm)', type: 'number', width: 'third' },
//     { name: 'preferred_foot', label: 'Preferred foot', type: 'select', options: ['left', 'right', 'both'] },
//   ], existingValues);
//   somewhere.append(form.element);
//   const { values, errors } = form.read();
//
// THE RULE THAT MATTERS: an empty field is read as null, never as "" or 0.
// That is how "unknown stays unknown" starts, here in the browser.
//
// Field types: text (default), number, date, textarea, select, checkbox,
//   suggest  text with a drop-down of suggestions; your own wording is allowed
//   clock    a video or match time such as 32:14, read as seconds
//   list     comma-separated words, read as an array
//   choices  several tick-boxes, read as an array of the ticked values

import { h } from './dom.js';
import { formatClockExact, parseClock } from './format.js';

let fieldCounter = 0;

function optionPair(option) {
  return Array.isArray(option) ? option : [option, option];
}

function makeControl(field, value, id) {
  const common = { id, name: field.name, required: field.required, placeholder: field.placeholder };
  switch (field.type) {
    case 'textarea':
      return h('textarea', { ...common, rows: field.rows || 3, value: value ?? '' });
    case 'select': {
      const select = h('select', common,
        field.required ? null : h('option', { value: '' }, field.emptyLabel || 'Not known'),
        (field.options || []).map((option) => {
          const [optionValue, optionLabel] = optionPair(option);
          return h('option', { value: optionValue }, optionLabel);
        }));
      select.value = value === null || value === undefined ? '' : String(value);
      return select;
    }
    case 'checkbox':
      return h('input', { ...common, type: 'checkbox', checked: Boolean(value), required: false });
    case 'number':
      return h('input', { ...common, type: 'number', min: field.min, max: field.max, step: field.step || 1, value: value ?? '' });
    case 'date':
      return h('input', { ...common, type: 'date', value: value ?? '' });
    case 'clock':
      return h('input', { ...common, type: 'text', inputMode: 'numeric', value: formatClockExact(value), placeholder: field.placeholder || '32:14' });
    case 'list':
      return h('input', { ...common, type: 'text', value: (value || []).join(', ') });
    case 'suggest': {
      const listId = `${id}-suggestions`;
      return [
        h('input', { ...common, type: 'text', list: listId, value: value ?? '', autocomplete: 'off' }),
        h('datalist', { id: listId }, (field.options || []).map((option) => h('option', { value: optionPair(option)[0] }))),
      ];
    }
    default:
      return h('input', { ...common, type: field.type === 'url' ? 'url' : 'text', value: value ?? '', maxLength: field.maxLength });
  }
}

/**
 * Build a form from field descriptions. Returns:
 *   element      the grid of fields (put it inside a <form> or a dialog)
 *   read()       { values, errors }: values keyed by field name; errors keyed the same
 *   showErrors() show messages next to fields (pass an ApiError's fieldErrors)
 *   control(n)   the input element of field `n`, for wiring fields together
 */
export function buildForm(fields, initial = {}) {
  const controls = {};
  const errorBoxes = {};
  const formError = h('div', { class: 'field error', role: 'alert' });
  formError.hidden = true;

  const rows = fields.map((field) => {
    if (field.type === 'heading') return h('h3', { class: 'field' }, field.label);
    if (field.type === 'note') return h('p', { class: 'field small muted' }, field.label);

    fieldCounter += 1;
    const id = `field-${fieldCounter}`;
    const value = field.name in initial ? initial[field.name] : field.default;
    const errorBox = h('div', { class: 'error', id: `${id}-error` });
    errorBox.hidden = true;
    errorBoxes[field.name] = errorBox;
    const width = field.width ? ` ${field.width}` : '';

    if (field.type === 'choices') {
      const chosen = new Set((value || []).map(String));
      const boxes = (field.options || []).map((option) => {
        const [optionValue, optionLabel] = optionPair(option);
        const boxId = `${id}-${optionValue}`;
        return h('span', { class: 'row' },
          h('input', { type: 'checkbox', id: boxId, value: optionValue, checked: chosen.has(String(optionValue)) }),
          h('label', { for: boxId }, optionLabel));
      });
      const group = h('fieldset', { class: `field${width}` }, h('legend', {}, field.label),
        h('div', { class: 'row' }, boxes), field.help ? h('div', { class: 'help' }, field.help) : null, errorBox);
      controls[field.name] = group;
      return group;
    }

    const made = makeControl(field, value, id);
    const control = Array.isArray(made) ? made[0] : made;
    control.setAttribute('aria-describedby', `${id}-error`);
    controls[field.name] = control;

    if (field.type === 'checkbox') {
      return h('div', { class: `field check${width}` }, control, h('label', { for: id }, field.label), errorBox);
    }
    return h('div', { class: `field${width}` },
      h('label', { for: id }, field.label, field.required ? h('span', { class: 'muted' }, ' (required)') : null),
      made,
      field.help ? h('div', { class: 'help' }, field.help) : null,
      errorBox);
  });

  const element = h('div', { class: 'form-grid' }, rows, formError);

  function clearErrors() {
    formError.hidden = true;
    for (const [name, box] of Object.entries(errorBoxes)) {
      box.hidden = true;
      if (controls[name].removeAttribute) controls[name].removeAttribute('aria-invalid');
    }
  }

  function showErrors(errors) {
    clearErrors();
    const leftover = [];
    for (const [name, message] of Object.entries(errors || {})) {
      if (errorBoxes[name]) {
        errorBoxes[name].textContent = message;
        errorBoxes[name].hidden = false;
        controls[name].setAttribute('aria-invalid', 'true');
      } else {
        leftover.push(name ? `${name.replaceAll('_', ' ')}: ${message}` : message);
      }
    }
    if (leftover.length) {
      formError.textContent = leftover.join(' ');
      formError.hidden = false;
    }
    const firstInvalid = element.querySelector('[aria-invalid="true"]');
    if (firstInvalid && firstInvalid.focus) firstInvalid.focus();
  }

  function read() {
    const values = {};
    const errors = {};
    for (const field of fields) {
      if (!field.name) continue;
      const control = controls[field.name];
      if (field.type === 'checkbox') {
        values[field.name] = control.checked;
      } else if (field.type === 'choices') {
        values[field.name] = [...control.querySelectorAll('input:checked')].map((box) => box.value);
      } else if (field.type === 'list') {
        values[field.name] = control.value.split(',').map((part) => part.trim()).filter(Boolean);
      } else {
        const text = control.value.trim();
        if (text === '') {
          values[field.name] = null;  // empty means unknown
          if (field.required) errors[field.name] = 'This is required.';
        } else if (field.type === 'number') {
          const number = Number(text);
          if (Number.isFinite(number)) values[field.name] = number;
          else errors[field.name] = 'Enter a number.';
        } else if (field.type === 'clock') {
          try {
            values[field.name] = parseClock(text);
          } catch (error) {
            errors[field.name] = error.message;
          }
        } else if (field.type === 'select' && field.numeric) {
          values[field.name] = Number(text);
        } else {
          values[field.name] = text;
        }
      }
    }
    return { values, errors };
  }

  return {
    element, read, showErrors, clearErrors,
    control: (name) => controls[name],
    showFormError(message) { showErrors({ '': message }); },
  };
}
