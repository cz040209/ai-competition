import "@testing-library/jest-dom/vitest";

class ImmediateIntersectionObserver {
  constructor(_: IntersectionObserverCallback) {}

  observe(_: Element) {}

  unobserve() {}

  disconnect() {}

  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }
}

beforeEach(() => {
  vi.stubGlobal("IntersectionObserver", ImmediateIntersectionObserver);
});
