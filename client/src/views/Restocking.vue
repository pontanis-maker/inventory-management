<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { api } from '../api'
import { useFilters } from '../composables/useFilters'
import { useI18n } from '../composables/useI18n'
import { formatCurrency, formatCurrencyWithDecimals } from '../utils/currency'

const { t, currentLocale, currentCurrency, translateProductName, translateWarehouse } = useI18n()
const { selectedLocation, selectedCategory, getCurrentFilters } = useFilters()

const BUDGET_MIN = 10000
const BUDGET_MAX = 500000
const BUDGET_STEP = 5000
const DEBOUNCE_MS = 250

const budget = ref(100000)
const recommendations = ref([])
const loading = ref(true)
const error = ref(null)

// Editable order quantities keyed by SKU; reset to the server's recommendation on every reload
const quantities = ref({})

const submitting = ref(false)
const submitError = ref(null)
const confirmation = ref(null)

const money = (amount) => formatCurrency(amount, currentCurrency.value)
// formatCurrencyWithDecimals puts the sign after the symbol ("$-6,331.00"). "Remaining" goes
// negative when edited quantities exceed the budget, so format the magnitude and prefix the sign.
const moneyExact = (amount) => {
  const formatted = formatCurrencyWithDecimals(Math.abs(amount), currentCurrency.value, 2)
  return amount < 0 ? `-${formatted}` : formatted
}

// Dates may be missing or malformed; return an empty marker rather than "Invalid Date"
const formatDate = (value) => {
  const date = new Date(value)
  if (isNaN(date.getTime())) return '-'
  return date.toLocaleDateString(currentLocale.value === 'ja' ? 'ja-JP' : 'en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric'
  })
}

// Request counter so a slow, stale response cannot overwrite a newer one
let requestId = 0

const loadRecommendations = async () => {
  const myId = ++requestId
  loading.value = true
  error.value = null
  try {
    const data = await api.getRestockRecommendations(budget.value, getCurrentFilters())
    if (myId !== requestId) return
    const items = Array.isArray(data.items) ? data.items : []
    recommendations.value = items
    const reset = {}
    for (const item of items) reset[item.sku] = item.recommended_quantity
    quantities.value = reset
  } catch (err) {
    if (myId !== requestId) return
    error.value = t('restocking.loadError') + ': ' + (err.response?.data?.detail || err.message)
    console.error(err)
  } finally {
    if (myId === requestId) loading.value = false
  }
}

// Debounce slider/filter changes so dragging does not fire a request per step
let debounceTimer = null
const scheduleLoad = () => {
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(loadRecommendations, DEBOUNCE_MS)
}
watch([budget, selectedLocation, selectedCategory], scheduleLoad)

onMounted(loadRecommendations)
onBeforeUnmount(() => clearTimeout(debounceTimer))

// Clamp user input to a whole number within [0, shortfall]
const setQuantity = (item, rawValue) => {
  let qty = Math.floor(Number(rawValue))
  if (!Number.isFinite(qty) || qty < 0) qty = 0
  if (qty > item.shortfall) qty = item.shortfall
  quantities.value[item.sku] = qty
}

const qtyOf = (item) => quantities.value[item.sku] ?? 0

// Totals are computed in cents to avoid floating point drift when comparing with the budget
const orderTotal = computed(() => {
  const cents = recommendations.value.reduce(
    (sum, item) => sum + Math.round(item.unit_cost * 100) * qtyOf(item),
    0
  )
  return cents / 100
})
const remaining = computed(() => Math.round((budget.value - orderTotal.value) * 100) / 100)
const overBudget = computed(() => remaining.value < 0)

const orderLines = computed(() =>
  recommendations.value
    .filter(item => qtyOf(item) > 0)
    .map(item => ({ sku: item.sku, quantity: qtyOf(item) }))
)

const canSubmit = computed(
  () => orderLines.value.length > 0 && !overBudget.value && !submitting.value && !loading.value
)

const placeOrder = async () => {
  if (!canSubmit.value) return
  submitting.value = true
  submitError.value = null
  confirmation.value = null
  try {
    const order = await api.createRestockOrder(budget.value, orderLines.value)
    confirmation.value = {
      orderNumber: order.order_number,
      date: formatDate(order.expected_delivery),
      days: order.lead_time_days
    }
    await loadRecommendations()
  } catch (err) {
    submitError.value = err.response?.data?.detail
      ? (typeof err.response.data.detail === 'string'
        ? err.response.data.detail
        : JSON.stringify(err.response.data.detail))
      : t('restocking.submitError') + ': ' + err.message
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div class="card budget-card">
      <div class="budget-row">
        <label for="budget-slider" class="budget-label">{{ t('restocking.budget') }}</label>
        <span class="budget-value">{{ money(budget) }}</span>
      </div>
      <input
        id="budget-slider"
        v-model.number="budget"
        type="range"
        class="budget-slider"
        :min="BUDGET_MIN"
        :max="BUDGET_MAX"
        :step="BUDGET_STEP"
      />
      <div class="budget-scale">
        <span>{{ money(BUDGET_MIN) }}</span>
        <span>{{ money(BUDGET_MAX) }}</span>
      </div>
    </div>

    <div v-if="confirmation" class="confirmation" role="status">
      {{ t('restocking.confirmation', {
        orderNumber: confirmation.orderNumber,
        date: confirmation.date,
        days: confirmation.days
      }) }}
      <router-link to="/orders" class="confirmation-link">{{ t('restocking.viewOrders') }}</router-link>
    </div>
    <div v-if="submitError" class="error" role="alert">{{ submitError }}</div>

    <div v-if="loading && recommendations.length === 0" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div class="summary-bar">
        <div class="summary-item">
          <span class="summary-label">{{ t('restocking.budget') }}</span>
          <span class="summary-value">{{ money(budget) }}</span>
        </div>
        <div class="summary-item">
          <span class="summary-label">{{ t('restocking.orderTotal') }}</span>
          <span :class="['summary-value', { 'over-budget': overBudget }]">{{ moneyExact(orderTotal) }}</span>
        </div>
        <div class="summary-item">
          <span class="summary-label">{{ t('restocking.remaining') }}</span>
          <span :class="['summary-value', { 'over-budget': overBudget }]">{{ moneyExact(remaining) }}</span>
        </div>
        <div class="summary-action">
          <span v-if="overBudget" class="over-budget-message">{{ t('restocking.overBudget') }}</span>
          <button type="button" class="place-order" :disabled="!canSubmit" @click="placeOrder">
            {{ submitting ? t('restocking.submitting') : t('restocking.placeOrder') }}
          </button>
        </div>
      </div>

      <div :class="['card', { refreshing: loading }]">
        <div v-if="recommendations.length === 0" class="empty">{{ t('restocking.noRecommendations') }}</div>
        <div v-else class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.name') }}</th>
                <th>{{ t('restocking.table.category') }}</th>
                <th>{{ t('restocking.table.warehouse') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th class="num">{{ t('restocking.table.forecast') }}</th>
                <th class="num">{{ t('restocking.table.onHand') }}</th>
                <th class="num">{{ t('restocking.table.shortfall') }}</th>
                <th class="num">{{ t('restocking.table.unitCost') }}</th>
                <th class="num">{{ t('restocking.table.quantity') }}</th>
                <th class="num">{{ t('restocking.table.lineTotal') }}</th>
                <th class="num">{{ t('restocking.table.leadTime') }}</th>
              </tr>
            </thead>
            <tbody>
              <!-- The backend rejects duplicate SKUs, so SKU is a unique key (and the quantities map key) -->
              <tr v-for="item in recommendations" :key="item.sku">
                <td><strong>{{ item.sku }}</strong></td>
                <td>{{ translateProductName(item.name) }}</td>
                <td>{{ item.category }}</td>
                <td>{{ translateWarehouse(item.warehouse) }}</td>
                <td>
                  <span :class="['badge', item.trend]">{{ t(`trends.${item.trend}`) }}</span>
                </td>
                <td class="num">{{ item.forecasted_demand.toLocaleString() }}</td>
                <td class="num">{{ item.quantity_on_hand.toLocaleString() }}</td>
                <td class="num">{{ item.shortfall.toLocaleString() }}</td>
                <td class="num">{{ moneyExact(item.unit_cost) }}</td>
                <td class="num">
                  <input
                    type="number"
                    class="qty-input"
                    min="0"
                    :max="item.shortfall"
                    step="1"
                    :value="qtyOf(item)"
                    :aria-label="`${t('restocking.table.quantity')} ${item.sku}`"
                    @input="setQuantity(item, $event.target.value)"
                    @change="$event.target.value = qtyOf(item)"
                  />
                </td>
                <td class="num">{{ moneyExact(qtyOf(item) * item.unit_cost) }}</td>
                <td class="num">{{ t('orders.submitted.days', { count: item.lead_time_days }) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.budget-card {
  padding: 1.25rem 1.5rem;
  margin-bottom: 1.5rem;
}

.budget-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 0.75rem;
}

.budget-label {
  font-size: 0.875rem;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.025em;
}

.budget-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #0f172a;
}

.budget-slider {
  width: 100%;
  accent-color: #0f172a;
}

.budget-scale {
  display: flex;
  justify-content: space-between;
  font-size: 0.75rem;
  color: #64748b;
}

.summary-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 2rem;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 1rem 1.5rem;
  margin-bottom: 1.5rem;
}

.summary-item {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.summary-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.025em;
}

.summary-value {
  font-size: 1.25rem;
  font-weight: 700;
  color: #0f172a;
}

.summary-value.over-budget {
  color: #dc2626;
}

.summary-action {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 1rem;
}

.over-budget-message {
  font-size: 0.813rem;
  color: #dc2626;
}

.place-order {
  background: #0f172a;
  color: white;
  border: none;
  border-radius: 6px;
  padding: 0.625rem 1.25rem;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
}

.place-order:hover:not(:disabled) {
  background: #1e293b;
}

.place-order:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.confirmation {
  background: #d1fae5;
  color: #065f46;
  border: 1px solid #a7f3d0;
  border-radius: 8px;
  padding: 0.875rem 1.25rem;
  margin-bottom: 1rem;
  font-size: 0.875rem;
}

.confirmation-link {
  margin-left: 0.5rem;
  color: #065f46;
  font-weight: 600;
  text-decoration: underline;
}

.refreshing {
  opacity: 0.6;
  transition: opacity 0.15s;
}

.empty {
  padding: 2rem;
  text-align: center;
  color: #64748b;
}

th.num,
td.num {
  text-align: right;
  white-space: nowrap;
}

.qty-input {
  width: 5rem;
  padding: 0.25rem 0.5rem;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  text-align: right;
  font-size: 0.875rem;
  color: #0f172a;
}
</style>
