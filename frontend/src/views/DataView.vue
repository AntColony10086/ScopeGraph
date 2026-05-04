<template>
  <div class="data-page">
    <!-- Header bar -->
    <header class="data-header">
      <el-icon :size="20" color="#0d9488"><DataAnalysis /></el-icon>
      <span class="data-header-title">企业碳数据查询与维护</span>
      <el-tag v-if="authStore.isAdmin" type="danger" size="small" effect="dark" round>
        管理员视图
      </el-tag>
      <el-tag v-else type="success" size="small" effect="plain">
        已绑定 {{ enterprises.length }} 家企业
      </el-tag>
      <div class="header-spacer" />
      <el-button type="primary" :icon="Plus" @click="openCreate">新增数据</el-button>
    </header>

    <!-- Filters -->
    <section class="data-filters">
      <el-form :inline="true" @submit.prevent>
        <el-form-item label="企业">
          <el-select
            v-model="filters.customer_id"
            placeholder="全部企业"
            clearable
            filterable
            style="width: 240px"
            @change="loadObservations"
          >
            <el-option
              v-for="e in enterprises"
              :key="e.customer_id"
              :label="`${e.customer_id}  ${e.name}`"
              :value="e.customer_id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="年份">
          <el-select
            v-model="filters.year"
            placeholder="全部年份"
            clearable
            style="width: 140px"
            @change="loadObservations"
          >
            <el-option v-for="y in availableYears" :key="y" :label="y" :value="y" />
          </el-select>
        </el-form-item>
        <el-form-item label="指标">
          <el-select
            v-model="filters.indicator_id"
            placeholder="全部指标"
            clearable
            filterable
            style="width: 280px"
            @change="loadObservations"
          >
            <el-option
              v-for="i in indicators"
              :key="i.indicator_id"
              :label="`${i.name}（${i.unit || '—'}）`"
              :value="i.indicator_id"
            />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button :icon="Refresh" @click="loadObservations">刷新</el-button>
        </el-form-item>
      </el-form>
    </section>

    <!-- Table -->
    <section class="data-table-wrap">
      <el-table
        v-loading="loading"
        :data="rows"
        height="100%"
        stripe
        empty-text="未查询到数据"
      >
        <el-table-column type="index" label="#" width="50" />
        <el-table-column prop="enterprise" label="企业" min-width="240" show-overflow-tooltip />
        <el-table-column prop="year" label="年份" width="80" align="center" />
        <el-table-column prop="indicator" label="指标" min-width="180" show-overflow-tooltip />
        <el-table-column prop="category" label="类别" width="120" />
        <el-table-column prop="value" label="数值" width="120" align="right">
          <template #default="{ row }">
            <span class="value-cell">{{ formatValue(row.value) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="unit" label="单位" width="140" />
        <el-table-column prop="source" label="数据来源" min-width="200" show-overflow-tooltip />
        <el-table-column label="操作" width="160" align="center">
          <template #default="{ row }">
            <el-button text :icon="Edit" type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button text :icon="Delete" type="danger" @click="onDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <!-- Edit / Create dialog -->
    <el-dialog
      v-model="dialogOpen"
      :title="dialogMode === 'create' ? '新增数据点' : '编辑数据点'"
      width="480px"
      :close-on-click-modal="false"
    >
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="80px">
        <el-form-item label="企业" prop="customer_id">
          <el-select
            v-model="form.customer_id"
            placeholder="选择企业"
            filterable
            :disabled="dialogMode === 'edit'"
            style="width: 100%"
          >
            <el-option
              v-for="e in enterprises"
              :key="e.customer_id"
              :label="`${e.customer_id}  ${e.name}`"
              :value="e.customer_id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="年份" prop="year">
          <el-select
            v-model="form.year"
            placeholder="选择年份"
            :disabled="dialogMode === 'edit'"
            style="width: 100%"
          >
            <el-option v-for="y in availableYears" :key="y" :label="y" :value="y" />
          </el-select>
        </el-form-item>
        <el-form-item label="指标" prop="indicator_id">
          <el-select
            v-model="form.indicator_id"
            placeholder="选择指标"
            filterable
            :disabled="dialogMode === 'edit'"
            style="width: 100%"
          >
            <el-option
              v-for="i in indicators"
              :key="i.indicator_id"
              :label="`${i.name}（${i.unit || '—'}）`"
              :value="i.indicator_id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="数值" prop="value">
          <el-input-number
            v-model="form.value"
            :precision="2"
            :step="1"
            :min="0"
            controls-position="right"
            style="width: 100%"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="onSubmit">
          {{ dialogMode === 'create' ? '创建' : '保存' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  ElMessage,
  ElMessageBox,
  type FormInstance,
  type FormRules,
} from 'element-plus'
import { DataAnalysis, Delete, Edit, Plus, Refresh } from '@element-plus/icons-vue'

import api from '@/utils/api'
import { useAuthStore } from '@/stores/auth'
import type { EnterpriseRow, IndicatorRow, ObservationRow } from '@/types'

const authStore = useAuthStore()

const enterprises = ref<EnterpriseRow[]>([])
const indicators = ref<IndicatorRow[]>([])
const rows = ref<ObservationRow[]>([])
const loading = ref(false)

// Years: derived from observations actually present in the DB. Until the first
// fetch arrives, fall back to a sane window around the current year so the
// "新增数据" form is always usable.
const knownYears = ref<number[]>([])
const availableYears = computed<number[]>(() => {
  if (knownYears.value.length > 0) return knownYears.value
  const cy = new Date().getFullYear()
  const fallback: number[] = []
  for (let y = cy - 5; y <= cy + 1; y++) fallback.push(y)
  return fallback
})

const filters = reactive<{
  customer_id?: string
  year?: number
  indicator_id?: number
}>({})

const dialogOpen = ref(false)
const dialogMode = ref<'create' | 'edit'>('create')
const submitting = ref(false)
const formRef = ref<FormInstance | null>(null)
const form = reactive<{
  order_id?: number
  customer_id?: string
  year?: number
  indicator_id?: number
  value: number
}>({ value: 0 })
const formRules: FormRules = {
  customer_id: [{ required: true, message: '请选择企业', trigger: 'change' }],
  year: [{ required: true, message: '请选择年份', trigger: 'change' }],
  indicator_id: [{ required: true, message: '请选择指标', trigger: 'change' }],
  value: [{ required: true, message: '请输入数值', trigger: 'blur' }],
}

onMounted(async () => {
  await Promise.all([loadEnterprises(), loadIndicators()])
  await loadObservations()
})

async function loadEnterprises() {
  try {
    const { data } = await api.get<EnterpriseRow[]>('/data/enterprises')
    enterprises.value = data
  } catch {
    ElMessage.error('加载企业列表失败')
  }
}

async function loadIndicators() {
  try {
    const { data } = await api.get<IndicatorRow[]>('/data/indicators')
    indicators.value = data
  } catch {
    ElMessage.error('加载指标列表失败')
  }
}

async function loadObservations() {
  loading.value = true
  try {
    const params: Record<string, string | number> = {}
    if (filters.customer_id) params.customer_id = filters.customer_id
    if (filters.year) params.year = filters.year
    if (filters.indicator_id) params.indicator_id = filters.indicator_id
    const { data } = await api.get<ObservationRow[]>('/data/observations', { params })
    rows.value = data
    // Refresh the global year set whenever we get an unfiltered query back
    // (we want the dropdown to reflect what's actually in the DB).
    if (!filters.year) {
      const ys = Array.from(new Set(data.map((r) => r.year))).sort((a, b) => a - b)
      if (ys.length > 0) knownYears.value = ys
    }
  } catch (e) {
    const msg =
      (e as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
      '加载数据失败'
    ElMessage.error(msg)
    rows.value = []
  } finally {
    loading.value = false
  }
}

function openCreate() {
  dialogMode.value = 'create'
  form.order_id = undefined
  form.customer_id = filters.customer_id
  form.year = filters.year
  form.indicator_id = filters.indicator_id
  form.value = 0
  dialogOpen.value = true
}

function openEdit(row: ObservationRow) {
  dialogMode.value = 'edit'
  form.order_id = row.order_id
  form.customer_id = row.customer_id
  form.year = row.year
  form.indicator_id = row.indicator_id
  form.value = row.value
  dialogOpen.value = true
}

async function onSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    if (dialogMode.value === 'create') {
      await api.post<ObservationRow>('/data/observations', {
        customer_id: form.customer_id,
        year: form.year,
        indicator_id: form.indicator_id,
        value: form.value,
      })
      ElMessage.success('已创建数据点')
    } else {
      await api.put<ObservationRow>('/data/observations', {
        order_id: form.order_id,
        indicator_id: form.indicator_id,
        value: form.value,
      })
      ElMessage.success('已更新数据点')
    }
    dialogOpen.value = false
    await loadObservations()
  } catch (e) {
    const msg =
      (e as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
      '操作失败'
    ElMessage.error(msg)
  } finally {
    submitting.value = false
  }
}

async function onDelete(row: ObservationRow) {
  try {
    await ElMessageBox.confirm(
      `确认删除 ${row.enterprise} ${row.year} 年 ${row.indicator} 的数据？`,
      '删除数据点',
      {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
      },
    )
  } catch {
    return // user cancelled
  }
  try {
    await api.delete('/data/observations', {
      data: { order_id: row.order_id, indicator_id: row.indicator_id },
    })
    ElMessage.success('已删除')
    await loadObservations()
  } catch (e) {
    const msg =
      (e as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
      '删除失败'
    ElMessage.error(msg)
  }
}

function formatValue(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}
</script>

<style scoped>
.data-page {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: #f5f7fa;
}

.data-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 24px;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  flex-shrink: 0;
}

.data-header-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.header-spacer { flex: 1; }

.data-filters {
  padding: 14px 24px 0;
  background: #fff;
  border-bottom: 1px solid #f0f2f5;
}

.data-table-wrap {
  flex: 1;
  padding: 12px 24px 18px;
  min-height: 0;
}

.value-cell {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  color: #0d9488;
}
</style>
