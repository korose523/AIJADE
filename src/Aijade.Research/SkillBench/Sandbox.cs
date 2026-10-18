using System.Diagnostics;
using System.Text;

using Acornima;

using Jint;
using Jint.Native;
using Jint.Native.Object;
using Jint.Runtime;

using Aijade.Core.Js;

namespace Aijade.Research.SkillBench;

// The RQ-C sandbox, on the Jint JavaScript engine.
// Submitted code runs in an isolated engine with only the ECMAScript intrinsics and a no-op console — no require, process,
// fs or CLR access. Behaviour the verdicts depend on:
// - the callable is `solve`, else the single user-defined global function, else the whole code as an expression;
// - a timeout anywhere aborts the whole evaluation as a sandbox-level error;
// - errors from inside the sandbox are reported as String(e) ("ReferenceError: x is not defined"), as cross-realm
//   errors are;
// - deep equality is structural, and comparing null with an object throws (recorded as that case's failure);
// - test arguments are shared state of the process: a candidate that mutates its arguments in place changes what later
//   candidates of the same task receive (shared module-level fixtures). A Sandbox instance is
//   one such process.

public sealed record BenchFailure(int Index, string Args, string Expected, string? Actual = null, string? Error = null);

public sealed record ExecutionVerdict(bool Ok, int Passed, int Total, double DurationMs, IReadOnlyList<BenchFailure> Failures, string? Error = null);

public sealed class Sandbox
{
    /// <summary>
    /// Give every test case freshly parsed arguments instead of the shared fixtures, so that a candidate that mutates its
    /// arguments in place cannot affect later candidates of the same task. Off by default: the reported runs used the shared
    /// fixtures, and the isolation experiment (aijade-experiments sandbox-isolation) replays them both ways.
    /// </summary>
    public bool IsolateArguments { get; init; }

    /// <summary>Recursion depth for candidate code (V8's default stack allows roughly this many simple frames).</summary>
    public const int MaxRecursion = 10_000;

    private const int StackBytes = 256 * 1024 * 1024;
    private const long MemoryLimitBytes = 512L * 1024 * 1024;

    private const string DetectionSuffix = """

        ;globalThis.__CANDIDATE__ = (function () {
          if (typeof solve !== 'undefined' && typeof solve === 'function') return solve;
          var names = __INTRINSIC_FNS__;
          var fns = [];
          var keys = Object.getOwnPropertyNames(globalThis);
          for (var i = 0; i < keys.length; i++) {
            var k = keys[i];
            var excluded = false;
            for (var j = 0; j < names.length; j++) {
              if (names[j] === k) { excluded = true; break; }
            }
            if (excluded) continue;
            var v;
            try { v = globalThis[k]; } catch (e) { continue; }
            if (typeof v === 'function') fns.push(v);
          }
          if (fns.length === 1) return fns[0];
          return undefined;
        })();

        """;

    private const string IntrinsicProbe = """
        Object.getOwnPropertyNames(globalThis).filter(function (k) {
          try { return typeof globalThis[k] === 'function'; } catch (e) { return false; }
        })
        """;

    /// <summary>Current argument literals per task and case (the shared fixtures of this "process").</summary>
    private readonly Dictionary<string, string[]> _args = new(StringComparer.Ordinal);

    private string[] ArgsOf(BenchTask task)
    {
        if (!_args.TryGetValue(task.Id, out var a))
            _args[task.Id] = a = task.Tests.Select(t => t.Args).ToArray();
        return a;
    }

    /// <summary>A fresh engine with the no-op console; captures the intrinsics the host-side comparison uses before any candidate code runs.</summary>
    private static (Engine Engine, Realm Host) NewEngine(int timeoutMs)
    {
        var engine = new Engine(o => o
            .TimeoutInterval(TimeSpan.FromMilliseconds(timeoutMs))
            .LimitRecursion(MaxRecursion)
            .LimitMemory(MemoryLimitBytes)
            .Strict(false));
        engine.Execute("var console = { log() {}, info() {}, warn() {}, error() {}, debug() {}, trace() {} };");
        var host = new Realm((ObjectInstance)engine.Evaluate("({ keys: Object.keys, hasOwn: Object.hasOwn, isArray: Array.isArray })"));
        return (engine, host);
    }

    /// <summary>Host-side intrinsics, captured before candidate code can replace the globals.</summary>
    private sealed class Realm(ObjectInstance o)
    {
        public JsValue Keys { get; } = o.Get("keys");
        public JsValue HasOwn { get; } = o.Get("hasOwn");
        public JsValue IsArray { get; } = o.Get("isArray");
    }

    private sealed class TimedOut(string message) : Exception(message);

    private sealed class HostTypeError(string message) : Exception(message);

    /// <summary>Jint appends the source position to parse errors; V8's message has none.</summary>
    private static readonly System.Text.RegularExpressions.Regex Position = new(@" \(<anonymous>:\d+:\d+\)$", System.Text.RegularExpressions.RegexOptions.CultureInvariant);

    /// <summary>String(e) for a value thrown inside the sandbox; parse errors read like V8's ("SyntaxError: …").</summary>
    private static string ErrorText(Exception e, int timeoutMs) => Position.Replace(e switch
    {
        TimeoutException or TimedOut => $"Error: Script execution timed out after {timeoutMs}ms",
        JavaScriptException js => SafeToString(js.Error) ?? js.Message,
        ParseErrorException p => $"SyntaxError: {p.Error.Description}",
        RecursionDepthOverflowException => "RangeError: Maximum call stack size exceeded",
        MemoryLimitExceededException => "RangeError: Invalid array length",
        HostTypeError h => h.Message,
        _ => e.Message,
    }, "");

    private static string? SafeToString(JsValue v)
    {
        try
        {
            return TypeConverter.ToString(v);
        }
#pragma warning disable CA1031 // A thrown value whose toString throws is reported by its type instead.
        catch (Exception)
#pragma warning restore CA1031
        {
            return null;
        }
    }

    private static bool IsTimeout(Exception e) => e is TimeoutException or TimedOut;

    /// <summary>Run the candidate against every case of the task. Never throws for anything the candidate does.</summary>
    public ExecutionVerdict RunTask(string code, BenchTask task)
    {
        ExecutionVerdict? result = null;
        // Jint recurses on the CLR stack, so candidates run on a thread with a large stack.
        var thread = new Thread(() => result = RunCore(code, task), StackBytes);
        thread.Start();
        thread.Join();
        return result!;
    }

    private ExecutionVerdict RunCore(string code, BenchTask task)
    {
        var timeout = task.TimeoutMs ?? 2000;
        var clock = Stopwatch.StartNew();
        ExecutionVerdict Verdict(bool ok, int passed, List<BenchFailure> failures, string? error = null) =>
            new(ok, passed, task.Tests.Count, clock.Elapsed.TotalMilliseconds, failures, error);

        var (engine, host) = NewEngine(timeout);
        JsValue fn;
        try
        {
            engine.SetValue("__INTRINSIC_FNS__", engine.Evaluate(IntrinsicProbe));
        }
#pragma warning disable CA1031 // A failed probe falls back to the `solve` heuristic.
        catch (Exception)
#pragma warning restore CA1031
        {
            engine.SetValue("__INTRINSIC_FNS__", engine.Evaluate("[]"));
        }
        try
        {
            engine.Execute(code + DetectionSuffix);
            fn = engine.GetValue("__CANDIDATE__");
        }
#pragma warning disable CA1031 // Anything the candidate does at load time is a verdict, not a crash.
        catch (Exception e)
#pragma warning restore CA1031
        {
            return Verdict(false, 0, [], ErrorText(e, timeout));
        }

        if (!fn.IsCallable())
        {
            try
            {
                var (exprEngine, exprHost) = NewEngine(timeout);
                var expr = exprEngine.Evaluate($"({code})");
                if (expr.IsCallable())
                    (fn, engine, host) = (expr, exprEngine, exprHost);
            }
#pragma warning disable CA1031 // Not an expression either: reported below.
            catch (Exception)
#pragma warning restore CA1031
            {
            }
        }
        if (!fn.IsCallable())
            return Verdict(false, 0, [], "no callable function found (tried `solve`, single global function, and whole-code expression)");

        var shared = IsolateArguments ? [.. task.Tests.Select(t => t.Args)] : ArgsOf(task);
        var failures = new List<BenchFailure>();
        var passed = 0;
        for (var i = 0; i < task.Tests.Count; i++)
        {
            var expectedLiteral = task.Tests[i].Expected;
            var argsLiteral = shared[i];
            JsValue args = JsValue.Undefined;
            try
            {
                args = engine.Evaluate($"({argsLiteral})");
                var callArgs = ((JsArray)args).ToArray();
                var actual = engine.Call(fn, JsValue.Null, callArgs);
                var expected = engine.Evaluate($"({expectedLiteral})");
                if (DeepEqual(engine, host, actual, expected))
                    passed++;
                else
                    failures.Add(new BenchFailure(i, argsLiteral, expectedLiteral, Actual: JsLiteral.Of(engine, host, actual)));
            }
#pragma warning disable CA1031 // A failing case is recorded; only a timeout ends the evaluation.
            catch (Exception e)
#pragma warning restore CA1031
            {
                if (IsTimeout(e))
                    return Verdict(false, passed, failures, ErrorText(e, timeout));
                failures.Add(new BenchFailure(i, argsLiteral, expectedLiteral, Error: ErrorText(e, timeout)));
            }
            finally
            {
                // Arguments mutated in place stay mutated for later candidates of this task.
                if (!args.IsUndefined())
                    shared[i] = JsLiteral.Of(engine, host, args);
            }
        }
        return Verdict(failures.Count == 0, passed, failures);
    }

    /// <summary>Realm-agnostic structural equality (NaN equals NaN; null against an object throws).</summary>
    internal static bool DeepEqual(Engine engine, object hostRealm, JsValue a, JsValue b)
    {
        var host = (Realm)hostRealm;
        if (IsNaN(a) && IsNaN(b))
            return true;
        if (StrictEquals(a, b))
            return true;
        if (TypeOf(a) != TypeOf(b))
            return false;
        if (TypeOf(a) != "object")
            return false;
        var aArr = TypeConverter.ToBoolean(engine.Call(host.IsArray, JsValue.Undefined, [a]));
        var bArr = TypeConverter.ToBoolean(engine.Call(host.IsArray, JsValue.Undefined, [b]));
        if (aArr || bArr)
        {
            if (!aArr || !bArr)
                return false;
            var la = TypeConverter.ToNumber(a.Get("length"));
            if (la != TypeConverter.ToNumber(b.Get("length")))
                return false;
            for (var i = 0; i < la; i++)
            {
                if (!DeepEqual(engine, host, a.Get(i), b.Get(i)))
                    return false;
            }
            return true;
        }
        if (a.IsNull() || b.IsNull())
            throw new HostTypeError("Cannot convert undefined or null to object");
        var ka = (JsArray)engine.Call(host.Keys, JsValue.Undefined, [a]);
        var kb = (JsArray)engine.Call(host.Keys, JsValue.Undefined, [b]);
        if (Len(ka) != Len(kb))
            return false;
        foreach (var k in ka.ToArray())
        {
            if (!TypeConverter.ToBoolean(engine.Call(host.HasOwn, JsValue.Undefined, [b, k])))
                return false;
            if (!DeepEqual(engine, host, a.Get(k), b.Get(k)))
                return false;
        }
        return true;
    }

    private static double Len(JsArray a) => TypeConverter.ToNumber(a.Get("length"));

    private static bool IsNaN(JsValue v) => v.IsNumber() && double.IsNaN(v.AsNumber());

    private static bool StrictEquals(JsValue a, JsValue b) => JintStrict.Equal(a, b);

    internal static string TypeOf(JsValue v) => v switch
    {
        _ when v.IsUndefined() => "undefined",
        _ when v.IsNull() => "object",
        _ when v.IsBoolean() => "boolean",
        _ when v.IsNumber() => "number",
        _ when v.IsString() => "string",
        _ when v.IsSymbol() => "symbol",
        _ when v.IsBigInt() => "bigint",
        _ when v.IsCallable() => "function",
        _ => "object",
    };
}

/// <summary>JavaScript strict equality (===).</summary>
internal static class JintStrict
{
    public static bool Equal(JsValue a, JsValue b)
    {
        if (a.IsNumber() && b.IsNumber())
            return a.AsNumber() == b.AsNumber();
        if (a.IsString() && b.IsString())
            return string.Equals(a.AsString(), b.AsString(), StringComparison.Ordinal);
        if (a.IsBoolean() && b.IsBoolean())
            return a.AsBoolean() == b.AsBoolean();
        if (a.IsUndefined() && b.IsUndefined())
            return true;
        if (a.IsNull() && b.IsNull())
            return true;
        return ReferenceEquals(a, b);
    }
}

/// <summary>Serializes a value as JavaScript literal source, keeping undefined, ±Infinity, NaN and -0.</summary>
internal static class JsLiteral
{
    public static string Of(Engine engine, object hostRealm, JsValue v)
    {
        var sb = new StringBuilder();
        Write(engine, hostRealm, v, sb, 0);
        return sb.ToString();
    }

    private static void Write(Engine engine, object hostRealm, JsValue v, StringBuilder sb, int depth)
    {
        if (depth > 64)
        {
            sb.Append("null");
            return;
        }
        if (v.IsUndefined())
        {
            sb.Append("undefined");
            return;
        }
        if (v.IsNumber())
        {
            var x = v.AsNumber();
            sb.Append(double.IsNaN(x) ? "NaN" : double.IsPositiveInfinity(x) ? "Infinity" : double.IsNegativeInfinity(x) ? "-Infinity"
                : x == 0 && double.IsNegative(x) ? "-0" : JsFormat.Number(x));
            return;
        }
        if (v.IsNull())
        {
            sb.Append("null");
            return;
        }
        if (v.IsString())
        {
            sb.Append(JsFormat.JsonString(v.AsString()));
            return;
        }
        if (v.IsBoolean())
        {
            sb.Append(v.AsBoolean() ? "true" : "false");
            return;
        }
        if (v is JsArray arr)
        {
            sb.Append('[');
            var n = (uint)TypeConverter.ToNumber(arr.Get("length"));
            for (uint i = 0; i < n; i++)
            {
                if (i > 0)
                    sb.Append(',');
                Write(engine, hostRealm, arr.Get(i), sb, depth + 1);
            }
            sb.Append(']');
            return;
        }
        if (v is ObjectInstance o && !v.IsCallable())
        {
            sb.Append('{');
            var first = true;
            foreach (var k in o.GetOwnPropertyKeys(Types.String))
            {
                var desc = o.GetOwnProperty(k);
                if (!desc.Enumerable)
                    continue;
                if (!first)
                    sb.Append(',');
                first = false;
                sb.Append(JsFormat.JsonString(k.AsString())).Append(':');
                Write(engine, hostRealm, o.Get(k), sb, depth + 1);
            }
            sb.Append('}');
            return;
        }
        sb.Append("/*").Append(Sandbox.TypeOf(v)).Append("*/null");
    }
}
