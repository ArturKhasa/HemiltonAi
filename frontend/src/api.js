import axios from 'axios'

// Без таймаута зависший запрос крутит спиннер до закрытия вкладки: так «висело»
// добавление группы, хотя группа к тому моменту уже была создана, и так же
// молча стояла загрузка картинки. Сорок пять секунд — с запасом на любой наш
// обычный запрос; долгие загрузки файлов задают свой таймаут отдельно.
const api = axios.create({ baseURL: '/api', timeout: 45_000 })

api.interceptors.request.use((config) => {
  let token = ''
  try { token = localStorage.getItem('token') } catch {}
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error.code === 'ECONNABORTED' && !error.response) {
      // Ошибку показывает вызывающий код — ему нужен текст, а не «timeout of
      // 45000ms exceeded».
      error.response = { data: { detail: 'Сервер не ответил. Проверьте, применилось ли действие, и повторите.' } }
    }
    if (error.response?.status === 401) {
      try { localStorage.removeItem('token') } catch {}
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export default api
