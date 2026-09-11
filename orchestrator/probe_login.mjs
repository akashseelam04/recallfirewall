// Which RocketRide host does our key actually authenticate against?
// The checklist says staging, the docs say cloud, the extension defaults to api.
// Ask the servers instead of guessing. Never prints the key.
import { readFileSync } from "node:fs";
import { RocketRideClient } from "rocketride";

const env = Object.fromEntries(
  readFileSync(new URL("../.env", import.meta.url), "utf8")
    .split("\n")
    .filter((l) => /^[A-Z_]+=/.test(l))
    .map((l) => [l.slice(0, l.indexOf("=")), l.slice(l.indexOf("=") + 1).trim()]),
);

const auth = env.ROCKETRIDE_APIKEY;
if (!auth) throw new Error("ROCKETRIDE_APIKEY is empty in .env");

const candidates = [
  "https://staging.rocketride.ai",
  "https://cloud.rocketride.ai",
  "https://api.rocketride.ai",
];

for (const uri of candidates) {
  const client = new RocketRideClient({ auth, uri, persist: false });
  try {
    const result = await Promise.race([
      client.login(),
      new Promise((_, rej) => setTimeout(() => rej(new Error("timeout 20s")), 20000)),
    ]);
    console.log(`\nOK  ${uri}`);
    console.log(`    user   : ${result?.email ?? result?.displayName ?? "?"}`);
    console.log(`    orgs   : ${JSON.stringify(result?.organizations ?? [])}`);
    console.log(`    apps   : ${(result?.apps ?? []).map((a) => a.id).join(", ") || "none"}`);
    await client.disconnect().catch(() => {});
  } catch (err) {
    console.log(`\nFAIL ${uri}`);
    console.log(`    ${err?.constructor?.name}: ${String(err?.message).slice(0, 160)}`);
    await client.disconnect().catch(() => {});
  }
}
process.exit(0);
