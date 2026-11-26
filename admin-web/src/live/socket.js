import { useEffect, useRef } from 'react';

import { getToken, liveSocketUrl } from '../api/client.js';

/* The server's live channel, as the app hears it (v1.12.53; 26 Nov 2026:
 * "the web isn't fast when getting info"; answered "Live, within a
 * second"). Every incident change goes out on map:areas, and every alarm
 * escalation on agency:bfp; an Admin may listen to both. A message only
 * says "something changed": each screen reads again what it shows, so what
 * it shows is always the server's. If the connection drops it comes back
 * after a pause, and the screens' own checks every 12 seconds go on. */

const EVENT = 'replit:live';
const CHANNELS = ['map:areas', 'agency:bfp'];
const QUIET = new Set(['ping', 'pong', 'connected', 'subscribed', 'unsubscribed', 'error']);

/// Keeps one connection open while signed in; returns a stop function.
export function openLiveSocket() {
  let socket = null;
  let stopped = false;
  let wait = 2000;
  let retry = null;

  function connect() {
    const token = getToken();
    if (stopped || !token || typeof WebSocket === 'undefined') return;
    try {
      socket = new WebSocket(liveSocketUrl(token));
    } catch {
      schedule();
      return;
    }
    socket.onopen = () => {
      wait = 2000;
      CHANNELS.forEach((channel) => socket.send(JSON.stringify({ action: 'subscribe', channel })));
    };
    socket.onmessage = (frame) => {
      let message = null;
      try { message = JSON.parse(frame.data); } catch { return; }
      if (!message || QUIET.has(message.type)) return;
      window.dispatchEvent(new CustomEvent(EVENT, { detail: message }));
    };
    socket.onclose = () => { socket = null; schedule(); };
    socket.onerror = () => { try { socket?.close(); } catch { /* closing */ } };
  }

  function schedule() {
    if (stopped) return;
    clearTimeout(retry);
    retry = setTimeout(connect, wait);
    wait = Math.min(wait * 2, 30000);
  }

  connect();
  return () => {
    stopped = true;
    clearTimeout(retry);
    try { socket?.close(); } catch { /* already closed */ }
  };
}

/// Calls [onChange] (at most every 300 ms) when the server says something changed.
export function useLiveEvents(onChange) {
  const handler = useRef(onChange);
  handler.current = onChange;
  useEffect(() => {
    let timer = null;
    const heard = () => {
      clearTimeout(timer);
      timer = setTimeout(() => handler.current?.(), 300);
    };
    window.addEventListener(EVENT, heard);
    return () => { clearTimeout(timer); window.removeEventListener(EVENT, heard); };
  }, []);
}
