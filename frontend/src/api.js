import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

api.interceptors.request.use((config) => {
  let token = ''
  try { token = localStorage.getItem('token') } catch {}
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error.response?.status === 401) {
      try { localStorage.removeItem('token') } catch {}
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export default api
