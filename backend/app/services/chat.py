import re
from app.models.schemas import EnvironmentalInput

class ConversationMemory:
    def __init__(self):
        self.sessions={}
    def get(self, cid):
        return self.sessions.setdefault(cid, {'messages':[], 'environment':{}})
    def update(self, cid, env: EnvironmentalInput | None):
        s=self.get(cid)
        if env:
            s['environment'].update(env.model_dump(exclude_none=True))
        return s
    def add_message(self,cid,role,text):
        self.get(cid)['messages'].append({'role':role,'content':text})

memory=ConversationMemory()

class ChatParser:
    def parse(self, text):
        t=text.lower(); d={}
        m=re.search(r'(?:soc|organic carbon)\s*(?:is|=|:)\s*(\d+(?:\.\d+)?)\s*%?',t)
        if m: d['soil_organic_carbon']=float(m.group(1))
        m=re.search(r'(?:rainfall|rain)\s*(?:is|=|:)\s*(\d+(?:\.\d+)?)\s*(mm)?',t)
        if m: d['rainfall_mm']=float(m.group(1))
        for phrase,val in [('monoculture','monoculture'),('semi-arid','semi-arid'),('fragmented','fragmented')]:
            if phrase in t: d['land_use' if phrase=='monoculture' else 'region']=val
        return EnvironmentalInput(**d)
