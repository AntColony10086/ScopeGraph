<template>
  <el-drawer
    :model-value="modelValue"
    direction="rtl"
    size="420px"
    :with-header="false"
    @update:model-value="(v: boolean) => emit('update:modelValue', v)"
  >
    <div class="profile-drawer">
      <header class="profile-header">
        <h3>个人设置</h3>
        <el-button text :icon="Close" @click="close" />
      </header>

      <!-- Avatar block -->
      <section class="profile-avatar-block">
        <el-upload
          :show-file-list="false"
          :before-upload="beforeAvatarUpload"
          :http-request="uploadAvatar"
          accept="image/*"
        >
          <div class="avatar-slot">
            <el-avatar :size="96" :src="avatarSrc">
              <el-icon :size="36"><UserFilled /></el-icon>
            </el-avatar>
            <div class="avatar-overlay">
              <el-icon :size="20"><Camera /></el-icon>
              <span>更换头像</span>
            </div>
          </div>
        </el-upload>
        <p class="avatar-hint">支持 png / jpg / webp，≤ 5 MB</p>
      </section>

      <!-- Account info -->
      <section class="profile-info">
        <div class="info-row"><span>账号</span><b>{{ user?.username }}</b></div>
        <div class="info-row"><span>角色</span>
          <el-tag :type="user?.role === 'admin' ? 'danger' : 'success'" size="small">
            {{ user?.role === 'admin' ? '管理员' : '普通用户' }}
          </el-tag>
        </div>
        <div class="info-row info-row--vertical">
          <span>已绑定企业</span>
          <div class="enterprise-tags">
            <el-tag v-if="user?.role === 'admin' || user?.accessible_enterprises?.includes('*')" type="warning" effect="dark">
              全部企业（管理员）
            </el-tag>
            <template v-else>
              <el-tag
                v-for="cid in user?.accessible_enterprises || []"
                :key="cid"
                effect="plain"
              >
                {{ enterpriseLabel(cid) }}
              </el-tag>
              <span v-if="!(user?.accessible_enterprises || []).length" class="empty-hint">
                未绑定，请联系管理员
              </span>
            </template>
          </div>
        </div>
      </section>

      <!-- Editable fields -->
      <section class="profile-form">
        <el-form :model="form" label-position="top">
          <el-form-item label="昵称">
            <el-input v-model="form.nickname" placeholder="给自己起个名字" />
          </el-form-item>
          <el-form-item label="联系电话">
            <el-input v-model="form.phone" placeholder="可选，便于人工顾问联络" />
          </el-form-item>
          <el-form-item label="个人简介">
            <el-input
              v-model="form.bio"
              type="textarea"
              :rows="3"
              placeholder="例如：负责化工企业A碳排放数据上报与配额履约"
            />
          </el-form-item>
        </el-form>
        <el-button
          type="primary"
          class="save-btn"
          :loading="saving"
          @click="onSave"
        >
          保存修改
        </el-button>
      </section>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Camera, Close, UserFilled } from '@element-plus/icons-vue'
import type { UploadRawFile } from 'element-plus'

import { useAuthStore } from '@/stores/auth'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<(e: 'update:modelValue', v: boolean) => void>()

const authStore = useAuthStore()
const user = computed(() => authStore.user)
const avatarSrc = computed(() => authStore.userAvatar || '')

const form = reactive({ nickname: '', phone: '', bio: '' })
const saving = ref(false)

const ENTERPRISE_LABELS: Record<string, string> = {
  C001: '化工企业A',
  C002: '化工企业B',
  C003: '化工企业C',
  C004: '化工企业D',
  C005: '化工企业E',
  C006: '化工企业F',
  C007: '化工企业G',
  C008: '化工企业H',
  C009: '化工企业I',
  C010: '炼化企业A',
  C011: '地区A化工聚合',
  C012: '地区A 工业园 3产业园',
  C013: '地区A 工业园 2产业园',
  C014: '地区A 城市4地区A 工业园 1',
  C015: '地区B',
  C016: '地区C',
  C017: '地区D',
  C018: '地区E',
  C019: '地区F',
  C020: '全国基准',
  C021: '中国石油地区A油田（石化）',
  C022: '光伏企业A（光伏）',
  C023: '煤炭企业A（煤炭）',
}
function enterpriseLabel(cid: string): string {
  return ENTERPRISE_LABELS[cid] || cid
}

watch(
  () => props.modelValue,
  (v) => {
    if (v) {
      form.nickname = user.value?.nickname || ''
      form.phone = user.value?.phone || ''
      form.bio = user.value?.bio || ''
    }
  },
)

function close() {
  emit('update:modelValue', false)
}

function beforeAvatarUpload(file: UploadRawFile): boolean {
  if (file.size > 5 * 1024 * 1024) {
    ElMessage.warning('头像不能超过 5MB')
    return false
  }
  if (!file.type.startsWith('image/')) {
    ElMessage.warning('请上传图片文件')
    return false
  }
  return true
}

async function uploadAvatar({ file }: { file: File }) {
  try {
    await authStore.uploadAvatar(file)
    ElMessage.success('头像更新成功')
  } catch (e) {
    const msg =
      (e as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
      '头像上传失败'
    ElMessage.error(msg)
  }
}

async function onSave() {
  saving.value = true
  try {
    await authStore.updateProfile({
      nickname: form.nickname,
      phone: form.phone,
      bio: form.bio,
    })
    ElMessage.success('个人信息已保存')
  } catch {
    ElMessage.error('保存失败，请稍后再试')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.profile-drawer {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 16px 20px 24px;
  overflow-y: auto;
}

.profile-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.profile-header h3 {
  font-size: 18px;
  font-weight: 700;
  color: #303133;
}

.profile-avatar-block {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 18px 0 14px;
  border-bottom: 1px solid #ebeef5;
}

.avatar-slot {
  position: relative;
  cursor: pointer;
}

.avatar-overlay {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  background: rgba(13, 148, 136, 0.65);
  color: #fff;
  font-size: 12px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  opacity: 0;
  transition: opacity 0.18s ease;
}

.avatar-slot:hover .avatar-overlay {
  opacity: 1;
}

.avatar-hint {
  font-size: 12px;
  color: #909399;
}

.profile-info {
  padding: 16px 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  border-bottom: 1px solid #ebeef5;
}

.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
}

.info-row > span {
  color: #909399;
}

.info-row > b {
  color: #303133;
  font-weight: 600;
}

.info-row--vertical {
  flex-direction: column;
  align-items: stretch;
  gap: 6px;
}

.enterprise-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.empty-hint {
  font-size: 12px;
  color: #c0c4cc;
}

.profile-form {
  padding-top: 16px;
}

.save-btn {
  width: 100%;
  background: #0d9488;
  border-color: #0d9488;
}

.save-btn:hover,
.save-btn:focus {
  background: #0f766e;
  border-color: #0f766e;
}
</style>
