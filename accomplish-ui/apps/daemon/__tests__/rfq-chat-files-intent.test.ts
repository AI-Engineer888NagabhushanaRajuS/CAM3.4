import { describe, expect, it, vi } from 'vitest';
import { filesIntent } from '../src/rfq-chat/rfq-chat-intent.js';
import { chatReply, type ChatServiceDeps } from '../src/rfq-chat/rfq-chat-service.js';
import { attachedNote } from '../src/rfq-chat/rfq-chat-general.js';
import type { ChatActionDeps } from '../src/rfq-chat/rfq-chat-contract.js';
import type { ChatModel } from '../src/rfq-chat/rfq-chat-types.js';

/** SPEC-023: files attached in the chat + "process these" is decided by rules; the model is never asked. */
describe('filesIntent', () => {
  it.each([
    'can u process this files',
    'go select the files and run the process',
    'use these',
    'run it',
    'go',
    'ingest them please',
    'map the bom and upload it',
  ])('"%s" asks to work on the attached files', (q) => expect(filesIntent(q)).toBe(true));

  it.each([
    'how do i process files?', // a how-to goes to the guide
    'process RFQ-00007', // names an RFQ: a control, not the attachments
    'ghgcf',
    'what is the MOQ of this part',
    'read this and tell me the MOQ', // a question about numbers, not a request to ingest
    'check it',
    'do this',
    'use the total from the sheet',
  ])('"%s" does not', (q) => expect(filesIntent(q)).toBe(false));
});

const noModel: ChatModel = { label: 'none', complete: vi.fn(async () => { throw new Error('the model must not be asked'); }) };
const deps = (actions: ChatActionDeps, over: Partial<ChatServiceDeps> = {}): ChatServiceDeps =>
  ({ model: () => noModel, listRfqs: async () => [], actions, sessionKey: 's1', ...over }) as unknown as ChatServiceDeps;
const refs = [{ attachmentId: 'a1', name: 'QCAD.pdf' }, { attachmentId: 'a2', name: 'bom.xlsx' }];

describe('chatReply with attached files', () => {
  it('"can u process this files" goes to create with the files, without asking the model', async () => {
    const proposeCreateRfq = vi.fn(async () => ({ message: 'I can\'t create an RFQ from these files yet. None is the BOM workbook.' }));
    const out = await chatReply({ rfqId: null, fileRefs: refs, messages: [{ role: 'user', content: 'can u process this files' }] }, deps({ proposeCreateRfq, proposeStartPipeline: vi.fn(), proposeEditValue: vi.fn(), confirm: vi.fn() } as unknown as ChatActionDeps));
    expect(proposeCreateRfq).toHaveBeenCalledWith({ sessionKey: 's1', request: 'can u process this files', fileRefs: refs });
    expect(out.message).toContain('None is the BOM workbook');
    expect(noModel.complete).not.toHaveBeenCalled();
  });

  it('a pressed customer button is read together with the earlier request', async () => {
    const proposeCreateRfq = vi.fn(async () => ({ message: 'Ready.' }));
    await chatReply({
      rfqId: null,
      fileRefs: refs,
      messages: [
        { role: 'user', content: 'process these files' },
        { role: 'assistant', content: 'To create the RFQ I still need this. Which customer?' },
        { role: 'user', content: 'customer Acme' },
      ],
    }, deps({ proposeCreateRfq, proposeStartPipeline: vi.fn(), proposeEditValue: vi.fn(), confirm: vi.fn() } as unknown as ChatActionDeps));
    expect(proposeCreateRfq.mock.calls[0][0].request).toBe('process these files\ncustomer Acme');
  });

  it('with one RFQ open the files are not turned into a new RFQ', async () => {
    const proposeCreateRfq = vi.fn(async () => ({ message: 'x' }));
    const complete = vi.fn(async () => ({ text: 'ok', model: 'm' }));
    await chatReply({ rfqId: 'RFQ-00001', fileRefs: refs, messages: [{ role: 'user', content: 'process these files' }] },
      deps({ proposeCreateRfq, proposeStartPipeline: vi.fn(), proposeEditValue: vi.fn(), confirm: vi.fn() } as unknown as ChatActionDeps, { model: () => ({ label: 'm', complete }) as ChatModel, listRfqs: async () => [] }));
    expect(proposeCreateRfq).not.toHaveBeenCalled();
  });

  it('the model is told the attached files exist', () => {
    expect(attachedNote(['a.pdf', 'b.xlsx'])).toContain('attached 2 files (a.pdf, b.xlsx)');
    expect(attachedNote(['a.pdf'])).toContain('Never say the files are missing');
  });
});
