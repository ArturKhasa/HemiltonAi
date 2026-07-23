<template>
  <div class="min-h-screen bg-gray-100">
    <div class="bg-white border-b px-6 py-4 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <button @click="$router.push('/')" class="text-sm text-gray-400 hover:text-gray-600">← Назад</button>
        <h1 class="text-lg font-semibold text-gray-800">Пинг-правила</h1>
      </div>
      <button @click="auth.logout(); $router.push('/login')" class="text-xs text-gray-400 hover:text-gray-600">Выйти</button>
    </div>

    <div class="max-w-7xl mx-auto p-6">
      <div class="bg-white rounded-xl shadow-sm border overflow-hidden">
        <!-- Dialog type tabs -->
        <div class="border-b flex items-center overflow-x-auto">
          <button
            v-for="tab in typeTabs" :key="String(tab.id)"
            @click="activeTypeId = tab.id"
            :class="[
              'px-4 py-3 text-sm font-medium whitespace-nowrap border-b-2 transition-colors',
              activeTypeId === tab.id
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            ]"
          >{{ tab.label }}</button>
        </div>

        <!-- Funnel type tabs -->
        <div class="border-b flex items-center overflow-x-auto bg-gray-50 px-2">
          <button
            v-for="ft in funnelTabs" :key="ft"
            @click="activeFunnel = ft"
            :class="[
              'px-3 py-2 text-xs font-medium whitespace-nowrap rounded-md mx-1 my-1.5 transition-colors',
              activeFunnel === ft
                ? 'bg-white border border-gray-200 text-gray-800 shadow-sm'
                : 'text-gray-500 hover:text-gray-700 hover:bg-white'
            ]"
          >{{ ft ?? 'Все воронки' }}</button>
        </div>

        <!-- Toolbar -->
        <div class="px-4 py-3 flex justify-between items-center border-b">
          <div class="flex items-center gap-4">
            <span class="text-sm text-gray-500">{{ filteredRules.length }} правил</span>
            <div class="flex items-center gap-2">
              <label class="text-xs text-gray-400">Тег</label>
              <select
                v-model="activeTag"
                class="border rounded-lg px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
              >
                <option :value="null">Все</option>
                <option value="__none__">Без тега</option>
                <option v-for="tag in existingTags" :key="tag" :value="tag">{{ tag }}</option>
              </select>
            </div>
          </div>
          <button @click="openCreate" class="bg-blue-600 text-white text-sm px-4 py-2 rounded-lg hover:bg-blue-700 font-medium">
            + Добавить шаг
          </button>
        </div>

        <!-- Table -->
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="bg-gray-50 text-left border-b">
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-12">ID</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-16">Шаг</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-28">Задержка</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-32">Воронка</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-28">Тег</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium">Текст шага</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium">Текст</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-24">Активен</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-24">Действия</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-100">
              <tr v-if="loading">
                <td colspan="9" class="px-4 py-10 text-center text-gray-400">Загрузка...</td>
              </tr>
              <tr v-else-if="filteredRules.length === 0">
                <td colspan="9" class="px-4 py-10 text-center text-gray-400">Нет правил</td>
              </tr>
              <tr v-else v-for="r in filteredRules" :key="r.id" class="hover:bg-gray-50 transition-colors">
                <td class="px-4 py-3 text-gray-400 font-mono text-xs">{{ r.id }}</td>
                <td class="px-4 py-3 font-mono font-medium text-gray-700">{{ r.step }}</td>
                <td class="px-4 py-3 text-gray-600 text-xs">{{ formatDelay(r.delay_seconds) }}</td>
                <td class="px-4 py-3">
                  <span class="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 font-medium">{{ r.funnel_type }}</span>
                </td>
                <td class="px-4 py-3">
                  <span v-if="r.marketing_tag" class="text-xs px-2 py-0.5 rounded-full bg-purple-100 text-purple-700 font-medium">{{ r.marketing_tag }}</span>
                  <span v-else class="text-gray-300 text-xs">—</span>
                </td>
                <td class="px-4 py-3 text-gray-500 text-xs max-w-xs">
                  <p v-if="r.phrase_text" class="truncate" :title="r.phrase_text">{{ r.phrase_text }}</p>
                  <span v-else class="text-gray-300">—</span>
                </td>
                <td class="px-4 py-3 text-gray-700 max-w-xs">
                  <p v-if="r.manual_text" class="truncate text-xs" :title="r.manual_text">{{ r.manual_text }}</p>
                  <span v-else class="text-gray-300 text-xs">—</span>
                </td>
                <td class="px-4 py-3">
                  <button
                    @click="toggleActive(r)"
                    :class="[
                      'px-2.5 py-1 rounded-full text-xs font-medium transition-colors',
                      r.is_active
                        ? 'bg-green-100 text-green-700 hover:bg-green-200'
                        : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
                    ]"
                  >{{ r.is_active ? 'Да' : 'Нет' }}</button>
                </td>
                <td class="px-4 py-3">
                  <div class="flex gap-3">
                    <button @click="openEdit(r)" class="text-blue-500 hover:text-blue-700 text-xs font-medium">Ред.</button>
                    <button @click="confirmDelete(r)" class="text-red-400 hover:text-red-600 text-xs font-medium">Удал.</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Create/Edit Modal -->
    <div v-if="showModal" class="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div class="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div class="px-6 py-4 border-b flex items-center justify-between sticky top-0 bg-white">
          <h2 class="font-semibold text-gray-800">{{ editRule ? 'Редактировать шаг' : 'Добавить шаг' }}</h2>
          <button @click="showModal = false" class="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
        </div>
        <div class="p-6 space-y-4">
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-xs text-gray-500 mb-1.5">Тип диалога</label>
              <select v-model="form.type_id" class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white">
                <option :value="null">— не задан —</option>
                <option v-for="t in dialogTypes" :key="t.id" :value="t.id">{{ t.display_name }}</option>
              </select>
            </div>
            <div>
              <label class="block text-xs text-gray-500 mb-1.5">Воронка</label>
              <input
                v-model="form.funnel_type"
                list="funnel-list"
                class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="regular"
              />
              <datalist id="funnel-list">
                <option v-for="ft in existingFunnels" :key="ft" :value="ft" />
              </datalist>
            </div>
          </div>
          <div>
            <label class="block text-xs text-gray-500 mb-1.5">Маркетинговый тег <span class="text-gray-400">(необязательно)</span></label>
            <input
              v-model="form.marketing_tag"
              list="tag-list"
              :disabled="forAllTags"
              class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100 disabled:text-gray-400"
              :placeholder="forAllTags ? 'Все существующие теги' : '#ПРОФЕССИЯ'"
            />
            <datalist id="tag-list">
              <option v-for="tag in existingTags" :key="tag" :value="tag" />
            </datalist>
            <div v-if="!editRule && tagsForFormType.length" class="flex items-center gap-2 mt-2">
              <input type="checkbox" v-model="forAllTags" id="for_all_tags" class="rounded w-4 h-4 cursor-pointer" />
              <label for="for_all_tags" class="text-sm text-gray-700 cursor-pointer">
                Создать для всех существующих тегов <span class="text-gray-400">({{ tagsForFormType.length }})</span>
              </label>
            </div>
          </div>
          <div class="grid grid-cols-2 gap-4">
            <div>
              <label class="block text-xs text-gray-500 mb-1.5">Шаг</label>
              <input
                v-model.number="form.step"
                type="number"
                min="0"
                class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                :class="{ 'border-amber-400 focus:ring-amber-400': stepConflict }"
                placeholder="0"
              />
              <p v-if="stepConflict" class="text-xs text-amber-600 mt-1">
                Шаг {{ form.step }} занят — он и последующие шаги сдвинутся на +1<template v-if="forAllTags && conflictTags.length"> (теги: {{ conflictTags.join(', ') }})</template>
              </p>
            </div>
            <div>
              <label class="block text-xs text-gray-500 mb-1.5">Задержка (секунды)</label>
              <input
                v-model.number="form.delay_seconds"
                type="number"
                min="0"
                class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="1200"
              />
              <p v-if="form.delay_seconds" class="text-xs text-gray-400 mt-1">{{ formatDelay(form.delay_seconds) }}</p>
            </div>
          </div>
          <div>
            <label class="block text-xs text-gray-500 mb-1.5">Текст шага</label>
            <textarea
              v-model="form.phrase_text"
              rows="4"
              class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
              placeholder="Текст сообщения шага..."
            ></textarea>
            <p class="text-xs text-gray-400 mt-1">Поддерживается spintax: {вариант1|вариант2} — выбирается случайный вариант.</p>
          </div>
          <div>
            <label class="block text-xs text-gray-500 mb-1.5">
              Текст вручную
              <span v-if="!form.phrase_text?.trim()" class="text-red-500 ml-1">* обязательно</span>
            </label>
            <textarea
              v-model="form.manual_text"
              rows="4"
              class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
              :class="{ 'border-red-400': textRequired && !form.manual_text?.trim() }"
              placeholder="Текст сообщения..."
            ></textarea>
            <p v-if="textRequired && !form.manual_text?.trim()" class="text-xs text-red-500 mt-1">
              Укажите текст — текст шага не задан
            </p>
          </div>
          <div v-if="editRule" class="flex items-center gap-2">
            <input type="checkbox" v-model="form.is_active" id="rule_is_active" class="rounded w-4 h-4 cursor-pointer" />
            <label for="rule_is_active" class="text-sm text-gray-700 cursor-pointer">Активен</label>
          </div>
        </div>
        <div class="px-6 py-4 border-t flex justify-end gap-2 sticky bottom-0 bg-white">
          <button @click="showModal = false" class="px-4 py-2 text-sm text-gray-600 border rounded-lg hover:bg-gray-50">Отмена</button>
          <button
            @click="saveRule"
            :disabled="saving || !canSave"
            class="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 font-medium"
          >
            {{ saving ? 'Сохранение...' : (editRule ? 'Сохранить' : 'Создать') }}
          </button>
        </div>
      </div>
    </div>

    <!-- Delete confirmation -->
    <div v-if="deleteTarget" class="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div class="bg-white rounded-xl shadow-xl w-full max-w-sm p-6">
        <h2 class="font-semibold text-gray-800 mb-2">Удалить шаг #{{ deleteTarget.step }} ({{ deleteTarget.funnel_type }})?</h2>
        <p class="text-sm text-gray-500 mb-6">ID: {{ deleteTarget.id }}</p>
        <div class="flex justify-end gap-2">
          <button @click="deleteTarget = null" class="px-4 py-2 text-sm text-gray-600 border rounded-lg hover:bg-gray-50">Отмена</button>
          <button
            @click="doDelete"
            :disabled="saving"
            class="px-4 py-2 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 font-medium"
          >
            {{ saving ? '...' : 'Удалить' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import api from '../api'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()

const loading = ref(false)
const saving = ref(false)
const dialogTypes = ref([])
const rules = ref([])
const activeTypeId = ref(null)
const activeFunnel = ref(null)
const activeTag = ref(null)

const showModal = ref(false)
const forAllTags = ref(false)
const editRule = ref(null)
const deleteTarget = ref(null)

const form = ref({
  type_id: null,
  funnel_type: '',
  step: 0,
  delay_seconds: 1200,
  phrase_text: '',
  manual_text: '',
  marketing_tag: null,
  is_active: true,
})

const typeTabs = computed(() => [
  { id: null, label: 'Все типы' },
  ...dialogTypes.value.map(t => ({ id: t.id, label: t.display_name })),
])

const rulesForType = computed(() =>
  activeTypeId.value === null
    ? rules.value
    : rules.value.filter(r => r.type_id === activeTypeId.value)
)

const funnelTabs = computed(() => {
  const funnels = [...new Set(rulesForType.value.map(r => r.funnel_type))].sort()
  return [null, ...funnels]
})

const filteredRules = computed(() => {
  let base = rulesForType.value
  if (activeFunnel.value !== null) base = base.filter(r => r.funnel_type === activeFunnel.value)
  if (activeTag.value === '__none__') base = base.filter(r => !r.marketing_tag)
  else if (activeTag.value !== null) base = base.filter(r => r.marketing_tag === activeTag.value)
  return [...base].sort((a, b) => a.step - b.step)
})

const existingFunnels = computed(() =>
  [...new Set(rules.value.map(r => r.funnel_type))].sort()
)

const existingTags = computed(() =>
  [...new Set(rules.value.map(r => r.marketing_tag).filter(Boolean))].sort()
)

const tagsForFormType = computed(() =>
  [...new Set(
    rules.value
      .filter(r => r.type_id === form.value.type_id)
      .map(r => r.marketing_tag)
      .filter(Boolean)
  )].sort()
)

const textRequired = computed(() => !form.value.phrase_text?.trim())

function hasConflict(tag) {
  return rules.value.some(r =>
    r.id !== editRule.value?.id &&
    r.type_id === form.value.type_id &&
    r.funnel_type === form.value.funnel_type &&
    r.step === form.value.step &&
    (r.marketing_tag ?? null) === tag
  )
}

const conflictTags = computed(() => {
  if (form.value.step === null || form.value.step === undefined || !form.value.funnel_type) return []
  if (forAllTags.value && !editRule.value) return tagsForFormType.value.filter(tag => hasConflict(tag))
  return hasConflict(form.value.marketing_tag || null) ? [form.value.marketing_tag || null] : []
})

const stepConflict = computed(() => conflictTags.value.length > 0)

watch(() => form.value.type_id, () => { forAllTags.value = false })

// Next free step in the group the form points to (funnel starts at 0 or 1 — keep its base).
function nextStepFor(typeId, funnel, tag) {
  const steps = rules.value
    .filter(r => r.type_id === typeId && r.funnel_type === funnel && (r.marketing_tag ?? null) === (tag || null))
    .map(r => r.step)
  return steps.length ? Math.max(...steps) + 1 : 0
}

// While creating, keep the step suggestion in sync with the chosen group.
watch(
  () => [form.value.type_id, form.value.funnel_type, form.value.marketing_tag],
  () => {
    if (!editRule.value && showModal.value) {
      form.value.step = nextStepFor(form.value.type_id, form.value.funnel_type, form.value.marketing_tag)
    }
  }
)

const canSave = computed(() => {
  if (!form.value.funnel_type.trim()) return false
  if (!form.value.phrase_text?.trim() && !form.value.manual_text?.trim()) return false
  return true
})

function formatDelay(seconds) {
  if (seconds < 60) return `${seconds} сек`
  if (seconds < 3600) return `${Math.round(seconds / 60)} мин`
  const h = seconds / 3600
  return h === Math.floor(h) ? `${h} ч` : `${(h).toFixed(1)} ч`
}

async function load() {
  loading.value = true
  try {
    const [typesRes, rulesRes] = await Promise.all([
      api.get('/dialog-types/'),
      api.get('/ping-rules/', { params: { include_inactive: true } }),
    ])
    dialogTypes.value = typesRes.data
    rules.value = rulesRes.data
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editRule.value = null
  forAllTags.value = false
  const funnel = activeFunnel.value ?? ''
  const tag = activeTag.value === '__none__' ? null : activeTag.value
  form.value = {
    type_id: activeTypeId.value,
    funnel_type: funnel,
    step: nextStepFor(activeTypeId.value, funnel, tag),
    delay_seconds: 1200,
    phrase_text: '',
    manual_text: '',
    marketing_tag: tag,
    is_active: true,
  }
  showModal.value = true
}

function openEdit(r) {
  editRule.value = r
  forAllTags.value = false
  form.value = {
    type_id: r.type_id,
    funnel_type: r.funnel_type,
    step: r.step,
    delay_seconds: r.delay_seconds,
    phrase_text: r.phrase_text ?? '',
    manual_text: r.manual_text ?? '',
    marketing_tag: r.marketing_tag ?? null,
    is_active: r.is_active,
  }
  showModal.value = true
}

async function saveRule() {
  saving.value = true
  try {
    const payload = {
      type_id: form.value.type_id,
      funnel_type: form.value.funnel_type,
      step: form.value.step,
      delay_seconds: form.value.delay_seconds,
      phrase_text: form.value.phrase_text,
      manual_text: form.value.manual_text || null,
      marketing_tag: form.value.marketing_tag || null,
      ...(editRule.value ? { is_active: form.value.is_active } : {}),
    }
    if (editRule.value) {
      await api.patch(`/ping-rules/${editRule.value.id}`, payload)
    } else if (forAllTags.value) {
      // Sequential, not Promise.all: the server re-sequences each tag group, and
      // concurrent inserts into the same table risk unique-constraint races.
      for (const tag of tagsForFormType.value) {
        await api.post('/ping-rules/', { ...payload, marketing_tag: tag })
      }
    } else {
      await api.post('/ping-rules/', payload)
    }
    // The server may have renumbered neighbouring steps — refetch the whole list.
    await load()
    showModal.value = false
  } finally {
    saving.value = false
  }
}

async function toggleActive(r) {
  const res = await api.patch(`/ping-rules/${r.id}`, { is_active: !r.is_active })
  const idx = rules.value.findIndex(x => x.id === r.id)
  if (idx !== -1) rules.value[idx] = res.data
}

function confirmDelete(r) {
  deleteTarget.value = r
}

async function doDelete() {
  saving.value = true
  try {
    await api.delete(`/ping-rules/${deleteTarget.value.id}`)
    deleteTarget.value = null
    // Remaining steps were renumbered server-side — refetch.
    await load()
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>
