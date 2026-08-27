/**
 * Knowledge Base API Endpoints
 * Includes statistics, document retrieval, and deep index diagnostics
 */

import { httpClient } from './http_client.js';

export const KbApi = {
  getStats() {
    return httpClient.get('/api/v1/stats');
  },

  getIndexesStatus() {
    return httpClient.get('/api/v1/kb/indexes');
  },

  verifyIndexes() {
    return httpClient.post('/api/v1/kb/indexes/verify');
  },

  getDocuments(limit = 500, search = '') {
    return httpClient.get('/api/v1/kb/docs', { limit, search });
  },

  getDocPreview(docId = '', title = '') {
    return httpClient.get('/api/v1/kb/doc/preview', { doc_id: docId, title: title });
  }
};

if (typeof window !== 'undefined') {
  window.KbApi = KbApi;
}
