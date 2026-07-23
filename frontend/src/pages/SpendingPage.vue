<template>
  <div class="min-h-screen bg-gray-100">
    <div class="bg-white border-b px-6 py-4 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <button @click="$router.push('/admin')" class="text-sm text-gray-400 hover:text-gray-600">← Назад</button>
        <h1 class="text-lg font-semibold text-gray-800">Расход по направлениям</h1>
        <span class="text-xs text-gray-400">данные с 14.07.2026 — после исправления учёта</span>
      </div>
      <button @click="auth.logout(); $router.push('/login')" class="text-xs text-gray-400 hover:text-gray-600">Выйти</button>
    </div>

    <div class="max-w-7xl mx-auto p-6 space-y-6">
      <!-- Controls -->
      <div class="bg-white rounded-xl shadow-sm border p-4 flex flex-wrap gap-4">
        <label class="flex flex-col gap-1">
          <span class="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Период</span>
          <select v-model="preset" @change="load()" class="px-3 py-1.5 text-sm rounded-lg border bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option v-for="p in presets" :key="p.key" :value="p.key">{{ p.label }}</option>
          </select>
        </label>
        <label class="flex flex-col gap-1">
          <span class="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Дата по</span>
          <select v-model="dateBasis" @change="load()" class="px-3 py-1.5 text-sm rounded-lg border bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option v-for="b in dateBases" :key="b.key" :value="b.key" :title="b.hint">{{ b.label }}</option>
          </select>
        </label>
        <label class="flex flex-col gap-1">
          <span class="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Провайдер</span>
          <select v-model="provider" @change="load()" class="px-3 py-1.5 text-sm rounded-lg border bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option v-for="p in providers" :key="p.key" :value="p.key">{{ p.label }}</option>
          </select>
        </label>
        <label class="flex flex-col gap-1">
          <span class="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Сегмент</span>
          <select v-model="segment" @change="load()" class="px-3 py-1.5 text-sm rounded-lg border bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option v-for="s in segments" :key="s.key" :value="s.key" :title="s.hint">{{ s.label }}</option>
          </select>
        </label>
        <label class="flex flex-col gap-1">
          <span class="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Метрика</span>
          <select v-model="metric" class="px-3 py-1.5 text-sm rounded-lg border bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option v-for="m in metrics" :key="m.key" :value="m.key">{{ m.label }}</option>
          </select>
        </label>
      </div>

      <div v-if="loading" class="bg-white rounded-xl shadow-sm border p-10 text-center text-gray-400">Загрузка...</div>
      <div v-else-if="series.length === 0" class="bg-white rounded-xl shadow-sm border p-10 text-center text-gray-400">Нет данных за период</div>

      <template v-else>
        <!-- Summary cards -->
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div class="bg-white rounded-xl shadow-sm border p-4">
            <p class="text-xs text-gray-400 mb-1">Всего расход</p>
            <p class="text-xl font-semibold text-gray-800">${{ totalCost.toFixed(4) }}</p>
          </div>
          <div class="bg-white rounded-xl shadow-sm border p-4">
            <p class="text-xs text-gray-400 mb-1">Всего запусков</p>
            <p class="text-xl font-semibold text-gray-800">{{ totalRuns }}</p>
          </div>
          <div class="bg-white rounded-xl shadow-sm border p-4" :title="perDialogHint">
            <p class="text-xs text-gray-400 mb-1">{{ dialogsLabel }}</p>
            <p class="text-xl font-semibold text-gray-800">{{ totalDialogs }}</p>
          </div>
          <div class="bg-white rounded-xl shadow-sm border p-4" :title="perDialogHint">
            <p class="text-xs text-gray-400 mb-1">{{ perDialogLabel }}</p>
            <p class="text-xl font-semibold text-gray-800">${{ avgCostPerDialog.toFixed(4) }}</p>
          </div>
        </div>

        <!-- Combined chart -->
        <div class="bg-white rounded-xl shadow-sm border p-5">
          <h2 class="text-sm font-semibold text-gray-700 mb-4">{{ metricLabel }} по дням — все направления</h2>
          <LineChart :dates="dates" :series="chartSeries" :metric="metric" :height="280" />
          <div class="flex flex-wrap gap-4 mt-4">
            <div v-for="(s, i) in series" :key="String(s.type_id)" class="flex items-center gap-1.5 text-xs text-gray-600">
              <span class="w-3 h-3 rounded-sm" :style="{ background: color(i) }"></span>
              {{ s.display_name }}
            </div>
          </div>
        </div>

        <!-- Daily table -->
        <div class="bg-white rounded-xl shadow-sm border overflow-hidden">
          <div class="px-5 py-3 border-b">
            <h2 class="text-sm font-semibold text-gray-700">{{ metricLabel }} — разбивка по дням</h2>
          </div>
          <div class="overflow-x-auto">
            <table class="w-full text-sm">
              <thead>
                <tr class="bg-gray-50 text-left border-b">
                  <th class="px-4 py-2.5 text-xs text-gray-500 font-medium sticky left-0 bg-gray-50">Дата</th>
                  <th v-for="(s, i) in series" :key="String(s.type_id)" class="px-4 py-2.5 text-xs text-gray-500 font-medium text-right whitespace-nowrap">
                    <span class="inline-flex items-center gap-1.5">
                      <span class="w-2.5 h-2.5 rounded-sm" :style="{ background: color(i) }"></span>
                      {{ s.display_name }}
                    </span>
                  </th>
                  <th class="px-4 py-2.5 text-xs text-gray-500 font-medium text-right">Итого</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-gray-100">
                <tr v-for="row in tableRows" :key="row.date" class="hover:bg-gray-50">
                  <td class="px-4 py-2 text-gray-600 font-mono text-xs sticky left-0 bg-white">{{ row.date }}</td>
                  <td v-for="(c, i) in row.cells" :key="i" class="px-4 py-2 text-right tabular-nums" :class="c ? 'text-gray-800' : 'text-gray-300'">
                    {{ fmt(c) }}
                  </td>
                  <td class="px-4 py-2 text-right font-medium tabular-nums text-gray-900">{{ fmt(row.total) }}</td>
                </tr>
              </tbody>
              <tfoot>
                <tr class="border-t bg-gray-50 font-medium">
                  <td class="px-4 py-2.5 text-xs text-gray-500 sticky left-0 bg-gray-50">Всего за период</td>
                  <td v-for="(s, i) in series" :key="String(s.type_id)" class="px-4 py-2.5 text-right tabular-nums text-gray-800">
                    {{ metric === 'cost_per_dialog' ? '$' + s.avg_cost_per_dialog.toFixed(4) : (metric === 'cost_usd' ? '$' + s.total_cost_usd.toFixed(4) : s.total_runs) }}
                  </td>
                  <td class="px-4 py-2.5 text-right tabular-nums text-gray-900">
                    {{ metric === 'cost_per_dialog' ? '$' + avgCostPerDialog.toFixed(4) : (metric === 'cost_usd' ? '$' + totalCost.toFixed(4) : totalRuns) }}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        </div>

        <!-- Per-direction breakdown -->
        <div class="grid md:grid-cols-2 gap-4">
          <div v-for="(s, i) in series" :key="String(s.type_id)" class="bg-white rounded-xl shadow-sm border p-5">
            <div class="flex items-center justify-between mb-3">
              <div class="flex items-center gap-2">
                <span class="w-3 h-3 rounded-sm" :style="{ background: color(i) }"></span>
                <h3 class="text-sm font-semibold text-gray-700">{{ s.display_name }}</h3>
              </div>
              <span class="text-xs text-gray-400">
                ${{ s.avg_cost_per_dialog.toFixed(4) }}/диалог · {{ s.total_dialogs }} диал. · ${{ s.total_cost_usd.toFixed(4) }}
              </span>
            </div>
            <LineChart :dates="dates" :series="[{ ...s, _color: color(i) }]" :metric="metric" :height="120" />
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, h } from 'vue'
import { Line } from 'vue-chartjs'
import {
  Chart as ChartJS,
  LineController, LineElement, PointElement,
  LinearScale, CategoryScale, Tooltip, Filler, Legend,
} from 'chart.js'
import api from '../api'
import { useAuthStore } from '../stores/auth'

ChartJS.register(LineController, LineElement, PointElement, LinearScale, CategoryScale, Tooltip, Filler, Legend)

const auth = useAuthStore()

const presets = [
  { key: 'today', label: 'Сегодня' },
  { key: 'yesterday', label: 'Вчера' },
  { key: 'week', label: 'Эта неделя' },
  { key: 'month', label: 'Этот месяц' },
  { key: 'prev_month', label: 'Прошлый месяц' },
]
function isoDate(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
// Calendar-anchored range → { days, end } (end inclusive, ISO date).
function presetRange(key) {
  const now = new Date()
  if (key === 'yesterday') {
    const y = new Date(now); y.setDate(now.getDate() - 1)
    return { days: 1, end: isoDate(y) }
  }
  if (key === 'week') return { days: ((now.getDay() + 6) % 7) + 1, end: isoDate(now) }  // since Monday
  if (key === 'month') return { days: now.getDate(), end: isoDate(now) }                // since 1st
  if (key === 'prev_month') {
    const last = new Date(now.getFullYear(), now.getMonth(), 0)  // last day of prev month
    return { days: last.getDate(), end: isoDate(last) }
  }
  return { days: 1, end: isoDate(now) }  // today
}
// Семантика «диалога» зависит от базы даты: по дате запуска знаменатель —
// диалоги, активные в периоде (включая пинги по старым); по дате диалога —
// когорта созданных в периоде диалогов со всеми их ранами (юнит-экономика).
const metrics = computed(() => [
  { key: 'cost_per_dialog', label: perDialogLabel.value + ' $' },
  { key: 'cost_usd', label: 'Расход $' },
])
const dateBases = [
  { key: 'run', label: 'Дате запуска', hint: 'Траты по дню списания — сверяется с ЛК провайдеров. Диалоги = активные в периоде, включая пинги по старым.' },
  { key: 'dialog', label: 'Дате диалога', hint: 'Когорта диалогов, созданных в периоде, со всеми их ранами (в т.ч. будущими пингами) — стоимость нового диалога.' },
]
const providers = [
  { key: 'all', label: 'Все' },
  { key: 'openai', label: 'OpenAI' },
  { key: 'qwen', label: 'Qwen' },
]
// Segment = A/B-ветка диалога (dialogs.ai_provider). В отличие от фильтра
// «Провайдер», qwen-сегмент включает и свои openai-пинги — полная цена ветки.
const segments = [
  { key: 'all', label: 'Все', hint: 'Оба сегмента A/B-теста' },
  { key: 'openai', label: 'GPT+GPT — ответы и пинги на GPT', hint: 'Диалоги на OpenAI: ответы и пинги на GPT' },
  { key: 'qwen', label: 'Qwen+GPT — ответы Qwen, пинги GPT', hint: 'Диалоги на Qwen: ответы Qwen, пинги GPT' },
]
const preset = ref('today')
const metric = ref('cost_per_dialog')
const dateBasis = ref('run')
const provider = ref('all')
const segment = ref('all')
const loading = ref(false)
const dates = ref([])
const series = ref([])
const taxRate = ref(0)

const PALETTE = ['#2563eb', '#16a34a', '#db2777', '#ea580c', '#7c3aed', '#0891b2', '#ca8a04', '#dc2626', '#4f46e5', '#059669']
function color(i) { return PALETTE[i % PALETTE.length] }

const isCohort = computed(() => dateBasis.value === 'dialog')
const perDialogLabel = computed(() => isCohort.value ? 'Стоимость нового диалога' : 'Стоимость активного диалога')
const dialogsLabel = computed(() => isCohort.value ? 'Новых диалогов' : 'Активных диалогов')
const perDialogHint = computed(() => isCohort.value
  ? 'Все раны диалогов, созданных в периоде (включая поздние пинги), делённые на число этих диалогов'
  : 'Расход периода, делённый на диалоги с хотя бы одним раном в периоде — включая пинги по старым диалогам')
const metricLabel = computed(() => metrics.value.find(m => m.key === metric.value)?.label || '')
const totalCost = computed(() => series.value.reduce((a, s) => a + s.total_cost_usd, 0))
const totalRuns = computed(() => series.value.reduce((a, s) => a + s.total_runs, 0))
const totalDialogs = computed(() => series.value.reduce((a, s) => a + s.total_dialogs, 0))
const avgCostPerDialog = computed(() => totalDialogs.value ? totalCost.value / totalDialogs.value : 0)
const chartSeries = computed(() => series.value.map((s, i) => ({ ...s, _color: color(i) })))

const isMoney = computed(() => metric.value !== 'runs')
function fmt(v) {
  if (v == null) return '—'
  return isMoney.value ? '$' + Number(v).toFixed(4) : Math.round(v)
}

// Rows = days, columns = directions. Newest day first.
const tableRows = computed(() => {
  const rows = []
  for (let i = dates.value.length - 1; i >= 0; i--) {
    const cells = series.value.map(s => s[metric.value]?.[i] ?? 0)
    let total
    if (metric.value === 'cost_per_dialog') {
      const cost = series.value.reduce((a, s) => a + (s.cost_usd?.[i] || 0), 0)
      const dlg = series.value.reduce((a, s) => a + (s.dialogs?.[i] || 0), 0)
      total = dlg ? cost / dlg : 0
    } else {
      total = cells.reduce((a, v) => a + v, 0)
    }
    rows.push({ date: dates.value[i], cells, total })
  }
  return rows
})

async function load() {
  loading.value = true
  try {
    const range = presetRange(preset.value)
    const res = await api.get('/admin/spending-by-type', { params: { days: range.days, end: range.end, date_basis: dateBasis.value, provider: provider.value, segment: segment.value } })
    dates.value = res.data.dates
    series.value = res.data.series
    taxRate.value = res.data.tax_rate || 0
  } finally {
    loading.value = false
  }
}

onMounted(load)

// --- Chart.js line chart ---
function hexToRgba(hex, a) {
  const m = hex.replace('#', '')
  const r = parseInt(m.slice(0, 2), 16)
  const g = parseInt(m.slice(2, 4), 16)
  const b = parseInt(m.slice(4, 6), 16)
  return `rgba(${r}, ${g}, ${b}, ${a})`
}
function tickLabel(v, metric) {
  return metric === 'runs' ? Math.round(v) : '$' + Number(v).toFixed(Math.abs(v) < 1 ? 3 : 2)
}
function valueLabel(v, metric) {
  return metric === 'runs' ? Math.round(v) : '$' + Number(v).toFixed(4)
}

const LineChart = {
  props: {
    dates: { type: Array, required: true },
    series: { type: Array, required: true },
    metric: { type: String, required: true },
    height: { type: Number, default: 220 },
  },
  setup(props) {
    const chartData = computed(() => ({
      labels: props.dates.map(d => d.slice(5)),
      datasets: props.series.map(s => {
        const col = s._color || '#2563eb'
        return {
          label: s.display_name,
          data: s[props.metric] || [],
          borderColor: col,
          backgroundColor: hexToRgba(col, 0.12),
          fill: true,
          tension: 0.35,
          borderWidth: 2,
          pointRadius: props.dates.length <= 31 ? 2.5 : 0,
          pointHoverRadius: 5,
          pointBackgroundColor: col,
        }
      }),
    }))
    const options = computed(() => ({
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: { label: (c) => ` ${c.dataset.label}: ${valueLabel(c.parsed.y, props.metric)}` },
        },
      },
      scales: {
        y: {
          beginAtZero: true,
          border: { display: false },
          ticks: { callback: (v) => tickLabel(v, props.metric), font: { size: 10 }, color: '#94a3b8', maxTicksLimit: 6 },
          grid: { color: '#f1f5f9' },
        },
        x: {
          border: { display: false },
          ticks: { font: { size: 10 }, color: '#94a3b8', maxTicksLimit: 8, autoSkip: true, maxRotation: 0 },
          grid: { display: false },
        },
      },
    }))
    return () => h('div', { style: { position: 'relative', height: props.height + 'px' } }, [
      h(Line, { data: chartData.value, options: options.value }),
    ])
  },
}
</script>
