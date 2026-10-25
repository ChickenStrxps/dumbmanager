"""Owner-only configuration/session operations; never exported to model tools."""
from ..registry import boolean, capability, integer, string


def definitions():
    provider = {'provider': string('Integration ID returned by ai.integrations.list.', maxLength=80)}
    session = {'session_id': string(maxLength=100)}
    rows = [
        ('ai.integrations.list', 'Read integration settings and actual test receipts, without credentials.', {}, (), False),
        ('ai.integrations.configure', 'Save one independently versioned integration. No network request. An empty credential preserves the saved key.',
         {**provider, 'expected_version': integer(0, 0, 1_000_000), 'config': string('JSON: enabled, model, allowed_capabilities, settings.', maxLength=24000),
          'credential': string(default='', maxLength=2000), 'clear_credential': boolean()}, ('provider', 'config', 'expected_version'), True),
        ('ai.integrations.test', 'Explicit provider provisioning probe, or local MCP readiness check. Does not claim audio/Dots success.', provider, ('provider',), True),
        ('ai.integrations.issue_token', 'Rotate a scoped MCP HTTP bearer token. Shown once; old token is revoked.', provider, ('provider',), True),
        ('ai.sessions.start', 'Provision a short-lived direct browser voice session. Only granted tools are available.',
         {**provider, 'project': string(default='', maxLength=100)}, ('provider',), True),
        ('ai.sessions.touch', 'Record browser-observed connection state; this is not a server-verified audio test.',
         {**session, 'state': string(enum=['connected', 'error', 'closed'])}, ('session_id', 'state'), True),
        ('ai.sessions.tool', 'Run a permitted read or request review of a permitted action. Model arguments cannot approve actions.',
         {**session, 'name': string(maxLength=80), 'arguments': string(default='{}', maxLength=24000),
          'call_id': string(maxLength=100)}, ('session_id', 'name', 'call_id'), True),
        ('ai.approvals.list', 'Read pending exact tool actions for owner review.', {}, (), False),
        ('ai.approvals.get', 'Read one durable tool approval receipt without dispatching it.', {'id': string(maxLength=100)}, ('id',), False),
        ('ai.approvals.decide', 'Owner approves or declines one exact stored action. Single dispatch; uncertain failures are not retried.',
         {'id': string(maxLength=100), 'approve': boolean()}, ('id', 'approve'), True),
    ]
    return [{**capability(name, 'dumbapi', description, args, required, tags=('ai', 'integrations', 'voice', 'mcp')),
             'mode': 'action' if write else 'read', 'ai_exposable': False} for name, description, args, required, write in rows]
