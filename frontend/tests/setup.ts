import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Vitest does not expose `afterEach` on the global object unless
// `test.globals: true` is set (it isn't, here), so Testing Library's own
// auto-cleanup -- which feature-detects a global `afterEach` -- never
// registers. Without this, every render from every test in a file stays
// mounted, and later tests can match stale DOM from earlier ones.
afterEach(() => {
  cleanup();
});
