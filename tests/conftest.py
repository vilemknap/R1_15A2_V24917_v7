from __future__ import annotations
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import math

class FakeAttr:
    def __init__(self, **attrs):
        object.__setattr__(self, '_attrs', dict(attrs))
    def AttValue(self, name):
        if name in self._attrs:
            return self._attrs[name]
        raise KeyError(name)
    def SetAttValue(self, name, value):
        self._attrs[name] = value
    def __getattr__(self, name):
        attrs=object.__getattribute__(self,'_attrs')
        if name in attrs:
            return attrs[name]
        raise AttributeError(name)
    def __setattr__(self,name,value):
        if name=='_attrs': object.__setattr__(self,name,value)
        else: self._attrs[name]=value

class FakeCollection:
    def __init__(self, items, keys=None):
        self.items=list(items)
        self.keys = dict(keys or {})
        self.Count=len(self.items)
    @property
    def GetAll(self):
        return tuple(self.items)
    def ItemByKey(self,key):
        if key in self.keys: return self.keys[key]
        for x in self.items:
            for name in ('CODE','NO','DEMANDSTRATUMCODE'):
                try:
                    if x.AttValue(name)==key: return x
                except Exception: pass
        raise KeyError(key)
    def Item(self,key): return self.ItemByKey(key)

class FakeZones(FakeCollection):
    def __init__(self, rows):
        self.rows=[dict(r) for r in rows]
        super().__init__([FakeAttr(**r) for r in self.rows], keys={int(r['NO']): FakeAttr(**r) for r in rows})
    def GetMultiAttValues(self, attr):
        return [(int(r['NO']), r.get(attr,'')) for r in self.rows]
    def SetMultiAttValues(self, attr, pairs):
        pmap={int(k):v for k,v in pairs}
        for r in self.rows:
            if int(r['NO']) in pmap: r[attr]=pmap[int(r['NO'])]

class FakeDstratCollection(FakeCollection): pass

class FakeOperation(FakeAttr):
    pass

class FakeVisum:
    def __init__(self, operations=None, zones=None, matrices=None, dsegs=None):
        self.Procedures=FakeAttr(Operations=FakeCollection(operations or []))
        self.Net=FakeAttr(
            Zones=zones or FakeZones([]),
            Matrices=matrices or FakeCollection([]),
            DemandSegments=dsegs or FakeCollection([]),
        )
