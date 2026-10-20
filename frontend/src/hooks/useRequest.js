import { useEffect, useRef, useState } from 'react'

/**
 * Run a promise-returning function once and expose its state.
 *
 * The request is created once and reused if the effect re-runs (React StrictMode
 * double-invokes effects in development), so no duplicate request is fired and
 * the result is never dropped by a stale cancellation flag.
 *
 * @param {() => Promise<any>} fn
 * @param {any[]} deps
 */
export function useRequest(fn, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const promiseRef = useRef(null)
  const fnRef = useRef(fn)
  fnRef.current = fn

  useEffect(() => {
    if (!promiseRef.current) {
      promiseRef.current = fnRef.current()
    }

    let active = true
    promiseRef.current
      .then((data) => {
        if (active) setState({ data, error: null, loading: false })
      })
      .catch((error) => {
        if (active) setState({ data: null, error, loading: false })
      })

    return () => {
      active = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return state
}
