import { http } from './http';

export interface Product {
  id: number;
  name: string;
  sku: string;
  price: number;
  isActive: boolean;
  categoryId: number;
  stock: number;
}

export const productApi = {
  list: () => http.get<Product[]>('/products').then((r) => r.data),
  get: (id: number) => http.get<Product>(`/products/${id}`).then((r) => r.data),
  create: (body: Omit<Product, 'id'>) => http.post<Product>('/products', body).then((r) => r.data),
  update: (id: number, body: Omit<Product, 'id'>) => http.put<Product>(`/products/${id}`, body).then((r) => r.data),
  remove: (id: number) => http.delete(`/products/${id}`),
};
