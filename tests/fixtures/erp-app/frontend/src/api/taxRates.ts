import { http } from './http';

export interface TaxRate {
  id: number;
  name: string;
  rate: number;
}

export const taxRateApi = {
  list: () => http.get<TaxRate[]>('/tax-rates').then((r) => r.data),
  get: (id: number) => http.get<TaxRate>(`/tax-rates/${id}`).then((r) => r.data),
  create: (body: Omit<TaxRate, 'id'>) => http.post<TaxRate>('/tax-rates', body).then((r) => r.data),
  update: (id: number, body: Omit<TaxRate, 'id'>) => http.put<TaxRate>(`/tax-rates/${id}`, body).then((r) => r.data),
  remove: (id: number) => http.delete(`/tax-rates/${id}`),
};
