/**
 * Standardized HTTP Client Layer for RegTrust-RAG Frontend
 */

export class HttpClient {
  constructor(baseURL = '') {
    this.baseURL = baseURL || this.getDefaultBaseURL();
    this.timeoutMs = 60000; // 60s for LLM/RAG responses
  }

  getDefaultBaseURL() {
    if (typeof window !== 'undefined' && window.location && window.location.protocol.startsWith('http')) {
      const port = window.location.port;
      // If frontend is running on a static dev server (e.g. 8080, 5173, 3000), backend is on 8000
      if (port && port !== '8000') {
        return `${window.location.protocol}//${window.location.hostname}:8000`;
      }
      return window.location.origin;
    }
    return 'http://127.0.0.1:8000';
  }

  setBaseURL(url) {
    this.baseURL = url.replace(/\/+$/, '');
  }

  async request(endpoint, options = {}) {
    const url = endpoint.startsWith('http') ? endpoint : `${this.baseURL}${endpoint.startsWith('/') ? '' : '/'}${endpoint}`;
    const headers = {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...(options.headers || {})
    };

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), options.timeout || this.timeoutMs);

    try {
      const response = await fetch(url, {
        ...options,
        headers,
        signal: controller.signal
      });
      clearTimeout(timeoutId);

      const isJson = response.headers.get('content-type')?.includes('application/json');
      const data = isJson ? await response.json() : await response.text();

      if (!response.ok) {
        const error = new Error(data?.detail?.message || data?.detail || response.statusText || 'Request failed');
        error.status = response.status;
        error.data = data;
        throw error;
      }

      return data;
    } catch (err) {
      clearTimeout(timeoutId);
      if (err.name === 'AbortError') {
        throw new Error(`请求超时（超过 ${this.timeoutMs / 1000} 秒），请检查后端服务`);
      }
      throw err;
    }
  }

  get(endpoint, params = {}, options = {}) {
    let queryStr = '';
    if (params && Object.keys(params).length > 0) {
      const sp = new URLSearchParams();
      Object.entries(params).forEach(([k, v]) => {
        if (v !== undefined && v !== null && v !== '') {
          sp.append(k, String(v));
        }
      });
      const qs = sp.toString();
      if (qs) queryStr = `?${qs}`;
    }
    return this.request(`${endpoint}${queryStr}`, { method: 'GET', ...options });
  }

  post(endpoint, body = {}, options = {}) {
    return this.request(endpoint, {
      method: 'POST',
      body: JSON.stringify(body),
      ...options
    });
  }

  delete(endpoint, options = {}) {
    return this.request(endpoint, { method: 'DELETE', ...options });
  }
}

export const httpClient = new HttpClient();

if (typeof window !== 'undefined') {
  window.HttpClient = HttpClient;
  window.httpClient = httpClient;
}
