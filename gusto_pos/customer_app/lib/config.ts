/**
 * Required build-time configuration.
 *
 * `NEXT_PUBLIC_*` is inlined by Next at BUILD time, not read at runtime — so a
 * missing value is a build defect that must surface while building, and cannot
 * be repaired by restarting the deployed app. Setting it later needs a rebuild.
 *
 * There are deliberately NO defaults here. Every value below used to carry a
 * hardcoded fallback, and all three pointed at the same dead deployment:
 *
 *   NEXT_PUBLIC_API_URL    || 'https://pos-1st-cut.onrender.com'
 *   NEXT_PUBLIC_OUTLET_ID  || '0b8a8349-…'   (outlet row in that service's DB)
 *   NEXT_PUBLIC_MENU_ID    || '1cde6491-…'
 *
 * The UUIDs are abbreviated on purpose: spelled out in full they invite being
 * pasted back in as a "restored" default.
 *
 * `pos-1st-cut` is a superseded Render service still running mid-July code, and
 * that outlet UUID is a row in ITS database — not production's. So a build
 * where these failed to inline did not merely lose configuration: it silently
 * addressed a real, wrong, abandoned backend, and the IDs made the requests
 * look legitimate to it. A loud failure is strictly better.
 */
function requireEnv(name: string, value: string | undefined): string {
  if (!value) {
    throw new Error(
      `${name} is not set. It is inlined at build time, so set it in the ` +
        `build environment (.env.local for local dev) and rebuild. There is ` +
        `no default backend URL by design.`,
    );
  }
  return value;
}

// The `process.env.NEXT_PUBLIC_API_URL` member expression must stay written out
// in full for Next to substitute it — a destructured or dynamically-keyed read
// is not inlined and would always look unset.
export const API_BASE = requireEnv(
  'NEXT_PUBLIC_API_URL',
  process.env.NEXT_PUBLIC_API_URL,
);

/** Outlet this build serves. Seeds the cart and drives the dev landing page. */
export const OUTLET_ID = requireEnv(
  'NEXT_PUBLIC_OUTLET_ID',
  process.env.NEXT_PUBLIC_OUTLET_ID,
);

/**
 * Menu used by `fetchMenu()` when called with no argument. Note that
 * `fetchMenu` currently has no callers — this is required for consistency
 * rather than because a live path needs it; see the note in lib/api.ts.
 */
export const MENU_ID = requireEnv(
  'NEXT_PUBLIC_MENU_ID',
  process.env.NEXT_PUBLIC_MENU_ID,
);
