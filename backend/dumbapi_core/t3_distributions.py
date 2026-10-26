"""Session identity and locking for the standard local T3 Code connection."""
import os
import copy
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from .common import APIError,atomic_json,now,read_json
_held=threading.local()
_gates={}
_gates_guard=threading.Lock()

@contextmanager
def connection_lock(config):
    path=config.data/'t3-connection.lock'
    key=os.path.normcase(str(path.resolve()))
    held=getattr(_held,'paths',set())
    if key in held:
        yield;return
    with _gates_guard:gate=_gates.setdefault(key,threading.Lock())
    if not gate.acquire(blocking=False):
        raise APIError('A connection change or send is in progress. Retry after it finishes.','busy',409)
    try:
        fd=os.open(path,os.O_RDWR|os.O_CREAT,0o600)
        with os.fdopen(fd,'r+b') as handle:
            handle.seek(0,2)
            if not handle.tell():handle.write(b'0');handle.flush()
            handle.seek(0)
            try:
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError:raise APIError('A connection change or send is in progress. Retry after it finishes.','busy',409) from None
            _held.paths=held|{key}
            try:yield
            finally:
                _held.paths=held;handle.seek(0)
                if os.name=='nt':msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
                else:fcntl.flock(handle,fcntl.LOCK_UN)
    finally:gate.release()

def active(config):
    try:
        value=read_json(config.data/'t3-connection.json')
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError):return {}
def distribution(value):return 't3'
def value_target(value):return 't3@'+str(value.get('url') or 'unconfigured').rstrip('/')
def target(config):return value_target(active(config))
@contextmanager
def request_target(expected):
    previous=getattr(_held,'expected','');_held.expected=expected if isinstance(expected,str) else ''
    try:yield
    finally:_held.expected=previous
def check_target(value):
    expected=getattr(_held,'expected','')
    if expected and expected!=value_target(value):raise APIError('The T3 endpoint changed. Reload before sending.','t3_target_changed',409)

class Distributions:
    def __init__(self,config):self.config=config
    def list(self):
        value=active(self.config)
        return {'items':[{'id':'t3','label':'T3 Code','installed':(Path.home()/'.t3/bin/t3.cmd').is_file(),
                         'selected':bool(value.get('url')),'configured':bool(value.get('token')),
                         'endpoint':value.get('url','http://127.0.0.1:3773'),'expires_at':value.get('expiresAt')}],
                'selected':'t3' if value.get('url') else '', 'target':target(self.config),
                'note':'Only the standard local T3 Code installation is supported in this preview.'}
    def select(self,id,reconnect=False,expected_target=''):
        if id!='t3':raise APIError('Choose the standard local T3 Code connection.')
        with connection_lock(self.config):
            if expected_target and expected_target!=target(self.config):raise APIError('The endpoint changed. Reload before reconnecting.','t3_target_changed',409)
            from .t3 import T3
            client=T3(self.config)
            if reconnect or not active(self.config).get('token'):
                with tempfile.TemporaryDirectory(prefix='t3-pair-',dir=self.config.data) as folder:
                    candidate_config=copy.copy(self.config);candidate_config.data=Path(folder)
                    candidate=T3(candidate_config);candidate._connect(3773)
                    value=candidate.validate_connection(read_json(candidate_config.data/'t3-connection.json'))
                    candidate.get_from(value,'/api/orchestration/shell')
                    value['verified_at']=now()
                    atomic_json(self.config.data/'t3-connection.json',value)
            else:client.get('/api/orchestration/shell')
            return {**self.list(),'connected':True,'changed':False,'note':'Local T3 connection checked. No message was sent.'}
