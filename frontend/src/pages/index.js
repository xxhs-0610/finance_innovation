/**
 * Page Views Module Registry
 */
export { ChatPage } from './chat_page.js';

export class ImportPage {
  static render() {
    return document.getElementById('view-import');
  }
}

export class KBPage {
  static render() {
    return document.getElementById('view-kb');
  }
}

export class EvidencePage {
  static render() {
    return document.getElementById('view-evidence');
  }
}

export class PipelinePage {
  static render() {
    return document.getElementById('view-pipeline');
  }
}
