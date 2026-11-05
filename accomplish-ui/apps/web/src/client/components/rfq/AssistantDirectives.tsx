import { Button } from '@/components/ui/button';
import type { DisambiguateOption } from '@/lib/chatContract';
import { ConfirmActionCard } from './ConfirmActionCard';
import type { ChatMsg, ConfirmOutcome } from './useAssistantChat';

export interface DirectiveActions {
  onChoose: (msg: ChatMsg, option: DisambiguateOption) => void;
  onOpenPicker: (msgId: string) => void;
  onUpload: (accept: string[]) => void;
  onSettle: (msgId: string, outcome: ConfirmOutcome) => void;
}

/** What the daemon asked the UI to draw under an assistant message. The UI only shows it; the user decides. */
export function Directive({ msg, actions, busy }: { msg: ChatMsg; actions: DirectiveActions; busy: boolean }) {
  const ui = msg.ui;
  if (!ui) return null;
  switch (ui.type) {
    case 'disambiguate':
      return (
        <div className="mt-3 space-y-2">
          <p className="text-sm font-medium text-foreground">{ui.prompt}</p>
          <ul className="flex flex-wrap gap-2" aria-label="Options">
            {ui.options.map((o) => (
              <li key={o.id}>
                <Button
                  size="sm"
                  variant="outline"
                  className="h-auto min-h-8 whitespace-normal py-1.5 text-left"
                  disabled={busy || Boolean(msg.done)}
                  aria-pressed={msg.done === o.label}
                  onClick={() => actions.onChoose(msg, o)}
                >
                  <span className="block">{o.label}</span>
                  {o.detail && <span className="block text-xs font-normal text-muted-foreground">{o.detail}</span>}
                </Button>
              </li>
            ))}
          </ul>
          {msg.done && <p className="text-xs text-muted-foreground">Chosen: {msg.done}</p>}
        </div>
      );
    case 'pick_rfq':
      return (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {msg.done ? (
            <p className="text-xs text-muted-foreground">Scope set: {msg.done}</p>
          ) : (
            <Button size="sm" variant="outline" disabled={busy} onClick={() => actions.onOpenPicker(msg.id)}>Choose RFQs</Button>
          )}
        </div>
      );
    case 'ask_upload':
      return (
        <div className="mt-3 space-y-2">
          <p className="text-xs text-muted-foreground">{ui.purpose}</p>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => actions.onUpload(ui.accept)}>Choose files</Button>
        </div>
      );
    case 'confirm_action':
      return <ConfirmActionCard ui={ui} outcome={msg.confirm} onSettle={(o) => actions.onSettle(msg.id, o)} />;
    default:
      return null;
  }
}
