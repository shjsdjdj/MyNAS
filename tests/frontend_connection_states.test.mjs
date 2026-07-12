import assert from 'node:assert/strict'
import test from 'node:test'
import axios from 'axios'

import { classifyApiError, resolveConnectionFailure } from '../src/api.js'

test('classifies an expired authenticated request', () => {
  assert.equal(classifyApiError({ response: { status: 401 }, config: { url: '/dashboard' } }), 'auth_expired')
})

test('does not classify invalid login credentials as an expired session', () => {
  assert.equal(classifyApiError({ response: { status: 401 }, config: { url: '/auth/login' } }), null)
})

test('uses explicit sanitized backend readiness codes', () => {
  assert.equal(classifyApiError({ response: { status: 503, data: { error: { code: 'database_error' } } } }), 'database_error')
  assert.equal(classifyApiError({ response: { status: 503, data: { error: { code: 'storage_unavailable' } } } }), 'storage_unavailable')
})

test('distinguishes device offline from an unreachable backend', () => {
  assert.equal(classifyApiError({}, false), 'network_error')
  assert.equal(classifyApiError({}, true), 'backend_offline')
})

test('does not mislabel an internal API failure as a network error', async () => {
  const originalGet = axios.get
  axios.get = async () => ({ data: { status: 'ok', backend: 'running' } })
  try {
    assert.equal(await resolveConnectionFailure({ response: { status: 500 } }), 'backend_error')
  } finally {
    axios.get = originalGet
  }
})
