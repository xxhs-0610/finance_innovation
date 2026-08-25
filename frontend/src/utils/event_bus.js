/**
 * Frontend Utilities - Lightweight Event Bus (Pub/Sub)
 */

export class EventBus {
  constructor() {
    this.listeners = new Map();
  }

  on(event, callback) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    this.listeners.get(event).add(callback);
    return () => this.off(event, callback);
  }

  off(event, callback) {
    if (this.listeners.has(event)) {
      this.listeners.get(event).delete(callback);
    }
  }

  emit(event, data) {
    if (this.listeners.has(event)) {
      this.listeners.get(event).forEach((cb) => {
        try {
          cb(data);
        } catch (err) {
          console.error(`[EventBus] Error in handler for event '${event}':`, err);
        }
      });
    }
  }
}

export const globalEventBus = new EventBus();

if (typeof window !== 'undefined') {
  window.EventBus = EventBus;
  window.globalEventBus = globalEventBus;
}
