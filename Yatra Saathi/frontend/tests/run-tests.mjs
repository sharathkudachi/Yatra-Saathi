import { readdirSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const testDirectory = dirname(fileURLToPath(import.meta.url))
const testFiles = readdirSync(testDirectory)
  .filter((name) => name.endsWith('.test.ts'))
  .map((name) => join(testDirectory, name))
const timezones = ['Asia/Kolkata', 'UTC', 'America/Los_Angeles', 'Pacific/Kiritimati', 'Europe/London']

for (const timezone of timezones) {
  console.log(`\nRunning frontend tests with TZ=${timezone}`)
  const result = spawnSync(process.execPath, ['--test', ...testFiles], {
    cwd: dirname(testDirectory),
    env: { ...process.env, TZ: timezone },
    stdio: 'inherit',
  })
  if (result.error) throw result.error
  if (result.status !== 0) process.exit(result.status ?? 1)
}
