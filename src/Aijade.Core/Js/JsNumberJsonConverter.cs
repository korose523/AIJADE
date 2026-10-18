using System.Text.Json;
using System.Text.Json.Serialization;

namespace Aijade.Core.Js;

/// <summary>Writes doubles as JSON.stringify does (shortest round-trip, JS exponent form, non-finite as null).</summary>
public sealed class JsNumberJsonConverter : JsonConverter<double>
{
    public override double Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options) =>
        reader.TokenType == JsonTokenType.Null ? double.NaN : reader.GetDouble();

    public override void Write(Utf8JsonWriter writer, double value, JsonSerializerOptions options)
    {
        ArgumentNullException.ThrowIfNull(writer);
        writer.WriteRawValue(JsFormat.JsonNumber(value), skipInputValidation: true);
    }

    public override bool HandleNull => true;
}
