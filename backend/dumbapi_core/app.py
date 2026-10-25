import hashlib

from . import __version__
from .catalog import Catalog
from .common import APIError, now, page
from .guidance import guided
from .jobs import Jobs
from .registry import definitions, validate


class App:
    def __init__(self, config):
        self.config = config
        self.capabilities = definitions()
        self.catalog = Catalog(config)
        self.jobs = Jobs(config)
        self._ai = None

    @property
    def ai(self):
        # Lazy: ordinary lookups do not create integration state or start anything.
        if self._ai is None:
            from .ai.service import Integrations
            self._ai = Integrations(self)
        return self._ai

    def health(self):
        identity = hashlib.sha256(str(self.config.root).encode() + b"\0" + str(self.config.data).encode()).hexdigest()[:16]
        return {"name": "DumbAPI", "version": __version__, "instance": identity, "time": now(), "access": "local only"}

    def search(self, query, project=None, kind=None, limit=8, offset=0):
        args = validate({"properties": {"query": {"type": "string"}, "project": {"type": "string"},
                         "kind": {"type": "string", "enum": ["project", "capability", "file"]},
                         "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 8},
                         "offset": {"type": "integer", "minimum": 0, "maximum": 1_000_000, "default": 0}}, "required": ["query"]},
                        {"query": query, "limit": limit, "offset": offset, **({"project": project} if project else {}), **({"kind": kind} if kind else {})})
        self.catalog.ensure(self.capabilities)
        return guided(self.catalog.search(**args))

    def describe(self, id):
        if id in self.capabilities:
            return guided(self.capabilities[id])
        self.catalog.ensure(self.capabilities)
        for project in self.catalog.projects():
            if project["id"] == id:
                return guided({**project, "capabilities": [{"id": c["id"], "description": c["description"], "mode": c["mode"]}
                        for c in self.capabilities.values() if c["project"] == id]})
        raise APIError("Project or capability not found. Search first.", "not_found", 404)

    def call(self, name, arguments=None, idempotency_key=None, launch=True):
        cap = self.capabilities.get(name)
        if not cap:
            raise APIError("Unknown capability. Search or describe a named capability first.", "not_found", 404)
        args = validate(cap["input_schema"], {} if arguments is None else arguments)
        if cap["mode"] == "job":
            return self.jobs.submit(name, args, idempotency_key, launch=launch)
        if idempotency_key:
            raise APIError("idempotency_key is only used for job capabilities.")
        if name.startswith('ai.'):
            return guided(self.ai.call(name, args))
        if name.startswith('bridge.'):
            from .bridge import Bridge
            return guided(Bridge(self.config).call(name, args))
        if name == "jobs.cancel":
            return self.jobs.cancel(args["id"])
        if name == "catalog.refresh":
            return guided(self.catalog.refresh(self.capabilities))
        if name == "projects.list":
            self.catalog.ensure(self.capabilities)
            return guided(page(self.catalog.projects(), **args))
        if name == "source.read":
            self.catalog.ensure(self.capabilities)
            return guided(self.catalog.read(**args))
        if name == "manager.send":
            from .manager_send import Handoff
            return guided(Handoff(self.config).send(**args))
        if name == 'manager.research.send':
            from .manager_research_send import ResearchHandoff
            return guided(ResearchHandoff(self.config).research_send(**args))
        if name.startswith('manager.inspiration.'):
            from .manager_inspiration import Inspiration
            return guided(Inspiration(self.config).call(name, args))
        if name.startswith("manager.social."):
            from .manager_social import Social
            return guided(Social(self.config).call(name, args))
        if name.startswith("manager."):
            from .manager import Manager
            result = Manager(self.config).call(name, args)
            if name == "manager.scout.plan":
                from .manager_scout import SCOUT_GUIDANCE
                return guided(result, SCOUT_GUIDANCE)
            return guided(result)
        if name.startswith("git."):
            from .git import Git
            return guided(getattr(Git(self.config), name.split('.', 1)[1])(**args))
        if name.startswith("browser."):
            from .browser import instance
            return guided(getattr(instance(self.config), name.split('.', 1)[1])(**args))
        if name.startswith("t3."):
            from .t3 import T3
            return guided(getattr(T3(self.config), name.split(".", 1)[1])(**args))
        if name.startswith('workspace.'):
            from .workspace import Workspace
            return guided(getattr(Workspace(self.config), name.split('.', 1)[1])(**args))
        raise APIError('Capability is not available in this distribution.', 'not_found', 404)
