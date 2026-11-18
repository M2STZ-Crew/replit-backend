/* No emoji in any text box (v1.12.39, 18 Nov 2026: "make in any characters
 * typing in every typebox in the app and web cannot be typed by any emoji").
 *
 * One listener for the whole console: every <input> and <textarea>, whatever
 * page or dialog it is on. It runs in the capture phase, before React reads
 * the field, so React's state only ever sees the text without emoji. Emoji,
 * and what builds them (skin tones, the joiner, presentation selectors,
 * keycaps, flags' letters and tags), are dropped as they are typed or pasted;
 * everything else goes in as typed, and the cursor stays where it was among
 * what is left. The same ranges as the app (lib/widgets/no_emoji.dart) and the
 * residents' site (residents-web/assets/account.js). */

export function isEmojiCodePoint(c) {
  return (
    (c >= 0x1f000 && c <= 0x1faff) ||
    (c >= 0x2600 && c <= 0x27bf) ||
    (c >= 0x2194 && c <= 0x2199) || c === 0x21a9 || c === 0x21aa ||
    c === 0x231a || c === 0x231b || c === 0x2328 || c === 0x23cf ||
    (c >= 0x23e9 && c <= 0x23f3) || (c >= 0x23f8 && c <= 0x23fa) ||
    c === 0x24c2 || c === 0x25aa || c === 0x25ab || c === 0x25b6 || c === 0x25c0 ||
    (c >= 0x25fb && c <= 0x25fe) || c === 0x2934 || c === 0x2935 ||
    (c >= 0x2b05 && c <= 0x2b07) || c === 0x2b1b || c === 0x2b1c || c === 0x2b50 || c === 0x2b55 ||
    c === 0x203c || c === 0x2049 || c === 0x2139 ||
    c === 0x3030 || c === 0x303d || c === 0x3297 || c === 0x3299 ||
    c === 0x200d || c === 0xfe0e || c === 0xfe0f || c === 0x20e3 ||
    (c >= 0xe0020 && c <= 0xe007f)
  );
}

/* [text] without emoji, and where [offsets] (UTF-16) land in it. */
export function withoutEmoji(text, offsets = []) {
  let out = '';
  const landing = new Array(text.length + 1);
  let i = 0;
  for (const ch of text) {
    for (let k = 0; k < ch.length; k++) landing[i + k] = out.length;
    if (!isEmojiCodePoint(ch.codePointAt(0))) out += ch;
    i += ch.length;
  }
  landing[text.length] = out.length;
  return { text: out, offsets: offsets.map((o) => (o == null ? o : landing[Math.min(Math.max(o, 0), text.length)])) };
}

export function hasEmoji(text) {
  for (const ch of text) if (isEmojiCodePoint(ch.codePointAt(0))) return true;
  return false;
}

const TEXT_TYPES = new Set(['', 'text', 'search', 'email', 'url', 'tel', 'password']);

function clean(event) {
  const field = event.target;
  const isText = field instanceof HTMLTextAreaElement
    || (field instanceof HTMLInputElement && TEXT_TYPES.has(field.type));
  if (!isText || !hasEmoji(field.value)) return;
  let start = null;
  let end = null;
  try {
    start = field.selectionStart;
    end = field.selectionEnd;
  } catch {
    // An email field has no selection to read.
  }
  const { text, offsets } = withoutEmoji(field.value, [start, end]);
  const proto = field instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, 'value').set.call(field, text);
  if (offsets[0] != null) {
    try {
      field.setSelectionRange(offsets[0], offsets[1]);
    } catch {
      // As above.
    }
  }
}

let installed = false;

/* Once, at start-up (main.jsx). */
export function installNoEmoji(doc = document) {
  if (installed) return;
  installed = true;
  doc.addEventListener('input', clean, true);
}
