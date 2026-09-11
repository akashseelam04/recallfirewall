#!/usr/bin/env -S rote play run
/**
 * @rote-frontmatter
 * ---
 * name: city_weather
 * description: 'Two-step read-only method: resolve a city to coordinates, then read its current temperature.'
 * provenance:
 *   author: akashseelam04@gmail.com
 * metadata:
 *   rote_version: 0.82.0
 *   version: 0.0.2
 *   status: draft
 *   kind: atomic
 *   flow_type: sequential
 *   execution_model: steps_with_presentation
 *   requires_endpoints:
 *   - adapter/open-meteo
 *   - adapter/open-meteo-geocoding
 *   requires_sessions: true
 * parameters:
 * - name: city
 *   param_type: string
 *   required: true
 *   description: "City name to resolve to coordinates and report on"
 * steps:
 *   searchlocations:
 *     endpoint: adapter/open-meteo-geocoding
 *     method: searchLocations
 *     params:
 *       name: $city
 *       count: '1'
 *   get_v1_forecast:
 *     endpoint: adapter/open-meteo
 *     method: get_v1_forecast
 *     depends_on: [searchlocations]
 *     params:
 *       latitude: '@searchlocations{.results[0].latitude}'
 *       longitude: '@searchlocations{.results[0].longitude}'
 *       current: temperature_2m
 * ---
 */

const presentationSdk = await import("__ROTE_PRESENTATION_SDK__").catch((cause) => {
  throw new Error(
    "This is a rote steps presentation program. Run it with `rote play run <name>`.",
    { cause },
  );
});
const { FlowOutput, loadPresentationContext, stepName } = presentationSdk;

const out = new FlowOutput();
const ctx = await loadPresentationContext();
out.setRunStatus(ctx.run.status);

function body(step: ReturnType<typeof ctx.step>): any {
  const outcome = step.outcome;
  switch (outcome.status) {
    case "completed":
    case "restored":
      return outcome.output.body;
    case "partial":
      return outcome.output.output.body;
    default:
      throw new Error(`step did not complete: ${JSON.stringify(outcome)}`);
  }
}

const place = body(ctx.step(stepName("searchlocations"))).results[0];
const weather = body(ctx.step(stepName("get_v1_forecast")));

const headline =
  `${place.name}, ${place.country_code}: ${weather.current.temperature_2m}` +
  `${weather.current_units.temperature_2m} at ${weather.current.time}`;

out.human(headline);
out.summary(headline);
out.result({
  run_id: ctx.run.run_id,
  status: ctx.run.status,
  complete: ctx.run.status === "succeeded",
  resolved: {
    name: place.name,
    country_code: place.country_code,
    latitude: place.latitude,
    longitude: place.longitude,
  },
  observed_at: weather.current.time,
  temperature: weather.current.temperature_2m,
  unit: weather.current_units.temperature_2m,
});
