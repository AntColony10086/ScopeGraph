<template>
  <div class="app-layout">
    <!-- ==================== Sidebar ==================== -->
    <aside class="sidebar">
      <!-- Avatar (click to open profile drawer) -->
      <div class="sidebar-user" @click="openProfile" role="button" tabindex="0">
        <el-avatar :size="48" :src="avatarSrc" class="sidebar-avatar">
          <el-icon :size="22"><User /></el-icon>
        </el-avatar>
        <div class="sidebar-user-info">
          <p class="sidebar-nickname">
            {{ authStore.userNickname }}
            <el-tag
              v-if="authStore.isAdmin"
              type="danger"
              size="small"
              effect="dark"
              round
              style="margin-left: 6px"
            >管理员</el-tag>
          </p>
          <p class="sidebar-role">
            {{ authStore.isAdmin ? '可访问全部企业' : `已绑定 ${authStore.accessibleEnterprises.length} 家企业` }}
          </p>
        </div>
      </div>

      <el-divider />

      <!-- Navigation menu -->
      <el-menu
        :default-active="route.name?.toString()"
        class="sidebar-menu"
        :router="false"
        @select="handleSelect"
      >
        <el-menu-item index="Chat">
          <el-icon><ChatDotRound /></el-icon>
          <span>对话助手</span>
        </el-menu-item>
        <el-menu-item index="Dashboard">
          <el-icon><PieChart /></el-icon>
          <span>数据看板</span>
        </el-menu-item>
        <el-menu-item index="Data">
          <el-icon><DataAnalysis /></el-icon>
          <span>碳数据查询</span>
        </el-menu-item>
      </el-menu>

      <div class="sidebar-spacer" />

      <!-- Bottom: logout -->
      <div class="sidebar-footer">
        <el-button text type="danger" @click="handleLogout">
          <el-icon class="btn-icon"><SwitchButton /></el-icon>
          退出登录
        </el-button>
      </div>
    </aside>

    <!-- ==================== Main outlet ==================== -->
    <main class="main-outlet">
      <router-view />
    </main>

    <!-- ==================== Profile drawer ==================== -->
    <ProfileDrawer v-model="profileOpen" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  User,
  ChatDotRound,
  DataAnalysis,
  PieChart,
  SwitchButton,
} from '@element-plus/icons-vue'

import { useAuthStore } from '@/stores/auth'
import ProfileDrawer from '@/components/ProfileDrawer.vue'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const profileOpen = ref(false)

const avatarSrc = computed(() => authStore.userAvatar || '')

onMounted(async () => {
  // Refresh full profile (bio/phone/avatar) on first mount
  try {
    await authStore.fetchProfile()
  } catch {
    // ignore — token may already be expired and the interceptor handles it
  }
})

function handleSelect(name: string) {
  router.push({ name })
}

function openProfile() {
  profileOpen.value = true
}

function handleLogout() {
  authStore.logout()
  ElMessage.success('已退出登录')
  router.push('/login')
}
</script>

<style scoped>
.app-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.sidebar {
  width: 240px;
  min-width: 240px;
  background: #fff;
  border-right: 1px solid #e4e7ed;
  display: flex;
  flex-direction: column;
  padding: 20px 12px;
}

.sidebar-user {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.18s ease;
}

.sidebar-user:hover {
  background: #ecfdf5;
}

.sidebar-avatar {
  background-color: #0d9488;
  color: #fff;
  flex-shrink: 0;
}

.sidebar-user-info {
  min-width: 0;
}

.sidebar-nickname {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  display: flex;
  align-items: center;
}

.sidebar-role {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}

.sidebar .el-divider {
  margin: 12px 0;
}

.sidebar-menu {
  border-right: 0;
}

.sidebar-menu :deep(.el-menu-item) {
  border-radius: 6px;
  margin-bottom: 4px;
}

.sidebar-menu :deep(.el-menu-item.is-active) {
  background-color: #ecfdf5;
  color: #0d9488;
}

.sidebar-spacer {
  flex: 1;
}

.sidebar-footer {
  padding-top: 12px;
  border-top: 1px solid #ebeef5;
}

.btn-icon {
  margin-right: 6px;
}

.main-outlet {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: #f5f7fa;
}

@media (max-width: 768px) {
  .sidebar { display: none; }
}
</style>
