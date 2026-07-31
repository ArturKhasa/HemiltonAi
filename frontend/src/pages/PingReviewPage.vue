<template>
  <div class="flex flex-col h-screen bg-gray-100">
    <!-- Navigation bar -->
    <div class="bg-white border-b px-4 py-3 flex-shrink-0">
      <div class="flex items-center gap-4 max-w-3xl mx-auto">
        <button
          @click="prev"
          :disabled="currentIndex === 0 || loading"
          class="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium disabled:opacity-40 hover:bg-brand-700 transition-colors whitespace-nowrap"
        >← Предыдущий</button>
        <div class="flex-1 flex flex-col items-center gap-1.5">
          <span class="text-sm text-gray-700 font-medium">
            <template v-if="loadingAll">Загрузка...</template>
            <template v-else-if="dialogs.length === 0">Нет диалогов</template>
            <template v-else>Клиент {{ currentIndex + 1 }} из {{ dialogs.length }}</template>
          </span>
          <div class="w-full bg-gray-200 rounded-full h-1.5">
            <div
              class="bg-green-500 h-1.5 rounded-full transition-all duration-300"
              :style="{ width: progressPercent + '%' }"
            ></div>
          </div>
        </div>
        <button
          @click="next"
          :disabled="currentIndex >= dialogs.length - 1 || loading"
          class="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium disabled:opacity-40 hover:bg-brand-700 transition-colors whitespace-nowrap"
        >Следующий →</button>
      </div>
    </div>

    <!-- Client info bar -->
    <div class="bg-white border-b px-6 py-2.5 flex items-center gap-3 flex-shrink-0">
      <template v-if="currentDialog">
        <p class="font-medium text-gray-800 text-sm">VK ID: {{ currentDialog.vk_user_id ?? '—' }}</p>
        <p v-if="currentDialog.client_name && String(currentDialog.client_name) !== String(currentDialog.vk_user_id)" class="text-xs text-gray-500">{{ currentDialog.client_name }}</p>
        <div class="flex items-center gap-2 ml-2">
          <span class="text-xs text-gray-500">Статус:</span>
          <select
            :value="currentDialog?.current_status || ''"
            @change="changeStatus($event.target.value)"
            :disabled="statusChanging"
            class="text-xs border rounded-lg px-2 py-1 bg-white focus:outline-none focus:ring-2 focus:ring-brand-500 disabled:opacity-50"
          >
            <option value="" disabled>— не задан —</option>
            <option v-for="s in activeStatuses" :key="s.id" :value="s.name">{{ s.name }}</option>
          </select>
          <span v-if="statusChanging" class="text-xs text-gray-400">...</span>
        </div>
        <div class="ml-auto flex items-center gap-2">
          <div v-if="currentDialog.marketing_tags?.length" class="flex flex-wrap items-center gap-1">
            <span
              v-for="tag in currentDialog.marketing_tags"
              :key="tag"
              class="text-xs px-2 py-0.5 rounded-full bg-brand-50 text-brand-700 border border-brand-200"
            >{{ tag }}</span>
          </div>
          <span class="text-xs text-gray-400">Dialog #{{ currentDialog.id }}</span>
        </div>
      </template>
      <span v-else-if="!loadingAll" class="text-sm text-gray-400">—</span>
    </div>

    <!-- Ping state -->
    <div v-if="pingState" class="bg-amber-50 border-b border-amber-200 px-6 py-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs flex-shrink-0">
      <span class="font-medium text-amber-700">🔔 Пинг</span>
      <span class="text-gray-600">Воронка: <span class="font-medium text-gray-800">{{ pingState.funnel_type }}</span></span>
      <span class="text-gray-600">Шаг: <span class="font-medium text-gray-800">{{ pingState.current_step }}</span></span>
      <span :class="pingState.is_completed ? 'text-green-700' : 'text-amber-700'">
        {{ pingState.is_completed ? '✓ Завершена' : '● Активна' }}
      </span>
      <span v-if="pingState.marketing_tag" class="text-gray-600">Тег: <span class="font-medium text-gray-800">{{ pingState.marketing_tag }}</span></span>
      <span class="text-gray-600">Следующий: <span class="font-medium text-gray-800">{{ formatFullDateTime(pingState.next_ping_due_at) }}</span></span>
    </div>

    <!-- Messages -->
    <div ref="messagesEl" class="flex-1 overflow-y-auto p-6 space-y-4">
      <div v-if="loadingAll || loading" class="flex items-center justify-center h-full">
        <p class="text-gray-400 text-sm">Загрузка...</p>
      </div>
      <div v-else-if="dialogs.length === 0" class="flex items-center justify-center h-full">
        <p class="text-gray-400 text-sm">Нет диалогов по текущим фильтрам</p>
      </div>
      <template v-else v-for="msg in messages" :key="msg.id">
        <div :class="['flex flex-col', msg.role === 'client' ? 'items-end' : 'items-start']">
          <div class="mb-0.5 px-1">
            <span v-if="msg.role === 'curator'" class="text-xs text-purple-500 font-medium">👤 Оператор (ВК)</span>
            <span v-else-if="msg.role === 'ai' && msg.is_ping" class="text-xs text-amber-500 font-medium">🔔 Пинг</span>
            <span v-else-if="msg.role === 'ai'" class="text-xs text-emerald-500 font-medium">🤖 AI</span>
          </div>
          <div :class="[
            'max-w-xl px-4 py-2.5 rounded-2xl text-sm shadow-sm',
            msg.role === 'client'
              ? 'bg-brand-600 text-white rounded-br-sm'
              : msg.role === 'curator'
                ? 'bg-purple-50 border border-purple-200 rounded-bl-sm text-gray-800'
                : msg.is_ping
                  ? 'bg-amber-50 border border-amber-200 rounded-bl-sm text-gray-800'
                  : 'bg-white border rounded-bl-sm text-gray-800',
            msg.need_curator ? 'border-orange-400 border-2' : '',
          ]">
            <p class="leading-relaxed whitespace-pre-wrap">{{ msg.text }}</p>
            <div v-if="msg.files && msg.files.length" class="mt-2 flex flex-col gap-2">
              <template v-for="(url, i) in msg.files" :key="i">
                <audio v-if="isAudioUrl(url)" :src="url" controls class="w-72 rounded-lg" />
                <img v-else :src="url" class="rounded-lg max-w-full max-h-64 object-contain" loading="lazy" />
              </template>
            </div>
            <div v-if="msg.audio_urls && msg.audio_urls.length" class="mt-2 flex flex-col gap-2">
              <audio v-for="(url, i) in msg.audio_urls" :key="i" :src="url" controls class="w-full max-w-xs rounded-lg" />
            </div>
            <div class="mt-1 flex items-center justify-between gap-2">
              <div v-if="msg.role !== 'client'" class="flex gap-2 text-xs text-gray-400">
                <span v-if="msg.confidence_score !== null && msg.confidence_score !== undefined">
                  {{ (msg.confidence_score * 100).toFixed(0) }}% уверенность
                </span>
                <span v-if="msg.need_curator" class="text-orange-500 font-medium">⚠ На проверку куратору</span>
              </div>
              <div v-else></div>
              <span v-if="msg.created_at" :class="['text-xs ml-auto', msg.role === 'client' ? 'text-brand-200' : 'text-gray-400']">
                {{ formatMsgTime(msg.created_at) }}
              </span>
            </div>
          </div>
          <!-- Feedback button for AI messages -->
          <div v-if="msg.role === 'ai'" class="mt-1 px-1 flex gap-2">
            <button
              @click="openFeedback(msg)"
              :class="[
                'text-xs px-2 py-0.5 rounded-lg border transition-colors',
                msg.feedback_id
                  ? 'border-amber-300 text-amber-600 bg-amber-50 hover:bg-amber-100'
                  : 'border-gray-200 text-gray-400 hover:text-gray-600 hover:bg-gray-50'
              ]"
            >{{ msg.feedback_id ? 'Отредактировать ошибку' : 'Указать ошибку' }}</button>
            <button
              v-if="msg.has_context"
              @click="openContext(msg)"
              class="text-xs px-2 py-0.5 rounded-lg border border-gray-200 text-gray-400 hover:text-gray-600 hover:bg-gray-50 transition-colors"
            >Размышления ИИ</button>
          </div>
        </div>
      </template>
    </div>

    <!-- Feedback modal -->
    <div v-if="feedbackModal.show" class="fixed inset-0 bg-black/40 flex items-center justify-center z-50" @click.self="feedbackModal.show = false">
      <div class="bg-white rounded-2xl shadow-xl p-6 w-full max-w-md">
        <h2 class="text-lg font-semibold mb-1">Правило для ИИ</h2>
        <p class="text-xs text-gray-400 mb-4">Опишите ошибку или что нужно исправить. Это правило будет применяться ко всем следующим ответам.</p>
        <textarea
          v-model="feedbackModal.text"
          rows="4"
          autofocus
          placeholder="Например: Не называть цену без выявления потребности клиента"
          class="w-full border rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 resize-none"
        />
        <p v-if="feedbackModal.error" class="text-red-500 text-xs mt-1">{{ feedbackModal.error }}</p>
        <p v-if="feedbackModal.text.trim().length > 0 && feedbackModal.text.trim().length < 30" class="text-xs text-gray-400 mt-1">Минимум 30 символов ({{ feedbackModal.text.trim().length }}/30)</p>
        <div class="flex gap-2 mt-4">
          <button
            @click="saveFeedback"
            :disabled="feedbackModal.loading || feedbackModal.text.trim().length < 30"
            class="flex-1 bg-brand-600 text-white py-2 rounded-lg text-sm hover:bg-brand-700 disabled:opacity-50"
          >{{ feedbackModal.loading ? 'Сохраняем...' : 'Сохранить' }}</button>
          <button
            v-if="feedbackModal.feedbackId"
            @click="deleteFeedback"
            :disabled="feedbackModal.loading"
            class="px-4 py-2 border border-red-200 text-red-500 rounded-lg text-sm hover:bg-red-50 disabled:opacity-50"
          >Удалить</button>
          <button @click="feedbackModal.show = false" class="px-4 py-2 border rounded-lg text-sm hover:bg-gray-50">Отмена</button>
        </div>
      </div>
    </div>

    <!-- AI context modal -->
    <div v-if="contextModal.show" class="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" @click.self="contextModal.show = false">
      <div class="bg-white rounded-2xl shadow-xl w-full max-w-3xl max-h-[85vh] flex flex-col">
        <div class="flex items-center justify-between p-5 border-b">
          <div>
            <h2 class="text-lg font-semibold">Размышления ИИ</h2>
            <p v-if="contextModal.model" class="text-xs text-gray-400 mt-0.5">{{ contextModal.provider }} · {{ contextModal.model }}</p>
          </div>
          <button @click="contextModal.show = false" class="text-gray-400 hover:text-gray-600 text-xl leading-none">&times;</button>
        </div>
        <div class="p-5 overflow-y-auto space-y-3">
          <div v-if="contextModal.loading" class="text-sm text-gray-400">Загрузка...</div>
          <p v-else-if="contextModal.error" class="text-red-500 text-sm">{{ contextModal.error }}</p>
          <template v-else>
            <div v-if="contextModal.system">
              <div class="text-xs font-semibold text-purple-600 uppercase mb-1">System</div>
              <pre class="whitespace-pre-wrap break-words text-xs bg-purple-50 border border-purple-100 rounded-xl p-3 text-gray-700">{{ contextModal.system }}</pre>
            </div>
            <div v-for="(m, i) in contextModal.messages" :key="i">
              <div :class="['text-xs font-semibold uppercase mb-1', m.role === 'user' ? 'text-brand-600' : 'text-gray-500']">{{ m.role }}</div>
              <pre :class="['whitespace-pre-wrap break-words text-xs rounded-xl p-3 text-gray-700 border', m.role === 'user' ? 'bg-brand-50 border-brand-100' : 'bg-gray-50 border-gray-100']">{{ m.content }}</pre>
            </div>
            <div v-if="!contextModal.system && contextModal.messages.length === 0" class="text-sm text-gray-400">Контекст пуст</div>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, onUnmounted } from 'vue'
import api from '../api'

const FILTERS_KEY = 'dialog_filters'

const dialogs = ref([])
const currentIndex = ref(0)
const messages = ref([])
const pingState = ref(null)
const loadingAll = ref(true)
const loading = ref(false)
const messagesEl = ref(null)
const statuses = ref([])
const statusChanging = ref(false)
const activeStatuses = computed(() => statuses.value.filter(s => s.is_active))

function formatFullDateTime(d) {
  if (!d) return '—'
  const date = new Date(d)
  return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' }) +
    ', ' + date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

const feedbackModal = ref({ show: false, messageId: null, feedbackId: null, text: '', loading: false, error: '' })

function openFeedback(msg) {
  feedbackModal.value = {
    show: true,
    messageId: msg.id,
    feedbackId: msg.feedback_id || null,
    text: msg.feedback_text || '',
    loading: false,
    error: '',
  }
}

async function saveFeedback() {
  const fm = feedbackModal.value
  if (!fm.text.trim()) return
  fm.loading = true
  fm.error = ''
  try {
    if (fm.feedbackId) {
      await api.patch(`/feedback/${fm.feedbackId}`, { rule_text: fm.text.trim() })
    } else {
      const res = await api.post(`/feedback/messages/${fm.messageId}`, { rule_text: fm.text.trim() })
      const msg = messages.value.find(m => m.id === fm.messageId)
      if (msg) { msg.feedback_id = res.data.id; msg.feedback_text = res.data.rule_text }
    }
    const msg = messages.value.find(m => m.id === fm.messageId)
    if (msg) msg.feedback_text = fm.text.trim()
    fm.show = false
  } catch (e) {
    fm.error = e.response?.data?.detail || 'Ошибка'
  } finally {
    fm.loading = false
  }
}

async function deleteFeedback() {
  const fm = feedbackModal.value
  if (!fm.feedbackId) return
  fm.loading = true
  fm.error = ''
  try {
    await api.delete(`/feedback/${fm.feedbackId}`)
    const msg = messages.value.find(m => m.id === fm.messageId)
    if (msg) { msg.feedback_id = null; msg.feedback_text = null }
    fm.show = false
  } catch (e) {
    fm.error = e.response?.data?.detail || 'Ошибка'
  } finally {
    fm.loading = false
  }
}

const contextModal = ref({ show: false, loading: false, error: '', provider: '', model: '', system: '', messages: [] })

function normalizeContent(content) {
  if (typeof content === 'string') return content
  if (Array.isArray(content)) {
    return content.map(b => {
      if (typeof b === 'string') return b
      if (b && typeof b === 'object') {
        if (typeof b.text === 'string') return b.text
        if (b.type) return `[${b.type}]\n${JSON.stringify(b, null, 2)}`
      }
      return JSON.stringify(b, null, 2)
    }).join('\n\n')
  }
  if (content == null) return ''
  return JSON.stringify(content, null, 2)
}

async function openContext(msg) {
  contextModal.value = { show: true, loading: true, error: '', provider: '', model: '', system: '', messages: [] }
  try {
    const res = await api.get(`/chat/run-context/${msg.id}`)
    const fc = res.data.full_context || {}
    contextModal.value.provider = res.data.provider || ''
    contextModal.value.model = res.data.model || ''
    contextModal.value.system = normalizeContent(fc.system)
    contextModal.value.messages = (fc.messages || []).map(m => {
      // Tool calls come back without a `role` (they carry `type` instead) — label
      // them explicitly so they don't render as empty "?" rows.
      if (m.type === 'function_call') {
        return { role: `🔧 ${m.name || 'tool'} (вызов)`, content: normalizeContent(m.arguments) }
      }
      if (m.type === 'function_call_output') {
        return { role: '🔧 результат', content: normalizeContent(m.output) }
      }
      return { role: m.role || '?', content: normalizeContent(m.content) }
    })
  } catch (e) {
    contextModal.value.error = e.response?.data?.detail || 'Ошибка загрузки'
  } finally {
    contextModal.value.loading = false
  }
}

const currentDialog = computed(() => dialogs.value[currentIndex.value] ?? null)

const progressPercent = computed(() => {
  if (dialogs.value.length === 0) return 0
  return ((currentIndex.value + 1) / dialogs.value.length) * 100
})

function loadFilters() {
  try {
    const raw = localStorage.getItem(FILTERS_KEY)
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

function getDateRange(preset, customFrom, customTo) {
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const endOfToday = new Date(startOfToday.getTime() + 86400000 - 1)

  switch (preset) {
    case 'today':
      return { from: startOfToday.toISOString(), to: endOfToday.toISOString() }
    case 'yesterday': {
      const s = new Date(startOfToday.getTime() - 86400000)
      const e = new Date(startOfToday.getTime() - 1)
      return { from: s.toISOString(), to: e.toISOString() }
    }
    case 'current_week': {
      const day = startOfToday.getDay() || 7
      const s = new Date(startOfToday.getTime() - (day - 1) * 86400000)
      return { from: s.toISOString(), to: endOfToday.toISOString() }
    }
    case 'last_7': {
      const s = new Date(startOfToday.getTime() - 6 * 86400000)
      return { from: s.toISOString(), to: endOfToday.toISOString() }
    }
    case 'last_30': {
      const s = new Date(startOfToday.getTime() - 29 * 86400000)
      return { from: s.toISOString(), to: endOfToday.toISOString() }
    }
    case 'current_month': {
      const s = new Date(now.getFullYear(), now.getMonth(), 1)
      return { from: s.toISOString(), to: endOfToday.toISOString() }
    }
    case 'last_month': {
      const s = new Date(now.getFullYear(), now.getMonth() - 1, 1)
      const e = new Date(now.getFullYear(), now.getMonth(), 1, 0, 0, 0, -1)
      return { from: s.toISOString(), to: e.toISOString() }
    }
    case 'custom': {
      const from = customFrom ? new Date(customFrom).toISOString() : null
      const to = customTo ? new Date(customTo + 'T23:59:59').toISOString() : null
      return { from, to }
    }
    default:
      return { from: null, to: null }
  }
}

function buildParams(filters, offset) {
  const params = new URLSearchParams()
  const showTest = filters?.filterShowTest ?? true
  const showReal = filters?.filterShowReal ?? false
  if (showTest && !showReal) params.append('is_test', 'true')
  else if (!showTest && showReal) params.append('is_test', 'false')
  for (const s of (filters?.filterStatuses ?? [])) params.append('status_filter', s)
  for (const p of (filters?.filterAiProviders ?? [])) params.append('ai_provider_filter', p)
  if (filters?.filterDialogTypeId != null) params.append('dialog_type_ids', filters.filterDialogTypeId)
  if (filters?.filterClientId?.trim()) params.append('vk_user_id', filters.filterClientId.trim())
  const { from, to } = getDateRange(filters?.filterDatePreset ?? 'all', filters?.filterDateFrom ?? '', filters?.filterDateTo ?? '')
  if (from) params.append('date_from', from)
  if (to) params.append('date_to', to)
  const { from: cf, to: ct } = getDateRange(filters?.filterClientDatePreset ?? 'all', filters?.filterClientDateFrom ?? '', filters?.filterClientDateTo ?? '')
  if (cf) params.append('client_date_from', cf)
  if (ct) params.append('client_date_to', ct)
  params.append('offset', offset)
  return params
}

async function loadAllDialogs() {
  loadingAll.value = true
  const filters = loadFilters()
  const all = []
  let offset = 0
  while (true) {
    const res = await api.get('/chat/dialogs', { params: buildParams(filters, offset) })
    all.push(...res.data)
    if (res.data.length < 50) break
    offset += res.data.length
  }
  dialogs.value = all
  loadingAll.value = false
  if (all.length > 0) await loadMessages(all[0].id)
}

async function loadMessages(dialogId) {
  loading.value = true
  pingState.value = null
  try {
    const res = await api.get(`/chat/${dialogId}/history`)
    messages.value = res.data
  } finally {
    loading.value = false
  }
  api.get(`/dialogs/${dialogId}`)
    .then(r => { if (currentDialog.value?.id === dialogId) pingState.value = r.data.ping_state })
    .catch(() => {})
  await nextTick()
  const el = messagesEl.value
  if (!el) return
  el.scrollTop = el.scrollHeight
  el.querySelectorAll('img, audio, video').forEach(media => {
    media.addEventListener('load', () => { el.scrollTop = el.scrollHeight }, { once: true })
  })
}

async function prev() {
  if (currentIndex.value === 0) return
  currentIndex.value--
  await loadMessages(dialogs.value[currentIndex.value].id)
}

async function next() {
  if (currentIndex.value >= dialogs.value.length - 1) return
  currentIndex.value++
  await loadMessages(dialogs.value[currentIndex.value].id)
}

async function loadStatuses() {
  try {
    const res = await api.get('/dialog_statuses/')
    statuses.value = res.data
  } catch {}
}

async function changeStatus(newStatusName) {
  if (!currentDialog.value || !newStatusName) return
  statusChanging.value = true
  try {
    await api.post(`/dialogs/${currentDialog.value.id}/status`, { new_status: newStatusName })
    const d = dialogs.value[currentIndex.value]
    if (d) d.current_status = newStatusName
  } catch (e) {
    alert('Ошибка: ' + (e.response?.data?.detail || e.message))
  } finally {
    statusChanging.value = false
  }
}

function onKeyDown(e) {
  if (e.key === 'ArrowLeft') prev()
  else if (e.key === 'ArrowRight') next()
}

function isAudioUrl(url) {
  const lower = (url || '').toLowerCase().split('?')[0]
  return ['.mp3', '.ogg', '.wav', '.m4a', '.aac', '.oga', '.opus', '.flac'].some(ext => lower.endsWith(ext))
}

function formatMsgTime(d) {
  if (!d) return ''
  const date = new Date(d)
  const now = new Date()
  const time = date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  if (date.toDateString() === now.toDateString()) return time
  return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' }) + ', ' + time
}

onMounted(async () => {
  window.addEventListener('keydown', onKeyDown)
  await Promise.all([loadStatuses(), loadAllDialogs()])
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeyDown)
})
</script>
