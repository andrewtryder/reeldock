/** Shared chrome + DOM fakes for extension unit tests. */

export function emitter() {
  const listeners = [];
  return {
    addListener(fn) {
      listeners.push(fn);
    },
    listeners,
    emit(...args) {
      return listeners.map((fn) => fn(...args));
    },
  };
}

export function installChromeMock({ store = {}, tabs = [] } = {}) {
  const onMessage = emitter();
  const onInstalled = emitter();
  const onStartup = emitter();
  const onClickedNotifications = emitter();
  const onClickedMenus = emitter();
  const onChanged = emitter();
  const createdTabs = [];
  const createdNotifications = [];

  const chrome = {
    runtime: {
      id: 'testid',
      lastError: undefined,
      getManifest: () => ({ version: '1.11.0' }),
      getURL: (path) => `chrome-extension://testid/${path}`,
      sendMessage: async () => ({ ok: true }),
      onMessage,
      onInstalled,
      onStartup,
    },
    storage: {
      local: {
        async get(keys) {
          if (keys == null) return { ...store };
          if (typeof keys === 'string') return { [keys]: store[keys] };
          if (Array.isArray(keys)) {
            const out = {};
            for (const key of keys) out[key] = store[key];
            return out;
          }
          const out = {};
          for (const key of Object.keys(keys)) out[key] = store[key];
          return out;
        },
        async set(obj) {
          Object.assign(store, obj);
        },
      },
      onChanged,
    },
    tabs: {
      query: async () => tabs,
      create: async (opts) => {
        createdTabs.push(opts);
        return opts;
      },
    },
    notifications: {
      create(id, _opts, callback) {
        createdNotifications.push(id);
        callback?.();
      },
      getAll: async () => Object.fromEntries(createdNotifications.map((id) => [id, {}])),
      onClicked: onClickedNotifications,
    },
    contextMenus: {
      remove(_id, callback) {
        callback?.();
      },
      create(_opts, callback) {
        callback?.();
      },
      onClicked: onClickedMenus,
    },
    permissions: {
      contains: async () => true,
      request: async () => true,
    },
  };

  globalThis.chrome = chrome;
  return {
    chrome,
    store,
    createdTabs,
    createdNotifications,
    onMessage,
    onInstalled,
    onStartup,
    onClickedNotifications,
    onClickedMenus,
    onChanged,
  };
}

export function makeElement(tag = 'div', id = '') {
  const classes = new Set();
  const children = [];
  const listeners = {};
  const el = {
    tagName: String(tag).toUpperCase(),
    id,
    textContent: '',
    innerHTML: '',
    value: '',
    checked: false,
    disabled: false,
    hidden: false,
    className: '',
    dataset: {},
    style: {},
    href: '',
    type: tag === 'button' ? 'button' : '',
    options: [],
    classList: {
      add(...names) {
        names.forEach((name) => classes.add(name));
        el.className = [...classes].join(' ');
      },
      remove(...names) {
        names.forEach((name) => classes.delete(name));
        el.className = [...classes].join(' ');
      },
      contains(name) {
        return classes.has(name);
      },
      toggle(name, force) {
        if (force === true) this.add(name);
        else if (force === false) this.remove(name);
        else if (this.contains(name)) this.remove(name);
        else this.add(name);
        return this.contains(name);
      },
    },
    addEventListener(type, fn) {
      (listeners[type] ||= []).push(fn);
    },
    dispatchEvent(evt) {
      for (const fn of listeners[evt.type] || []) fn(evt);
      return true;
    },
    append(...nodes) {
      for (const node of nodes) {
        children.push(typeof node === 'string' ? { textContent: node } : node);
      }
    },
    appendChild(node) {
      children.push(node);
      if (node?.tagName === 'OPTION') el.options.push(node);
      return node;
    },
    replaceChildren(...nodes) {
      children.length = 0;
      el.options = [];
      for (const node of nodes) this.appendChild(node);
    },
    querySelectorAll(sel) {
      return queryAll(sel, flatten(el));
    },
    querySelector(sel) {
      return this.querySelectorAll(sel)[0] || null;
    },
    click() {
      this.dispatchEvent({ type: 'click', preventDefault() {} });
    },
    _children: children,
    _listeners: listeners,
  };
  return el;
}

function flatten(root, acc = []) {
  acc.push(root);
  for (const child of root._children || []) {
    if (child && child.classList) flatten(child, acc);
  }
  return acc;
}

function queryAll(sel, roots) {
  if (sel === '[data-quality]') {
    return roots.filter((el) => el.dataset && el.dataset.quality);
  }
  return [];
}

export function installFakeDom(ids, extra = []) {
  const byId = new Map();
  const all = [];
  for (const id of ids) {
    const el = makeElement('div', id);
    byId.set(id, el);
    all.push(el);
  }
  for (const el of extra) {
    all.push(el);
    if (el.id) byId.set(el.id, el);
  }
  const document = {
    getElementById: (id) => byId.get(id) || null,
    createElement: (tag) => {
      const el = makeElement(tag);
      all.push(el);
      return el;
    },
    querySelectorAll: (sel) => queryAll(sel, all),
    querySelector: (sel) => queryAll(sel, all)[0] || null,
  };
  globalThis.document = document;
  return { document, byId, all };
}

export function qualityPills(values = ['standard', 'high', 'best']) {
  return values.map((quality) => {
    const button = makeElement('button');
    button.dataset.quality = quality;
    button.classList.add('pill', 'quality-pill');
    if (quality === 'standard') button.classList.add('active');
    return button;
  });
}

export class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances = [];

  constructor(url) {
    this.url = url;
    this.readyState = FakeWebSocket.OPEN;
    this.keepaliveInterval = null;
    FakeWebSocket.instances.push(this);
  }

  send() {}

  close(code = 1000) {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.({ code });
  }
}

export function jsonResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 204 ? 'No Content' : status < 400 ? 'OK' : 'Error',
    json: async () => body,
    text: async () => (body == null ? '' : JSON.stringify(body)),
  };
}

export function installFetch(routes) {
  globalThis.fetch = async (url, opts = {}) => {
    const parsed = new URL(String(url), 'http://127.0.0.1:8080');
    const method = (opts.method || 'GET').toUpperCase();
    const handler = routes[`${method} ${parsed.pathname}`] || routes[parsed.pathname];
    if (!handler) return jsonResponse(404, { detail: `missing ${method} ${parsed.pathname}` });
    const result = typeof handler === 'function' ? await handler(opts, parsed) : handler;
    if (result && typeof result.json === 'function') return result;
    return jsonResponse(200, result);
  };
}

export function v2Status(extra = {}) {
  return {
    ok: true,
    api_version: 1,
    extension_api_enabled: true,
    auth_required: true,
    dry_run: false,
    abs_configured: true,
    allow_playlists: false,
    allow_channels: false,
    supports: {
      destinations: true,
      quality_presets: true,
      sponsorblock: true,
      cancel: true,
      retry: true,
    },
    ...extra,
  };
}

export async function emitAsync(el, type = 'click') {
  const event = { type, preventDefault() {} };
  await Promise.all((el._listeners[type] || []).map((fn) => fn(event)));
}

export async function sendBackground(onMessage, message) {
  return new Promise((resolve) => {
    onMessage.emit(message, {}, resolve);
  });
}

/** Keep setInterval from holding the test process open. */
export function silenceIntervals() {
  const original = globalThis.setInterval.bind(globalThis);
  const ids = [];
  globalThis.setInterval = (fn, delay, ...rest) => {
    const id = original(() => {}, 2_147_483_647);
    ids.push(id);
    return id;
  };
  return () => {
    for (const id of ids) clearInterval(id);
    globalThis.setInterval = original;
  };
}
