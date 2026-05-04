import axios, { AxiosError, type AxiosInstance } from "axios";
import { useAuthStore } from "@/stores/auth";

export const api: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE ?? "/api",
  timeout: 30000,
});

api.interceptors.request.use((config) => {
  const token = useAuthStore().token;
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (resp) => resp,
  (err: AxiosError) => {
    if (err.response?.status === 401) {
      useAuthStore().logout();
      window.location.href = "/login";
    }
    return Promise.reject(err);
  },
);

export default api;
