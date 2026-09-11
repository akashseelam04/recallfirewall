// What credentials and credits does the RocketRide account already hold?
// Node providers read LLM keys from server-side account env vars, so a key we
// think we need may already be provisioned. Prints key NAMES only, never values.
import { readFileSync } from "node:fs";
import { RocketRideClient } from "rocketride";

const env = Object.fromEntries(
  readFileSync(new URL("../.env", import.meta.url), "utf8")
    .split("\n")
    .filter((l) => /^[A-Z_]+=/.test(l))
    .map((l) => [l.slice(0, l.indexOf("=")), l.slice(l.indexOf("=") + 1).trim()]),
);

const client = new RocketRideClient({
  auth: env.ROCKETRIDE_APIKEY,
  uri: env.ROCKETRIDE_URI,
  persist: false,
});
await client.login();

async function show(label, fn) {
  try {
    const v = await fn();
    // Redact anything that looks like a secret value.
    const safe = JSON.stringify(v, (k, val) =>
      typeof val === "string" && val.length > 24 && /key|token|secret|auth/i.test(k)
        ? `<redacted ${val.length} chars>`
        : val,
    );
    console.log(`${label}: ${safe?.slice(0, 1200)}`);
  } catch (e) {
    console.log(`${label}: ERROR ${String(e?.message).slice(0, 120)}`);
  }
}

console.log("account surface:", Object.keys(client.account ?? {}).join(", ") || "(none)");
console.log("billing surface:", Object.keys(client.billing ?? {}).join(", ") || "(none)");

await show("environmentKeys", () => client.account.getEnvironmentKeys());
await show("env", () => client.account.getEnv());
await show("profile", () => client.account.getProfile?.());
await show("org", () => client.account.getOrg?.());
await show("credits", () => client.billing.getCredits?.());

await client.disconnect().catch(() => {});
process.exit(0);
