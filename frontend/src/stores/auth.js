import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '../api'

export const useAuthStore = defineStore('auth', () => {
  // Safari в приватном окне бросает и на чтении, и на записи localStorage —
  // без обёртки панель там не открывается вовсе.
  function readToken() {
    try { return localStorage.getItem('token') || '' } catch { return '' }
  }
  function writeToken(value) {
    try {
      if (value) localStorage.setItem('token', value)
      else localStorage.removeItem('token')
    } catch {}
  }

  const token = ref(readToken())
  const user = ref(null)
  // Профиль запрошен и ответ получен (или окончательно не получен).
  const ready = ref(false)

  const isAuthenticated = computed(() => !!token.value)

  async function login(email, password) {
    const res = await api.post('/auth/login', { email, password })
    token.value = res.data.access_token
    writeToken(token.value)
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
    writeToken('')
  }

  if (token.value) fetchMe()
  else ready.value = true

  return { token, user, ready, isAuthenticated, login, register, fetchMe, logout }
})
