// jsdom has no ResizeObserver. chart.js's responsive-resize handling
// depends on one being present and crashes (reads a null canvas mid
// resize-check) without it, the moment a mounted chart's data updates -
// see any test that mounts LiveChart/CurveChart/RunChart and then causes
// a re-render with new points. A minimal stub is enough: no test here
// depends on it actually firing, only on chart.js not crashing when it
// looks for one.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver
}
