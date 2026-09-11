# Recall Firewall — two-minute walkthrough

Open `http://127.0.0.1:8791/` at 1440×1000 or 1920×1080. The page is a
read-only replay of saved live executions. Click **Next step** between chapters;
the animation reveals recorded evidence, without making a sponsor request.
For a presentation, open `/presentation.html` and use the arrow keys.

| Time | Screen | Narration |
|---|---|---|
| 0:00–0:15 | Overview | “A planning note says retained blend may enter another batch. Recall Firewall preserves that uncertainty while investigating the records and verifying protective actions.” |
| 0:15–0:30 | The source note | “Cognee extracts three proposed links. We retain the original wording and a source pointer. ‘May’ does not become ‘happened.’” |
| 0:30–0:45 | Proposed links | “HydraDB stores those proposals with provenance. A separate process reads them back. The dashed path tells us where to investigate next.” |
| 0:45–1:10 | Two facilities | “A reviewed procedure executes inside RocketRide Cloud. It reads PLANT-A through the gateway, finds a relevant proposed link, and queries PLANT-B. Hotdata returns scoped records and native query IDs. In the no-records variant, Cloud requests coverage and never queries PLANT-B.” |
| 1:10–1:30 | Recorded protection | “This is a separate approved protective hold in a fictional simulator. We read it back, then attempt departure. Departure is blocked. That verifies this hold—not global containment.” |
| 1:30–1:45 | A reusable method | “Rote captures the query and its dependent receipt read-back. The parameterized procedure runs on different inputs, producing fresh receipts. The empty result stays an explicit coverage gap.” |
| 1:45–2:00 | Security checks | “Snyk found an archive dependency issue. We removed that dependency and rescanned. This page reports the actual dependency and source-scan outcomes.” |

Close with: “Five sponsor layers, distinct responsibilities, and receipts for
what actually happened. Unknowns stay visible.”

The working recording uses **deterministic Cloud orchestration**, not an LLM
investigator. The replacement model key passed a separate connectivity check,
but the attempted LLM investigator returned tool errors without receipts.
Do not claim that attempt completed the investigation.

Other boundaries: these are existing fictional facility databases; source
links remain proposed; the hold was a separately recorded simulator test;
the recording combines executed receipts rather than one uninterrupted run.
No performance multiplier, fresh-snapshot acceptance, production readiness or
regulatory certification is claimed.
