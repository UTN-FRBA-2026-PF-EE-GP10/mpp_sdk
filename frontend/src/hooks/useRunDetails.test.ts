import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/lib/apiError'
import type { RunDetail } from '@/lib/runs'
import { MAX_CONCURRENT_RUN_FETCHES, RunDetailLoader } from './useRunDetails'

vi.mock('@/lib/api', () => ({ fetchRun: vi.fn() }))

import { fetchRun } from '@/lib/api'

const detail = (id: string) => ({ id }) as unknown as RunDetail

// Lets the promise chains inside the loader settle.
const settle = () => new Promise((r) => setTimeout(r, 0))

function setup() {
  const events = { loaded: vi.fn(), gone: vi.fn(), failed: vi.fn() }
  return { events, loader: new RunDetailLoader(events) }
}

afterEach(() => {
  vi.resetAllMocks()
})

describe('RunDetailLoader', () => {
  it('fetches each id once, however often it is wanted', async () => {
    vi.mocked(fetchRun).mockImplementation(async (id) => detail(id))
    const { loader, events } = setup()

    loader.want(['a', 'b'])
    loader.want(['a', 'b', 'c'])
    await settle()

    expect(vi.mocked(fetchRun).mock.calls.map((c) => c[0])).toEqual(['a', 'b', 'c'])
    expect(events.loaded).toHaveBeenCalledTimes(3)
  })

  it('never has more than the cap in flight, and drains the rest as they finish', async () => {
    const resolvers: Array<() => void> = []
    vi.mocked(fetchRun).mockImplementation(
      (id) => new Promise((resolve) => resolvers.push(() => resolve(detail(id)))),
    )
    const { loader, events } = setup()
    const ids = Array.from({ length: MAX_CONCURRENT_RUN_FETCHES + 2 }, (_, i) => `r${i}`)

    loader.want(ids)
    expect(fetchRun).toHaveBeenCalledTimes(MAX_CONCURRENT_RUN_FETCHES)

    resolvers[0]()
    await settle()
    expect(fetchRun).toHaveBeenCalledTimes(MAX_CONCURRENT_RUN_FETCHES + 1)

    for (const resolve of resolvers) resolve()
    await settle()
    for (const resolve of resolvers) resolve()
    await settle()
    expect(events.loaded).toHaveBeenCalledTimes(ids.length)
  })

  it('reports only a 404 as gone; any other failure is failed, and retry asks again', async () => {
    vi.mocked(fetchRun).mockImplementation(async (id) => {
      if (id === 'deleted') throw new ApiError('GET: run not found', 404, 'run not found')
      throw new Error('connection dropped')
    })
    const { loader, events } = setup()

    loader.want(['deleted', 'flaky'])
    await settle()
    expect(events.gone).toHaveBeenCalledWith('deleted')
    expect(events.failed).toHaveBeenCalledWith('flaky')

    vi.mocked(fetchRun).mockImplementation(async (id) => detail(id))
    loader.retry(['flaky'])
    await settle()
    expect(events.loaded).toHaveBeenCalledWith('flaky', detail('flaky'))
    expect(fetchRun).toHaveBeenCalledTimes(3)
  })

  it('drops results after dispose, and takes them again after attach', async () => {
    vi.mocked(fetchRun).mockImplementation(async (id) => detail(id))
    const { loader, events } = setup()

    loader.want(['a'])
    loader.dispose()
    await settle()
    expect(events.loaded).not.toHaveBeenCalled()

    loader.attach()
    loader.want(['b'])
    await settle()
    expect(events.loaded).toHaveBeenCalledWith('b', detail('b'))
  })
})
