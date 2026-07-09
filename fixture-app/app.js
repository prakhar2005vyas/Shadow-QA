/*
  Fixture App JavaScript — app.js
  
  BUGS SEEDED IN THIS FILE:
    #1  handleSubmit is referenced from index.html but NEVER defined here
        → clicking #submit-btn throws: ReferenceError: handleSubmit is not defined
  
  What IS defined:
    - loadMoreFeatures() — but it's never called (the button is disabled, bug #5)
    - logPageView()      — a benign analytics stub (no bugs)
*/

// ---------------------------------------------------------------------------
// BUG #1: handleSubmit() is intentionally NOT defined.
// The button in index.html has onclick="handleSubmit()" which will throw
// ReferenceError: handleSubmit is not defined
// ---------------------------------------------------------------------------
// (no handleSubmit function here — that's the bug)


/*
  BUG #5 (broken_interaction): loadMoreNoOp() is intentionally a silent no-op.
  The button looks fully enabled — same colour, cursor:pointer, no disabled attribute.
  Clicking it calls this function, which does nothing. No error, no feedback,
  no state change. A user clicking repeatedly has no idea why nothing happens.
*/
function loadMoreNoOp() {
  // Intentionally empty — this is bug #5.
  // A real implementation would fetch the next page of results here.
}


// ---------------------------------------------------------------------------
// Benign page analytics stub — no bugs here.
// ---------------------------------------------------------------------------
function logPageView() {
  // In a real app this would call an analytics endpoint.
  // In this fixture it does nothing — just confirms JS loads without error.
  console.info('[AcmeCorp] Page viewed:', document.title);
}

document.addEventListener('DOMContentLoaded', function () {
  logPageView();

  // Demonstrate that console.error fires (agents with console listeners will see this)
  // This simulates a common "we left a debug warning in prod" scenario.
  console.warn('[AcmeCorp] Warning: running in development mode. Remove before production.');
});
