import { useEffect, useRef, useState } from 'react'

/** Re-render every `ms` (or never when null). Used for live timers. */
export function useTick(ms: number | null) {
  const [, setN] = useState(0)
  useEffect(() => {
    if (ms === null) return
    const id = window.setInterval(() => setN((n) => n + 1), ms)
    return () => window.clearInterval(id)
  }, [ms])
}

/** Tween a number toward its target (for the cash hero figure). */
export function useTweened(target: number, durationMs = 900): number {
  const [value, setValue] = useState(target)
  const from = useRef(target)
  useEffect(() => {
    const start = performance.now()
    const a = from.current
    let raf = 0
    const step = (t: number) => {
      const k = Math.min(1, (t - start) / durationMs)
      const eased = 1 - Math.pow(1 - k, 3)
      setValue(a + (target - a) * eased)
      if (k < 1) raf = requestAnimationFrame(step)
      else from.current = target
    }
    raf = requestAnimationFrame(step)
    return () => {
      cancelAnimationFrame(raf)
      from.current = target
    }
  }, [target, durationMs])
  return value
}
