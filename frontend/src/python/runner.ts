// Main-thread side of the Python worker: sends requests, waits for answers,
// and stops the worker if a program runs too long (infinite loop safety).
import type { Trace, WhyAnswer } from '../types'

export type EngineStatus = 'loading' | 'ready' | 'running' | 'failed'

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

  async run(code: string, stdin: string): Promise<{ trace: Trace; narration: string[] }> {
    this.onStatus('running')
    try {
      const trace = JSON.parse(await this.call('run', [code, stdin], RUN_TIMEOUT_MS)) as Trace
      const narration = JSON.parse(await this.call('explain_all', [])) as string[]
      return { trace, narration }
    } finally {
      if (this.loaded) this.onStatus('ready')  // not if it was just restarted
    }
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
