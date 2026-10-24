// Main-thread side of the Python worker: sends requests, waits for answers,
// and stops the worker if a program runs too long (infinite loop safety).
import type { Trace, WhyAnswer } from '../types'

export type EngineStatus = 'loading' | 'ready' | 'running' | 'failed'

export interface LiveResult {
  status: 'input' | 'done'
  stdout: string
  error: string | null
  error_line: number | null
}

const RUN_TIMEOUT_MS = 20_000

interface Pending {
  resolve: (value: string) => void
  reject: (error: Error) => void
}

export class PythonEngine {
  private worker!: Worker
  private pending = new Map<number, Pending>()
  private nextId = 1
  private loaded = false
  private onStatus: (status: EngineStatus, detail?: string) => void

  constructor(onStatus: (status: EngineStatus, detail?: string) => void) {
    this.onStatus = onStatus
    this.start()
  }

  private start() {
    this.loaded = false
    this.onStatus('loading')
    this.worker = new Worker(new URL('./worker.ts', import.meta.url), { type: 'module' })
    this.worker.onmessage = (event) => {
      const data = event.data
      if (data.type === 'ready') {
        this.loaded = true
        return this.onStatus('ready')
      }
      if (data.type === 'failed') return this.onStatus('failed', data.error)
      const waiting = this.pending.get(data.id)
      if (!waiting) return
      this.pending.delete(data.id)
      if (data.error !== undefined) waiting.reject(new Error(lastLine(data.error)))
      else waiting.resolve(data.result)
    }
  }

  dispose() {
    this.worker.terminate()
  }

  /** Stop whatever is running and load a fresh Python. */
  restart(reason: string) {
    this.worker.terminate()
    for (const waiting of this.pending.values()) waiting.reject(new Error(reason))
    this.pending.clear()
    this.start()
  }

  private call(method: string, args: (string | number)[], timeoutMs?: number): Promise<string> {
    const id = this.nextId++
    return new Promise<string>((resolve, reject) => {
      let timer: number | undefined
      if (timeoutMs) {
        timer = window.setTimeout(() => {
          this.restart(`Stopped after ${timeoutMs / 1000} seconds: the program took too long (an endless loop?).`)
        }, timeoutMs)
      }
      this.pending.set(id, {
        resolve: (value) => { clearTimeout(timer); resolve(value) },
        reject: (error) => { clearTimeout(timer); reject(error) },
      })
      this.worker.postMessage({ id, method, args })
    })
  }

  /** seed: the live run's random seed, so random numbers repeat (-1: none). */
  async run(code: string, stdin: string, seed = -1): Promise<{ trace: Trace; narration: string[] }> {
    this.onStatus('running')
    try {
      const trace = JSON.parse(await this.call('run', [code, stdin, 2000, seed], RUN_TIMEOUT_MS)) as Trace
      const narration = JSON.parse(await this.call('explain_all', [])) as string[]
      return { trace, narration }
    } finally {
      if (this.loaded) this.onStatus('ready')  // not if it was just restarted
    }
  }

  /**
   * Run the program normally (not traced) with the lines typed so far.
   * "input" means it is waiting for another line: ask, then call again
   * with that line added (the program repeats itself up to that point).
   */
  async runLive(code: string, stdin: string, seed: number, eof = false): Promise<LiveResult> {
    return JSON.parse(await this.call('run_live', [code, stdin, seed, eof ? 1 : 0], RUN_TIMEOUT_MS)) as LiveResult
  }

  /** Use a trace from the C/C++ backend for "Why?" questions. */
  async load(trace: Trace): Promise<string[]> {
    await this.call('load', [JSON.stringify(trace)])
    return JSON.parse(await this.call('explain_all', [])) as string[]
  }

  async why(step: number, name: string, frameIndex: number): Promise<WhyAnswer> {
    return JSON.parse(await this.call('why', [step, name, frameIndex])) as WhyAnswer
  }

  async whyOutput(lineIndex: number): Promise<WhyAnswer | null> {
    return JSON.parse(await this.call('why_output', [lineIndex])) as WhyAnswer | null
  }
}

/** A Python traceback is long; its last line says what went wrong. */
function lastLine(message: string): string {
  const lines = message.trim().split('\n')
  return lines[lines.length - 1]
}
