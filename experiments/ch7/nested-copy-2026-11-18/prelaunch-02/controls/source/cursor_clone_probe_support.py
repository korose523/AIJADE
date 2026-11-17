"""Typed and mutable-alias checks used only by offline candidate controls."""
def typed_equal(a,b,seen=None):
    if type(a) is not type(b):return False
    if seen is None:seen=set()
    if type(a) in (dict,list,tuple):
        pair=(id(a),id(b))
        if pair in seen:return True
        seen.add(pair)
    if type(a) is dict:return set(a)==set(b) and all(typed_equal(a[k],b[k],seen) for k in a)
    if type(a) in (list,tuple):return len(a)==len(b) and all(typed_equal(x,y,seen) for x,y in zip(a,b))
    return a==b


def assert_mutable_detached(a,b):
    mapping={};reverse={};pairs=set();left_ids=set();right_ids=set()
    def visit(x,y):
        assert type(x) is type(y)
        if type(x) not in (dict,list,tuple):return
        pair=(id(x),id(y))
        if pair in pairs:return
        pairs.add(pair)
        if type(x) in (dict,list):
            assert mapping.get(id(x),id(y))==id(y) and reverse.get(id(y),id(x))==id(x)
            mapping[id(x)]=id(y);reverse[id(y)]=id(x)
            left_ids.add(id(x));right_ids.add(id(y))
        if type(x) is dict:
            assert list(x)==list(y)
            for key in x:visit(x[key],y[key])
        else:
            assert len(x)==len(y)
            for u,v in zip(x,y):visit(u,v)
    visit(a,b)
    assert left_ids.isdisjoint(right_ids)
    return len(left_ids)
