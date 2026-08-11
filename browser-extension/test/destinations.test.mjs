import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  LIBRARY_ROOT_LABEL,
  LIBRARY_ROOT_VALUE,
  destinationChoices,
  resolveSavedDestination,
} from '../src/destinations.js';

describe('destinations', () => {
  it('always prepends Library root', () => {
    const choices = destinationChoices(['Theology', 'Lectures']);
    assert.equal(choices[0].value, LIBRARY_ROOT_VALUE);
    assert.equal(choices[0].label, LIBRARY_ROOT_LABEL);
    assert.equal(choices.length, 3);
  });

  it('keeps a still-valid saved destination', () => {
    const resolved = resolveSavedDestination('Theology', ['Lectures', 'Theology'], 'Lectures');
    assert.equal(resolved.value, 'Theology');
    assert.equal(resolved.banner, '');
  });

  it('falls back to the server default then root with a banner', () => {
    const toDefault = resolveSavedDestination('Gone', ['Theology'], 'Theology');
    assert.equal(toDefault.value, 'Theology');
    assert.match(toDefault.banner, /Gone/);

    const toRoot = resolveSavedDestination('Gone', ['Lectures'], '');
    assert.equal(toRoot.value, LIBRARY_ROOT_VALUE);
    assert.match(toRoot.banner, /Library root/);
  });
});
