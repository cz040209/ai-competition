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
  // jsdom implements neither, and both are decoration rather than behaviour.
  Element.prototype.scrollIntoView = vi.fn();
  Element.prototype.scrollTo = vi.fn();
});
