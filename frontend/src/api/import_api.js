/**
 * Document Import & Parsing API Endpoints
 */

import { httpClient } from './http_client.js';

export const ImportApi = {
  triggerParse(filenames = []) {
    return httpClient.post('/api/v1/import/parse', { filenames });
  }
};

if (typeof window !== 'undefined') {
  window.ImportApi = ImportApi;
}
