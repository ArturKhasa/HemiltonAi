// Вложения хранятся токенами «[photo-…]» прямо в тексте фразы. Править их
// руками среди трёхсотсимвольных ссылок невозможно — до самого текста было не
// добраться, — поэтому в интерфейсе текст и картинки разведены: здесь их
// разбирают на открытии формы и собирают обратно при сохранении.
export const ATTACHMENT_TOKEN_RE = /\[(?:photo|video|clip|audio_message|doc)-?[^\]\s]+\]/g

export function splitAttachments(text) {
  const tokens = (text || '').match(ATTACHMENT_TOKEN_RE) || []
  const body = (text || '')
    .replace(ATTACHMENT_TOKEN_RE, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
  return { body, tokens }
}

export function joinAttachments(draft) {
  const body = (draft?.body || '').trim()
  const tokens = draft?.tokens || []
  if (!tokens.length) return body
  return body ? `${body}\n\n${tokens.join('\n')}` : tokens.join('\n')
}
