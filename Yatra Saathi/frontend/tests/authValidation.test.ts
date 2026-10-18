import assert from 'node:assert/strict'
import { test } from 'node:test'
import { hasExplicitRegistrationConsent } from '../src/utils/authValidation.ts'

test('registration requires an explicit affirmative terms choice', () => {
  assert.equal(hasExplicitRegistrationConsent(undefined), false)
  assert.equal(hasExplicitRegistrationConsent(null), false)
  assert.equal(hasExplicitRegistrationConsent(false), false)
  assert.equal(hasExplicitRegistrationConsent(true), true)
})
