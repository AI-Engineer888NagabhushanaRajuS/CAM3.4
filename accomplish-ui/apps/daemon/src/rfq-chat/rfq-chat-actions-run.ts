/**
 * The write steps of the Create-RFQ action, in order: create_rfq -> fetch_files -> scan_files -> upload_files ->
 * start_pipeline. A failure stops the run, names the step, and removes what this run created, unless removing could
 * destroy a live RFQ (unknown upload outcome, pipeline not started): then the message says exactly what exists.
 */
import type { ActionConfirmResponse } from './rfq-chat-contract.js';
import { UnknownOutcomeError, sha12, type ActionDeps, type CreateRfqParams } from './rfq-chat-actions-types.js';

type Step = ActionConfirmResponse['steps'][number];
type Bytes = { name: string; bytes: Uint8Array };

class StepFailure extends Error {
  constructor(readonly step: string, readonly cause2: unknown) {
    super(cause2 instanceof Error ? cause2.message : String(cause2));
  }
}

export async function runCreateRfq(
  deps: ActionDeps,
  p: CreateRfqParams,
  audit: (action: string, result: string) => Promise<void>,
): Promise<ActionConfirmResponse> {
  const steps: Step[] = [];
  const bom = p.files.find((f) => f.role === 'BOM');
  const vol = p.files.find((f) => f.role === 'VOLUME');
  let created = false;
  const released: string[] = [];
  const data: Record<string, Bytes> = {};

  const step = async (name: string, fn: () => Promise<string | void>): Promise<void> => {
    try {
      const detail = (await fn()) || undefined;
      steps.push({ step: name, status: 'done', detail });
      await audit(`create_rfq.${name}`, `done${detail ? `: ${detail}` : ''}`);
    } catch (err) {
      steps.push({ step: name, status: 'failed', detail: err instanceof Error ? err.message : String(err) });
      await audit(`create_rfq.${name}`, `failed: ${err instanceof Error ? err.message : String(err)}`);
      throw new StepFailure(name, err);
    }
  };

  try {
    if (!bom || !vol) {
      throw new StepFailure('create_rfq', new Error('the parameters hold no BOM and Volume file'));
    }
    await step('create_rfq', async () => {
      await deps.createRfq({ rfqId: p.rfqId, customerId: p.customer.id, projectId: p.project.id });
      created = true;
      return p.rfqId;
    });
    await step('fetch_files', async () => {
      for (const f of [bom, vol]) {
        const bytes = await deps.readAttachment(f.sourceScope, f.attachmentId);
        // The attachment id is the file's sha256 prefix: a different digest means the stored file is not what was scanned.
        if (sha12(bytes) !== f.attachmentId) {
          throw new Error(`${f.name} does not match the scanned file (checksum mismatch)`);
        }
        data[f.role] = { name: f.name, bytes };
      }
    });
    await step('scan_files', async () => {
      const verdicts = await deps.scanFiles(p.rfqId, [data.BOM, data.VOLUME]);
      for (const v of verdicts) {
        if (v.attachmentId) {
          released.push(v.attachmentId);
        }
      }
      const bad = verdicts.filter((v) => v.decision !== 'released' || !v.attachmentId);
      if (bad.length > 0 || verdicts.length !== 2) {
        throw new Error(`${bad.map((v) => `${v.name} was ${v.decision}`).join('; ') || 'the scan returned no verdict'}; nothing is uploaded`);
      }
      const now = new Set((await deps.listAttachments(p.rfqId)).map((a) => a.attachmentId));
      if (!released.every((id) => now.has(id))) {
        throw new Error('the files are not listed as released under the new RFQ id');
      }
      return 'both engines released both files';
    });
    let pipelineStatus = '';
    await step('upload_files', async () => {
      pipelineStatus = (await deps.upload(p.rfqId, data.BOM, data.VOLUME)).pipelineStatus;
    });
    await step('start_pipeline', async () => {
      if (pipelineStatus !== 'TRIGGERED') {
        throw new Error(`the pipeline status is ${pipelineStatus || 'unknown'}`);
      }
      return pipelineStatus;
    });
    return {
      ok: true,
      rfqId: p.rfqId,
      message: `Created ${p.rfqId} for ${p.customer.name} / ${p.project.name}: BOM ${bom.name} and Volume ${vol.name} uploaded, pipeline started. Follow it in the RFQ list.`,
      steps,
    };
  } catch (err) {
    const failed = err instanceof StepFailure ? err : new StepFailure('create_rfq', err);
    const head = `Stopped at ${failed.step}: ${failed.message}.`;
    if (!created) {
      return { ok: false, message: `${head} Nothing was created.`, steps };
    }
    if (failed.step === 'start_pipeline') {
      return { ok: false, rfqId: p.rfqId, message: `${head} ${p.rfqId} exists with both files uploaded; open it in the RFQ list and press Continue to start the pipeline.`, steps };
    }
    if (failed.cause2 instanceof UnknownOutcomeError) {
      return { ok: false, rfqId: p.rfqId, message: `${head} The server may have finished the upload, so I did not delete anything: ${p.rfqId} exists and its files and pipeline may exist too. Check the RFQ list before asking again.`, steps };
    }
    try {
      for (const id of released) {
        await deps.deleteAttachment(p.rfqId, id);
      }
      await deps.deleteRfqRows(p.rfqId);
      steps.push({ step: 'rollback', status: 'done', detail: `${p.rfqId} removed` });
      await audit('create_rfq.rollback', `done: ${p.rfqId} removed`);
      const stray = failed.step === 'upload_files' ? ' Copies of the uploaded files may remain in the intake folder, unreferenced.' : '';
      return { ok: false, message: `${head} ${p.rfqId} was removed again; nothing is left in the RFQ list.${stray}`, steps };
    } catch (rbErr) {
      const why = rbErr instanceof Error ? rbErr.message : String(rbErr);
      steps.push({ step: 'rollback', status: 'failed', detail: why });
      await audit('create_rfq.rollback', `failed: ${why}`);
      return { ok: false, rfqId: p.rfqId, message: `${head} Removing it failed (${why}), so ${p.rfqId} still exists in the RFQ list and needs to be deleted by hand.`, steps };
    }
  }
}
