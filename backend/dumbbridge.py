"""Dedicated Discord interaction endpoint. Never exposes the DumbAPI transport."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from dumbapi_core.bridge import Bridge
from dumbapi_core.common import APIError, Config
from dumbapi_core.discord_bridge import Discord


def make_server(port,config):
    bridge=Bridge(config);discord=Discord(bridge)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,status,value):
            body=json.dumps(value).encode()
            self.send_response(status);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers()
            self.wfile.write(body)
        def do_GET(self):
            self.reply(200,{'name':'DumbBridge','listener':True,'configured':bridge.status()['configured']}) if self.path=='/health' else self.reply(404,{'error':'Not found'})
        def do_POST(self):
            if self.path!='/interactions':self.reply(404,{'error':'Not found'});return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=128*1024:raise APIError('Invalid body size.','too_large',413)
                self.connection.settimeout(5)
                body=self.rfile.read(length)
                if len(body)!=length:raise APIError('Incomplete request.')
                response,event=discord.receive(body,self.headers)
                try:
                    self.reply(200,response)
                    self.wfile.flush()
                finally:discord.start(event)
            except APIError as exc:self.reply(exc.status,{'error':str(exc)})
            except Exception:self.reply(400,{'error':'Interaction could not be read.'})
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.discord=discord
    return server


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['serve']);parser.add_argument('--port',type=int,default=8780)
    parser.add_argument('--data-dir');args=parser.parse_args()
    server=make_server(args.port,Config(data=args.data_dir))
    print(f'DumbBridge listening on loopback port {server.server_port}. Expose only /interactions through your chosen HTTPS proxy.')
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();server.discord.close()
