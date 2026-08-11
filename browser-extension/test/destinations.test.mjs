import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  LIBRARY_ROOT_LABEL,
  LIBRARY_ROOT_VALUE,
  SERVER_DEFAULT_VALUE,
  destinationChoices,
  resolveSavedDestination,
  serverDefaultLabel,
} from '../src/destinations.js';

describe('destinations', () => {
  it('prepends server default then Library root', () => {
    const choices = destinationChoices(['Theology', 'Lectures'], 'Theology');
    assert.equal(choices[0].value, SERVER_DEFAULT_VALUE);
    assert.equal(choices[0].label, 'Server default — Theology');
    assert.equal(choices[1].value, LIBRARY_ROOT_VALUE);
    assert.equal(choices[1].label, LIBRARY_ROOT_LABEL);
    assert.equal(choices.length, 4);
    assert.equal(serverDefaultLabel(''), 'Server default');
  });

  it('treats missing or blank storage as server default', () => {
    assert.equal(resolveSavedDestination('', ['Theology'], 'Theology').value, SERVER_DEFAULT_VALUE);
    assert.equal(resolveSavedDestination(null, ['Theology'], 'Theology').value, SERVER_DEFAULT_VALUE);
    assert.equal(resolveSavedDestination(undefined, ['Theology'], 'Theology').banner, '');
  });

  it('keeps explicit library root and still-valid folders', () => {
    assert.equal(
      resolveSavedDestination(LIBRARY_ROOT_VALUE, ['Theology'], 'Theology').value,
      LIBRARY_ROOT_VALUE,
    );
    const resolved = resolveSavedDestination('Theology', ['Lectures', 'Theology'], 'Lectures');
    assert.equal(resolved.value, 'Theology');
    assert.equal(resolved.banner, '');
  });

  it('falls back to server default with a banner when a folder is gone', () => {
    const toDefault = resolveSavedDestination('Gone', ['Theology'], 'Theology');
    assert.equal(toDefault.value, SERVER_DEFAULT_VALUE);
    assert.match(toDefault.banner, /Gone/);
    assert.match(toDefault.banner, /server default/);
  });
});
