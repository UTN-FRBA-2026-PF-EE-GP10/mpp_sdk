import { useCallback, useEffect, useRef, useState } from 'react'
import { runDuration, sampleIndexAtTime } from '@/lib/runPlayback'
import type { RunSample } from '@/lib/runs'

export interface RunPlayback {
  playing: boolean
  /** Seconds elapsed since the run's own start (RunSample.t's origin),
   * not wall-clock. */
  time: number
  duration: number
  /** The sample to show right now, -1 for an empty run. */
  index: number
  play: () => void
  pause: () => void
  toggle: () => void
  restart: () => void
  seek: (t: number) => void
  speed: number
  setSpeed: (speed: number) => void
}

/**
 * Drives run playback with `requestAnimationFrame`, advancing `time` at
 * `speed` times real time so a run plays back in roughly the wall-clock
 * time it took to capture - no animation library, per the frontend's
 * no-new-dependencies rule.
 *
 * Design calls this makes, since the brief leaves them open:
 * - Seeking (via `seek`, what the scrub bar calls) pauses playback. A
 *   drag-while-playing preview would need to fight the RAF loop over the
 *   same state on every pointer move; pausing on seek is simpler and
 *   still lets an operator resume with one click from wherever they
 *   dropped the scrubber.
 * - Reaching the end pauses rather than looping, matching a normal video
 *   player - a run finishing (or aborting) is meaningful and shouldn't
 *   quietly restart before it's been read.
 * - `play()` called at the end restarts from zero, the same as pressing
 *   play on a finished video, so there is no "stuck at the end, play does
 *   nothing" dead state.
 * - `restart()` only resets the clock to zero; it does not change
 *   `playing`, so scrubbing back to the start while paused stays paused
 *   and while playing keeps playing.
 */
export function useRunPlayback(samples: RunSample[]): RunPlayback {
  const duration = runDuration(samples)
  const [time, setTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const frameRef = useRef<number | null>(null)
  const lastWallMsRef = useRef<number | null>(null)

  // A newly opened run (different `samples` reference) starts fresh -
  // otherwise the previous run's scrub position would leak into the next
  // one opened in the same dialog instance. Resetting during render
  // rather than in an effect avoids a one-frame flash of the old time
  // against the new samples (React docs call this pattern out by name:
  // "adjusting state when a prop changes").
  const [knownSamples, setKnownSamples] = useState(samples)
  if (samples !== knownSamples) {
    setKnownSamples(samples)
    setTime(0)
    setPlaying(false)
  }

  useEffect(() => {
    if (!playing) {
      lastWallMsRef.current = null
      return
    }
    function tick(nowMs: number) {
      const lastMs = lastWallMsRef.current
      if (lastMs !== null) {
        const deltaS = ((nowMs - lastMs) / 1000) * speed
        setTime((t) => {
          const next = t + deltaS
          if (next >= duration) {
            setPlaying(false)
            return duration
          }
          return next
        })
      }
      lastWallMsRef.current = nowMs
      frameRef.current = requestAnimationFrame(tick)
    }
    frameRef.current = requestAnimationFrame(tick)
    return () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current)
    }
  }, [playing, speed, duration])

  const play = useCallback(() => {
    setTime((t) => (t >= duration ? 0 : t))
    setPlaying(true)
  }, [duration])

  const pause = useCallback(() => setPlaying(false), [])

  // Routed through play()/pause() rather than toggling `playing`
  // directly, so pressing the same button at the end of a run gets
  // play()'s "restart from zero" behaviour instead of a no-op.
  const toggle = useCallback(() => {
    if (playing) pause()
    else play()
  }, [playing, pause, play])

  const restart = useCallback(() => setTime(0), [])

  const seek = useCallback(
    (t: number) => {
      setPlaying(false)
      setTime(Math.max(0, Math.min(duration, t)))
    },
    [duration],
  )

  const index = sampleIndexAtTime(samples, time)

  return {
    playing,
    time,
    duration,
    index,
    play,
    pause,
    toggle,
    restart,
    seek,
    speed,
    setSpeed,
  }
}
