// Ask the live staging server what node providers actually exist, so we build
// the Gate 0 pipeline against reality rather than against the marketing page.
import { readFileSync, writeFileSync } from "node:fs";
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
const services = await client.getServices();
writeFileSync(new URL("services.json", import.meta.url), JSON.stringify(services, null, 2));

const names = Object.keys(services);
console.log(`total services: ${names.length}`);

const interesting = names.filter((n) =>
  /http|rest|api|request|fetch|web|hook|curl|tool|call|custom|script|python|code/i.test(n),
);
console.log(`\nlikely outbound-call nodes:\n  ${interesting.join("\n  ") || "(none matched)"}`);
console.log(`\nall:\n  ${names.join("\n  ")}`);

await client.disconnect().catch(() => {});
process.exit(0);
