import { useSyncExternalStore } from 'react'

const key = 'service-desk.demo-operator'
const changeEvent = 'service-desk-operator-change'

export function getDemoOperator() {
  try { return localStorage.getItem(key) || 'G001' }
  catch { return 'G001' }
}

export function setDemoOperator(value: string) {
  localStorage.setItem(key, value)
  window.dispatchEvent(new Event(changeEvent))
}

function subscribe(listener: () => void) {
  const storage = (event: StorageEvent) => { if (event.key === key || event.key === null) listener() }
  window.addEventListener(changeEvent, listener)
  window.addEventListener('storage', storage)
  return () => {
    window.removeEventListener(changeEvent, listener)
    window.removeEventListener('storage', storage)
  }
}

export function useDemoOperator() {
  return useSyncExternalStore(subscribe, getDemoOperator, () => 'G001')
}
