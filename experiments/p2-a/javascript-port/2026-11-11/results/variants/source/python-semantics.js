// Runtime operations used by the source-derived JavaScript ports of the frozen direct tasks.
const $p = (() => {
  const tuples = new WeakSet();
  const defaultFactories = new WeakMap();
  const keyword = Symbol('keyword arguments');
  const numeric = x => ['bigint', 'number', 'boolean'].includes(typeof x);
  const integral = x => typeof x === 'bigint' || typeof x === 'boolean';
  const number = x => typeof x === 'boolean' ? BigInt(x) : x;
  const neg = x => -number(x);
  const tuple = values => { const result = [...values]; tuples.add(result); return result; };
  const truth = value => Array.isArray(value) ? value.length !== 0
    : value instanceof Map || value instanceof Set ? value.size !== 0
    : typeof value === 'number' && Number.isNaN(value) ? true : Boolean(value);
  function codePoints(text) {
    const result=[];
    for (let index=0;index<text.length;index++) {
      const first=text.charCodeAt(index), second=text.charCodeAt(index+1);
      if (first>=0xd800 && first<=0xdbff && second>=0xdc00 && second<=0xdfff) {
        result.push(text.slice(index,index+2));
        index++;
      } else result.push(text[index]);
    }
    return result;
  }
  const iter = value => value instanceof Map ? value.keys() : typeof value==='string' ? codePoints(value) : value;
  const list = (value = []) => Array.from(iter(value));
  const length = value => typeof value === 'string' ? codePoints(value).length
    : value instanceof Map || value instanceof Set ? value.size : value.length;
  const unpack = (value, size) => {
    const items = list(value);
    if (items.length !== size) throw new Error('unpack arity mismatch');
    return items;
  };

  function equal(a, b) {
    if (a === b) return true;
    if (numeric(a) && numeric(b)) return number(a) == number(b);
    if (Array.isArray(a) && Array.isArray(b)) {
      return tuples.has(a) === tuples.has(b) && a.length === b.length && a.every((x, i) => equal(x, b[i]));
    }
    if (a instanceof Map && b instanceof Map) {
      return a.size === b.size && [...a].every(([k,v]) => findKey(b, k) !== undefined && equal(v, b.get(findKey(b,k))));
    }
    if (a instanceof Set && b instanceof Set) return a.size === b.size && [...a].every(x => contains(b,x));
    return false;
  }

  function findKey(map, key) {
    if (map.has(key)) return key;
    if (typeof key === 'string') return undefined;
    for (const existing of map.keys()) if (equal(existing, key)) return existing;
    return undefined;
  }

  function dict(entries = []) {
    const result = new Map();
    for (const pair of entries) put(result, ...pair);
    return result;
  }

  function sequence(value) { return typeof value === 'string' ? codePoints(value) : value; }

  function get(value, key) {
    if (value instanceof Map) {
      const found = findKey(value, key);
      if (found !== undefined) return value.get(found);
      if (!defaultFactories.has(value)) throw new Error('missing dictionary key');
      const result = defaultFactories.get(value)();
      value.set(key, result);
      return result;
    }
    const data = sequence(value);
    const index = Number(key);
    const i = index < 0 ? data.length + index : index;
    if (!Number.isInteger(i) || i < 0 || i >= data.length) throw new Error('index out of range');
    return data[i];
  }

  function put(value, key, next) {
    if (value instanceof Map) {
      const found = findKey(value, key);
      value.set(found === undefined ? key : found, next);
      return;
    }
    const index = Number(key);
    value[index < 0 ? value.length + index : index] = next;
  }

  function slice(value, start, stop, step = null) {
    const data = sequence(value);
    const n = data.length;
    const direction = step === null ? 1 : Number(step);
    if (direction === 0) throw new Error('zero slice step');
    const bound = (x, fallback) => {
      if (x === null) return fallback;
      const i = Number(x);
      return direction > 0 ? Math.min(n, Math.max(0, i < 0 ? i + n : i))
        : Math.min(n - 1, Math.max(-1, i < 0 ? i + n : i));
    };
    const lower = bound(start, direction > 0 ? 0 : n - 1);
    const upper = bound(stop, direction > 0 ? n : -1);
    const result = [];
    for (let i=lower; direction > 0 ? i<upper : i>upper; i+=direction) result.push(data[i]);
    return typeof value === 'string' ? result.join('') : tuples.has(value) ? tuple(result) : result;
  }

  function compare(a,b) {
    if (equal(a,b)) return 0;
    if (Array.isArray(a) && Array.isArray(b)) {
      for (let i=0; i<Math.min(a.length,b.length); i++) {
        const c = compare(a[i], b[i]);
        if (c) return c;
      }
      return a.length < b.length ? -1 : 1;
    }
    if (typeof a === 'string' && typeof b === 'string') {
      const left = codePoints(a), right = codePoints(b);
      for (let i=0; i<Math.min(left.length,right.length); i++) {
        if (left[i] !== right[i]) return left[i].codePointAt(0)-right[i].codePointAt(0);
      }
      return left.length-right.length;
    }
    if (numeric(a) && numeric(b)) return number(a)<number(b) ? -1 : 1;
    throw new Error('incomparable Python values');
  }

  function contains(container, value) {
    if (typeof container === 'string') return container.includes(value);
    if (container instanceof Map || container instanceof Set) return findKey(container, value) !== undefined;
    for (const item of iter(container)) if (equal(item, value)) return true;
    return false;
  }

  function set(items = []) {
    const result = new Set();
    for (const item of iter(items)) if (!contains(result,item)) result.add(item);
    return result;
  }

  function op(operation, a, b) {
    switch (operation) {
      case 'is': return a === b;
      case 'isNot': return a !== b;
      case 'eq': return equal(a,b);
      case 'ne': return !equal(a,b);
      case 'lt': return compare(a,b)<0;
      case 'le': return compare(a,b)<=0;
      case 'gt': return compare(a,b)>0;
      case 'ge': return compare(a,b)>=0;
      case 'in': return contains(b,a);
      case 'notIn': return !contains(b,a);
    }
    if (typeof a==='boolean' && typeof b==='boolean') {
      if (operation==='band') return a && b;
      if (operation==='bor') return a || b;
      if (operation==='xor') return a !== b;
    }
    if (operation === 'add') {
      if (Array.isArray(a) && Array.isArray(b)) return tuples.has(a) ? tuple([...a,...b]) : [...a,...b];
      if (typeof a === 'string' && typeof b === 'string') return a+b;
    }
    if (operation === 'mul' && (Array.isArray(a) || Array.isArray(b) || typeof a==='string' || typeof b==='string')) {
      const [data,n] = Array.isArray(a) || typeof a==='string' ? [a,b] : [b,a];
      const count = Math.max(0, Number(n));
      if (typeof data==='string') return data.repeat(count);
      const result=[];
      for (let i=0; i<count; i++) for (const item of data) result.push(item);
      return tuples.has(data) ? tuple(result) : result;
    }
    if (!numeric(a) || !numeric(b)) throw new Error('non-numeric operation '+operation);
    const ints = integral(a) && integral(b);
    const x = ints ? BigInt(a) : Number(a), y = ints ? BigInt(b) : Number(b);
    switch (operation) {
      case 'add': return x+y;
      case 'sub': return x-y;
      case 'mul': return x*y;
      case 'div': return Number(x)/Number(y);
      case 'floor': {
        if (!ints) return Math.floor(x/y);
        const quot=x/y, rem=x%y;
        return rem!==0n && (x<0n)!==(y<0n) ? quot-1n : quot;
      }
      case 'mod': {
        const rem=x%y;
        return rem!==0 && rem!==0n && (rem<0)!==(y<0) ? rem+y : rem;
      }
      case 'pow': return ints && y>=0n ? x**y : Number(x)**Number(y);
      case 'shl': return BigInt(x)<<BigInt(y);
      case 'shr': return BigInt(x)>>BigInt(y);
      case 'band': return BigInt(x)&BigInt(y);
      case 'bor': return BigInt(x)|BigInt(y);
      case 'xor': return BigInt(x)^BigInt(y);
      default: throw new Error('unknown operation '+operation);
    }
  }

  function chain(ops, expressions) {
    let a=expressions[0]();
    for (let i=0; i<ops.length; i++) {
      const b=expressions[i+1]();
      if (!op(ops[i],a,b)) return false;
      a=b;
    }
    return true;
  }
  function logical(and, expressions) {
    let value;
    for (const read of expressions) {
      value=read();
      if (truth(value)!==and) break;
    }
    return value;
  }
  const call = (fn, args, kwargs) => fn(...args, { [keyword]: kwargs });

  function int(value=0n, base=10n) {
    if (typeof value !== 'string') return typeof value==='number' ? BigInt(Math.trunc(value)) : BigInt(value);
    let s=value.trim().replaceAll('_','');
    const sign=s.startsWith('-') ? -1n : 1n;
    if (s.startsWith('-') || s.startsWith('+')) s=s.slice(1);
    const radix=BigInt(base);
    if (radix===10n && /^\d+$/.test(s)) return sign*BigInt(s);
    let out=0n;
    if (!s) throw new Error('empty integer');
    for (const ch of s.toLowerCase()) {
      const digit=parseInt(ch,36);
      if (!Number.isInteger(digit) || digit>=radix) throw new Error('invalid integer digit');
      out=out*radix+BigInt(digit);
    }
    return sign*out;
  }

  function str(value='') {
    if (typeof value==='string') return value;
    if (value===null) return 'None';
    if (typeof value==='boolean') return value ? 'True' : 'False';
    if (typeof value==='bigint') return value.toString();
    if (typeof value==='number') {
      if (Object.is(value,-0)) return '-0.0';
      const magnitude=Math.abs(value);
      if (magnitude>=1e16 || magnitude!==0 && magnitude<1e-4) {
        return value.toExponential().replace(/e([+-])(\d)$/, 'e$10$2');
      }
      return Number.isInteger(value) ? value.toFixed(1) : String(value);
    }
    const repr=x=>typeof x==='string' ? reprString(x) : str(x);
    if (Array.isArray(value)) {
      const body=value.map(repr).join(', ');
      return tuples.has(value) ? '('+body+(value.length===1?',':'')+')' : '['+body+']';
    }
    if (value instanceof Map) return '{'+[...value].map(([k,v])=>repr(k)+': '+repr(v)).join(', ')+'}';
    throw new Error('unsupported string conversion');
  }

  function reprString(value) {
    const quote=value.includes("'") && !value.includes('"') ? '"' : "'";
    let out=quote;
    for (const ch of codePoints(value)) {
      if (ch===quote || ch==='\\') out+='\\'+ch;
      else if (ch==='\n') out+='\\n';
      else if (ch==='\r') out+='\\r';
      else if (ch==='\t') out+='\\t';
      else if (ch.codePointAt(0)<32 || ch.codePointAt(0)===127) out+='\\x'+ch.codePointAt(0).toString(16).padStart(2,'0');
      else out+=ch;
    }
    return out+quote;
  }

  function* range(start, stop, step=1n) {
    if (stop===undefined) { stop=start; start=0n; }
    const a=int(start), b=int(stop), d=int(step);
    if (d===0n) throw new Error('zero range step');
    for (let i=a; d>0n ? i<b : i>b; i+=d) yield i;
  }

  function* zip(...values) {
    const iterators=values.map(x=>iter(x)[Symbol.iterator]());
    while (iterators.length) {
      const row=iterators.map(x=>x.next());
      if (row.some(x=>x.done)) return;
      yield tuple(row.map(x=>x.value));
    }
  }
  const map = function* (fn,...values) { for (const items of zip(...values)) yield fn(...items); };
  const filter = function* (fn,values) { for (const x of iter(values)) if (truth(fn(x))) yield x; };
  const enumerate = function* (values,start=0n) { let i=start; for (const x of iter(values)) yield tuple([i++,x]); };
  const round = (value, digits) => {
    if (integral(value) && digits===undefined) return int(value);
    const scale=digits===undefined ? 1 : 10**Number(digits);
    const x=Number(value)*scale;
    const lo=Math.floor(x);
    const result=x-lo===0.5 ? (lo%2===0 ? lo : lo+1) : Math.round(x);
    return digits===undefined ? BigInt(result) : result/scale;
  };

  function sorted(values, options) {
    const { key, reverse } = options?.[keyword] ?? {};
    const direction=truth(reverse) ? -1 : 1;
    if (key?.comparator) return list(values).sort((a,b)=>direction*Number(key.comparator(a,b)));
    return list(values).map(x=>[key ? key(x) : x, x]).sort((a,b)=>direction*compare(a[0],b[0])).map(x=>x[1]);
  }
  function extreme(direction, args) {
    const options=args.at(-1)?.[keyword];
    if (options) args.pop();
    const values=args.length===1 ? iter(args[0]) : args;
    let best, key;
    for (const value of values) {
      const k=options?.key ? options.key(value) : value;
      if (best===undefined || direction*compare(k,key)>0) { best=value; key=k; }
    }
    if (best===undefined) throw new Error('empty min/max');
    return best;
  }

  function type(value) {
    if (typeof value==='bigint') return b.int;
    if (typeof value==='number') return b.float;
    if (typeof value==='boolean') return b.bool;
    if (typeof value==='string') return b.str;
    if (Array.isArray(value)) return tuples.has(value) ? b.tuple : b.list;
    if (value instanceof Map) return b.dict;
    if (value instanceof Set) return b.set;
    return null;
  }
  function all(xs) { for (const x of iter(xs)) if (!truth(x)) return false; return true; }
  function any(xs) { for (const x of iter(xs)) if (truth(x)) return true; return false; }
  const b = { abs:x=>x<0 ? neg(x) : number(x), all, any,
    bin:x=> (x<0 ? '-0b'+(-int(x)).toString(2) : '0b'+int(x).toString(2)), bool:truth,
    chr:x=>String.fromCodePoint(Number(x)), dict, enumerate, filter, float:Number, int, len:x=>BigInt(length(x)),
    isinstance:(x,t)=>Array.isArray(t) ? t.some(v=>b.isinstance(x,v)) : type(x)===t || t===b.int && typeof x==='boolean',
    list, map, max:(...args)=>extreme(1,args), min:(...args)=>extreme(-1,args),
    next:(it, fallback)=>{const x=it.next();if (x.done && fallback===undefined) throw new Error('StopIteration');return x.done?fallback:x.value;},
    ord:x=>BigInt(x.codePointAt(0)), pow:(x,y)=>op('pow',x,y), range, reversed:x=>list(x).reverse(), round,
    set, sorted, str, sum:(xs,start=0n)=>list(xs).reduce((a,x)=>op('add',a,x),start), tuple:x=>tuple(list(x)), type, zip };

  function regex(pattern, flags='') { return new RegExp(pattern.replaceAll('\\Z','(?![\\s\\S])'), flags); }
  function matchRecord(m) {
    return m===null ? null : { start:()=>BigInt(length(m.input.slice(0,m.index))),
      end:()=>BigInt(length(m.input.slice(0,m.index+m[0].length))),
      group:(i=0n)=>m[Number(i)] ?? null, groups:()=>tuple(m.slice(1).map(x=>x??null)) };
  }
  const re={ search:(p,s)=>matchRecord(regex(p).exec(s)), match:(p,s)=>matchRecord(regex('^(?:'+p+')').exec(s)),
    sub:(p,r,s)=>s.replace(regex(p,'g'),r.replaceAll('$','$$$$').replace(/\\(\d+)/g,(_,n)=>'$'+n)),
    findall:(p,s)=>[...s.matchAll(regex(p,'g'))].map(m=>m.length===1?m[0]:m.length===2?m[1]??'':tuple(m.slice(1).map(x=>x??''))),
    finditer:(p,s)=>[...s.matchAll(regex(p,'g'))].map(matchRecord), compile:p=>({search:s=>re.search(p,s)}) };
  const reSearch=re.search;
  re.search=(p,s)=>{const m=reSearch(p,s);if(m) m.re={pattern:p};return m;};

  function attr(value,name) {
    if (value instanceof Map) {
      const methods={ items:()=>[...value].map(tuple), values:()=>value.values(), keys:()=>value.keys(),
        get:(k,d=null)=>{const found=findKey(value,k);return found===undefined?d:value.get(found);} };
      if (Object.hasOwn(methods,name)) return methods[name];
    }
    if (value instanceof Set) {
      if (name==='add') return item=>{if(!contains(value,item)) value.add(item);return null;};
      if (name==='intersection') return items=>{
        const [small,large]=value.size<items.size?[value,items]:[items,value];
        return set([...small].filter(item=>contains(large,item)));
      };
    }
    if (Array.isArray(value)) {
      const methods={ append:x=>{value.push(x);return null;}, extend:x=>{for(const i of iter(x)) value.push(i);return null;},
        pop:(i=-1n)=>value.splice(Number(i),1)[0], index:x=>BigInt(value.findIndex(i=>equal(x,i))),
        remove:x=>{value.splice(value.findIndex(i=>equal(i,x)),1);return null;},
        count:x=>BigInt(value.filter(i=>equal(i,x)).length), sort:options=>{const out=sorted(value,options);value.splice(0,value.length,...out);return null;} };
      if (Object.hasOwn(methods,name)) return methods[name];
    }
    if (typeof value==='string') {
      const methods={ join:x=>list(x).join(value), split:(sep=null,max=-1n)=>split(value,sep,max),
        replace:(from,to,count=-1n)=>replace(value,from,to,count), count:sub=>BigInt(sub===''?length(value)+1:value.split(sub).length-1),
        index:x=>BigInt(length(value.slice(0,value.indexOf(x)))), startswith:x=>value.startsWith(x), endswith:x=>value.endsWith(x),
        strip:()=>value.trim(), lower:()=>value.toLowerCase(), upper:()=>value.toUpperCase(),
        capitalize:()=>codePoints(value).slice(0,1).join('').toUpperCase()+codePoints(value).slice(1).join('').toLowerCase(),
        swapcase:()=>codePoints(value).map(c=>c===c.toLowerCase()?c.toUpperCase():c.toLowerCase()).join(''),
        isdigit:()=>/^\p{Nd}+$/u.test(value), isalpha:()=>/^\p{L}+$/u.test(value), isspace:()=>/^\s+$/u.test(value),
        islower:()=>value===value.toLowerCase() && value!==value.toUpperCase(),
        isupper:()=>value===value.toUpperCase() && value!==value.toLowerCase(),
        format:(...args)=>{let i=0;return value.replace(/\{(\d*)\}/g,(_,n)=>str(args[n===''?i++:Number(n)]));} };
      if (Object.hasOwn(methods,name)) return methods[name];
    }
    if (typeof value==='number' && name==='is_integer') return ()=>Number.isInteger(value);
    if (value && Object.hasOwn(value,name)) return value[name];
    throw new Error('unsupported attribute '+name);
  }

  function replace(value, from, to, count) {
    if (from==='') {
      let result='';
      let used=0;
      for (const ch of codePoints(value)) {
        if (count<0 || used<count) {result+=to;used++;}
        result+=ch;
      }
      return result+(count<0 || used<count ? to : '');
    }
    if (count<0) return value.replaceAll(from,()=>to);
    let offset=0;
    let result='';
    for (let i=0;i<count;i++) {
      const found=value.indexOf(from,offset);
      if(found<0) break;
      result+=value.slice(offset,found)+to;
      offset=found+from.length;
    }
    return result+value.slice(offset);
  }

  function split(value, separator, max) {
    const text=separator===null ? value.trimStart() : value;
    if (separator===null && text==='') return [];
    const delim=separator===null ? /\s+/ : separator;
    const chunks=(separator===null && max<0 ? text.trimEnd() : text).split(delim);
    if (max<0 || chunks.length<=Number(max)+1) return chunks;
    if (separator!==null) return [...chunks.slice(0,Number(max)),chunks.slice(Number(max)).join(separator)];
    let end=0;
    const regex=/\s+/g;
    for (let i=0;i<Number(max);i++) {regex.exec(text);end=regex.lastIndex;}
    return [...chunks.slice(0,Number(max)),text.slice(end)];
  }

  const gcd=(a,b)=>{a=builtAbs(int(a));b=builtAbs(int(b));while(b!==0n)[a,b]=[b,a%b];return a;};
  const builtAbs=x=>x<0n?-x:x;
  function bisect(a,x,lower=0n,upper=BigInt(a.length),right=false) {
    let lo=Number(lower),hi=Number(upper);
    while(lo<hi){const mid=Math.floor((lo+hi)/2);const c=compare(a[mid],x);if(c<0||right&&c===0)lo=mid+1;else hi=mid;}
    return BigInt(lo);
  }
  function* combinations(items,count,repeated=false) {
    const a=list(items), n=Number(count);
    function* visit(start, prefix) {
      if (prefix.length===n){yield tuple(prefix);return;}
      for(let i=start;i<a.length;i++) yield* visit(i+(repeated?0:1),[...prefix,a[i]]);
    }
    yield* visit(0,[]);
  }
  function* groupby(items,key=x=>x) {
    let group=[], prior;
    for (const item of iter(items)) {
      const k=key(item);
      if (group.length && !equal(prior,k)) {yield tuple([prior,group]);group=[];}
      prior=k;
      group.push(item);
    }
    if(group.length) yield tuple([prior,group]);
  }
  const modules = {
    typing:{List:null,Tuple:null}, re,
    math:{sqrt:x=>Math.sqrt(Number(x)),pow:(x,y)=>Number(x)**Number(y),log:(x,b)=>b===undefined?Math.log(Number(x)):Math.log(Number(x))/Math.log(Number(b)),
      ceil:x=>BigInt(Math.ceil(Number(x))),floor:x=>BigInt(Math.floor(Number(x))),gcd},
    collections:{deque:list,Counter:items=>{const out=dict();for(const x of iter(items)) put(out,x,(out.get(findKey(out,x))??0n)+1n);return out;},
      defaultdict:factory=>{const out=dict();defaultFactories.set(out,factory);return out;},
      ChainMap:(...maps)=>dict(maps.reverse().flatMap(x=>[...x]))},
    functools:{cmp_to_key:comparator=>({comparator}),reduce:(fn,xs,...init)=>list(xs).reduce(fn,...init)},
    operator:{eq:equal,itemgetter:(...indices)=>x=>indices.length===1?get(x,indices[0]):tuple(indices.map(i=>get(x,i)))},
    itertools:{combinations,combinations_with_replacement:(x,n)=>combinations(x,n,true),groupby},
    heapq:{heapify:x=>x.sort(compare),heappop:x=>x.shift(),nlargest:(n,items,opts)=>sorted(items,{[keyword]:{...opts?.[keyword],reverse:true}}).slice(0,Number(n))},
    bisect:{bisect_left:bisect,bisect_right:(x,v,l,h)=>bisect(x,v,l,h,true)}
  };

  function lift(value, contract) {
    if (typeof value==='number' && !contract.bigint && Number.isSafeInteger(value) && !Object.is(value,-0)) return BigInt(value);
    if (Array.isArray(value)) return value.map(x=>lift(x,contract));
    if (value===null || typeof value!=='object') return value;
    if (contract.tuples && Object.hasOwn(value,'$tuple')) return tuple(value.$tuple.map(x=>lift(x,contract)));
    const entries=contract.entries && Object.hasOwn(value,'$entries') ? value.$entries : Object.entries(value);
    return dict(entries.map(([k,v])=>[lift(k,contract),lift(v,contract)]));
  }

  function lower(value, contract) {
    if (typeof value==='bigint' && !contract.bigint) {
      const n=Number(value);
      if(!Number.isSafeInteger(n))throw new Error('unsafe Number projection');
      return n;
    }
    if (Array.isArray(value)) {
      const elements=value.map(x=>lower(x,contract));
      return contract.tuples&&tuples.has(value)?{$tuple:elements}:elements;
    }
    if (value instanceof Map) {
      const entries=[...value].map(([k,v])=>[lower(k,contract),lower(v,contract)]);
      return contract.entries?{$entries:entries}:Object.fromEntries(entries);
    }
    if (value instanceof Set || value===undefined || typeof value==='function') throw new Error('unsupported result');
    return value;
  }

  const wrap=(entry,contract)=>(...args)=>lower(entry(...args.map(x=>lift(x,contract))),contract);
  function prime64(value) {
    const n=BigInt(value);
    if (n<2n || n%2n===0n) return n===2n;
    if (n>=1n<<64n) throw new RangeError('prime outside replay range');
    let odd=n-1n, exponent=0;
    while (odd%2n===0n) {odd>>=1n;exponent++;}
    for (const witness of [2n,325n,9375n,28178n,450775n,9780504n,1795265022n]) {
      if (witness%n===0n) continue;
      let base=witness%n, result=1n;
      for (let power=odd;power>0n;power>>=1n) {
        if (power&1n) result=result*base%n;
        base=base*base%n;
      }
      if (result===1n || result===n-1n) continue;
      for (let i=1;i<exponent && result!==n-1n;i++) result=result*result%n;
      if (result!==n-1n) return false;
    }
    return true;
  }
  return {attr,b,call,chain,dict,get,iter,logical,modules,neg,number,op,prime64,put,slice,truth,tuple,unpack,wrap};
})();
