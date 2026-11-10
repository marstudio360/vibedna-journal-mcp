// journals: one brain over the project journals.
// The search itself is the journal tool's quick map (quick_hook.py next to its server.py, no AI, ~0.3 s);
// this mod decides when it runs and puts the answer where your AI cannot skip it:
//   - tool.call: a file edit, or a command that writes or reaches a server, gets the map; the first touch
//     of a piece in a "## Brain map" table carries that piece's JOURNAL BRIEF (its Handoff, state, pending,
//     decisions, what exists, rules and newest entries, read from the file) and goes through; the brief counts as
//     the read. Only when the journal file is missing is the touch denied (quick_hook.py's gate, escape on the 3rd
//     attempt). Your exact rule tests (rulecompile.py) and the server flood counter (cmdguard.py) run first, no AI
//   - tool.call that writes code, runs a script or a remote command, or briefs an agent: the TOOLS map first
//     (toolmap.py: the tools and working flows that already do it, matched by concept); when the action builds its
//     own way of doing what a tool does, the list comes with it (DENIED ONCE only with JOURNAL_AI_CHECKS=risky|all) (2026-10-26: an Instagram carousel was
//     posted by a loose Playwright script while the posting tool sat unused)
//   - tool.call on reads (Read, Grep, Glob, read-only commands, data queries): the first read of a mapped piece or a
//     project folder with journals in a session goes through the same gate; later, the first read in each user
//     message carries a short "read its journal first" note
//   - after a shell command ran: identifiers in what it RETURNED (units, scripts, sessions) that the owner already
//     ruled on come back as a note (quick_hook.py --output), once per session per name
//   - after a journal read runs (journal_read, journal_read_section, journal_handoff_brief, journal_search,
//     journal_quick, or a Read of a *_JOURNAL.md), the mod reports it to quick_hook.py: that record opens the gate
//   - prompt.submit: a message that names something concrete (a Brain map key, a journal's name, or two common
//     words that together point at one journal) carries its map; a word's map comes back a few messages later
//   - classic.Stop: before the turn ends, the reply is judged against the owner brief (owner_brief.py) of the
//     projects in play; a reply that breaks it is sent back for a rewrite in the same turn
//   - turn.complete: the AI's finished reply, when it proposes something, is checked against what the owner already
//     said (journal verdicts); the check rides into the next turn for the AI, never drawn in the chat
//   - prompt.compose: a short fixed section in the system prompt, so the habit is part of every turn
//   - the status line is for the person, never for the AI: a quiet "Journals DNA · active", reset at every message,
//     and one plain sentence only when something real happens in that turn (2026-11-03: the owner saw the internal
//     "journals: a tool already does this, use it or say why not" stuck under his prompt, in words meant for the AI)
// Config (environment): JOURNAL_MCP_DIR = folder of the journal tool's server.py; JOURNAL_PYTHON = python to use.
import type { Register } from 'claude-code'

const EDIT = /^(Write|Edit|MultiEdit|NotebookEdit)$/
const SHELL = /^(Bash|PowerShell)$/
const AGENT = /^(Agent|Task)$/
const JOURNAL_FILE = /journal[^\\/]*\.md$/i
const READ = /^(Read|Grep|Glob)$/
const DATA = /^mcp__(?!journal__).*(sql|query)/i
const MCP = /^mcp__/
const JOURNAL_READ_TOOL = /^mcp__journal__journal_(read|read_section|handoff_brief|search|quick)$/
const JOURNAL_SAVE_TOOL = /^mcp__journal__journal_(append|update_section|decision_add|capability_add)$/

// What the person sees under the prompt: calm by default, one plain sentence for a real event.
const ACTIVE = 'Journals DNA · active'
const SAID = {
  read: 'Journals DNA · reading your notes on this first',
  tool: 'Journals DNA · using a tool you already have instead',
  decided: 'Journals DNA · found what you already decided on this',
  saved: 'Journals DNA · saved to your journal',
  fixed: 'Journals DNA · fixing a reply that went against your notes',
}
const DECIDED = /OWNER BRIEF|DECIDED:|already decided|the owner already said/i

const BRAIN = [
  'JOURNALS (one brain). Every project keeps its context in a *_JOURNAL.md.',
  'Before touching, building or answering about anything, call journal_quick("<word or file>") and read what it',
  'points to: what was decided, what exists, what is in flight, who is working on it now. There are no owners:',
  'anyone may take any piece once its context is read. The journals mod shows the map by itself when you touch',
  'a mapped piece, and hands you that piece\'s journal brief with the call: read it before you act.',
  'Before writing or running your own script for a job, use the tool that already does it: the mod lists them',
  '("TOOLS THAT ALREADY DO THIS"); if none fits, say in one line why and improve that tool.',
].join('\n')

type Out = { permissionDecision?: string; permissionDecisionReason?: string; additionalContext?: string }

// The text a finished tool call returned, whatever shape the result has.
function resultText(ran: any): string {
  for (const k of ['text', 'output', 'stdout']) if (typeof ran?.[k] === 'string' && ran[k]) return ran[k]
  if (Array.isArray(ran?.content)) return ran.content.map((x: any) => (typeof x === 'string' ? x : x?.text ?? '')).join('\n')
  try { return typeof ran?.result === 'string' ? ran.result : JSON.stringify(ran?.result ?? '') } catch { return '' }
}

async function quick($: any, call: Record<string, unknown>, prompt: boolean | 'reply' | 'output' | 'stop'): Promise<Out | null> {
  const dir = await $.env.get('JOURNAL_MCP_DIR')
  if (!dir) return null
  const py = (await $.env.get('JOURNAL_PYTHON')) || 'python3'
  const flag = prompt === 'reply' ? ['--reply'] : prompt === 'output' ? ['--output'] : prompt === 'stop' ? ['--stop']
    : prompt ? ['--prompt'] : []
  const argv = [py, `${dir}/quick_hook.py`, ...flag]
  try {
    const r = await $.process.run(argv, {
      // reports_reads: this mod reports journal reads, so the gate may wait for one (older mods never did).
      stdin: JSON.stringify({ ...call, reports_reads: true, session_id: await $.session.id(), cwd: await $.session.cwd() }),
      // The owner brief asks the judge model (~5 s; the stop check reads a whole reply).
      // The end-of-turn check reads the reply, searches every journal for each claim and asks the judge twice (14-25 s
      // measured 2026-11-03); at 30 s it was cut and said nothing.
      // A command's check reads the owner's rules and asks the judge twice (8-19 s measured 2026-11-04); at 15 s it was
      // cut and the command ran unchecked.
      // The stop check holds the end of the turn, so it gets 12 s at most (2026-11-06: up to 60 s of "Philosophizing..."
      // after a finished reply); past that the reply goes out unchecked rather than leaving the owner waiting.
      timeoutMs: prompt === 'stop' ? 12000 : prompt === true ? 30000 : prompt === false ? 45000 : 15000,
      env: { PYTHONIOENCODING: 'utf-8' },
    })
    if (r.exitCode !== 0 || !r.stdout.trim()) return null
    return JSON.parse(r.stdout).hookSpecificOutput ?? null
  } catch {
    return null
  }
}

// After a journal read ran: tell quick_hook.py which journal was read and whether it worked.
async function report($: any, e: any, ran: any) {
  const ok = ran?.deny === undefined && ran?.isError !== true
  let input: Record<string, unknown>
  if (e.tool === 'Read') {
    input = { journal_read: e.file_path, ok }
  } else {
    const { tool, ...args } = e
    let text = typeof ran?.text === 'string' ? ran.text : ''
    if (!text) { try { text = JSON.stringify(ran?.result ?? '') } catch {} }
    input = { journal_tool: tool, args, text: text.slice(0, 40000), ok }
  }
  await quick($, { tool_name: e.tool, tool_input: input }, false)
}

export const register: Register = on => {
  on('tool.call', async ($, e: any, next) => {
    let input: Record<string, unknown> | null = null
    if (EDIT.test(e.tool)) {
      const fp = e.file_path ?? e.notebook_path
      // The first 4 KB of what is written: the tools map reads code signals in it (connect_over_cdp, smtplib...).
      const content = String(e.content ?? e.new_string ?? e.new_source
        ?? (Array.isArray(e.edits) ? e.edits.map((x: any) => x?.new_string ?? '').join('\n') : '')).slice(0, 4000)
      if (fp && !JOURNAL_FILE.test(fp)) input = { file_path: fp, content }
    } else if (SHELL.test(e.tool)) {
      // Writes get the map and the gate; reads get the gate once, then the per-message note. quick_hook.py decides.
      // The description is the AI's own words for what it is about to do: quick_hook maps THAT, not the typed words.
      if (e.command) input = { command: e.command, description: e.description ?? '' }
    } else if (AGENT.test(e.tool)) {
      input = { description: e.description ?? '', prompt: String(e.prompt ?? '').slice(0, 4000) }
    } else if (READ.test(e.tool)) {
      if (e.tool === 'Read' && JOURNAL_FILE.test(e.file_path ?? '')) {
        // Reading a journal is never gated; once it ran, it opens the gate for that journal's pieces.
        const ran: any = await next(e)
        await report($, e, ran)
        return ran
      }
      input = { paths: [e.file_path, e.path, e.tool === 'Glob' ? e.pattern : null, e.glob].filter(Boolean) }
    } else if (DATA.test(e.tool)) {
      input = { query: String(e.query ?? e.sql ?? JSON.stringify(e)).slice(0, 4000) }
    } else if (MCP.test(e.tool) && !JOURNAL_READ_TOOL.test(e.tool) && !JOURNAL_SAVE_TOOL.test(e.tool)) {
      // Any other MCP tool (browser, posting, mail, servers) is checked too, with the owner's latest message as its
      // context (2026-11-04: a browser launch to find a mail already read on 11-03 ran with no check at all).
      const { tool, ...args } = e
      let a = ''
      try { a = JSON.stringify(args) } catch {}
      input = { mcp_tool: tool, args: a.slice(0, 3000) }
    } else if (JOURNAL_READ_TOOL.test(e.tool)) {
      const ran: any = await next(e)
      await report($, e, ran)
      return ran
    } else if (JOURNAL_SAVE_TOOL.test(e.tool)) {
      const ran: any = await next(e)
      if (ran?.deny === undefined && ran?.isError !== true) $.ui.status(SAID.saved)
      return ran
    }
    if (!input) return next(e)
    const out = await quick($, { tool_name: e.tool, tool_input: input }, false)
    if (out?.permissionDecision === 'deny' && out.permissionDecisionReason) {
      $.ui.status(out.permissionDecisionReason.startsWith('TOOLS THAT ALREADY DO THIS') ? SAID.tool : SAID.read)
      return { deny: out.permissionDecisionReason }
    }
    const ran: any = await next(e)
    if (ran.deny !== undefined) return ran
    const ctx = out?.additionalContext ? [out.additionalContext] : []
    // What the command RETURNED: names in it the owner already ruled on (2026-10-28: `systemctl --failed` listed three
    // units the owner had called "NOT outages to report" on 10-23, and the session reported them as outages).
    if (SHELL.test(e.tool)) {
      const text = resultText(ran)
      if (text.length > 20) {
        const o2 = await quick($, { output: text.slice(-60000) }, 'output')
        if (o2?.additionalContext) ctx.push(o2.additionalContext)
      }
    }
    return ctx.length ? { ...ran, context: [...(ran.context ?? []), ...ctx] } : ran
  })

  // The AI's own finished reply: when it proposes something, what the owner already said about each thing it names
  // is shown under the reply and carried into the next turn (2026-10-26: a method tested on 10-15 was proposed as
  // new in plain chat, where no tool call ever reached the map). The note is for the AI only: it rides into the next
  // turn and is never drawn in the chat (2026-10-27: the owner saw it under his message, garbled, and asked what it was).
  let replyNote = ''
  // Never awaited (2026-11-06, owner with a screenshot of "Philosophizing..." under a finished reply: "it cannot stay
  // stuck after a reply, everything has to pass before"): this note is for the NEXT turn, so the turn ends at once and
  // the check finishes in the background.
  on('turn.complete', async ($, e: any, next) => {
    const r = await next(e)
    if (e.agentId || e.reason !== 'answer' || !e.answer) return r
    quick($, { reply: e.answer }, 'reply').then(out => { if (out?.additionalContext) replyNote = out.additionalContext })
      .catch(() => {})
    return r
  })

  // Before the turn ends: the finished reply against the owner brief of the projects in play. A reply that proposes
  // again what the owner rejected or already saw lose is sent back for a rewrite in the same turn (2026-11-03: the
  // check above rode into the next turn, after the owner had read the repeated proposal and had to correct it).
  on('classic.Stop', async ($, e: any, next) => {
    const r: any = await next(e)
    if (r?.block || e.stop_hook_active || !e.last_assistant_message) return r
    const out: any = await quick($, { reply: e.last_assistant_message, stop_hook_active: false }, 'stop')
    if (!out?.block) return r
    $.ui.status(SAID.fixed)
    return { ...r, block: String(out.block) }
  })

  on('session.start', async ($, e, next) => {
    $.ui.status(ACTIVE)
    // Your own start-of-session command, if you want one (a backup, a sync): a JSON array in JOURNAL_ON_SESSION_START,
    // for example ["python3", "/path/backup.py"]; never awaited, so it never slows the start; unset by default.
    const cmd = await $.env.get('JOURNAL_ON_SESSION_START')
    if (cmd) {
      try {
        const argv = JSON.parse(cmd)
        if (Array.isArray(argv) && argv.length) $.process.run(argv.map(String), { timeoutMs: 120000 }).catch(() => {})
      } catch { /* a bad value is ignored */ }
    }
    return next(e)
  })

  on('prompt.submit', async ($, e, next) => {
    $.ui.status(ACTIVE)
    const out = await quick($, { prompt: e.text }, true)
    if (out?.additionalContext && DECIDED.test(out.additionalContext)) $.ui.status(SAID.decided)
    const ctx = [...(e.context ?? [])]
    if (replyNote) { ctx.push(replyNote); replyNote = '' }
    if (out?.additionalContext) ctx.push(out.additionalContext)
    return ctx.length !== (e.context ?? []).length ? next({ ...e, context: ctx }) : next(e)
  })

  on('prompt.compose', async ($, e, next) => {
    const r = await next(e)
    return { sections: [...r.sections, { id: 'journals:brain', text: BRAIN, scope: 'session' as const }] }
  })
}
