// The left-hand side of the analysis desk: the match, as it can be watched here.
//
//   fileViewer(video)      a video file the app plays itself: on this computer, or a direct link to a file
//   youtubeViewer(video)   YouTube's own player, inside the app
//   windowViewer(video)    a match playing in another window: any website, or a video app
//   noVideoViewer(...)     nothing to play here yet
//
// Every viewer returns the same kind of object, so the page treats them all alike:
//
//   element      what to show
//   analyse()    pause if it can, and resolve to the MOMENT captured (below), or to null
//   canResume    the app can start the video again ("Save and keep watching")
//   canJump      a saved moment's time can be jumped to
//   play(), togglePlay(), skip(seconds), jumpTo(seconds)   do nothing where the app cannot control the video
//   destroy()
//
// A MOMENT is what the draft (moment-draft.js) is filled with:
//   time           the video time in seconds, or null where the app cannot know it
//   timeFromVideo  true when `time` was read from the video, not typed
//   frame          the picture: { dataUrl, width, height, source }, or null
//   pictures       instead of `frame`, for a capture of the screen: the frames of the last seconds
//                  to choose from (screen-share.js), with `chosen`, the one picked first
//   paused         the video had already been paused when Analyse was pressed
//   note           when there is no picture: why, and what to do
//   videoId        the video it came from
//
// WHAT "ANALYSE" CAN DO, BY KIND OF VIDEO (see backend/services/video_service.py)
//   a video file on this computer   pause, read the time, copy the frame: all automatic and exact
//   a video file on the web         the same, except the frame when that website forbids copying it
//   YouTube                         pause and read the time through YouTube's own messages. The picture
//                                   with one-click pictures (sharing this window), or a pasted screenshot
//   any other link, or any app      the picture from its window (sharing that window). The time is typed

import { clear, h } from '../dom.js';
import { formatClock } from '../format.js';
import { FrameCaptureError, captureVideoFrame } from './frame-capture.js';
import { MatchWindow, OwnPlayerPictures, screenSharingSupported } from './screen-share.js';
import { youtubePlayer } from './youtube-player.js';

const onMac = () => /Mac/i.test(navigator.userAgent);

/** The big button every viewer has. The page decides what pressing it does. */
function analyseButton(onAnalyse) {
  return h('button', { type: 'button', class: 'button primary analyse', onclick: () => onAnalyse(),
    title: 'Pause here and analyse this moment (keyboard: A)' }, 'Analyse this moment');
}

/** Back and forward buttons, for seeing a run again while you draw it. */
function skipButtons(skip) {
  return [
    h('button', { type: 'button', class: 'button small', onclick: () => skip(-5), title: 'Back 5 seconds (keyboard: J)' }, '− 5 s'),
    h('button', { type: 'button', class: 'button small', onclick: () => skip(5), title: 'Forward 5 seconds (keyboard: L)' }, '+ 5 s'),
  ];
}

/** A line under the video for short messages. */
function notice() {
  const element = h('p', { class: 'small watch-notice', role: 'status' });
  element.hidden = true;
  return {
    element,
    say(text) {
      element.textContent = text || '';
      element.hidden = !text;
    },
  };
}

// ── A video file the app plays itself ───────────────────────────────────────
function describeVideoError(video) {
  const code = video.error ? video.error.code : 0;
  const reason = {
    1: 'Loading was interrupted.',
    2: 'The file could not be read (a network or disk problem).',
    3: 'The file is damaged or uses a format this browser cannot decode.',
    4: 'This browser cannot play this file\'s format, or the file is not there any more.',
  }[code] || 'The video could not be played.';
  return `${reason} A match saved as .mp4 with H.264 video plays in every browser. You can still analyse this match `
    + 'by typing the timestamp and adding a screenshot, or by playing it in another app and connecting that window.';
}

export function fileViewer(video, { seekTo = null, onAnalyse }) {
  const player = h('video', { controls: true, preload: 'metadata', playsInline: true, src: video.playback.source_url });
  const problem = h('div', { class: 'note error', role: 'alert' });
  problem.hidden = true;
  const said = notice();
  const clock = h('span', { class: 'watch-clock numeric' });
  const showTime = () => { clock.textContent = Number.isFinite(player.currentTime) ? `at ${formatClock(player.currentTime)}` : ''; };
  const skip = (seconds) => {
    const end = Number.isFinite(player.duration) ? player.duration : Infinity;
    player.currentTime = Math.min(end, Math.max(0, player.currentTime + seconds));
  };
  const bar = h('div', { class: 'watch-bar' }, analyseButton(onAnalyse), clock, h('span', { class: 'grow' }), skipButtons(skip));

  player.addEventListener('timeupdate', showTime);
  player.addEventListener('seeked', showTime);
  player.addEventListener('loadedmetadata', () => {
    if (seekTo !== null && Number.isFinite(seekTo)) player.currentTime = Math.min(seekTo, player.duration || seekTo);
    showTime();
  });
  player.addEventListener('error', () => {
    problem.textContent = describeVideoError(player);
    problem.hidden = false;
    bar.hidden = true;
  });

  return {
    element: h('div', { class: 'stack' }, h('div', { class: 'viewer' }, player), bar, said.element, problem),
    canResume: true,
    canJump: true,
    usable: () => !player.error,

    /** Pause, read the time once, and copy the frame. */
    async analyse() {
      if (player.error) return null;
      player.pause();
      const time = player.currentTime;  // read once; the form owns the timestamp from here on
      try {
        const shot = captureVideoFrame(player);
        return { time, timeFromVideo: true, frame: { ...shot, source: 'video_capture' }, videoId: video.id };
      } catch (error) {
        if (!(error instanceof FrameCaptureError) || error.reason !== 'blocked') {
          said.say(error.message);
          return null;
        }
        return { time, timeFromVideo: true, frame: null, note: error.message, videoId: video.id };
      }
    },
    play: () => player.play().catch(() => {}),
    togglePlay: () => (player.paused ? player.play().catch(() => {}) : player.pause()),
    skip,
    jumpTo: (seconds) => { player.currentTime = seconds; },
    destroy: () => {
      player.pause();
      player.removeAttribute('src');
      player.load();
    },
  };
}

// ── YouTube's player, inside the app ────────────────────────────────────────
/**
 * The app pauses the video and reads its time through YouTube's own messages. The
 * picture has to come from you: with "one-click pictures" on, the browser shares this
 * window and the app keeps the last seconds of the player's area; otherwise you paste
 * a screenshot.
 */
export function youtubeViewer(video, { seekTo = null, onAnalyse }) {
  const address = new URL(video.playback.source_url);
  address.searchParams.set('enablejsapi', '1');  // lets the player answer "pause" and report its time
  address.searchParams.set('origin', window.location.origin);
  address.searchParams.set('rel', '0');
  address.searchParams.set('playsinline', '1');
  if (seekTo !== null && Number.isFinite(seekTo)) address.searchParams.set('start', String(Math.floor(seekTo)));
  const frame = h('iframe', { src: address.href, title: video.label, allowFullscreen: true, referrerPolicy: 'strict-origin-when-cross-origin',
    allow: 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture' });
  const tube = youtubePlayer(frame);
  // The player's own buttons show while the mouse is over it, so a frame from before is preferred.
  let enteredAt = null;
  frame.addEventListener('mouseenter', () => { enteredAt = performance.now(); });

  // The two small marks beside the video's corners let a shared picture of the screen be cropped to the video.
  const marked = h('div', { class: 'capture-frame' }, h('div', { class: 'viewer' }, frame),
    h('span', { class: 'capture-mark top-left', 'aria-hidden': 'true' }),
    h('span', { class: 'capture-mark bottom-right', 'aria-hidden': 'true' }));
  const said = notice();
  const problem = h('div', { class: 'note error', role: 'alert' });
  problem.hidden = true;

  const clock = h('span', { class: 'watch-clock numeric' });
  tube.onChange(() => {
    clock.textContent = tube.time === null ? '' : `at ${formatClock(tube.time)}`;
    if (tube.problem && problem.hidden) {
      problem.textContent = `${tube.problem} You can still watch it on YouTube in another window: use "Watch it in another window" below.`;
      problem.hidden = false;
    }
  });

  let pictures = null;
  const oneClick = screenSharingSupported()
    ? h('button', { type: 'button', class: 'button', 'aria-pressed': 'false', onclick: () => toggleOneClick() }, 'Turn on one-click pictures')
    : null;
  const syncOneClick = () => {
    if (!oneClick) return;
    const on = Boolean(pictures && pictures.active);
    oneClick.textContent = on ? 'One-click pictures are on' : 'Turn on one-click pictures';
    oneClick.setAttribute('aria-pressed', String(on));
  };
  async function toggleOneClick() {
    if (pictures && pictures.active) {
      pictures.stop();
      said.say('');
      return;
    }
    oneClick.disabled = true;
    try {
      pictures = new OwnPlayerPictures(marked, { isPlaying: () => tube.playing, timeNow: () => tube.time, onStop: syncOneClick });
      await pictures.start();  // the browser asks what to share, then the video is looked for
      said.say('One-click pictures are on: Analyse takes the picture for you, from before the pause even when you paused '
        + 'with YouTube\'s own button. To switch it off, press the button again or stop sharing in the browser.');
    } catch (error) {
      if (pictures) pictures.stop();
      said.say(`${error.message} You can still paste a screenshot.`);
    } finally {
      oneClick.disabled = false;
      syncOneClick();
    }
  }

  /** What to do for the picture when the app cannot take it. */
  function pictureNote() {
    const keys = onMac()
      ? 'Take a screenshot: press Command + Control + Shift + 4, drag across the video, then press Command + V here.'
      : 'Take a screenshot of the video (on Windows: Windows key + Shift + S), then press Ctrl + V here.';
    return oneClick
      ? `${keys} Without YouTube's buttons on it, and without the keys: turn on one-click pictures under the video, and from then on Analyse takes the picture for you.`
      : keys;
  }

  const skip = (seconds) => { if (tube.time !== null) tube.seek(tube.time + seconds); };
  return {
    element: h('div', { class: 'stack' }, marked,
      h('div', { class: 'watch-bar' }, analyseButton(onAnalyse), clock, skipButtons(skip), h('span', { class: 'grow' }), oneClick),
      said.element, problem),
    canResume: true,
    canJump: true,
    usable: () => true,

    /** Take the picture first if one-click pictures are on, then pause and read the time. */
    async analyse() {
      const pausedAt = tube.playing ? null : tube.pausedAt;  // you paused it yourself, with YouTube's own button
      let offered = null;
      if (pictures && pictures.active) {
        // Taken BEFORE pausing: a paused YouTube player covers the picture with its title and buttons.
        try {
          offered = await pictures.moment({ pausedAt, enteredAt, time: tube.time });
        } catch (error) {
          said.say(error.message);
        }
      }
      const time = await tube.pause();  // read once; the form owns the timestamp from here on
      const known = time !== null;
      if (offered) {
        return { time, timeFromVideo: known, pictures: offered.pictures, chosen: offered.chosen, paused: pausedAt !== null, videoId: video.id };
      }
      return { time, timeFromVideo: known, frame: null, note: pictureNote(), videoId: video.id };
    },
    play: () => tube.play(),
    togglePlay: () => (tube.playing ? tube.pause() : tube.play()),
    skip,
    jumpTo: (seconds) => tube.seek(seconds),
    destroy: () => {
      if (pictures) pictures.stop();
      tube.destroy();
    },
  };
}

// ── A match playing in another window ───────────────────────────────────────
/**
 * Any website, or any app on this computer that plays video: the match is watched in its
 * own window, beside this one. With your permission the browser shares that window with
 * the app (screen-share.js), which finds the video in it, notices when you pause, and
 * keeps the last seconds, so Analyse takes the frame from just before the pause.
 * The app cannot read the time or pause that window: you pause it there, and type the
 * time if you want it.
 */
export function windowViewer(video, { onAnalyse }) {
  const link = video && video.location && /^https?:\/\//i.test(video.location) ? video.location : null;
  const said = notice();
  const panel = h('div', { class: 'match-window' });
  const status = h('span', { class: 'watch-status' });
  const bar = h('div', { class: 'watch-bar' }, analyseButton(onAnalyse), status);
  const tools = h('div', { class: 'row' });  // the less used buttons, under Analyse
  const preview = h('canvas', { class: 'window-preview', width: 640, height: 360, 'aria-label': 'What the app sees of the match window' });
  let marking = false;
  let refresh = null;

  const match = new MatchWindow({
    onChange: (what) => {
      if (what === 'stopped') {
        clearInterval(refresh);
        marking = false;
        said.say('Sharing stopped, so the app no longer sees the match window.');
      }
      if (what === 'moved') said.say('The video moved in the shared window, and the app followed it.');
      if (what === 'found') said.say('');
      render();
    },
  });

  function openMatch() {
    // A window of its own on the left of the screen, so this one can go beside it.
    const width = Math.round(screen.availWidth * 0.55);
    window.open(link, '_blank', `popup,noopener,left=${screen.availLeft || 0},top=${screen.availTop || 0},width=${width},height=${screen.availHeight}`);
  }

  async function connect() {
    try {
      await match.start();  // the browser asks which window (or screen) to share
      refresh = setInterval(() => { if (!marking) match.preview(preview); }, 1500);
      match.preview(preview);
    } catch (error) {
      said.say(`${error.message} The match window has to be shared for the app to take pictures of it.`);
    }
    render();
  }

  /** Show the whole shared picture, and let a rectangle be dragged across the video. */
  function startMarking() {
    marking = true;
    const still = match.whole();
    const view = h('canvas', { class: 'mark-view', width: still.width, height: still.height });
    view.getContext('2d').drawImage(still, 0, 0);
    const box = h('div', { class: 'mark-box' });
    box.hidden = true;
    const area = h('div', { class: 'mark-area', 'aria-label': 'Drag across the video to mark it' }, view, box);
    let from = null;
    const at = (event) => {
      const rect = view.getBoundingClientRect();
      return [Math.min(rect.width, Math.max(0, event.clientX - rect.left)), Math.min(rect.height, Math.max(0, event.clientY - rect.top))];
    };
    const shape = (to) => {
      const left = Math.min(from[0], to[0]);
      const top = Math.min(from[1], to[1]);
      return { left, top, width: Math.abs(to[0] - from[0]), height: Math.abs(to[1] - from[1]) };
    };
    area.addEventListener('pointerdown', (event) => {
      event.preventDefault();
      area.setPointerCapture(event.pointerId);
      from = at(event);
    });
    area.addEventListener('pointermove', (event) => {
      if (!from) return;
      const drawn = shape(at(event));
      Object.assign(box.style, { left: `${drawn.left}px`, top: `${drawn.top}px`, width: `${drawn.width}px`, height: `${drawn.height}px` });
      box.hidden = false;
    });
    area.addEventListener('pointerup', (event) => {
      if (!from) return;
      const drawn = shape(at(event));
      from = null;
      const rect = view.getBoundingClientRect();
      if (drawn.width < 30 || drawn.height < 20) {
        box.hidden = true;
        said.say('That was too small to be the video. Drag from one corner of the video to the opposite corner.');
        return;
      }
      const scale = still.width / rect.width;
      marking = false;
      match.setArea({
        x: Math.round(drawn.left * scale), y: Math.round(drawn.top * scale),
        width: Math.round(drawn.width * scale), height: Math.round(drawn.height * scale),
      });
      match.preview(preview);
      said.say('The video is marked. To let the app find it by itself again, press "Find the video automatically".');
    });
    clear(panel).append(
      h('p', { class: 'small' }, h('strong', {}, 'Drag across the video'), ' from one corner to the opposite corner.'),
      area,
      h('div', { class: 'row' }, h('button', { type: 'button', class: 'button small', onclick: () => { marking = false; render(); } }, 'Cancel')));
    clear(tools);
  }

  function render() {
    if (marking) return;
    clear(status);
    bar.hidden = !match.active;  // Analyse has nothing to take a picture of until the window is shared
    clear(tools);
    if (!match.active) {
      clear(panel).append(
        h('h3', {}, 'Watch the match in its own window'),
        h('ol', { class: 'window-steps' },
          h('li', {}, link
            ? ['Open the match: ', h('button', { type: 'button', class: 'button small', onclick: openMatch }, 'Open the match link'),
              ' It opens in a window of its own. Any other window works too: a different website, or a video app such as QuickTime Player.']
            : 'Open the match in any window: a website in another browser window, or a video app such as QuickTime Player.'),
          h('li', {}, 'Press ', h('strong', {}, 'Connect the match window'), ', and when the browser asks what to share, choose that window '
            + '(or the whole screen).'),
          h('li', {}, onMac()
            ? 'Put the two windows side by side: drag one to the left edge of the screen and the other to the right edge, or use the Window menu, Move & Resize.'
            : 'Put the two windows side by side.'),
          h('li', {}, 'Watch there. When something happens, pause it there, then press ', h('strong', {}, 'Analyse this moment'), ' here.')),
        h('p', { class: 'small muted' }, 'The app looks at that window only to find the video and keep its last few seconds in memory. '
          + 'A picture is kept only when you press Analyse and save. Nothing is recorded or sent anywhere.'),
        screenSharingSupported()
          ? h('button', { type: 'button', class: 'button primary', onclick: connect }, 'Connect the match window')
          : h('p', { class: 'note caution' }, 'This browser cannot share a window with a page. You can still type the timestamp and paste screenshots.'));
      return;
    }

    const state = match.state;
    if (state === 'found') {
      status.append(h('span', { class: match.paused ? 'chip-state paused' : 'chip-state playing' }, match.paused ? 'Paused' : 'Playing'));
    }
    clear(panel).append(
      h('div', { class: state === 'found' ? 'window-view found' : 'window-view' }, preview),
      state === 'found'
        ? h('p', { class: 'small muted' }, match.paused
          ? 'Paused. Analyse takes the frame from just before the pause, so the player\'s buttons are not on it.'
          : 'This is the part of the shared window the app takes pictures of.')
        : h('p', { class: 'small' }, state === 'looking'
          ? 'Looking for the video in the shared window. Keep the match playing; this takes a few seconds.'
          : 'No moving video found in what is shared yet. Check that the match is playing in the window you chose, or mark the video by hand.'));
    tools.append(...[
      h('button', { type: 'button', class: 'button small', onclick: startMarking }, 'Mark the video by hand'),
      state === 'found'
        ? h('button', { type: 'button', class: 'button small', onclick: () => match.findAgain() },
          match.manual ? 'Find the video automatically' : 'Find the video again')
        : null,
      h('button', { type: 'button', class: 'button small', onclick: () => match.stop() }, 'Stop sharing'),
    ].filter(Boolean));
  }

  render();
  return {
    element: h('div', { class: 'stack' }, panel, bar, said.element, tools),
    canResume: false,
    canJump: false,
    usable: () => true,

    async analyse() {
      if (!match.active) {
        said.say('Connect the match window first. Or paste a screenshot into the moment beside this.');
        return null;
      }
      if (!match.area) {
        said.say('The video has not been found in the shared window yet. Keep the match playing for a few seconds, or mark it by hand.');
        return null;
      }
      const offered = await match.moment();
      if (!offered) {
        said.say('No picture of the match has been kept yet. Let it play for a moment, then press Analyse again.');
        return null;
      }
      return {
        time: null, timeFromVideo: false, pictures: offered.pictures, chosen: offered.chosen, paused: match.paused,
        videoId: video ? video.id : null,
      };
    },
    play: () => {},
    togglePlay: () => {},
    skip: () => {},
    jumpTo: () => {},
    destroy: () => {
      clearInterval(refresh);
      match.stop();
    },
  };
}

// ── Nothing to play here ────────────────────────────────────────────────────
/** No video linked, or one that cannot be played here: say so, and point to what still works. */
export function noVideoViewer({ video = null, matchId, onUseWindow }) {
  return {
    element: h('div', { class: 'viewer fallback stack' },
      h('h3', {}, video ? 'This video cannot be played inside the app' : 'No video is linked to this match'),
      video ? h('p', { class: 'small' }, video.playback.explanation) : null,
      h('p', {}, 'Watch it anywhere: in another browser window or a video app, and connect that window. Analyse then takes '
        + 'pictures from it.'),
      h('div', { class: 'row' }, h('button', { type: 'button', class: 'button primary', onclick: onUseWindow }, 'Watch it in another window')),
      h('p', { class: 'muted small' }, 'Or type the timestamp and paste a screenshot of the moment beside this, and draw on it.'),
      video ? null : h('p', { class: 'small' }, h('a', { href: `match.html?id=${matchId}` }, 'Link a video to this match'))),
    canResume: false,
    canJump: false,
    usable: () => false,
    analyse: async () => null,
    play: () => {},
    togglePlay: () => {},
    skip: () => {},
    jumpTo: () => {},
    destroy: () => {},
  };
}
