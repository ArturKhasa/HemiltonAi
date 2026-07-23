import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from './stores/auth'

const routes = [
  { path: '/login', component: () => import('./pages/LoginPage.vue'), meta: { public: true } },
  { path: '/register', component: () => import('./pages/RegisterPage.vue'), meta: { public: true } },
  { path: '/', component: () => import('./pages/ChatPage.vue') },
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

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.token) return '/login'
  if (to.meta.roles && auth.user && !to.meta.roles.includes(auth.user.role)) return '/'
  return true
})

export default router
