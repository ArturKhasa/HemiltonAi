import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '../api'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('token') || '')
  const user = ref(null)

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

  async function fetchMe() {
    if (!token.value) return
    const res = await api.get('/auth/me')
    user.value = res.data
  }

  function logout() {
    token.value = ''
    user.value = null
    localStorage.removeItem('token')
  }

  if (token.value) fetchMe()

  return { token, user, isAuthenticated, login, register, fetchMe, logout }
})
