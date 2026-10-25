"""Queue transport compatibility. This core currently registers no background job providers."""
from .common import APIError
class Jobs:
    def __init__(self,config):self.config=config
    def list(self,limit=10,offset=0):return {'items':[],'total':0,'offset':offset,'next_offset':None}
    def view(self,id,log_lines=0):raise APIError('Job not found.','not_found',404)
    def cancel(self,id):raise APIError('Job not found.','not_found',404)
    def submit(self,*args,**kwargs):raise APIError('No job provider is configured.','not_available',503)
    def run(self):return None
