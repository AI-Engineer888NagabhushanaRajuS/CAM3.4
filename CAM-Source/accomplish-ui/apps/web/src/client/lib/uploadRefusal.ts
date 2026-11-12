/** SPEC-023: what to tell the user when the upload service refuses a file. The pre-flight (422 `input_invalid`) names the cells that would be NaN / error
 * in the output; 422 `quotewin_mismatch` says the QuoteWin file knows none of the BOM's parts. Anything else is left to the caller (null). */
type Detail = { code?: string; message?: string; issues?: Array<{ sheet: string | null; col: string | null; row: number | null; message: string }> };

export async function serverMessage(response: Response): Promise<string | null> {
  const body = (await response.json().catch(() => null)) as { detail?: Detail | string } | null;
  const d = body && typeof body.detail === 'object' ? body.detail : undefined;
  if (d?.code === 'input_invalid') {
    const first = (d.issues ?? []).slice(0, 3).map((i) => `${i.sheet ?? ''} ${i.col ?? ''}${i.row ?? ''}: ${i.message}`).join(' ');
    return `${d.message} First: ${first} Attach the file with the paperclip in the assistant to fix these cells there.`;
  }
  if (d?.code === 'quotewin_mismatch') {
    return d.message ?? null;
  }
  return null;
}

export async function refusalMessage(response: Response): Promise<string> {
  return (await serverMessage(response)) ?? `Server rejected the BOM upload (status ${response.status}).`;
}
