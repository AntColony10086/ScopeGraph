<template>
  <section class="dashboard-page">
    <header class="dashboard-header">
      <div>
        <h1>数据看板</h1>
        <p>地区A 4 大行业碳数据库实时汇总（2019 – 2026 年累计 + 同比）</p>
      </div>

      <div class="refresh-panel">
        <el-switch
          v-model="autoRefresh"
          active-text="自动 15s"
          inactive-text="暂停"
        />
        <el-button
          type="primary"
          :icon="Refresh"
          :loading="refreshing"
          @click="refreshNow"
        >
          手动刷新
        </el-button>
        <span class="updated-at">
          上次更新：{{ lastUpdatedText }}
        </span>
      </div>
    </header>

    <el-alert
      v-if="errorMessage"
      class="dashboard-alert"
      type="error"
      :title="errorMessage"
      show-icon
      :closable="false"
    />

    <el-skeleton v-if="loading && !dashboard" :rows="12" animated />

    <el-empty
      v-else-if="isEmpty"
      description="暂无可展示的碳数据 — 请联系管理员开通企业绑定"
      class="empty-state"
    />

    <template v-else>
      <!-- ==================== KPI cards ==================== -->
      <section class="kpi-grid">
        <article
          v-for="item in kpiCards"
          :key="item.key"
          class="kpi-card"
        >
          <div class="kpi-label">{{ item.label }}</div>
          <div class="kpi-value">
            {{ item.value }}
            <span v-if="item.unit">{{ item.unit }}</span>
          </div>
          <div :class="['kpi-trend', item.trendClass]">
            <span class="kpi-trend__icon">{{ item.trendIcon }}</span>
            {{ item.trendText }}
          </div>
        </article>
      </section>

      <!-- ==================== Main grid ==================== -->
      <section class="dashboard-grid">
        <article class="panel span-2">
          <div class="panel-head">
            <div>
              <h2>近 8 年排放趋势</h2>
              <p>Scope 1 + Scope 2，按可见企业聚合</p>
            </div>
            <span class="legend">
              <i class="dot scope1"></i>Scope 1
              <i class="dot scope2"></i>Scope 2
            </span>
          </div>

          <div class="chart-wrap">
            <svg
              class="stacked-chart"
              viewBox="0 0 760 320"
              role="img"
              aria-label="近 8 年 Scope1 和 Scope2 堆叠柱图"
            >
              <line x1="56" y1="260" x2="720" y2="260" class="axis" />
              <line x1="56" y1="36" x2="56" y2="260" class="axis" />

              <g v-for="tick in yTicks" :key="tick.value">
                <line
                  x1="56" :y1="tick.y" x2="720" :y2="tick.y"
                  class="grid-line"
                />
                <text x="48" :y="tick.y + 4" text-anchor="end" class="tick-text">
                  {{ tick.label }}
                </text>
              </g>

              <g v-for="bar in stackedBars" :key="bar.year">
                <rect
                  :x="bar.x" :y="bar.scope2Y"
                  :width="bar.width" :height="bar.scope2Height"
                  rx="4" class="bar-scope2"
                />
                <rect
                  :x="bar.x" :y="bar.scope1Y"
                  :width="bar.width" :height="bar.scope1Height"
                  rx="4" class="bar-scope1"
                />
                <text
                  :x="bar.x + bar.width / 2" y="286"
                  text-anchor="middle" class="axis-label"
                >
                  {{ bar.year }}
                </text>
                <text
                  :x="bar.x + bar.width / 2"
                  :y="Math.min(bar.scope1Y, bar.scope2Y) - 8"
                  text-anchor="middle" class="bar-label"
                >
                  {{ formatWanTons(bar.totalTons) }}
                </text>
              </g>
            </svg>
          </div>
        </article>

        <article class="panel">
          <div class="panel-head">
            <div>
              <h2>{{ currentYear }} 企业 Top 排放</h2>
              <p>按 Scope 1 + Scope 2 总量排序</p>
            </div>
          </div>

          <div v-if="topEnterpriseBars.length === 0" class="empty-mini">暂无数据</div>
          <div v-else class="top-list">
            <div
              v-for="item in topEnterpriseBars"
              :key="item.enterpriseId"
              class="top-row"
            >
              <div class="top-meta">
                <span class="top-name" :title="item.enterpriseName">
                  {{ shortName(item.enterpriseName) }}
                </span>
                <span class="top-value">{{ formatWanTons(item.totalEmissionTons) }} 万吨</span>
              </div>
              <div class="top-bar-track">
                <div
                  class="top-bar-fill"
                  :style="{ width: `${item.percent}%` }"
                />
              </div>
            </div>
          </div>
        </article>

        <article class="panel">
          <div class="panel-head">
            <div>
              <h2>行业占比</h2>
              <p>{{ currentYear }} 年排放结构</p>
            </div>
          </div>

          <div v-if="industryShares.length === 0" class="empty-mini">暂无数据</div>
          <div v-else class="industry-list">
            <div
              v-for="(item, i) in industryShares"
              :key="item.industry"
              class="industry-row"
            >
              <div class="industry-meta">
                <strong>
                  <span class="industry-dot" :style="{ background: industryColor(i) }"></span>
                  {{ item.industry }}
                </strong>
                <span class="industry-value">
                  {{ formatPercent(item.percent) }}
                  <em class="industry-tons">· {{ formatWanTons(item.totalEmissionTons) }} 万吨</em>
                </span>
              </div>
              <div class="industry-track">
                <div
                  class="industry-fill"
                  :style="{ width: `${(item.percent * 100).toFixed(1)}%`, background: industryColor(i) }"
                />
              </div>
            </div>
          </div>
        </article>

        <article class="panel span-2">
          <div class="panel-head">
            <div>
              <h2>最近更新</h2>
              <p>最近 10 条观测点变更（按 OrderID 倒序）</p>
            </div>
          </div>

          <el-table
            :data="recentUpdates"
            size="small"
            class="updates-table"
            empty-text="暂无更新"
          >
            <el-table-column prop="updatedAt" label="时间" width="170">
              <template #default="{ row }">
                {{ formatDateTime(row.updatedAt) }}
              </template>
            </el-table-column>
            <el-table-column label="企业" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="cell-strong">{{ row.enterpriseName }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="year" label="年份" width="80" align="center" />
            <el-table-column prop="metricName" label="指标" min-width="180" show-overflow-tooltip />
            <el-table-column label="数值" min-width="160" align="right">
              <template #default="{ row }">
                <span class="cell-value">{{ formatMetricValue(row.value, row.unit) }}</span>
              </template>
            </el-table-column>
          </el-table>
        </article>
      </section>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import api from '@/utils/api'

type VisibleScope = 'all' | 'bound_enterprises'

interface DashboardSummaryResponse {
  meta: {
    visibleScope: VisibleScope
    latestYear: number
    currentYear: number
    lastUpdatedAt: string | null
    pollingSeconds: number
  }
  kpis: {
    cumulativeEmissionTons: number
    latestYearEmissionTons: number
    latestYearEmissionYoyRate: number | null
    fiveYearEmissionChangeRate: number | null
    totalElectricityKwh: number | null
    dominantIndustryName: string | null
    dominantIndustryPercent: number | null
  }
  yearly: Array<{
    year: number
    scope1EmissionTons: number
    scope2EmissionTons: number
    totalEmissionTons: number
  }>
  enterpriseTop: Array<{
    enterpriseId: string
    enterpriseName: string
    industry: string
    year: number
    totalEmissionTons: number
  }>
  industryShares: Array<{
    industry: string
    totalEmissionTons: number
    percent: number
  }>
  recentUpdates: Array<{
    id: string
    enterpriseId: string
    enterpriseName: string
    year: number
    metricCode: string
    metricName: string
    value: number
    unit: string
    operatorName: string
    updatedAt: string
  }>
}

interface KpiCard {
  key: string
  label: string
  value: string
  unit: string
  trendText: string
  trendIcon: string
  trendClass: 'trend-up' | 'trend-down' | 'trend-flat'
}

const POLLING_MS = 15_000

const loading = ref(true)
const refreshing = ref(false)
const autoRefresh = ref(true)
const errorMessage = ref('')
const dashboard = ref<DashboardSummaryResponse | null>(null)

let pollingTimer: number | undefined

const isEmpty = computed(
  () => !dashboard.value || dashboard.value.yearly.every((y) => y.totalEmissionTons === 0),
)

const currentYear = computed(() => dashboard.value?.meta.latestYear ?? 2023)

const lastUpdatedText = computed(() => {
  const value = dashboard.value?.meta.lastUpdatedAt
  return value ? formatDateTime(value) : '—'
})

const kpiCards = computed<KpiCard[]>(() => {
  const data = dashboard.value
  if (!data) return []

  return [
    {
      key: 'cumulative',
      label: '累计排放（近 8 年）',
      value: formatWanTons(data.kpis.cumulativeEmissionTons),
      unit: '万吨 CO₂e',
      ...trendMeta(null, '近 8 年总和'),
    },
    {
      key: 'latest-year',
      label: `${data.meta.latestYear} 年排放`,
      value: formatWanTons(data.kpis.latestYearEmissionTons),
      unit: '万吨 CO₂e',
      ...trendMeta(data.kpis.latestYearEmissionYoyRate, '同比'),
    },
    {
      key: 'five-year',
      label: '8 年累计涨跌',
      value: formatPercent(data.kpis.fiveYearEmissionChangeRate),
      unit: '',
      ...trendMeta(data.kpis.fiveYearEmissionChangeRate, '2019→2023'),
    },
    {
      key: 'industry',
      label: '主导行业',
      value: data.kpis.dominantIndustryName ?? '—',
      unit: '',
      trendText: data.kpis.dominantIndustryPercent == null
        ? '占比暂无'
        : `占比 ${formatPercent(data.kpis.dominantIndustryPercent)}`,
      trendIcon: '◆',
      trendClass: 'trend-flat',
    },
    {
      key: 'electricity',
      label: '累计用电量',
      value: data.kpis.totalElectricityKwh == null
        ? '—'
        : formatYiKwh(data.kpis.totalElectricityKwh),
      unit: data.kpis.totalElectricityKwh == null ? '' : '亿千瓦时',
      ...trendMeta(null, '指标待录入'),
    },
  ]
})

const maxYearlyTotal = computed(() => {
  const max = Math.max(
    ...((dashboard.value?.yearly ?? []).map((item) => item.totalEmissionTons)),
    0,
  )
  return max > 0 ? max : 1
})

const yTicks = computed(() => {
  const max = maxYearlyTotal.value
  return [0.25, 0.5, 0.75, 1].map((ratio) => ({
    value: max * ratio,
    y: 260 - 224 * ratio,
    label: formatWanTons(max * ratio),
  }))
})

const stackedBars = computed(() => {
  const rows = dashboard.value?.yearly ?? []
  const chartLeft = 86
  const chartWidth = 600
  const gap = rows.length > 1 ? 34 : 0
  const width = rows.length > 0
    ? Math.min(72, (chartWidth - gap * (rows.length - 1)) / rows.length)
    : 0

  return rows.map((item, index) => {
    const x = chartLeft + index * (width + gap)
    const scope1Height = (item.scope1EmissionTons / maxYearlyTotal.value) * 224
    const scope2Height = (item.scope2EmissionTons / maxYearlyTotal.value) * 224
    const scope2Y = 260 - scope2Height
    const scope1Y = scope2Y - scope1Height
    return {
      year: item.year,
      x, width,
      totalTons: item.totalEmissionTons,
      scope1Y, scope1Height, scope2Y, scope2Height,
    }
  })
})

const topEnterpriseBars = computed(() => {
  const rows = dashboard.value?.enterpriseTop ?? []
  const max = Math.max(...rows.map((item) => item.totalEmissionTons), 0)
  return rows.slice(0, 8).map((item) => ({
    ...item,
    percent: max > 0 ? Math.max((item.totalEmissionTons / max) * 100, 4) : 0,
  }))
})

const industryShares = computed(() => dashboard.value?.industryShares ?? [])
const recentUpdates = computed(() => dashboard.value?.recentUpdates ?? [])

async function fetchDashboard(isManual = false): Promise<void> {
  if (isManual) refreshing.value = true
  try {
    errorMessage.value = ''
    const { data } = await api.get<DashboardSummaryResponse>('/data/dashboard/summary')
    dashboard.value = data
  } catch (error) {
    const detail =
      (error as { response?: { data?: { detail?: string } } }).response?.data?.detail
    errorMessage.value = detail || '看板数据加载失败，请稍后重试'
  } finally {
    loading.value = false
    refreshing.value = false
  }
}

function refreshNow() {
  void fetchDashboard(true)
}

function startPolling() {
  stopPolling()
  if (!autoRefresh.value) return
  pollingTimer = window.setInterval(() => {
    void fetchDashboard(false)
  }, POLLING_MS)
}

function stopPolling() {
  if (pollingTimer !== undefined) {
    window.clearInterval(pollingTimer)
    pollingTimer = undefined
  }
}

function trendMeta(
  rate: number | null,
  label = '同比',
): Pick<KpiCard, 'trendText' | 'trendIcon' | 'trendClass'> {
  if (rate == null) {
    return { trendText: label, trendIcon: '·', trendClass: 'trend-flat' }
  }
  if (Math.abs(rate) < 0.001) {
    return { trendText: `${label} 持平`, trendIcon: '→', trendClass: 'trend-flat' }
  }
  return {
    trendText: `${label} ${formatPercent(Math.abs(rate))}`,
    trendIcon: rate > 0 ? '↑' : '↓',
    trendClass: rate > 0 ? 'trend-up' : 'trend-down',
  }
}

const INDUSTRY_PALETTE = ['#0d9488', '#14b8a6', '#f59e0b', '#6366f1', '#dc2626']
function industryColor(i: number): string {
  return INDUSTRY_PALETTE[i % INDUSTRY_PALETTE.length]
}

function shortName(full: string): string {
  // Drop the parenthesised tag in CompanyName for compact display
  return full.split('（')[0].split('(')[0]
}

function formatWanTons(value: number | null | undefined): string {
  if (value == null) return '0'
  return formatNumber(value / 10_000, 2)
}

function formatYiKwh(value: number | null | undefined): string {
  if (value == null) return '0'
  return formatNumber(value / 100_000_000, 2)
}

function formatPercent(value: number | null | undefined): string {
  if (value == null) return '—'
  return `${formatNumber(value * 100, 1)}%`
}

function formatMetricValue(value: number, unit: string): string {
  if (unit === 'tCO2e') return `${formatWanTons(value)} 万吨 CO₂e`
  if (unit === 'kWh') return `${formatYiKwh(value)} 亿千瓦时`
  return `${formatNumber(value, 2)} ${unit}`
}

function formatNumber(value: number, digits: number): string {
  return new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  }).format(value)
}

function formatDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
    hour12: false,
  }).format(date)
}

watch(autoRefresh, startPolling)

onMounted(() => {
  void fetchDashboard()
  startPolling()
})

onUnmounted(stopPolling)
</script>

<style scoped>
.dashboard-page {
  flex: 1;
  min-width: 0;
  padding: 22px 24px 28px;
  background: #f6faf9;
  color: #12312b;
  overflow-y: auto;
}

.dashboard-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  margin-bottom: 18px;
}

.dashboard-header h1 {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  color: #064e3b;
}

.dashboard-header p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 13px;
}

.refresh-panel {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.updated-at {
  font-size: 12px;
  color: #64748b;
}

.dashboard-alert { margin-bottom: 14px; }

.empty-state {
  min-height: 360px;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 6px 18px rgba(15, 23, 42, 0.06);
}

/* ─── KPI cards ─── */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 14px;
}

.kpi-card,
.panel {
  background: #fff;
  border: 1px solid #e6efed;
  border-radius: 10px;
  box-shadow: 0 6px 18px rgba(15, 23, 42, 0.05);
}

.kpi-card { padding: 16px 18px; }

.kpi-label {
  font-size: 12px;
  color: #64748b;
  margin-bottom: 8px;
  letter-spacing: 0.4px;
}

.kpi-value {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-size: 24px;
  font-weight: 750;
  color: #064e3b;
  line-height: 1.15;
  font-variant-numeric: tabular-nums;
}

.kpi-value span {
  font-size: 12px;
  font-weight: 500;
  color: #64748b;
}

.kpi-trend {
  margin-top: 10px;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.kpi-trend__icon {
  font-weight: 700;
  font-size: 13px;
}

.trend-up    { color: #dc2626; }
.trend-down  { color: #0d9488; }
.trend-flat  { color: #64748b; }

/* ─── Main grid ─── */
.dashboard-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.panel {
  padding: 18px;
  min-width: 0;
}

.span-2 { grid-column: span 2; }

.panel-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.panel-head h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: #12312b;
}

.panel-head p {
  margin: 4px 0 0;
  font-size: 12px;
  color: #64748b;
}

.legend {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #64748b;
  font-size: 12px;
  white-space: nowrap;
}

.dot {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  display: inline-block;
}

.scope1 { background: #0d9488; }
.scope2 { background: #86efac; }

/* ─── Stacked chart ─── */
.chart-wrap {
  width: 100%;
  overflow-x: auto;
}

.stacked-chart {
  width: 100%;
  min-width: 640px;
  height: 320px;
}

.axis      { stroke: #94a3b8; stroke-width: 1; }
.grid-line { stroke: #e2e8f0; stroke-width: 1; stroke-dasharray: 3 3; }

.tick-text,
.axis-label {
  font-size: 11px;
  fill: #64748b;
}

.bar-label {
  font-size: 11px;
  font-weight: 700;
  fill: #064e3b;
}

.bar-scope1 { fill: #0d9488; }
.bar-scope2 { fill: #86efac; }

/* ─── Top list / industry list ─── */
.top-list,
.industry-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.top-meta,
.industry-meta {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 12px;
  color: #475569;
  margin-bottom: 6px;
}

.top-name {
  color: #12312b;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.top-value,
.industry-value {
  font-variant-numeric: tabular-nums;
  font-weight: 650;
  color: #064e3b;
}

.industry-tons {
  font-style: normal;
  font-weight: 500;
  color: #64748b;
  margin-left: 4px;
}

.industry-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 999px;
  margin-right: 6px;
  vertical-align: middle;
}

.top-bar-track,
.industry-track {
  height: 8px;
  background: #e6efed;
  border-radius: 999px;
  overflow: hidden;
}

.top-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #0d9488, #064e3b);
  border-radius: inherit;
  transition: width 0.35s ease;
}

.industry-fill {
  height: 100%;
  border-radius: inherit;
  transition: width 0.35s ease;
}

.empty-mini {
  text-align: center;
  font-size: 13px;
  color: #94a3b8;
  padding: 24px 0;
}

/* ─── Updates table ─── */
.updates-table {
  width: 100%;
}

.cell-strong {
  font-weight: 600;
  color: #12312b;
}

.cell-value {
  font-variant-numeric: tabular-nums;
  font-weight: 650;
  color: #0d9488;
}

/* ─── Element Plus tweaks ─── */
:deep(.el-button--primary) {
  --el-button-bg-color: #0d9488;
  --el-button-border-color: #0d9488;
  --el-button-hover-bg-color: #0f766e;
  --el-button-hover-border-color: #0f766e;
  --el-button-active-bg-color: #0f766e;
  --el-button-active-border-color: #0f766e;
}

:deep(.el-switch.is-checked .el-switch__core) {
  background-color: #0d9488 !important;
  border-color: #0d9488 !important;
}

:deep(.el-table) {
  --el-table-header-bg-color: #f1f9f7;
  --el-table-row-hover-bg-color: #ecfdf5;
}

/* ─── Responsive ─── */
@media (max-width: 1279px) {
  .kpi-grid     { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .dashboard-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .span-2       { grid-column: span 2; }
}

@media (max-width: 768px) {
  .dashboard-page { padding: 16px; }
  .dashboard-header { flex-direction: column; }
  .refresh-panel { width: 100%; justify-content: flex-start; }
  .kpi-grid,
  .dashboard-grid { grid-template-columns: 1fr; }
  .span-2 { grid-column: span 1; }
  .kpi-value { font-size: 20px; }
}
</style>
