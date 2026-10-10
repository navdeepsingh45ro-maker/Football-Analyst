// Talking to YouTube's embedded player: reading its time, pausing, playing, seeking.
//
// HOW THIS IS ALLOWED
// YouTube's player runs in its own frame, and a page cannot reach inside it. What
// YouTube does offer is a small set of MESSAGES the page and the player may send
// each other (its "IFrame Player API"): "pause", "play", "seek to", and regular
// reports of the current time. This file speaks those messages directly, so no
// script from YouTube has to be loaded into this app's pages.
//
// WHAT IT CANNOT DO
// It cannot see the picture. Only the browser can share that, with your
// permission (see editor/screen-capture.js), or you can paste a screenshot.
//
// The player answers only when the frame's address carries enablejsapi=1 and
// this page's own address as `origin`; pages/video.js adds both.

const STATE_PLAYING = 1;
const STATE_PAUSED = 2;

/**
 * Connect to the YouTube player inside `iframe`.
 *
 *   const tube = youtubePlayer(frame);
 *   tube.onChange(() => show(tube.time));
 *   const seconds = await tube.pause();   // the exact position it stopped at, or null if it never answered
 */
export function youtubePlayer(iframe) {
  const origin = new URL(iframe.src).origin;
  const info = { currentTime: null, playerState: null, duration: null };
  const listeners = new Set();
  let connected = false;

  const send = (message) => {
    if (iframe.contentWindow) iframe.contentWindow.postMessage(JSON.stringify({ id: 1, channel: 'widget', ...message }), origin);
  };
  const command = (func, args = []) => send({ event: 'command', func, args });

  function onMessage(event) {
    // Only messages from this very frame, and only from YouTube's address, are believed.
    if (event.source !== iframe.contentWindow || event.origin !== origin) return;
    let data;
    try {
      data = typeof event.data === 'string' ? JSON.parse(event.data) : event.data;
    } catch {
      return;
    }
    if (!data || typeof data.info !== 'object' || data.info === null) return;
    connected = true;
    for (const key of Object.keys(info)) {
      if (typeof data.info[key] === 'number' && Number.isFinite(data.info[key])) info[key] = data.info[key];
    }
    listeners.forEach((listener) => listener());
  }
  window.addEventListener('message', onMessage);

  // The player starts reporting only after it has been told someone is listening,
  // and it may not be ready when the frame finishes loading. So: ask until it answers.
  const knocking = setInterval(() => {
    if (connected) clearInterval(knocking);
    else send({ event: 'listening' });
  }, 400);

  return {
    /** Has the player answered at all? False means the app cannot read its time. */
    get connected() { return connected; },
    /** The position in seconds as last reported (several times a second while playing), or null. */
    get time() { return info.currentTime; },
    get playing() { return info.playerState === STATE_PLAYING; },
    onChange(listener) { listeners.add(listener); },
    play() { command('playVideo'); },
    seek(seconds) { command('seekTo', [seconds, true]); },

    /** Pause, and resolve to the position it stopped at (null if the player never answered). */
    pause() {
      command('pauseVideo');
      if (!connected) return Promise.resolve(null);
      return new Promise((resolve) => {
        const finish = () => {
          clearTimeout(giveUp);
          listeners.delete(check);
          resolve(info.currentTime);
        };
        // The player confirms the pause with its exact position. If it was already
        // paused it may say nothing more, so do not wait for long.
        const check = () => { if (info.playerState === STATE_PAUSED) finish(); };
        const giveUp = setTimeout(finish, 800);
        listeners.add(check);
        check();
      });
    },

    destroy() {
      clearInterval(knocking);
      window.removeEventListener('message', onMessage);
    },
  };
}
