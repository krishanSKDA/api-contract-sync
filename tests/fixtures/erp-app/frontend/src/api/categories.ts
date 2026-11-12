import { http } from './http';

export interface Category {
  id: number;
  name: string;
  parentId: number | null;
}

export const categoryApi = {
  list: () => http.get<Category[]>('/categories').then((r) => r.data),
  get: (id: number) => http.get<Category>(`/categories/${id}`).then((r) => r.data),
  create: (body: Omit<Category, 'id'>) => http.post<Category>('/categories', body).then((r) => r.data),
  update: (id: number, body: Omit<Category, 'id'>) => http.put<Category>(`/categories/${id}`, body).then((r) => r.data),
  remove: (id: number) => http.delete(`/categories/${id}`),
};
