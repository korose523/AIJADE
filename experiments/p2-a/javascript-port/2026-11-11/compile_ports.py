"""Emit JavaScript functions for the Python syntax used by the pinned direct tasks."""
import ast
import json


BUILTINS = set('abs all any bin bool chr dict enumerate filter float int isinstance len list map max min next ord pow range reversed round set sorted str sum tuple type zip'.split())
MODULES = set('bisect collections functools heapq itertools math operator re typing'.split())
OPS = {ast.Add:'add', ast.Sub:'sub', ast.Mult:'mul', ast.Div:'div', ast.FloorDiv:'floor', ast.Mod:'mod',
       ast.Pow:'pow', ast.LShift:'shl', ast.RShift:'shr', ast.BitOr:'bor', ast.BitAnd:'band', ast.BitXor:'xor',
       ast.Eq:'eq', ast.NotEq:'ne', ast.Gt:'gt', ast.GtE:'ge', ast.Lt:'lt', ast.LtE:'le',
       ast.In:'in', ast.NotIn:'notIn', ast.Is:'is', ast.IsNot:'isNot'}


class Unsupported(ValueError):
    pass


def js(value):
    return json.dumps(value, ensure_ascii=True, separators=(',', ':'))


def local(name):
    return '$v_' + name


class Bindings(ast.NodeVisitor):
    def __init__(self):
        self.variables = set()
        self.functions = set()

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Store):
            self.variables.add(node.id)

    def visit_FunctionDef(self, node):
        self.functions.add(node.name)

    def visit_Import(self, node):
        self.variables.update(item.asname or item.name for item in node.names)

    visit_ImportFrom = visit_Import

    def visit_Lambda(self, node):
        return

    def visit_ListComp(self, node):
        return

    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp


def bindings(nodes):
    result = Bindings()
    for node in nodes:
        result.visit(node)
    return result


class Compiler:
    def __init__(self):
        self.counter = 0

    def temporary(self):
        self.counter += 1
        return f'$item{self.counter}'

    def program(self, source, entry):
        body = ast.parse(source).body
        scope = bindings(body)
        if entry not in scope.functions:
            raise Unsupported('missing declared function')
        code = self.block(body, scope.variables | scope.functions, 1)
        decl = self.declare(scope.variables, 1)
        return f'const $entry = (() => {{\n{decl}{code}  return {local(entry)};\n}})();\n'

    @staticmethod
    def declare(names, level):
        return '  '*level + 'let ' + ', '.join(map(local, sorted(names))) + ';\n' if names else ''

    def block(self, nodes, scope, level):
        return ''.join(self.statement(node, scope, level) for node in nodes)

    def arguments(self, args, outer):
        if args.posonlyargs or args.kwonlyargs or args.kwarg:
            raise Unsupported('function argument binding')
        names = [a.arg for a in args.args]
        params = list(map(local, names))
        for offset, default in enumerate(args.defaults, len(names)-len(args.defaults)):
            params[offset] += ' = ' + self.expr(default, outer)
        if args.vararg:
            names.append(args.vararg.arg)
            params.append('...' + local(args.vararg.arg))
        return ', '.join(params), set(names)

    def statement(self, node, scope, level):
        tab = '  '*level
        expression = lambda n: self.expr(n, scope)
        if isinstance(node, ast.FunctionDef):
            if node.decorator_list:
                raise Unsupported('decorated function')
            params, names = self.arguments(node.args, scope)
            inner = bindings(node.body)
            nested_scope = scope | names | inner.variables | inner.functions
            body = self.declare(inner.variables-names-inner.functions, level+1) + self.block(node.body, nested_scope, level+1)
            generator = any(isinstance(n, (ast.Yield, ast.YieldFrom)) for n in ast.walk(node))
            star = '*' if generator else ''
            return f'{tab}function{star} {local(node.name)}({params}) {{\n{body}{tab}  return null;\n{tab}}}\n'
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            lines = []
            for alias in node.names:
                module = node.module if isinstance(node, ast.ImportFrom) else alias.name
                if module not in MODULES:
                    raise Unsupported('module '+str(module))
                value = f'$p.modules.{module}'
                if isinstance(node, ast.ImportFrom):
                    value += f'.{alias.name}'
                lines.append(f'{tab}{local(alias.asname or alias.name)} = {value};\n')
            return ''.join(lines)
        if isinstance(node, ast.Return):
            return f'{tab}return {expression(node.value) if node.value else "null"};\n'
        if isinstance(node, ast.Assign):
            value = expression(node.value)
            if len(node.targets)==1:
                return self.assign(node.targets[0], value, scope, level)
            temporary = self.temporary()
            return f'{tab}const {temporary} = {value};\n' + ''.join(self.assign(t, temporary, scope, level) for t in node.targets)
        if isinstance(node, ast.AugAssign):
            op = OPS[type(node.op)]
            if isinstance(node.target, ast.Name):
                name = local(node.target.id)
                return f'{tab}{name} = $p.op({js(op)}, {name}, {expression(node.value)});\n'
            if isinstance(node.target, ast.Subscript) and not isinstance(node.target.slice, ast.Slice):
                target, key = self.temporary(), self.temporary()
                return (f'{tab}const {target} = {expression(node.target.value)}, {key} = {expression(node.target.slice)};\n'
                        f'{tab}$p.put({target}, {key}, $p.op({js(op)}, $p.get({target}, {key}), {expression(node.value)}));\n')
            raise Unsupported('augmented assignment target')
        if isinstance(node, ast.If):
            body = self.block(node.body, scope, level+1)
            alternate = self.block(node.orelse, scope, level+1)
            clause = f' else {{\n{alternate}{tab}}}' if alternate else ''
            return f'{tab}if ($p.truth({expression(node.test)})) {{\n{body}{tab}}}{clause}\n'
        if isinstance(node, (ast.For, ast.While)):
            if node.orelse:
                raise Unsupported('loop else')
            binding = ''
            if isinstance(node, ast.For):
                temporary = self.temporary()
                header = f'for (const {temporary} of $p.iter({expression(node.iter)}))'
                binding = self.assign(node.target, temporary, scope, level+1)
            else:
                header = f'while ($p.truth({expression(node.test)}))'
            body = self.block(node.body, scope, level+1)
            return f'{tab}{header} {{\n{binding}{body}{tab}}}\n'
        if isinstance(node, ast.Assert):
            return f'{tab}if (!$p.truth({expression(node.test)})) throw new Error("Python assertion");\n'
        if isinstance(node, ast.Expr):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return ''
            return f'{tab}{expression(node.value)};\n'
        if isinstance(node, (ast.Break, ast.Continue, ast.Pass)):
            return f'{tab}{type(node).__name__.lower()};\n' if not isinstance(node, ast.Pass) else ''
        raise Unsupported(type(node).__name__)

    def assign(self, node, value, scope, level):
        tab = '  '*level
        if isinstance(node, ast.Name):
            return f'{tab}{local(node.id)} = {value};\n'
        if isinstance(node, (ast.Tuple, ast.List)):
            temporary = self.temporary()
            return f'{tab}const {temporary} = $p.unpack({value}, {len(node.elts)});\n' + ''.join(
                self.assign(child, f'{temporary}[{i}]', scope, level) for i, child in enumerate(node.elts))
        if isinstance(node, ast.Subscript) and not isinstance(node.slice, ast.Slice):
            return f'{tab}$p.put({self.expr(node.value,scope)}, {self.expr(node.slice,scope)}, {value});\n'
        raise Unsupported('assignment target '+type(node).__name__)

    def expr(self, node, scope):
        e = lambda n: self.expr(n, scope)
        if isinstance(node, ast.Name):
            if node.id in scope:
                return local(node.id)
            if node.id in BUILTINS:
                return '$p.b.' + node.id
            raise Unsupported('unbound name '+node.id)
        if isinstance(node, ast.Constant):
            if type(node.value) is int:
                return f'({node.value}n)'
            if node.value is None or type(node.value) in (str, bool, float):
                return js(node.value)
            raise Unsupported('constant '+type(node.value).__name__)
        if isinstance(node, (ast.List, ast.Tuple)):
            values = '[' + ', '.join(e(n) for n in node.elts) + ']'
            return '$p.tuple('+values+')' if isinstance(node, ast.Tuple) else values
        if isinstance(node, ast.Dict):
            if any(k is None for k in node.keys):
                raise Unsupported('dict unpacking')
            return '$p.dict([' + ', '.join(f'[{e(k)}, {e(v)}]' for k,v in zip(node.keys,node.values)) + '])'
        if isinstance(node, ast.Call):
            args = '[' + ', '.join(e(a) for a in node.args) + ']'
            kwargs = ', ' + js({}) if not node.keywords else ', {' + ', '.join(f'{js(n.arg)}: {e(n.value)}' for n in node.keywords) + '}'
            return f'$p.call({e(node.func)}, {args}{kwargs})' if node.keywords else f'{e(node.func)}(...{args})'
        if isinstance(node, ast.Starred):
            return f'...$p.iter({e(node.value)})'
        if isinstance(node, ast.Attribute):
            return f'$p.attr({e(node.value)}, {js(node.attr)})'
        if isinstance(node, ast.BinOp):
            return f'$p.op({js(OPS[type(node.op)])}, {e(node.left)}, {e(node.right)})'
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                return f'(!$p.truth({e(node.operand)}))'
            if isinstance(node.op, ast.USub):
                return f'$p.neg({e(node.operand)})'
            if isinstance(node.op, ast.UAdd):
                return f'$p.number({e(node.operand)})'
            raise Unsupported(type(node.op).__name__)
        if isinstance(node, ast.Compare):
            ops = [OPS[type(op)] for op in node.ops]
            exprs = [e(n) for n in [node.left]+node.comparators]
            if len(ops)==1:
                return f'$p.op({js(ops[0])}, {exprs[0]}, {exprs[1]})'
            return f'$p.chain({js(ops)}, [' + ', '.join('() => '+x for x in exprs) + '])'
        if isinstance(node, ast.BoolOp):
            return '$p.logical(' + ('true' if isinstance(node.op, ast.And) else 'false') + ', [' + ', '.join('() => '+e(x) for x in node.values) + '])'
        if isinstance(node, ast.IfExp):
            return f'($p.truth({e(node.test)}) ? {e(node.body)} : {e(node.orelse)})'
        if isinstance(node, ast.Subscript):
            if isinstance(node.slice, ast.Slice):
                args = ', '.join(e(p) if p else 'null' for p in [node.slice.lower, node.slice.upper, node.slice.step])
                return f'$p.slice({e(node.value)}, {args})'
            return f'$p.get({e(node.value)}, {e(node.slice)})'
        if isinstance(node, ast.Lambda):
            params, names = self.arguments(node.args, scope)
            return f'(({params}) => {self.expr(node.body,scope|names)})'
        if isinstance(node, (ast.ListComp, ast.GeneratorExp, ast.DictComp)):
            return self.comprehension(node, scope)
        if isinstance(node, ast.Yield):
            return f'yield {e(node.value) if node.value else "null"}'
        if isinstance(node, ast.YieldFrom):
            return f'yield* $p.iter({e(node.value)})'
        raise Unsupported(type(node).__name__)

    def comprehension(self, node, scope):
        def loops(index, inner, level):
            tab = '  '*level
            if index==len(node.generators):
                if isinstance(node, ast.DictComp):
                    value = f'[{self.expr(node.key, inner)}, {self.expr(node.value, inner)}]'
                else:
                    value = self.expr(node.elt, inner)
                return f'{tab}yield {value};\n'
            generator = node.generators[index]
            temporary = self.temporary()
            names = bindings([generator.target]).variables
            nested = inner | names
            condition = ''.join(f'{tab}  if (!$p.truth({self.expr(t,nested)})) continue;\n' for t in generator.ifs)
            return (f'{tab}for (const {temporary} of $p.iter({self.expr(generator.iter,inner)})) {{\n'
                    + self.declare(names, level+1) + self.assign(generator.target,temporary,nested,level+1)
                    + condition + loops(index+1,nested,level+1) + f'{tab}}}\n')
        source = '(function* () {\n' + loops(0,scope,1) + '})()'
        if isinstance(node, ast.DictComp):
            return f'$p.dict({source})'
        return f'$p.b.list({source})' if isinstance(node, ast.ListComp) else source
