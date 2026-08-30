import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from './stores/auth'

const routes = [
  { path: '/login', component: () => import('./pages/LoginPage.vue'), meta: { public: true } },
  { path: '/register', component: () => import('./pages/RegisterPage.vue'), meta: { public: true } },
  // Ссылки из Telegram-уведомлений ведут на /chat?dialog=... . Alias нужен,
  // чтобы catch-all redirect не потерял query до того, как его прочитает чат.
  { path: '/', alias: '/chat', component: () => import('./pages/ChatPage.vue') },
  { path: '/admin', component: () => import('./pages/AdminPage.vue'), meta: { roles: ['admin'] } },
  { path: '/admin/ping-rules', component: () => import('./pages/PingRulesPage.vue'), meta: { roles: ['admin'] } },
  { path: '/admin/spending', component: () => import('./pages/SpendingPage.vue'), meta: { roles: ['admin'] } },
  { path: '/admin/users', component: () => import('./pages/UsersPage.vue'), meta: { roles: ['admin'] } },
  { path: '/ping-review', component: () => import('./pages/PingReviewPage.vue'), meta: { roles: ['admin', 'curator'] } },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// Страницы грузятся отдельными файлами с хэшем в имени, и после деплоя старые
// файлы исчезают: сборка выкатывается целиком. Вкладка, открытая до деплоя,
// просит файл, которого больше нет, — импорт падает, и страница просто не
// открывается. Снаружи это выглядит как «панель не грузит»: вход есть, а
// «Группы», «Реф-метки» и «Картинки» не открываются ни в одном браузере.
//
// Лечится перезагрузкой — она заберёт свежий index.html с новыми именами.
// Делаем это сами и ровно один раз за вкладку, чтобы не зациклиться, если
// файла нет по другой причине.
const RELOADED_KEY = 'chunk_reload_done'

function reloadOnceForStaleChunk(error) {
  const message = String(error?.message || error)
  const stale = /dynamically imported module|Importing a module script failed|Failed to fetch/i.test(message)
  if (!stale) return false
  try {
    if (sessionStorage.getItem(RELOADED_KEY)) return false
    sessionStorage.setItem(RELOADED_KEY, '1')
  } catch {
    // Safari в приватном окне бросает на sessionStorage — перезагрузим и без метки.
  }
  window.location.reload()
  return true
}

router.onError(reloadOnceForStaleChunk)
// Vite сообщает о неудачной предзагрузке отдельно — до того, как до неё дойдёт
// роутер.
window.addEventListener('vite:preloadError', (event) => {
  if (reloadOnceForStaleChunk(event.payload)) event.preventDefault()
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.token) return '/login'
  if (to.meta.roles && auth.user && !to.meta.roles.includes(auth.user.role)) return '/'
  return true
})

export default router
