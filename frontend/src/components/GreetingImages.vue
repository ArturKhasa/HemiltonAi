<!--
  Вложения приветствия и скриптов: превью, порядок, удаление.

  В базе они лежат токенами «[photo-<ссылка>]» внутри текста приветствия, и
  править их приходилось руками в textarea — среди трёхсотсимвольных ссылок с
  параметрами кадрирования. Здесь текст и картинки разведены: наверху обычный
  текст, тут список картинок, а токены собираются обратно при сохранении.

  Токены не только фото: у пингов бывают video и clip. Их тоже показываем и
  двигаем, только без превью — плашкой с типом.

  Видео добавляется двумя путями, и оба спрашивала ОП 03.09 («добавьте,
  пожалуйста, возможность добавлять видео в скрипты»): файлом с компьютера — он
  ложится на наш сервер и уходит клиенту вложением-документом, — и ссылкой на
  ролик ВК, которая становится [video-…] и уходит настоящим видео-вложением.
  Раньше файл отбивался словами «Это не картинка», а ссылка на ролик молча
  превращалась в [photo-…] и до клиента не доезжала.
-->
<template>
  <div>
    <div v-if="modelValue.length" class="flex flex-wrap gap-2 mb-2">
      <div
        v-for="(token, i) in modelValue"
        :key="token + i"
        class="relative group border rounded-lg overflow-hidden bg-gray-50 w-24"
      >
        <img
          v-if="previewUrl(token) && !broken[token]"
          :src="previewUrl(token)"
          @error="broken[token] = true"
          class="w-24 h-24 object-cover bg-white"
          :alt="`Картинка ${i + 1}`"
        />
        <div v-else class="w-24 h-24 flex flex-col items-center justify-center text-center px-1 gap-0.5">
          <span class="text-[10px] font-medium text-gray-500 uppercase">{{ kind(token) }}</span>
          <span class="text-[9px] text-gray-400 leading-tight break-all">{{ shortLabel(token) }}</span>
        </div>

        <!-- Порядок важен: ВК показывает вложения в том, в котором их прислали. -->
        <div class="flex items-center justify-between border-t bg-white px-1 py-0.5">
          <button
            @click="move(i, -1)"
            :disabled="i === 0"
            class="px-1 text-xs text-gray-400 hover:text-gray-700 disabled:opacity-30"
            title="Левее"
          >←</button>
          <span class="text-[10px] text-gray-400">{{ i + 1 }}</span>
          <button
            @click="move(i, 1)"
            :disabled="i === modelValue.length - 1"
            class="px-1 text-xs text-gray-400 hover:text-gray-700 disabled:opacity-30"
            title="Правее"
          >→</button>
        </div>

        <button
          @click="remove(i)"
          class="absolute top-1 right-1 w-5 h-5 rounded-full bg-black/50 text-white text-xs leading-none
                 opacity-0 group-hover:opacity-100 transition-opacity hover:bg-black/70"
          title="Убрать"
        >×</button>
      </div>
    </div>

    <!-- Файл с компьютера: раньше картинку сначала надо было куда-то выложить,
         чтобы получить ссылку. Сюда же кидается перетаскиванием. -->
    <div
      @dragover.prevent="dragging = true"
      @dragleave.prevent="dragging = false"
      @drop.prevent="onDrop"
      :class="[
        'border border-dashed rounded-lg px-3 py-2.5 text-center transition-colors',
        dragging ? 'border-brand-500 bg-brand-50' : 'border-gray-300 bg-gray-50',
      ]"
    >
      <button
        @click="picker?.click()"
        :disabled="uploading"
        class="text-xs px-3 py-1.5 rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-40"
      >{{ uploading ? `Загружаю… ${progress}%` : 'Загрузить с компьютера' }}</button>
      <span v-if="uploading && uploadingName" class="text-xs text-gray-400 block mt-1">{{ uploadingName }}</span>
      <span class="text-xs text-gray-400 block mt-1">или перетащите файлы сюда</span>
      <span class="text-xs text-gray-400 block">картинка, видео (mp4, mov), pdf или аудио</span>
      <input
        ref="picker"
        type="file"
        accept="image/*,video/mp4,video/quicktime,audio/*,application/pdf"
        multiple
        class="hidden"
        @change="onPick"
      />
    </div>

    <div class="flex gap-2 mt-2">
      <input
        v-model="draft"
        @keyup.enter="add"
        placeholder="…или ссылка на картинку либо ролик ВК"
        class="flex-1 min-w-0 border rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-brand-500"
      />
      <button
        @click="add"
        :disabled="!draft.trim()"
        class="px-3 py-1.5 text-xs border rounded-lg hover:bg-gray-50 disabled:opacity-40 whitespace-nowrap"
      >+ Добавить</button>
    </div>
    <p v-if="error" class="text-xs text-red-500 mt-1">{{ error }}</p>
    <p v-else class="text-xs text-gray-400 mt-1">
      Файл ложится на наш сервер. Ссылку можно взять и из ВК («открыть оригинал» →
      адрес картинки) — такое фото перезаливается в сообщество при первой отправке.
    </p>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import api from '../api'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue'])

const draft = ref('')
const error = ref('')
const picker = ref(null)
const uploading = ref(false)
const uploadingName = ref('')
const progress = ref(0)
const dragging = ref(false)
// Ссылка может уже не открываться (ВК протухает старые), тогда вместо битой
// картинки показываем плашку — но токен не выбрасываем, это решение админа.
const broken = reactive({})

const kind = (token) => (token.match(/^\[([a-z_]+)/) || [, 'файл'])[1]

function previewUrl(token) {
  const m = token.match(/^\[photo-(https?:\/\/[^\]]+)\]$/)
  return m ? m[1] : null
}

function shortLabel(token) {
  const inner = token.replace(/^\[[a-z_]+-?/, '').replace(/\]$/, '')
  if (!inner.startsWith('http')) return inner
  const file = inner.split('?')[0].split('/').pop()
  return file.length > 18 ? file.slice(0, 18) + '…' : file
}

// Ссылка на ролик ВК → [video-…]: такое вложение уходит клиенту настоящим
// видео. Картинка → [photo-…], остальные файлы (mp4 с нашего сервера, pdf,
// аудио) → [doc-…] — так же, как их размечает бэкенд (app.utils.media).
const VIDEO_HOSTS = /(?:vkvideo\.ru|vk\.com\/(?:video|clip)|vk\.ru\/(?:video|clip))/i
const IMAGE_EXT = /\.(?:jpe?g|png|gif|webp|heic)(?:$|\?)/i

function tokenForUrl(url) {
  if (VIDEO_HOSTS.test(url)) return `[video-${url}]`
  if (IMAGE_EXT.test(url)) return `[photo-${url}]`
  return `[doc-${url}]`
}

// «https://…» → токен по типу ссылки; «photo-44440184_457423551» и
// «44440184_457423551» → [photo-…]; готовый токен принимаем как есть.
function toToken(raw) {
  const v = raw.trim()
  if (/^\[[a-z_]+-?[^\]\s]+\]$/.test(v)) return v
  if (/^https?:\/\//.test(v)) return tokenForUrl(v)
  const m = v.match(/^(photo|video|clip)-?(-?\d+_\d+)$/)
  if (m) return `[${m[1]}-${m[2]}]`
  if (/^-?\d+_\d+$/.test(v)) return `[photo-${v}]`
  return null
}

function add() {
  const token = toToken(draft.value)
  if (!token) {
    error.value = 'Нужна ссылка на файл или id вида photo-44440184_457423551'
    return
  }
  if (props.modelValue.includes(token)) {
    error.value = 'Это вложение уже добавлено'
    return
  }
  error.value = ''
  emit('update:modelValue', [...props.modelValue, token])
  draft.value = ''
}

function remove(i) {
  emit('update:modelValue', props.modelValue.filter((_, idx) => idx !== i))
}

// Файлы грузим по одному и добавляем по мере готовности: на десяти картинках
// разом ждать «всё или ничего» неприятно, а упавшая одна не должна уносить
// остальные.
// Ждать ответа бесконечно нельзя: у axios таймаута нет, и зависший запрос
// оставлял кнопку в «Загружаю…» навсегда — админ не знал, идёт загрузка или
// всё уже упало (17.08, «прошло более 5 минут»).
const UPLOAD_TIMEOUT_MS = 90_000
// Тот же предел, что и на сервере (MEDIA_MAX_UPLOAD_MB): отказать сразу лучше,
// чем гнать десятки мегабайт и получить отказ в конце.
const MAX_UPLOAD_MB = 20

// Что примет сервер: тот же белый список расширений, что в app.storage.local.
const ALLOWED_EXT = /\.(?:jpe?g|png|gif|webp|heic|mp4|mov|pdf|ogg|mp3|m4a)$/i

async function upload(files) {
  const images = [...files].filter(f => ALLOWED_EXT.test(f.name))
  if (!images.length) {
    error.value = 'Не тот тип файла: картинка, видео (mp4, mov), pdf или аудио'
    return
  }
  const tooBig = images.find(f => f.size > MAX_UPLOAD_MB * 1024 * 1024)
  if (tooBig) {
    error.value = `${tooBig.name}: больше ${MAX_UPLOAD_MB} МБ — файл не пройдёт`
    return
  }
  error.value = ''
  uploading.value = true
  uploadingName.value = ''
  // Копим список у себя: prop приедет обратно только со следующей отрисовкой
  // родителя, и вторая картинка из пачки затёрла бы первую.
  let next = [...props.modelValue]
  try {
    for (const file of images) {
      const form = new FormData()
      form.append('file', file)
      uploadingName.value = file.name
      progress.value = 0
      try {
        const res = await api.post('/media/upload', form, {
          headers: { 'Content-Type': 'multipart/form-data' },
          timeout: UPLOAD_TIMEOUT_MS,
          onUploadProgress: (e) => {
            if (e.total) progress.value = Math.round((e.loaded / e.total) * 100)
          },
        })
        next = [...next, tokenForUrl(res.data.url)]
        emit('update:modelValue', next)
      } catch (e) {
        const reason = e.code === 'ECONNABORTED'
          ? 'сервер не ответил за полторы минуты — попробуйте ещё раз'
          : (e.response?.data?.detail || 'не загрузилось')
        error.value = `${file.name}: ${reason}`
      }
    }
  } finally {
    uploading.value = false
    uploadingName.value = ''
    progress.value = 0
    if (picker.value) picker.value.value = ''
  }
}

function onPick(event) {
  if (event.target.files?.length) upload(event.target.files)
}

function onDrop(event) {
  dragging.value = false
  if (event.dataTransfer?.files?.length) upload(event.dataTransfer.files)
}

function move(i, delta) {
  const next = [...props.modelValue]
  const j = i + delta
  if (j < 0 || j >= next.length) return
  ;[next[i], next[j]] = [next[j], next[i]]
  emit('update:modelValue', next)
}
</script>
