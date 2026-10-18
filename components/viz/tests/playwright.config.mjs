// The renderer journey (journey.spec.mjs): Chromium, every host routed inside the test.
export default {
  testDir: ".",
  testMatch: "journey.spec.mjs",
  timeout: 60000,
  workers: 2,
  use: { browserName: "chromium" }
};
