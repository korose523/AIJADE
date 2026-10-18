using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace Aijade.Core.Schema;

/// <summary>
/// Minimal strict schema for JSON wire messages. Events cross process and network boundaries, so they are validated where
/// they arrive rather than trusted by type. One definition serves the kernel and the HTTP boundary, so the two cannot
/// drift apart. Semantics follow the zod schemas of the earlier implementation: strict objects reject unknown keys,
/// optional fields may be absent but not null, integers must be safe integers.
/// </summary>
public abstract class WireSchema
{
    public bool IsOptional { get; protected init; }

    /// <summary>Validate; returns the list of problems (empty = valid), each prefixed with its JSON path.</summary>
    public IReadOnlyList<string> Validate(JsonNode? node)
    {
        var errors = new List<string>();
        Check(node, "$", errors);
        return errors;
    }

    internal abstract void Check(JsonNode? node, string path, List<string> errors);

    /// <summary>
    /// The parsed output of a value that has passed validation, as zod's <c>parse</c> returns it: object keys in schema order,
    /// unknown keys of non-strict objects stripped. Event JSON (and every hash over it) is therefore canonical.
    /// </summary>
    public JsonNode? Shape(JsonNode? node) => ShapeCore(node);

    internal virtual JsonNode? ShapeCore(JsonNode? node) => node?.DeepClone();

    public WireSchema Optional() => CopyWith(IsOptional: true);

    protected abstract WireSchema CopyWith(bool IsOptional);

    protected static bool TryNumber(JsonNode? node, out double value)
    {
        value = 0;
        if (node is JsonValue v && v.GetValueKind() == JsonValueKind.Number)
        {
            value = double.Parse(v.ToJsonString(), CultureInfo.InvariantCulture);
            return true;
        }
        return false;
    }

    protected static bool TryString(JsonNode? node, out string value)
    {
        value = "";
        if (node is JsonValue v && v.GetValueKind() == JsonValueKind.String)
        {
            value = v.GetValue<string>();
            return true;
        }
        return false;
    }

    /// <summary>Numeric value of a JSON number node, whether it was parsed or built in memory as an int or a double.</summary>
    public static double NumberOf(JsonNode? node) =>
        TryNumber(node, out var x) ? x : throw new InvalidOperationException("not a JSON number");

    public static StringSchema Str(int minLength = 0) => new(minLength);

    public static NumberSchema Num(double? min = null, double? max = null) => new(min, max, wholeOnly: false);

    public static NumberSchema Whole(double? min = null, double? max = null) => new(min, max, wholeOnly: true);

    public static EnumSchema Enum(params string[] values) => new(values);

    public static LiteralSchema Literal(string value) => new(JsonValue.Create(value));

    public static LiteralSchema Literal(int value) => new(JsonValue.Create(value));

    public static UnionSchema Union(params WireSchema[] options) => new(options);

    public static ArraySchema Arr(WireSchema item, int minItems = 0) => new(item, minItems);

    public static ObjectSchema Obj(IReadOnlyDictionary<string, WireSchema> fields, bool strict = true) => new(fields, strict, []);

    public static RecordSchema Record() => new();

    public static UnknownSchema Unknown() => new();
}

public sealed class StringSchema(int minLength) : WireSchema
{
    internal override void Check(JsonNode? node, string path, List<string> errors)
    {
        if (!TryString(node, out var s))
            errors.Add($"{path}: expected string");
        else if (s.Length < minLength)
            errors.Add($"{path}: must have at least {minLength} character(s)");
    }

    protected override WireSchema CopyWith(bool IsOptional) => new StringSchema(minLength) { IsOptional = IsOptional };
}

public sealed class NumberSchema(double? min, double? max, bool wholeOnly) : WireSchema
{
    private const double MaxSafeInteger = 9007199254740991;

    internal override void Check(JsonNode? node, string path, List<string> errors)
    {
        if (!TryNumber(node, out var x) || !double.IsFinite(x))
        {
            errors.Add($"{path}: expected {(wholeOnly ? "integer" : "number")}");
            return;
        }
        if (wholeOnly && (Math.Floor(x) != x || Math.Abs(x) > MaxSafeInteger))
            errors.Add($"{path}: expected integer");
        if (min is { } lo && x < lo)
            errors.Add($"{path}: must be ≥ {lo.ToString(CultureInfo.InvariantCulture)}");
        if (max is { } hi && x > hi)
            errors.Add($"{path}: must be ≤ {hi.ToString(CultureInfo.InvariantCulture)}");
    }

    protected override WireSchema CopyWith(bool IsOptional) => new NumberSchema(min, max, wholeOnly) { IsOptional = IsOptional };
}

public sealed class EnumSchema(IReadOnlyList<string> values) : WireSchema
{
    internal override void Check(JsonNode? node, string path, List<string> errors)
    {
        if (!TryString(node, out var s) || !values.Contains(s))
            errors.Add($"{path}: expected one of {string.Join("|", values)}");
    }

    protected override WireSchema CopyWith(bool IsOptional) => new EnumSchema(values) { IsOptional = IsOptional };
}

public sealed class LiteralSchema(JsonValue value) : WireSchema
{
    internal override void Check(JsonNode? node, string path, List<string> errors)
    {
        if (node is not JsonValue v || !JsonNode.DeepEquals(v, value))
            errors.Add($"{path}: expected {value.ToJsonString()}");
    }

    protected override WireSchema CopyWith(bool IsOptional) => new LiteralSchema(value) { IsOptional = IsOptional };
}

public sealed class UnionSchema(IReadOnlyList<WireSchema> options) : WireSchema
{
    internal override void Check(JsonNode? node, string path, List<string> errors)
    {
        if (!options.Any(o => o.Validate(node).Count == 0))
            errors.Add($"{path}: matches none of the {options.Count} allowed forms");
    }

    internal override JsonNode? ShapeCore(JsonNode? node) =>
        (options.FirstOrDefault(o => o.Validate(node).Count == 0) ?? options[0]).ShapeCore(node);

    protected override WireSchema CopyWith(bool IsOptional) => new UnionSchema(options) { IsOptional = IsOptional };
}

public sealed class ArraySchema(WireSchema item, int minItems) : WireSchema
{
    internal override void Check(JsonNode? node, string path, List<string> errors)
    {
        if (node is not JsonArray arr)
        {
            errors.Add($"{path}: expected array");
            return;
        }
        if (arr.Count < minItems)
            errors.Add($"{path}: must contain at least {minItems} item(s)");
        for (var i = 0; i < arr.Count; i++)
            item.Check(arr[i], $"{path}[{i}]", errors);
    }

    internal override JsonNode? ShapeCore(JsonNode? node) =>
        node is JsonArray arr ? new JsonArray(arr.Select(item.ShapeCore).ToArray()) : node?.DeepClone();

    protected override WireSchema CopyWith(bool IsOptional) => new ArraySchema(item, minItems) { IsOptional = IsOptional };
}

/// <summary>Any JSON object (z.record(string, unknown)).</summary>
public sealed class RecordSchema : WireSchema
{
    internal override void Check(JsonNode? node, string path, List<string> errors)
    {
        if (node is not JsonObject)
            errors.Add($"{path}: expected object");
    }

    protected override WireSchema CopyWith(bool IsOptional) => new RecordSchema { IsOptional = IsOptional };
}

/// <summary>Anything, including absent (z.unknown()).</summary>
public sealed class UnknownSchema : WireSchema
{
    internal override void Check(JsonNode? node, string path, List<string> errors)
    {
    }

    protected override WireSchema CopyWith(bool IsOptional) => new UnknownSchema { IsOptional = true };
}

public sealed class ObjectSchema(IReadOnlyDictionary<string, WireSchema> fields, bool strict, IReadOnlyList<(Func<JsonObject, bool> Rule, string Message)> refinements) : WireSchema
{
    public IReadOnlyDictionary<string, WireSchema> Fields => fields;

    /// <summary>A whole-object rule checked after the fields are valid (z.refine).</summary>
    public ObjectSchema Refine(Func<JsonObject, bool> rule, string message) => new(fields, strict, [.. refinements, (rule, message)]) { IsOptional = IsOptional };

    /// <summary>The same object with extra fields (schema composition, {...base, extra}).</summary>
    public ObjectSchema Extend(IReadOnlyDictionary<string, WireSchema> extra) =>
        new(fields.Concat(extra).ToDictionary(kv => kv.Key, kv => kv.Value), strict, refinements);

    internal override void Check(JsonNode? node, string path, List<string> errors)
    {
        if (node is not JsonObject obj)
        {
            errors.Add($"{path}: expected object");
            return;
        }
        var before = errors.Count;
        foreach (var (name, schema) in fields)
        {
            if (!obj.TryGetPropertyValue(name, out var value))
            {
                if (!schema.IsOptional && schema is not UnknownSchema)
                    errors.Add($"{path}.{name}: required");
                continue;
            }
            schema.Check(value, $"{path}.{name}", errors);
        }
        if (strict)
        {
            foreach (var (name, _) in obj)
            {
                if (!fields.ContainsKey(name))
                    errors.Add($"{path}.{name}: unknown field");
            }
        }
        if (errors.Count == before)
        {
            foreach (var (rule, message) in refinements)
            {
                if (!rule(obj))
                    errors.Add($"{path}: {message}");
            }
        }
    }

    internal override JsonNode? ShapeCore(JsonNode? node)
    {
        if (node is not JsonObject obj)
            return node?.DeepClone();
        var output = new JsonObject();
        foreach (var (name, schema) in fields)
        {
            if (obj.TryGetPropertyValue(name, out var value))
                output[name] = schema.ShapeCore(value);
        }
        return output;
    }

    protected override WireSchema CopyWith(bool IsOptional) => new ObjectSchema(fields, strict, refinements) { IsOptional = IsOptional };
}
