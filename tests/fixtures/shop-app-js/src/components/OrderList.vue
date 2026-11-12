<template>
  <ul>
    <li v-for="order in orders" :key="order.id">
      {{ order.customerName }} - this text mentions fetch('/api/not-a-call') and must be ignored
    </li>
  </ul>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import axios from 'axios';

const orders = ref([]);
const customers = ref([]);

onMounted(async () => {
  const res = await axios.get('/api/customer', { params: { q: '' } });
  customers.value = res.data;
});

async function markPaid(id: number) {
  await axios.patch(`/api/orders/${id}/status`, { status: 'PAID' });
}
</script>

<style scoped>
li { padding: 4px; }
</style>
