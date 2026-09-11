#!/usr/bin/env -S rote play run
/**
 * @rote-frontmatter
 * ---
 * name: facility_query
 * description: 'Read fresh facility consumption through the scoped gateway and independently read back its receipt. No approvals or affected-lot lists are reused.'
 * provenance:
 *   author: akashseelam04@gmail.com
 * metadata:
 *   rote_version: 0.82.0
 *   version: 0.0.1
 *   status: draft
 *   kind: atomic
 *   flow_type: sequential
 *   execution_model: steps_with_presentation
 *   requires_endpoints: []
 *   requires_sessions: false
 *   exploration_model: null
 * parameters:
 * - name: root
 *   param_type: string
 *   required: true
 *   description: Absolute Recall Firewall project directory
 * - name: facility
 *   param_type: string
 *   required: true
 *   description: Facility assigned to this replay, PLANT-A or PLANT-B
 * - name: ingredient
 *   param_type: string
 *   required: true
 *   description: Ingredient to query from fresh source records
 * steps:
 *   python:
 *     type: process.exec
 *     argv:
 *     - $root/.venv/bin/python
 *     - $root/probes/facility_query.py
 *     - consumption
 *     - --facility
 *     - $facility
 *     - --ingredient
 *     - $ingredient
 *     timeout_ms: 90000
 *   python_2:
 *     type: process.exec
 *     argv:
 *     - $root/.venv/bin/python
 *     - $root/probes/facility_query.py
 *     - receipt
 *     - --facility
 *     - $facility
 *     - --receipt-id
 *     - '@python{.stdout.text | fromjson | .receipt_id}'
 *     timeout_ms: 90000
 *     depends_on:
 *     - python
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

const renderedSteps: Record<string, unknown> = {};

// Takes the step handle (not the name) so every `stepName("...")` at the
// call sites stays a literal that lint can verify against `steps:`.
function renderStep(step: ReturnType<typeof ctx.step>): unknown {
  switch (step.outcome.status) {
    case "completed":
      return step.outcome.output.body;
    case "restored": {
      const source = step.outcome.output.source;
      if (source?.status === "partial") {
        return {
          status: "partial",
          body: step.outcome.output.body,
          diagnostics: source.diagnostics,
          additional_diagnostics: source.additional_diagnostics,
        };
      }
      // A clean restored step completed in an earlier run, so it reads like one.
      return step.outcome.output.body;
    }
    case "partial":
      return {
        status: "partial",
        body: step.outcome.output.output.body,
        diagnostics: step.outcome.output.diagnostics,
      };
    case "skipped":
      return { status: "skipped", reason: step.outcome.output.reason };
    case "failed":
      return { status: "failed", message: step.outcome.output.message };
    case "blocked":
      return {
        status: "blocked",
        reason: step.outcome.output.reason,
        blocked_by: step.outcome.output.blocked_by ?? [],
      };
    default:
      // Unreachable while this body matches the SDK. A play exported before a new
      // outcome status was added lands here instead, so name the remedy.
      throw new Error(
        `unsupported step outcome: ${JSON.stringify(step.outcome)}. ` +
          `Re-export the play to regenerate this switch.`,
      );
  }
}
renderedSteps["python"] = renderStep(ctx.step(stepName("python")));
renderedSteps["python_2"] = renderStep(ctx.step(stepName("python_2")));

let finding: any = null;
let readBack: any = null;
if (ctx.run.status === "succeeded") {
  const queryBody = renderedSteps["python"] as {stdout: {text: string}};
  const receiptBody = renderedSteps["python_2"] as {stdout: {text: string}};
  finding = JSON.parse(queryBody.stdout.text);
  readBack = JSON.parse(receiptBody.stdout.text);
  if (finding.receipt_id !== readBack.receipt_id ||
      finding.result_sha256 !== readBack.result_sha256 ||
      finding.query_run_id !== readBack.query_run_id ||
      readBack.current_status !== "CURRENT") {
    throw new Error("Fresh query and independent receipt read-back do not match");
  }
}

const headlinePrefix = (() => {
  switch (ctx.run.status) {
    case "succeeded":
      return "";
    case "partial":
      return "INCOMPLETE: ";
    case "failed":
      return "FAILED: ";
  }
})();
out.human(`${headlinePrefix}Rendered ${Object.keys(renderedSteps).length} step(s).`);
out.summary(`${headlinePrefix}Rendered ${Object.keys(renderedSteps).length} step(s).`);
out.result({
  run_id: ctx.run.run_id,
  status: ctx.run.status,
  complete: ctx.run.status === "succeeded",
  finding,
  receipt_verified: readBack !== null,
  steps: renderedSteps,
});
