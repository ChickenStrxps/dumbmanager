"""Official wire contracts, isolated from DumbAPI domain operations (stdlib only)."""
import json
import socket
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ..common import APIError


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def post_json(url, headers, body):
    """Only adapters choose URLs. Never surface remote bodies, headers or credentials."""
    request = Request(url, json.dumps(body).encode(), {'Content-Type': 'application/json', **headers}, method='POST')
    try:
        with build_opener(NoRedirect()).open(request, timeout=12) as response:
            raw = response.read(131073)
        if len(raw) > 131072:
            raise ValueError()
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except HTTPError as exc:
        code = exc.code
        retry = exc.headers.get('Retry-After', '')
        exc.close()
        error = APIError({401: 'The provider rejected the credential.', 403: 'This account does not have access.',
                          404: 'The configured model or API is unavailable.', 429: 'The provider is rate limited.'}.get(
                              code, 'The provider could not provision a session.'),
                         'provider_rate_limited' if code == 429 else 'provider_unavailable', 429 if code == 429 else 503)
        if retry.isdigit():
            error.retry_after_ms = min(int(retry), 3600) * 1000
        raise error from None
    except (URLError, OSError, socket.timeout):
        raise APIError('The provider could not be reached. Check the connection and try again.', 'provider_unavailable', 503) from None
    except (ValueError, UnicodeError):
        raise APIError('The provider returned an unexpected session response.', 'provider_protocol', 502) from None


class OpenAIRealtime:
    id = 'openai_realtime'
    label = 'OpenAI GPT-Realtime 2.1'
    kind = 'voice'
    default_model = 'gpt-realtime-2.1'
    defaults = {'voice': 'marin', 'instructions': '', 'minutes': 15}
    voices = ('marin', 'cedar', 'alloy', 'ash', 'ballad', 'coral', 'echo', 'sage', 'shimmer', 'verse')
    docs = 'https://developers.openai.com/api/docs/guides/realtime-webrtc'
    requirements = 'An OpenAI API key with access to the selected Realtime model. API billing is separate from ChatGPT/Codex plans.'

    def bootstrap(self, key, model, settings, tools, instructions):
        session = {'type': 'realtime', 'model': model, 'instructions': instructions,
                   'audio': {'input': {'turn_detection': {'type': 'server_vad', 'interrupt_response': True}},
                             'output': {'voice': settings['voice']}},
                   'tools': [{'type': 'function', **tool} for tool in tools], 'tool_choice': 'auto'}
        data = post_json('https://api.openai.com/v1/realtime/client_secrets', {'Authorization': 'Bearer ' + key},
                         {'expires_after': {'anchor': 'created_at', 'seconds': 60}, 'session': session})
        if not isinstance(data.get('value'), str) or not data['value']:
            raise APIError('OpenAI did not return a client secret.', 'provider_protocol', 502)
        return {'transport': 'webrtc', 'client_secret': data['value'], 'expires_at': data.get('expires_at'),
                'endpoint': 'https://api.openai.com/v1/realtime/calls'}


class GeminiLive:
    id = 'gemini_live'
    label = 'Google Gemini Live'
    kind = 'voice'
    default_model = 'gemini-3.8-live'
    defaults = {'voice': 'Kore', 'instructions': '', 'minutes': 15}
    voices = ('Kore', 'Aoede', 'Puck', 'Charon', 'Fenrir', 'Leda', 'Orus', 'Zephyr')
    docs = 'https://ai.google.dev/gemini-api/docs/live'
    requirements = 'A Gemini API key with Live API access. Audio uses Google’s direct WebSocket connection.'

    def bootstrap(self, key, model, settings, tools, instructions):
        setup = {'model': 'models/' + model.removeprefix('models/'),
                 'generationConfig': {'responseModalities': ['AUDIO'],
                                      'speechConfig': {'voiceConfig': {'prebuiltVoiceConfig': {'voiceName': settings['voice']}}}},
                 'systemInstruction': {'parts': [{'text': instructions}]},
                 'tools': [{'functionDeclarations': [{'name': t['name'], 'description': t['description'],
                                                      'parametersJsonSchema': t['parameters'], 'behavior': 'NON_BLOCKING'} for t in tools]}],
                 'inputAudioTranscription': {}, 'outputAudioTranscription': {},
                 'realtimeInputConfig': {'automaticActivityDetection': {},
                                        'activityHandling': 'START_OF_ACTIVITY_INTERRUPTS'}}
        clock = datetime.now(timezone.utc)
        body = {'uses': 1, 'expireTime': (clock + timedelta(minutes=settings['minutes'])).isoformat(),
                'newSessionExpireTime': (clock + timedelta(seconds=60)).isoformat(),
                'bidiGenerateContentSetup': setup}
        data = post_json('https://generativelanguage.googleapis.com/v1beta/auth_tokens', {'x-goog-api-key': key}, body)
        if not isinstance(data.get('name'), str) or not data['name']:
            raise APIError('Gemini did not return an ephemeral token.', 'provider_protocol', 502)
        return {'transport': 'websocket', 'client_secret': data['name'], 'expires_at': body['expireTime'], 'setup': setup,
                'endpoint': 'wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContentConstrained'}


class MCPClient:
    id = 'mcp'
    label = 'MCP clients'
    kind = 'mcp'
    default_model = ''
    defaults = {'instructions': ''}
    voices = ()
    docs = ''
    requirements = 'Connect a local stdio client, an authenticated loopback HTTP client, or a supported private MCP tunnel.'


class Dots(MCPClient):
    id = 'dots'
    label = 'OpenAI Dots'
    docs = 'https://learn.chatgpt.com/docs/dots/getting-started'
    requirements = ('Requires Dots/workspace access and a custom MCP plugin. OpenAI Secure MCP Tunnel can forward '
                    'the local stdio server. No separate Dots API is assumed; the Dots connection remains untested until used there.')


# Adding an adapter changes this registry and its client transport, never domain logic.
PROVIDERS = {adapter.id: adapter for adapter in (OpenAIRealtime(), GeminiLive(), Dots(), MCPClient())}
