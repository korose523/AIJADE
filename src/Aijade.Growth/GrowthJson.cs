using System.Text.Json;
using System.Text.Json.Serialization;

namespace Aijade.Growth;

/// <summary>
/// The JSON shape of persisted growth records: camelCase members, enums as snake_case strings, absent (null) members
/// omitted — the recorded layout of the growth artefacts.
/// </summary>
public static class GrowthJson
{
    public static JsonSerializerOptions Options { get; } = new(JsonSerializerDefaults.Web)
    {
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        Converters = { new JsonStringEnumConverter(JsonNamingPolicy.SnakeCaseLower) },
    };
}
