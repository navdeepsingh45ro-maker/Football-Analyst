// Talking to YouTube's embedded player: reading its time, pausing, playing, seeking.
//
// HOW THIS IS ALLOWED
// YouTube's player runs in its own frame, and a page cannot reach inside it. What
// YouTube does offer is a small set of MESSAGES the page and the player may send
// each other (its "IFrame Player API"): "pause", "play", "seek to", and regular
// reports of the current time and state. This file speaks those messages directly,
// so no script from YouTube has to be loaded into this app's pages.
//
// WHAT IT CANNOT DO
// It cannot see the picture. Only the browser can share that, with your
// permission (see screen-share.js), or you can paste a screenshot.
//
// The player answers only when the frame's address carries enablejsapi=1 and
// this page's own address as `origin`; viewers.js adds both.

const STATE_ENDED = 0;
const STATE_PLAYING = 1;
const STATE_PAUSED = 2;

// What YouTube's error numbers mean, in words.
const ERRORS = {
  2: 'YouTube did not accept the address of this video.',
  5: 'YouTube\'s player could not play this video in this browser.',
  100: 'YouTube says this video does not exist or is private.',
  101: 'The owner of this video does not allow it to be played inside other websites.',
  150: 'The owner of this video does not allow it to be played inside other websites.',
};

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
  let stateSince = null;  // when the player last changed state (performance.now() time)
  let problem = null;     // what went wrong, in words, if YouTube reported an error

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
    if (!data) return;
    if (data.event === 'onError') {
      problem = ERRORS[data.info] || `YouTube's player reported a problem (error ${data.info}).`;
      listeners.forEach((listener) => listener());
      return;
    }
    if (typeof data.info !== 'object' || data.info === null) return;
    if (!connected) {
      connected = true;
      command('addEventListener', ['onError']);  // so that a video that cannot be shown here says why
    }
    const before = info.playerState;
    for (const key of Object.keys(info)) {
      if (typeof data.info[key] === 'number' && Number.isFinite(data.info[key])) info[key] = data.info[key];
    }
    if (info.playerState !== before) stateSince = performance.now();
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
    /** When it was paused or came to the end (performance.now() time); null while it plays or before it started. */
    get pausedAt() {
      return info.playerState === STATE_PAUSED || info.playerState === STATE_ENDED ? stateSince : null;
    },
    /** Why YouTube cannot show this video here, in words, or null. */
    get problem() { return problem; },
    onChange(listener) { listeners.add(listener); },
    play() { command('playVideo'); },
    seek(seconds) { command('seekTo', [Math.max(0, seconds), true]); },

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
      listeners.clear();
    },
  };
}
