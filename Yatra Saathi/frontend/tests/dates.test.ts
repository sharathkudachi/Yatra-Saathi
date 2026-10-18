// Trip-date rules and date-only handling (src/utils/dates.ts).
// `npm test` runs this file under several time zones, including ones far from UTC and ones
// with daylight-saving changes, so a UTC round-trip that moves a day would fail here.
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { briefFromMessage } from '../src/services/briefFromMessage.ts'
import {
  addDays, arrivalDayOffset, dateOnlyToLocal, formatDateOnly, formatWallClock, isDateOnly,
  toDateOnly, todayDateOnly, tripDateIssue,
} from '../src/utils/dates.ts'

const TODAY = '2026-09-25'

test('conversational date range formats keep both dates', () => {
  const current = {
    destination: '', startDate: '2026-11-16', endDate: '2026-11-20', travellers: 2,
    budget: '25000.00', currency: 'INR', preferences: '',
  }
  const examples = [
    '12 to 16 October 2026',
    '12th to 16th October 2026',
    '12 Oct to 16 Oct 2026',
    '12 October 2026 to 16 October 2026',
  ]
  for (const range of examples) {
    const message = `Plan a trip from Mumbai to Kolkata for 5 adults from ${range}, budget ₹50000`
    const brief = briefFromMessage(message, current, ['Mumbai', 'Kolkata'], ['INR'], new Date(2026, 8, 24))
    assert.equal(brief.destination, 'Kolkata', range)
    assert.equal(brief.startDate, '2026-10-12', range)
    assert.equal(brief.endDate, '2026-10-16', range)
    assert.equal(brief.travellers, 5, range)
    assert.equal(brief.budget, '50000.00', range)
    assert.equal(brief.currency, 'INR', range)
  }
})

test('a start date in the past is rejected, today is allowed', () => {
  assert.equal(tripDateIssue('2026-09-24', '2026-09-27', TODAY), 'past')
  assert.equal(tripDateIssue(TODAY, '2026-09-26', TODAY), null)
})

test('an end date on or before the start date is rejected', () => {
  assert.equal(tripDateIssue('2026-11-07', '2026-11-04', TODAY), 'order')
  assert.equal(tripDateIssue('2026-11-04', '2026-11-04', TODAY), 'order')
})

test('a valid multi-night trip (04/11/2026 -> 07/11/2026) is accepted', () => {
  assert.equal(tripDateIssue('2026-11-04', '2026-11-07', TODAY), null)
})

test('incomplete dates are not flagged until both are chosen', () => {
  assert.equal(tripDateIssue('', '2026-11-07', TODAY), null)
  assert.equal(tripDateIssue('2026-11-04', '', TODAY), null)
})

test('date-only values never shift by a day', () => {
  for (const day of ['2026-01-01', '2026-03-08', '2026-03-29', '2026-10-25', '2026-11-01', '2026-11-04', '2026-12-31']) {
    assert.equal(toDateOnly(dateOnlyToLocal(day)), day)
    assert.equal(addDays(addDays(day, 1), -1), day)
    assert.equal(formatDateOnly(day, 'en-GB', { day: '2-digit', month: '2-digit', year: 'numeric' }),
      `${day.slice(8)}/${day.slice(5, 7)}/${day.slice(0, 4)}`)
  }
  assert.equal(addDays('2026-11-04', 3), '2026-11-07')
  assert.equal(addDays('2026-12-31', 1), '2027-01-01')
  assert.equal(addDays('2026-03-07', 1), '2026-03-08') // US DST starts 8 Mar 2026
  assert.equal(addDays('2026-10-24', 1), '2026-10-25') // EU DST ends 25 Oct 2026
})

test("today is the browser's local calendar day, not the UTC day", () => {
  const lateEvening = new Date(2026, 8, 25, 23, 30) // 23:30 local on 25 Sep
  assert.equal(todayDateOnly(lateEvening), '2026-09-25')
  const earlyMorning = new Date(2026, 8, 25, 0, 30)
  assert.equal(todayDateOnly(earlyMorning), '2026-09-25')
})

test('only real YYYY-MM-DD dates are date-only values', () => {
  assert.equal(isDateOnly('2026-11-04'), true)
  for (const bad of ['2026-02-30', '04/11/2026', '2026-11-04T00:00:00Z', '']) assert.equal(isDateOnly(bad), false)
})

test('a flight landing after local midnight is shown as the next day, at local time', () => {
  const departs = '2026-11-09T22:40:00+05:30'
  const arrives = '2026-11-10T00:55:00+05:30'
  assert.equal(arrivalDayOffset(departs, arrives), 1)
  assert.equal(formatWallClock(arrives, 'en-GB'), '00:55')
  assert.equal(formatWallClock(departs, 'en-GB'), '22:40')
  // Arrival already converted to the destination airport's zone (Dubai) can be the same local day.
  assert.equal(arrivalDayOffset('2026-11-09T21:40:00+05:30', '2026-11-09T22:51:00+04:00'), 0)
})
