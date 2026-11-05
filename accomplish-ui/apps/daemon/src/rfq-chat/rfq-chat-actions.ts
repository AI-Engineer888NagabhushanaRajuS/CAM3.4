/**
 * SPEC-019 Create-RFQ action. The assistant never writes anything by itself: proposeCreateRfq validates and returns a
 * confirmation card; only confirm() with that card's single-use token runs createRfq -> files -> pipeline, and every
 * step is audited. Tokens live in memory (a daemon restart voids pending cards, which is the safe direction).
 */
import { log } from '../logger.js';
import type { ActionConfirmRequest, ActionConfirmResponse, ChatActionDeps } from './rfq-chat-contract.js';
import { realActionDeps } from './rfq-chat-actions-deps.js';
import { resolveFiles, resolveParties } from './rfq-chat-actions-parse.js';
import { runCreateRfq } from './rfq-chat-actions-run.js';
import { chatStagingId, hashParams, type ActionDeps, type CreateRfqParams } from './rfq-chat-actions-types.js';

export const TOKEN_TTL_MS = 5 * 60 * 1000;

interface Pending {
  sessionKey: string;
  params: CreateRfqParams;
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

  const refuse = async (sessionKey: string, hash: string, why: string): Promise<ActionConfirmResponse> => {
    await audit(sessionKey, 'confirm.refused', hash, why);
    return { ok: false, message: `Refused: ${why}. Nothing was created.`, steps: [] };
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
          return { message: `To create the RFQ I still need this. ${missing.join(' ')}` };
        }
        const params: CreateRfqParams = {
          rfqId: await deps.nextRfqId(),
          customer: parties.customer,
          project: parties.project,
          files: files.files,
          // The modal sends no profile, so the pipeline uses CAM_DEFAULT_PROFILE; the action does the same.
          profile: 'default (CAM_DEFAULT_PROFILE)',
        };
        const paramHash = hashParams(params);
        const confirmToken = deps.newToken();
        const expiresAt = deps.now() + TOKEN_TTL_MS;
        for (const [t, p] of pending) {
          if (p.expiresAt <= deps.now()) {
            pending.delete(t);
          }
        }
        pending.set(confirmToken, { sessionKey, params: structuredClone(params), paramHash, expiresAt });
        await audit(sessionKey, 'propose', paramHash, `card issued for ${params.rfqId}`);
        const [bom, vol] = [files.files.find((f) => f.role === 'BOM'), files.files.find((f) => f.role === 'VOLUME')];
        return {
          message: `Ready to create ${params.rfqId}. Check the details and press Confirm; nothing happens until you do.`,
          ui: {
            type: 'confirm_action',
            action: 'create_rfq',
            summary: `Create ${params.rfqId} for ${params.customer.name} / ${params.project.name}, upload BOM ${bom?.name} and Volume ${vol?.name}, then start the pipeline.`,
            params: params as unknown as Record<string, unknown>,
            confirmToken,
            expiresAt: new Date(expiresAt).toISOString(),
          },
        };
      } catch (err) {
        log.warn(`[RfqChatActions] propose failed: ${err}`);
        return { message: `I can't prepare the RFQ right now (${err instanceof Error ? err.message : String(err)}). Nothing was created.` };
      }
    },

    async confirm({ sessionKey, req }: { sessionKey: string; req: ConfirmReq }) {
      const p = pending.get(req.confirmToken);
      if (!p) {
        return refuse(sessionKey, '-', 'this confirmation is unknown, already used or expired');
      }
      if (p.sessionKey !== sessionKey) {
        // Not consumed: another session must not be able to burn the owner's card.
        return refuse(sessionKey, p.paramHash, 'this confirmation belongs to another session');
      }
      pending.delete(req.confirmToken); // single use from here, whatever happens next
      if (deps.now() > p.expiresAt) {
        return refuse(sessionKey, p.paramHash, 'this confirmation expired (valid 5 minutes); ask me again');
      }
      if (hashParams(p.params) !== p.paramHash || (req.params && hashParams(req.params) !== p.paramHash)) {
        return refuse(sessionKey, p.paramHash, 'the parameters changed after the confirmation was issued');
      }
      if (req.decision === 'cancel') {
        await audit(sessionKey, 'confirm.cancel', p.paramHash, 'cancelled; nothing created');
        return { ok: true, message: 'Cancelled. Nothing was created.', steps: [] };
      }
      try {
        await deps.appendAudit({ who: sessionKey, when: new Date(deps.now()).toISOString(), action: 'confirm.start', paramHash: p.paramHash, result: p.params.rfqId });
      } catch (err) {
        // No audit trail, no write.
        log.warn(`[RfqChatActions] audit unavailable, create refused: ${err}`);
        return { ok: false, message: 'Refused: the audit log is not writable, so nothing was created.', steps: [] };
      }
      return runCreateRfq(deps, p.params, (action, result) => audit(sessionKey, action, p.paramHash, result));
    },
  };
}
