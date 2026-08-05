<!--
  Картинки приветствия: превью, порядок, удаление.

  В базе они лежат токенами «[photo-<ссылка>]» внутри текста приветствия, и
  править их приходилось руками в textarea — среди трёхсотсимвольных ссылок с
  параметрами кадрирования. Здесь текст и картинки разведены: наверху обычный
  текст, тут список картинок, а токены собираются обратно при сохранении.

  Токены не только фото: у пингов бывают video и clip. Их тоже показываем и
  двигаем, только без превью — плашкой с типом.
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

    <div class="flex gap-2">
      <input
        v-model="draft"
        @keyup.enter="add"
        placeholder="Ссылка на картинку или photo-44440184_457423551"
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
      Ссылку берите из ВК («открыть оригинал» → адрес картинки). Фото перезаливается
      в наше сообщество при первой отправке.
    </p>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue'])

const draft = ref('')
const error = ref('')
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

// «https://…» → [photo-https://…]; «photo-44440184_457423551» и
// «44440184_457423551» → [photo-…]; готовый токен принимаем как есть.
function toToken(raw) {
  const v = raw.trim()
  if (/^\[[a-z_]+-?[^\]\s]+\]$/.test(v)) return v
  if (/^https?:\/\//.test(v)) return `[photo-${v}]`
  const m = v.match(/^(photo|video|clip)-?(-?\d+_\d+)$/)
  if (m) return `[${m[1]}-${m[2]}]`
  if (/^-?\d+_\d+$/.test(v)) return `[photo-${v}]`
  return null
}

function add() {
  const token = toToken(draft.value)
  if (!token) {
    error.value = 'Нужна ссылка на картинку или id вида photo-44440184_457423551'
    return
  }
  if (props.modelValue.includes(token)) {
    error.value = 'Эта картинка уже добавлена'
    return
  }
  error.value = ''
  emit('update:modelValue', [...props.modelValue, token])
  draft.value = ''
}

function remove(i) {
  emit('update:modelValue', props.modelValue.filter((_, idx) => idx !== i))
}

function move(i, delta) {
  const next = [...props.modelValue]
  const j = i + delta
  if (j < 0 || j >= next.length) return
  ;[next[i], next[j]] = [next[j], next[i]]
  emit('update:modelValue', next)
}
</script>
