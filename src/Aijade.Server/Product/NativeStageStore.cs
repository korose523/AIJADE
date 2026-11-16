using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Server.Infrastructure;

using Npgsql;

namespace Aijade.Server.Product;

/// <summary>AIJADE's per-account/character virtual scene. Logical state is never a renderer or physical receipt.</summary>
public sealed class NativeStageStore(NpgsqlDataSource db)
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    private sealed record CommandReceipt(string Text, JsonObject Result);
    private sealed record Scene
    {
        public long Revision { get; init; }
        public string Where { get; init; } = "虚拟场景：客厅";
        public string Posture { get; init; } = "stand";
        public string Speech { get; init; } = "";
        public IReadOnlyList<double> Expression { get; init; } = [0, 0, 0, 0];
    }

    private static string Key(string owner, string? character) => "aijade.scene." +
        Convert.ToHexStringLower(SHA256.HashData(JsonSerializer.SerializeToUtf8Bytes(new[] { owner, character ?? "default" })));

    private static async Task<Scene> LoadAsync(NpgsqlConnection connection, NpgsqlTransaction? tx, string key, CancellationToken ct)
    {
        var values = await Sql.QueryAsync(connection, tx, "SELECT value::text FROM config_kv WHERE key=$1", r => r.GetString(0), ct, Sql.Text(key)).ConfigureAwait(false);
        return values.Count == 0 ? new() : JsonSerializer.Deserialize<Scene>(values[0], Json) ?? throw new JsonException("Empty scene");
    }

    private static JsonObject View(Scene scene, string? id = null, bool replay = false, string? character = null) => new()
    {
        ["running"] = true, ["reachable"] = true, ["stateKind"] = "virtual", ["backend"] = "aijade-native",
        ["where"] = scene.Where, ["posture"] = scene.Posture, ["speech"] = scene.Speech,
        ["expression"] = new JsonArray(scene.Expression.Select(x => (JsonNode)JsonValue.Create(x)!).ToArray()),
        ["revision"] = scene.Revision, ["sequenceRunning"] = false, ["learned"] = new JsonArray(),
        ["notice"] = "AIJADE 虚拟场景状态；未取得身体动作、声音播放或渲染回执。",
        ["outcome"] = "state_applied", ["renderObserved"] = false, ["audioPlayed"] = false,
        ["commandId"] = id, ["replayed"] = replay, ["characterId"] = character,
    };

    public async Task<JsonObject> ReadAsync(string owner, string? character, CancellationToken ct)
    {
        await using var connection = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        return View(await LoadAsync(connection, null, Key(owner, character), ct).ConfigureAwait(false), character: character);
    }

    public async Task<JsonObject> ApplyAsync(string owner, string? character, string text, string id, long? expectedRevision, CancellationToken ct)
    {
        await using var connection = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        await using var tx = await connection.BeginTransactionAsync(ct).ConfigureAwait(false);
        var key = Key(owner, character);
        await Sql.ExecAsync(connection, tx, "SELECT pg_advisory_xact_lock(hashtextextended($1,0))", ct, Sql.Text(key)).ConfigureAwait(false);
        var state = await LoadAsync(connection, tx, key, ct).ConfigureAwait(false);
        var receiptKey = key + ".command." + Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(id)));
        var receipts = await Sql.QueryAsync(connection, tx, "SELECT value::text FROM config_kv WHERE key=$1", row => row.GetString(0), ct, Sql.Text(receiptKey)).ConfigureAwait(false);
        if (receipts.Count > 0)
        {
            var old = JsonSerializer.Deserialize<CommandReceipt>(receipts[0], Json) ?? throw new JsonException("Empty scene command receipt");
            if (old.Text != text) throw new ApiException(409, "STAGE_COMMAND_CONFLICT", "commandId was already used for different text");
            var replay = (JsonObject)old.Result.DeepClone(); replay["replayed"] = true;
            return replay;
        }
        if (expectedRevision is { } revision && revision != state.Revision)
            throw new ApiException(409, "STAGE_REVISION_CONFLICT", "scene changed; read its current revision");
        // Validate the WHOLE batch before persisting: an unsupported later command cannot partially change the scene.
        foreach (var part in text.Split([';', '；', '\n'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            var words = part.Split([' ', '\t'], 2, StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
            var argument = words.Length == 2 ? words[1] : "";
            state = words[0] switch
            {
                "说" when argument.Length is > 0 and <= 2000 => state with { Speech = argument },
                "表情" => state with { Expression = ParseExpression(argument) },
                "起来" when argument.Length == 0 => state with { Posture = "stand" },
                "去" => Place(state, argument),
                _ => throw new ApiException(422, "STAGE_ACTION_UNAVAILABLE", "The native virtual scene supports expression, text, standing and named places; motion playback requires a separate verified implementation"),
            };
        }
        state = state with { Revision = state.Revision + 1 };
        var result = View(state, id, character: character);
        await Sql.ExecAsync(connection, tx, "INSERT INTO config_kv(key,value) VALUES($1,$2) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now()", ct,
            Sql.Text(key), Sql.Jsonb(JsonSerializer.SerializeToNode(state, Json)!)).ConfigureAwait(false);
        await Sql.ExecAsync(connection, tx, "INSERT INTO config_kv(key,value) VALUES($1,$2)", ct,
            Sql.Text(receiptKey), Sql.Jsonb(JsonSerializer.SerializeToNode(new CommandReceipt(text, result), Json)!)).ConfigureAwait(false);
        await tx.CommitAsync(ct).ConfigureAwait(false);
        return result;
    }

    private static double[] ParseExpression(string argument)
    {
        var words = argument.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        if (words.Length != 4) throw ApiException.BadRequest("expression requires four finite values", "INVALID_STAGE_COMMAND");
        var values = new double[4];
        for (var i = 0; i < 4; i++)
            if (!double.TryParse(words[i], System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out values[i]) ||
                !double.IsFinite(values[i]) || values[i] < (i == 0 ? -1 : 0) || values[i] > 1)
                throw ApiException.BadRequest("expression value outside its range", "INVALID_STAGE_COMMAND");
        return values;
    }

    private static Scene Place(Scene state, string place) => place switch
    {
        "沙发" => state with { Where = "虚拟场景：客厅，沙发", Posture = "sit" },
        "床" or "床上" => state with { Where = "虚拟场景：卧室，床", Posture = "lie" },
        "客厅" or "卧室" or "厨房" or "院子" or "书桌" or "窗边" => state with { Where = "虚拟场景：" + place, Posture = "stand" },
        _ => throw new ApiException(422, "STAGE_PLACE_UNAVAILABLE", "Unknown virtual place"),
    };
}
