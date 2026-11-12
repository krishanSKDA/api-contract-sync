import axios from 'axios';

const http = axios.create({ baseURL: '/api', withCredentials: true });

export interface CustomerDto {
  id: number;
  fullName: string;
  email: string | null;
  loyaltyPoints: number;
  phone: string;
}

export async function searchCustomers(q: string): Promise<CustomerDto[]> {
  const { data } = await http.get<CustomerDto[]>('/customers', { params: { q } });
  return data;
}
