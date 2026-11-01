# Private character inspector

Use `/dbinspect text:` or the message-menu **Inspect characters** action. The
existing Discord signature, app identity and current user/channel guards
apply. Only supplied text is inspected; no history, attachment, file or provider
is fetched. Missing message content requires an explicit paste instead.

The private reply counts selected controls and invisible formatting characters,
showing a bounded first-occurrence list with code points and scalar-based line
positions. CRLF is one logical line break. This is a diagnostic for text received
from Discord, not original bytes, rendered columns or proof of malicious intent.
No automatic repair occurs. User text is not echoed in the diagnostic.

The input limit is 4,000 UTF-16 units and 16,000 UTF-8 bytes. Empty text is rejected;
whitespace-only text is useful and accepted. The full input is counted even when
the occurrence list is shortened, and the reply labels that limit explicitly.
The utility reports its selected categories, not every possible confusable or
Unicode difference. A clean result does not establish that text is safe.

Inspection is synchronous and deterministic. It bypasses intake, drafts, private
bookmarks and the persistent interaction replay ledger. Repeated signed requests
recompute the same result without side effects. The existing verifier performs temporary-file signature verification; those
temporary inputs are cleaned up after verification. The utility writes no input
to the persistent replay ledger or a draft.
Discord itself retains the command/message and reply under its own policies.
No claim is made that a local operation can erase Discord or copied content.

Register commands explicitly in Settings after reviewing their definitions. The
two existing commands remain, and the two inspector commands are named upserts.
Actual Discord appearance and user-install behavior require user testing.
