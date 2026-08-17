import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '../api'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('token') || '')
  const user = ref(null)
  // Профиль запрошен и ответ получен (или окончательно не получен).
  const ready = ref(false)

  const isAuthenticated = computed(() => !!token.value)

  async function login(email, password) {
    const res = await api.post('/auth/login', { email, password })
    token.value = res.data.access_token
    localStorage.setItem('token', token.value)
    await fetchMe()
  }

  async function register(email, password) {
    await api.post('/auth/register', { email, password })
    await login(email, password)
  }

  // Пока профиль не загружен, страница не знает роль и прячет то, что роли
  // положено. Один сбой сети на старте — и панель до перезагрузки думает, что
  // перед ней не админ: у менеджеров она так открывалась без реальных диалогов.
  async function fetchMe(retry = true) {
    if (!token.value) return
    try {
      const res = await api.get('/auth/me')
      user.value = res.data
    } catch (e) {
      if (retry && e.response?.status !== 401) {
        setTimeout(() => fetchMe(false), 2000)
      }
    } finally {
      ready.value = true
    }
  }

  function logout() {
    token.value = ''
    user.value = null
    ready.value = true
    localStorage.removeItem('token')
  }

  if (token.value) fetchMe()
  else ready.value = true

  return { token, user, ready, isAuthenticated, login, register, fetchMe, logout }
})
