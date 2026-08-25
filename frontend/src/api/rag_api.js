/**
 * RAG Core API Endpoints
 */

import { httpClient } from './http_client.js';

export const RagApi = {
  checkHealth() {
    return httpClient.get('/api/v1/health');
  },

  ask(question, topK = 5) {
    return httpClient.post('/api/v1/ask', {
      question: question.trim(),
      top_k: topK
    });
  },

  retrieve(question, topK = 5) {
    return httpClient.post('/api/v1/retrieve', {
      question: question.trim(),
      top_k: topK
    });
  }
};

if (typeof window !== 'undefined') {
  window.RagApi = RagApi;
}
