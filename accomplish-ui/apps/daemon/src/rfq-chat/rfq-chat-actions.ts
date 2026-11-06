/**
 * SPEC-019 actions (create_rfq, start_pipeline, edit_value). The assistant never writes anything by itself: a propose* call validates
 * and returns a confirmation card; only confirm() with that card's single-use token runs the steps, and every
 * step is audited. Tokens live in memory (a daemon restart voids pending cards, which is the safe direction).
 */
import { log } from '../logger.js';
import type { ActionConfirmRequest, ActionConfirmResponse, ChatActionDeps } from './rfq-chat-contract.js';
import { realActionDeps } from './rfq-chat-actions-deps.js';
import { resolveFiles, resolveParties } from './rfq-chat-actions-parse.js';
import { planStartPipeline, runStartPipeline } from './rfq-chat-actions-pipeline.js';
import { planEditValue, runEditValue } from './rfq-chat-actions-edit.js';
import { runCreateRfq } from './rfq-chat-actions-run.js';
import { chatStagingId, hashParams, type ActionDeps, type CreateRfqParams, type EditValueParams, type StartPipelineParams } from './rfq-chat-actions-types.js';

export const TOKEN_TTL_MS = 5 * 60 * 1000;

/** What "nothing was ..." says for each action when a card is refused or cancelled. */
const NOTHING = { create_rfq: 'created', start_pipeline: 'started', edit_value: 'changed' } as const;

interface Pending {
  sessionKey: string;
  action: keyof typeof NOTHING;
  params: CreateRfqParams | StartPipelineParams | EditValueParams;
  paramHash: string;
  expiresAt: number;
}

/** What the route may forward on top of the frozen contract: the params the card showed, re-verified against the token. */
type ConfirmReq = ActionConfirmRequest & { params?: Record<string, unknown> };
type FileRef = { attachmentId: string; name: string; rfqId?: string };

/** `_src` (key/model) is accepted for wiring symmetry with makeChatDeps: parsing is deterministic, so no model is used. */
export function makeChatActions(
  _src: { getApiKey: (p: string) => string | null; getSelectedModel: () => { provider: string; model: string } | null },
  deps: ActionDeps = realActionDeps(),
): ChatActionDeps {
  const pending = new Map<string, Pending>();

  const audit = async (who: string, action: string, paramHash: string, result: string): Promise<void> => {
    try {
      await deps.appendAudit({ who, when: new Date(deps.now()).toISOString(), action, paramHash, result });
    } catch (err) {
      log.warn(`[RfqChatActions] audit write failed for ${action}: ${err}`);
    }
  };

  const refuse = async (sessionKey: string, hash: string, why: string, action: Pending['action'] = 'create_rfq'): Promise<ActionConfirmResponse> => {
    await audit(sessionKey, 'confirm.refused', hash, why);
    return { ok: false, message: `Refused: ${why}. Nothing was ${NOTHING[action]}.`, steps: [] };
  };

  /** One token per card: single use, bound to the session and to the exact params (hash), valid 5 minutes. */
  const issue = async (sessionKey: string, action: Pending['action'], params: Pending['params'], note: string) => {
    const paramHash = hashParams(params);
    const confirmToken = deps.newToken();
    const expiresAt = deps.now() + TOKEN_TTL_MS;
    for (const [t, p] of pending) {
      if (p.expiresAt <= deps.now()) {
        pending.delete(t);
      }
    }
    pending.set(confirmToken, { sessionKey, action, params: structuredClone(params), paramHash, expiresAt });
    await audit(sessionKey, 'propose', paramHash, note);
    return { confirmToken, expiresAt: new Date(expiresAt).toISOString() };
  };

  return {
    async proposeCreateRfq({ sessionKey, request, fileRefs }) {
      try {
        const files = await resolveFiles(chatStagingId(sessionKey), fileRefs as FileRef[], deps);
        if (files.blocked.length > 0) {
          await audit(sessionKey, 'propose.blocked', '-', files.blocked.join(' | '));
          return { message: `I can't create an RFQ from these files. ${files.blocked.join(' ')}` };
        }
        const parties = await resolveParties(request, deps);
        const missing = [...parties.missing, ...files.missing];
        if (missing.length > 0 || !parties.customer || !parties.project) {
          // The assistant does not carry half an answer to the next message: the reply has to be the whole request again.
          const again = !parties.customer || !parties.project ? ' Reply with the whole request, for example: create an RFQ from these files for customer <customer>, project <project>.' : '';
          return { message: `To create the RFQ I still need this. ${missing.join(' ')}${again}` };
        }
        const params: CreateRfqParams = {
          rfqId: await deps.nextRfqId(),
          customer: parties.customer,
          project: parties.project,
          files: files.files,
          // The modal sends no profile, so the pipeline uses CAM_DEFAULT_PROFILE; the action does the same.
          profile: 'default (CAM_DEFAULT_PROFILE)',
        };
        const card = await issue(sessionKey, 'create_rfq', params, `card issued for ${params.rfqId}`);
        const [bom, vol] = [files.files.find((f) => f.role === 'BOM'), files.files.find((f) => f.role === 'VOLUME')];
        return {
          message: `Ready to create ${params.rfqId}. Check the details and press Confirm; nothing happens until you do.`,
          ui: {
            type: 'confirm_action',
            action: 'create_rfq',
            summary: `Create ${params.rfqId} for ${params.customer.name} / ${params.project.name}, upload BOM ${bom?.name} and Volume ${vol?.name}, then start the pipeline.`,
            params: params as unknown as Record<string, unknown>,
            ...card,
          },
        };
      } catch (err) {
        log.warn(`[RfqChatActions] propose failed: ${err}`);
        return { message: `I can't prepare the RFQ right now (${err instanceof Error ? err.message : String(err)}). Nothing was created.` };
      }
    },

    async proposeStartPipeline({ sessionKey, rfqId }) {
      try {
        const plan = await planStartPipeline(deps, rfqId);
        if (!plan.params || !plan.summary) {
          await audit(sessionKey, 'propose.refused', '-', `${rfqId}: ${plan.message}`);
          return { message: plan.message };
        }
        const card = await issue(sessionKey, 'start_pipeline', plan.params, `card issued to resume ${rfqId}`);
        return {
          message: plan.message,
          ui: { type: 'confirm_action', action: 'start_pipeline', summary: plan.summary, params: plan.params as unknown as Record<string, unknown>, ...card },
        };
      } catch (err) {
        log.warn(`[RfqChatActions] start proposal failed: ${err}`);
        return { message: `I can't check ${rfqId} right now (${err instanceof Error ? err.message : String(err)}). Nothing was started.` };
      }
    },

    async proposeEditValue({ sessionKey, rfqId, target, fieldText, value, volume }) {
      try {
        const plan = await planEditValue(deps, { rfqId, target, fieldText, value, volume });
        if (!plan.params || !plan.summary) {
          await audit(sessionKey, 'propose.refused', '-', `${rfqId}: ${plan.message}`);
          return { message: plan.message };
        }
        const card = await issue(sessionKey, 'edit_value', plan.params, `card issued to edit ${plan.params.field} of ${plan.params.bomItemId} in ${rfqId}`);
        return {
          message: plan.message,
          ui: { type: 'confirm_action', action: 'edit_value', summary: plan.summary, params: plan.params as unknown as Record<string, unknown>, ...card },
        };
      } catch (err) {
        log.warn(`[RfqChatActions] edit proposal failed: ${err}`);
        return { message: `I can't read the costed BOM of ${rfqId} right now (${err instanceof Error ? err.message : String(err)}). Nothing was changed.` };
      }
    },

    async confirm({ sessionKey, req }: { sessionKey: string; req: ConfirmReq }) {
      const p = pending.get(req.confirmToken);
      if (!p) {
        return refuse(sessionKey, '-', 'this confirmation is unknown, already used or expired');
      }
      if (p.sessionKey !== sessionKey) {
        // Not consumed: another session must not be able to burn the owner's card.
        return refuse(sessionKey, p.paramHash, 'this confirmation belongs to another session', p.action);
      }
      pending.delete(req.confirmToken); // single use from here, whatever happens next
      if (deps.now() > p.expiresAt) {
        return refuse(sessionKey, p.paramHash, 'this confirmation expired (valid 5 minutes); ask me again', p.action);
      }
      if (hashParams(p.params) !== p.paramHash || (req.params && hashParams(req.params) !== p.paramHash)) {
        return refuse(sessionKey, p.paramHash, 'the parameters changed after the confirmation was issued', p.action);
      }
      if (req.decision === 'cancel') {
        await audit(sessionKey, 'confirm.cancel', p.paramHash, `cancelled; nothing ${NOTHING[p.action]}`);
        return { ok: true, message: `Cancelled. Nothing was ${NOTHING[p.action]}.`, steps: [] };
      }
      try {
        await deps.appendAudit({ who: sessionKey, when: new Date(deps.now()).toISOString(), action: 'confirm.start', paramHash: p.paramHash, result: p.params.rfqId });
      } catch (err) {
        // No audit trail, no write.
        log.warn(`[RfqChatActions] audit unavailable, ${p.action} refused: ${err}`);
        return { ok: false, message: `Refused: the audit log is not writable, so nothing was ${NOTHING[p.action]}.`, steps: [] };
      }
      const auditStep = (action: string, result: string) => audit(sessionKey, action, p.paramHash, result);
      if (p.action === 'edit_value') {
        return runEditValue(deps, p.params as EditValueParams, auditStep);
      }
      return p.action === 'create_rfq' ? runCreateRfq(deps, p.params as CreateRfqParams, auditStep) : runStartPipeline(deps, p.params as StartPipelineParams, auditStep);
    },
  };
}
