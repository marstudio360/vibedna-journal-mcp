import { expect, test } from 'claude-code/testing'

// The journal tool is a python process; here it is answered by the test, and the status line is collected.
function world(on, hookOutput: Record<string, unknown> | null) {
  const status: (string | undefined)[] = []
  on('env.get', ($, e) => ({ value: String(e.name ?? e.args?.[0] ?? '') === 'JOURNAL_MCP_DIR' ? '/journal' : undefined }))
  on('session.id', () => ({ value: 's1' }))
  on('session.cwd', () => ({ value: '/work' }))
  on('process.run', () => ({ value: { exitCode: 0, stdout: hookOutput ? JSON.stringify({ hookSpecificOutput: hookOutput }) : '', stderr: '' } }))
  on('ui.status', ($, e) => { status.push(e.text); return { value: undefined } })
  on('tool.call', () => ({ result: 'ok' }))
  return status
}

test('a stop for an existing tool says it in plain words, never the internal text', async ($, on) => {
  const status = world(on, { permissionDecision: 'deny', permissionDecisionReason: 'TOOLS THAT ALREADY DO THIS:\n1. ...' })
  const r = await $.tool.call({ tool: 'Write', file_path: '/work/a.py', content: 'print(1)' })
  expect(String(r.deny || '')).toContain('TOOLS THAT ALREADY DO THIS')
  expect(status.at(-1)).toBe('Journals DNA · using a tool you already have instead')
  expect(status.join(' ')).not.toContain('say why not')
})

test('a stop until the journal is read says it in plain words', async ($, on) => {
  const status = world(on, { permissionDecision: 'deny', permissionDecisionReason: 'JOURNALS GATE, STOPPED. Before touching ...' })
  await $.tool.call({ tool: 'Edit', file_path: '/work/a.py', old_string: 'a', new_string: 'b' })
  expect(status.at(-1)).toBe('Journals DNA · reading your notes on this first')
})

test('saving to a journal is shown once it worked', async ($, on) => {
  const status = world(on, null)
  await $.tool.call({ tool: 'mcp__journal__journal_append', name_or_path: 'X_JOURNAL.md', entry: 'done' })
  expect(status.at(-1)).toBe('Journals DNA · saved to your journal')
})

test('a normal edit changes nothing on screen', async ($, on) => {
  const status = world(on, null)
  await $.tool.call({ tool: 'Edit', file_path: '/work/a.py', old_string: 'a', new_string: 'b' })
  expect(status.length).toBe(0)
})
