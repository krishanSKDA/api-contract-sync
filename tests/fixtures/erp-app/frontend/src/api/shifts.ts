import { http } from './http';

export interface Shift {
  id: number;
  employeeId: number;
  openedAt: string;
  closedAt: string | null;
}

export const shiftApi = {
  list: () => http.get<Shift[]>('/shifts').then((r) => r.data),
  get: (id: number) => http.get<Shift>(`/shifts/${id}`).then((r) => r.data),
  create: (body: Omit<Shift, 'id'>) => http.post<Shift>('/shifts', body).then((r) => r.data),
  update: (id: number, body: Omit<Shift, 'id'>) => http.put<Shift>(`/shifts/${id}`, body).then((r) => r.data),
  remove: (id: number) => http.delete(`/shifts/${id}`),
  close: (id: number) => http.post<Shift>(`/shifts/${id}/close`).then((r) => r.data),
};
