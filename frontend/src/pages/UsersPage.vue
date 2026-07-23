<template>
  <div class="min-h-screen bg-gray-100">
    <div class="bg-white border-b px-6 py-4 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <button @click="$router.push('/')" class="text-sm text-gray-400 hover:text-gray-600">← Назад</button>
        <h1 class="text-lg font-semibold text-gray-800">Пользователи</h1>
      </div>
      <button @click="auth.logout(); $router.push('/login')" class="text-xs text-gray-400 hover:text-gray-600">Выйти</button>
    </div>

    <div class="max-w-6xl mx-auto p-6">
      <div class="bg-white rounded-xl shadow-sm border overflow-hidden">
        <div class="px-4 py-3 flex justify-between items-center border-b bg-gray-50">
          <span class="text-sm text-gray-500">{{ users.length }} пользователей</span>
          <button @click="openCreate" class="bg-blue-600 text-white text-sm px-4 py-2 rounded-lg hover:bg-blue-700 font-medium">
            + Создать пользователя
          </button>
        </div>

        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="bg-gray-50 text-left border-b">
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-12">ID</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium">Email</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-36">Роль</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium">Доступ к направлениям</th>
                <th class="px-4 py-3 text-xs text-gray-500 font-medium w-32">Действия</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-100">
              <tr v-if="loading">
                <td colspan="5" class="px-4 py-10 text-center text-gray-400">Загрузка...</td>
              </tr>
              <tr v-else-if="users.length === 0">
                <td colspan="5" class="px-4 py-10 text-center text-gray-400">Нет пользователей</td>
              </tr>
              <tr v-else v-for="u in users" :key="u.id" class="hover:bg-gray-50 transition-colors">
                <td class="px-4 py-3 text-gray-400 font-mono text-xs">{{ u.id }}</td>
                <td class="px-4 py-3 text-gray-800">
                  {{ u.email }}
                  <span v-if="u.id === auth.user?.id" class="ml-1 text-xs text-blue-500">(вы)</span>
                </td>
                <td class="px-4 py-3">
                  <select
                    :value="u.role"
                    @change="changeRole(u, $event.target.value)"
                    :disabled="u.id === auth.user?.id || savingId === u.id"
                    class="border rounded-lg px-2 py-1 text-sm bg-white disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <option value="curator">curator</option>
                    <option value="admin">admin</option>
                  </select>
                </td>
                <td class="px-4 py-3">
                  <span v-if="u.role === 'admin'" class="text-xs text-gray-400">все направления (админ)</span>
                  <div v-else class="flex flex-wrap gap-1.5">
                    <button
                      v-for="t in dialogTypes" :key="t.id"
                      @click="toggleType(u, t.id)"
                      :disabled="savingId === u.id"
                      :class="[
                        'px-2.5 py-1 rounded-full text-xs font-medium transition-colors disabled:opacity-50',
                        u.dialog_type_ids.includes(t.id)
                          ? 'bg-green-100 text-green-700 hover:bg-green-200'
                          : 'bg-gray-100 text-gray-400 hover:bg-gray-200'
                      ]"
                    >{{ t.display_name }}</button>
                    <span v-if="u.dialog_type_ids.length === 0" class="text-xs text-red-400 self-center">нет доступа</span>
                  </div>
                </td>
                <td class="px-4 py-3">
                  <div class="flex gap-3">
                    <button @click="openPassword(u)" class="text-blue-500 hover:text-blue-700 text-xs font-medium">Пароль</button>
                    <button
                      v-if="u.id !== auth.user?.id"
                      @click="deleteTarget = u"
                      class="text-red-400 hover:text-red-600 text-xs font-medium"
                    >Удал.</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <p class="text-xs text-gray-400 mt-3">
        Куратор видит только диалоги привязанных направлений. Без привязок — не видит ни одного диалога.
      </p>
    </div>

    <!-- Create modal -->
    <div v-if="showCreate" class="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div class="bg-white rounded-xl shadow-xl w-full max-w-md">
        <div class="px-6 py-4 border-b flex items-center justify-between">
          <h2 class="font-semibold text-gray-800">Создать пользователя</h2>
          <button @click="showCreate = false" class="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
        </div>
        <div class="p-6 space-y-4">
          <div>
            <label class="block text-xs text-gray-500 mb-1.5">Email</label>
            <input v-model="createForm.email" type="email" class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="user@example.com" />
          </div>
          <div>
            <label class="block text-xs text-gray-500 mb-1.5">Пароль</label>
            <input v-model="createForm.password" type="text" class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="минимум 6 символов" />
          </div>
          <div>
            <label class="block text-xs text-gray-500 mb-1.5">Роль</label>
            <select v-model="createForm.role" class="w-full border rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="curator">curator</option>
              <option value="admin">admin</option>
            </select>
          </div>
          <div v-if="createForm.role === 'curator'">
            <label class="block text-xs text-gray-500 mb-1.5">Направления</label>
            <div class="flex flex-wrap gap-1.5">
              <button
                v-for="t in dialogTypes" :key="t.id"
                @click="toggleCreateType(t.id)"
                :class="[
                  'px-2.5 py-1 rounded-full text-xs font-medium transition-colors',
                  createForm.dialog_type_ids.includes(t.id)
                    ? 'bg-green-100 text-green-700 hover:bg-green-200'
                    : 'bg-gray-100 text-gray-400 hover:bg-gray-200'
                ]"
              >{{ t.display_name }}</button>
            </div>
          </div>
          <p v-if="createError" class="text-xs text-red-500">{{ createError }}</p>
        </div>
        <div class="px-6 py-4 border-t flex justify-end gap-2">
          <button @click="showCreate = false" class="px-4 py-2 text-sm text-gray-600 border rounded-lg hover:bg-gray-50">Отмена</button>
          <button
            @click="createUser"
            :disabled="saving || !createForm.email.trim() || !createForm.password.trim()"
            class="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 font-medium"
          >{{ saving ? 'Создание...' : 'Создать' }}</button>
        </div>
      </div>
    </div>

    <!-- Password modal -->
    <div v-if="passwordTarget" class="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div class="bg-white rounded-xl shadow-xl w-full max-w-sm p-6">
        <h2 class="font-semibold text-gray-800 mb-4">Новый пароль для {{ passwordTarget.email }}</h2>
        <input v-model="newPassword" type="text" class="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 mb-4" placeholder="Новый пароль" />
        <div class="flex justify-end gap-2">
          <button @click="passwordTarget = null; newPassword = ''" class="px-4 py-2 text-sm text-gray-600 border rounded-lg hover:bg-gray-50">Отмена</button>
          <button
            @click="savePassword"
            :disabled="saving || !newPassword.trim()"
            class="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 font-medium"
          >{{ saving ? '...' : 'Сохранить' }}</button>
        </div>
      </div>
    </div>

    <!-- Delete confirmation -->
    <div v-if="deleteTarget" class="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div class="bg-white rounded-xl shadow-xl w-full max-w-sm p-6">
        <h2 class="font-semibold text-gray-800 mb-2">Удалить пользователя?</h2>
        <p class="text-sm text-gray-500 mb-6">{{ deleteTarget.email }}</p>
        <div class="flex justify-end gap-2">
          <button @click="deleteTarget = null" class="px-4 py-2 text-sm text-gray-600 border rounded-lg hover:bg-gray-50">Отмена</button>
          <button
            @click="doDelete"
            :disabled="saving"
            class="px-4 py-2 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 font-medium"
          >{{ saving ? '...' : 'Удалить' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../api'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()

const loading = ref(false)
const saving = ref(false)
const savingId = ref(null)
const users = ref([])
const dialogTypes = ref([])

const showCreate = ref(false)
const createForm = ref({ email: '', password: '', role: 'curator', dialog_type_ids: [] })
const createError = ref('')
const passwordTarget = ref(null)
const newPassword = ref('')
const deleteTarget = ref(null)

async function load() {
  loading.value = true
  try {
    const [usersRes, typesRes] = await Promise.all([
      api.get('/admin/users'),
      api.get('/dialog-types/', { params: { active_only: false } }),
    ])
    users.value = usersRes.data
    dialogTypes.value = typesRes.data
  } finally {
    loading.value = false
  }
}

async function patchUser(u, payload) {
  savingId.value = u.id
  try {
    const res = await api.patch(`/admin/users/${u.id}`, payload)
    const idx = users.value.findIndex(x => x.id === u.id)
    if (idx !== -1) users.value[idx] = res.data
  } finally {
    savingId.value = null
  }
}

function toggleType(u, typeId) {
  const ids = u.dialog_type_ids.includes(typeId)
    ? u.dialog_type_ids.filter(id => id !== typeId)
    : [...u.dialog_type_ids, typeId]
  patchUser(u, { dialog_type_ids: ids })
}

function changeRole(u, role) {
  patchUser(u, { role })
}

function openCreate() {
  createForm.value = { email: '', password: '', role: 'curator', dialog_type_ids: [] }
  createError.value = ''
  showCreate.value = true
}

function toggleCreateType(typeId) {
  const ids = createForm.value.dialog_type_ids
  createForm.value.dialog_type_ids = ids.includes(typeId)
    ? ids.filter(id => id !== typeId)
    : [...ids, typeId]
}

async function createUser() {
  saving.value = true
  createError.value = ''
  try {
    const res = await api.post('/admin/users', createForm.value)
    users.value.push(res.data)
    showCreate.value = false
  } catch (e) {
    createError.value = e.response?.data?.detail || 'Ошибка создания'
  } finally {
    saving.value = false
  }
}

function openPassword(u) {
  passwordTarget.value = u
  newPassword.value = ''
}

async function savePassword() {
  saving.value = true
  try {
    await api.patch(`/admin/users/${passwordTarget.value.id}`, { password: newPassword.value })
    passwordTarget.value = null
    newPassword.value = ''
  } finally {
    saving.value = false
  }
}

async function doDelete() {
  saving.value = true
  try {
    await api.delete(`/admin/users/${deleteTarget.value.id}`)
    users.value = users.value.filter(u => u.id !== deleteTarget.value.id)
    deleteTarget.value = null
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>
