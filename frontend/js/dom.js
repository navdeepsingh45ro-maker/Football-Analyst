// Building page elements.
//
// Every page builds its HTML with h() instead of writing HTML strings. The
// reason is safety: text handed to h() is always inserted as TEXT, so a player
// name or a note containing "<script>" is shown literally and can never run.
// Nothing in this app assigns to innerHTML.

const SVG_NAMESPACE = 'http://www.w3.org/2000/svg';

function append(parent, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    parent.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

/**
 * Create an HTML element.
 *
 *   h('a', { class: 'button', href: 'players.html' }, 'Players')
 *   h('button', { onclick: save }, 'Save')
 *
 * `attrs` values that are null, undefined or false are skipped, so a condition
 * can be written inline: h('input', { disabled: isBusy }).
 * Children may be elements, text, numbers, arrays of those, or null (skipped).
 */
export function h(tag, attrs, ...children) {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (name === 'class') {
      element.className = value;
    } else if (name.startsWith('on') && typeof value === 'function') {
      element.addEventListener(name.slice(2), value);
    } else if (name === 'dataset') {
      Object.assign(element.dataset, value);
    } else if (name.includes('-') || ['role', 'for', 'list', 'form'].includes(name) || !(name in element)) {
      element.setAttribute(name, value === true ? '' : String(value));
    } else {
      element[name] = value;  // a real property such as value, checked, disabled, href
    }
  }
  append(element, children);
  return element;
}

/** Create an SVG element. Same idea as h(), but every attribute is set as an attribute. */
export function svg(tag, attrs, ...children) {
  const element = document.createElementNS(SVG_NAMESPACE, tag);
  for (const [name, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (name.startsWith('on') && typeof value === 'function') {
      element.addEventListener(name.slice(2), value);
    } else {
      element.setAttribute(name, value === true ? '' : String(value));
    }
  }
  append(element, children);
  return element;
}

/** Remove everything inside an element and return it. */
export function clear(element) {
  element.replaceChildren();
  return element;
}

/** The value of ?name=... in the page address, or null. */
export function queryParam(name) {
  return new URLSearchParams(window.location.search).get(name);
}
