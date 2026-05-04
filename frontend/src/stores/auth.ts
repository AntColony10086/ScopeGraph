import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/utils/api'
import type { UserProfile, LoginResponse } from '@/types'

const EMPTY_USER: UserProfile = {
  user_id: '',
  username: '',
  role: 'user',
  accessible_enterprises: [],
}

function loadStoredUser(): UserProfile | null {
  try {
    const raw = localStorage.getItem('user')
    if (!raw) return null
    const parsed = JSON.parse(raw)
    return { ...EMPTY_USER, ...parsed } as UserProfile
  } catch {
    return null
  }
}

export const useAuthStore = defineStore('auth', () => {
  // --------------- state ---------------
  const token = ref<string>(localStorage.getItem('token') || '')
  const user = ref<UserProfile | null>(loadStoredUser())
  const loading = ref(false)

  // --------------- getters ---------------
  const isAuthenticated = computed(() => !!token.value)
  const userNickname = computed(() => user.value?.nickname || user.value?.username || '用户')
  const userAvatar = computed(() => user.value?.avatar_url || '')
  const isAdmin = computed(() => user.value?.role === 'admin')
  const accessibleEnterprises = computed(() => user.value?.accessible_enterprises || [])

  // --------------- actions ---------------
  async function login(username: string, password: string): Promise<void> {
    loading.value = true
    try {
      const { data } = await api.post<LoginResponse>('/auth/login', {
        username,
        password,
      })
      token.value = data.access_token
      user.value = {
        ...EMPTY_USER,
        user_id: data.user_id,
        username: data.username,
        nickname: data.nickname || data.username,
        role: data.role,
        accessible_enterprises: data.accessible_enterprises || [],
        avatar_url: data.avatar_url,
      }
      localStorage.setItem('token', data.access_token)
      localStorage.setItem('user', JSON.stringify(user.value))
      // Pull the full profile (bio, phone, ...) right after login
      try {
        await fetchProfile()
      } catch {
        /* keep going even if profile fetch fails */
      }
    } finally {
      loading.value = false
    }
  }

  function logout(): void {
    token.value = ''
    user.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('user')
  }

  async function fetchProfile(): Promise<UserProfile | null> {
    if (!token.value) return null
    const { data } = await api.get<UserProfile>('/profile')
    user.value = { ...EMPTY_USER, ...data }
    localStorage.setItem('user', JSON.stringify(user.value))
    return user.value
  }

  async function updateProfile(payload: {
    nickname?: string
    bio?: string
    phone?: string
  }): Promise<UserProfile | null> {
    const { data } = await api.put<UserProfile>('/profile', payload)
    user.value = { ...EMPTY_USER, ...data }
    localStorage.setItem('user', JSON.stringify(user.value))
    return user.value
  }

  async function uploadAvatar(file: File): Promise<string> {
    const form = new FormData()
    form.append('file', file)
    const { data } = await api.post<{ avatar_url: string }>(
      '/profile/avatar',
      form,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    )
    if (user.value) {
      user.value = { ...user.value, avatar_url: data.avatar_url }
      localStorage.setItem('user', JSON.stringify(user.value))
    }
    return data.avatar_url
  }

  return {
    token,
    user,
    loading,
    isAuthenticated,
    userNickname,
    userAvatar,
    isAdmin,
    accessibleEnterprises,
    login,
    logout,
    fetchProfile,
    updateProfile,
    uploadAvatar,
  }
})
